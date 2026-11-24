"""
Tests for the compliance layer: SQL reporting marts, data-quality rules,
privacy controls and the data-sharing request engine.
Each test builds a small in-memory database by hand. Run with:  pytest
"""

import hashlib
import json
import sys
from datetime import datetime
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

import clean_data  # noqa: E402
import database  # noqa: E402
import dq  # noqa: E402
import marts  # noqa: E402
import privacy  # noqa: E402
import share  # noqa: E402


# ---------------------------------------------------------------- fixtures
def small_platform(seed=1):
    """Two routes, three vendors, enough trips to rank; cleaned like the real pipeline."""
    rng = np.random.default_rng(seed)
    rows, n = [], 0
    for route in ["R01", "R02"]:
        for vendor in ["V01", "V02", "V03"]:
            for _ in range(40 if vendor != "V03" else 10):      # V03 below the ranking threshold
                n += 1
                day = 1 + n % 28
                status = rng.choice(["completed", "completed", "completed", "cancelled_by_vendor"])
                delay = int(rng.integers(0, 25))
                rows.append({
                    "trip_id": f"T{n:06d}", "route_id": route, "vendor_id": vendor,
                    "vehicle_id": f"{vendor}-VH01", "driver_id": f"{vendor}-DR01",
                    "category": "Go Intercity", "booking_type": "reserve",
                    "booked_at": f"2026-09-{day:02d} 06:00:00",
                    "scheduled_pickup": f"2026-09-{day:02d} 08:00:00",
                    "actual_pickup": f"2026-09-{day:02d} 08:{delay:02d}:00" if status == "completed" else None,
                    "dropoff_at": f"2026-09-{day:02d} 11:00:00" if status == "completed" else None,
                    "status": status, "cancel_reason": None,
                    "fare_inr": int(rng.integers(1500, 3000)) if status == "completed" else 0,
                    "rating": float(rng.integers(3, 6)) if status == "completed" else None,
                    "complaint": int(rng.random() < 0.05) if status == "completed" else 0,
                })
    trips, _, _ = clean_data.clean_trips(pd.DataFrame(rows))
    routes = pd.DataFrame({"route_id": ["R01", "R02"], "origin": ["A", "B"], "destination": ["B", "A"],
                           "route_name": ["A to B", "B to A"], "distance_km": [150, 150],
                           "expected_minutes": [180, 180]})
    vendors = pd.DataFrame({"vendor_id": ["V01", "V02", "V03"], "vendor_name": ["One", "Two", "Three"],
                            "base_city": ["Bangalore", "Mumbai", "Delhi"],
                            "onboarded_on": ["2025-01-01"] * 3, "fleet_size": [5, 5, 5]})
    vehicles = pd.DataFrame({"vehicle_id": ["V01-VH01", "V02-VH01", "V03-VH01"],
                             "vendor_id": ["V01", "V02", "V03"], "category": ["Go Intercity"] * 3,
                             "registration_no": ["KA01AB1234", "MH12CD5678", "DL03EF9012"],
                             "permit_expiry": ["2027-01-01"] * 3, "insurance_expiry": ["2027-01-01"] * 3,
                             "fitness_expiry": ["2027-01-01"] * 3})
    drivers = pd.DataFrame({"driver_id": ["V01-DR01", "V02-DR01", "V03-DR01"],
                            "vendor_id": ["V01", "V02", "V03"], "licence_expiry": ["2027-01-01"] * 3})
    return trips, routes, vendors, vehicles, drivers


@pytest.fixture
def conn():
    c = database.connect(":memory:")
    trips, routes, vendors, vehicles, drivers = small_platform()
    trips.to_sql("trips", c, index=False)
    routes.to_sql("routes", c, index=False)
    vendors.to_sql("vendors", c, index=False)
    vehicles.to_sql("vehicles", c, index=False)
    drivers.to_sql("drivers", c, index=False)
    clean_data.vendor_scores(trips, routes, vendors).to_sql("vendor_route_scores", c, index=False)
    privacy.load_contacts(c)
    return c


# ---------------------------------------------------------------- marts
def test_sql_scores_match_pandas(conn):
    counts = marts.build(conn)
    assert counts["mart_vendor_route_scores"] == 6
    result = marts.check_consistency(conn)
    assert result["ranks_equal"] and result["max_score_diff"] < 1e-4


def test_vendor_below_threshold_is_not_ranked(conn):
    marts.build(conn)
    ranks = dict(conn.execute("SELECT vendor_id, rank_on_route FROM mart_vendor_route_scores "
                              "WHERE route_id='R01'").fetchall())
    assert ranks["V03"] is None and {ranks["V01"], ranks["V02"]} == {1, 2}


def test_rolling_window_uses_calendar_days():
    c = database.connect(":memory:")
    pd.DataFrame({"vendor_id": ["V01"] * 3, "trip_date": ["2026-09-01", "2026-09-20", "2026-10-15"],
                  "bookings": [1, 1, 1], "completed": [1, 1, 1],
                  "completed_on_time": [1, 0, 0]}).to_sql("int_vendor_day", c, index=False)
    sql = (marts.config.SQL_DIR / "marts.sql").read_text().split("DROP TABLE IF EXISTS mart_vendor_rolling_30d;")[1]
    c.executescript(sql)
    rows = c.execute("SELECT trip_date, bookings_30d FROM mart_vendor_rolling_30d ORDER BY trip_date").fetchall()
    # 1 Sep is 44 days before 15 Oct, so it falls outside that day's 30-day window
    assert rows == [("2026-09-01", 1), ("2026-09-20", 2), ("2026-10-15", 2)]


# ---------------------------------------------------------------- data quality
def test_clean_data_passes_all_rules(conn):
    results = dq.run(conn)
    assert (results[results.status != "skipped_table_missing"].status == "pass").all()
    assert dq.gate(results)["failed_critical"] == 0


def test_rules_catch_planted_errors(conn):
    conn.execute("UPDATE trips SET rating = 9 WHERE trip_id = (SELECT MIN(trip_id) FROM trips WHERE rating IS NOT NULL)")
    conn.execute("UPDATE trips SET vendor_id = 'V99' WHERE trip_id = (SELECT MAX(trip_id) FROM trips)")
    conn.execute("UPDATE trips SET fare_inr = 500 WHERE status <> 'completed' "
                 "AND trip_id = (SELECT MIN(trip_id) FROM trips WHERE status <> 'completed')")
    results = dq.run(conn).set_index("rule_id")
    assert results.loc["TRP-006", "rows_failed"] == 1      # rating out of range
    assert results.loc["TRP-004", "rows_failed"] == 1      # unknown vendor
    assert results.loc["TRP-010", "rows_failed"] == 1      # cancelled trip charged
    with pytest.raises(dq.DQGateError):
        dq.gate(results.reset_index())
    reasons = {r[0] for r in conn.execute("SELECT rule_id FROM dq_exceptions")}
    assert {"TRP-004", "TRP-006", "TRP-010"} <= reasons


def test_warning_does_not_block(conn):
    conn.execute("UPDATE drivers SET licence_expiry = NULL WHERE driver_id = 'V01-DR01'")
    results = dq.run(conn)
    assert dq.gate(results)["failed_warning"] == 1


def test_unsafe_identifier_is_refused():
    with pytest.raises(ValueError):
        dq.failing_rows_sql({"table": "trips; DROP TABLE trips", "type": "not_null", "column": "x"}, "trip_id")


# ---------------------------------------------------------------- privacy
def test_masks():
    assert privacy.mask_phone("+91 9876543210") == "+91 98XXXXXX10"
    assert privacy.mask_licence("KA0120190012345") == "KA01XXXXXXX2345"
    assert privacy.mask_registration("KA41AB3932") == "KA41XXXX32"
    assert privacy.mask_email("v01@vendors.example.com") == "v**@vendors.example.com"


def test_pseudonymise_is_consistent_and_salted(monkeypatch):
    a = privacy.pseudonymise("V01-DR01", "DRV")
    assert a == privacy.pseudonymise("V01-DR01", "DRV") and a.startswith("DRV_") and "V01" not in a
    monkeypatch.setenv("VENDOR_PSEUDO_SALT", "another-secret")
    assert privacy.pseudonymise("V01-DR01", "DRV") != a


def test_redact_text_keeps_trip_data():
    text = "Driver 98450 12345 / +91 9876543210, licence KA0120190012345, car KA41AB3932, trip T012345 Rs 2150"
    out = privacy.redact_text(text)
    assert "9876543210" not in out and "98450" not in out and "KA0120190012345" not in out
    assert "KA41AB3932" not in out and "T012345" in out and "2150" in out


def test_apply_policy_respects_keep_clear():
    df = pd.DataFrame({"driver_id": ["V01-DR01"], "driver_name": ["Ravi"], "phone": ["+91 9876543210"],
                       "licence_no": ["KA0120190012345"]})
    masked, _ = privacy.apply_policy(df, "driver_contacts")
    assert "driver_name" not in masked.columns and masked.phone[0] == "+91 98XXXXXX10"
    clear, _ = privacy.apply_policy(df, "driver_contacts", keep_clear={"phone", "driver_name"})
    assert clear.phone[0] == "+91 9876543210" and clear.driver_name[0] == "Ravi"


# ---------------------------------------------------------------- data sharing
@pytest.fixture
def ready(conn, tmp_path):
    dq.run(conn)
    return conn, tmp_path


def request(conn, out, **kw):
    args = {"template": "trips_by_vehicle", "requester_type": "regulator", "reference": "RTO/KA/2026/118",
            "requested_by": "priya.ops",
            "params": {"registration_no": "KA01AB1234", "date_from": "2026-09-01", "date_to": "2026-09-30"}}
    args.update(kw)
    return share.fulfil(conn, out_dir=out, now=datetime(2026, 11, 20, 10, 0, 0, len(str(kw))), **args)


def test_regulator_gets_only_allowed_columns(ready):
    conn, out = ready
    m = request(conn, out)
    df = pd.read_csv(out / m["request_id"] / m["file"])
    assert "phone" not in df.columns and "driver_id" not in df.columns
    assert m["rows"] == len(df) > 0
    assert m["sha256"] == hashlib.sha256((out / m["request_id"] / m["file"]).read_bytes()).hexdigest()


def test_internal_ops_gets_pseudonymised_ids(ready):
    conn, out = ready
    m = request(conn, out, requester_type="internal_ops")
    df = pd.read_csv(out / m["request_id"] / m["file"])
    assert df.driver_id.str.startswith("DRV_").all() and df.vehicle_id.str.startswith("VEH_").all()


def test_law_enforcement_needs_two_people(ready):
    conn, out = ready
    with pytest.raises(share.RequestRefused, match="approval"):
        request(conn, out, requester_type="law_enforcement")
    with pytest.raises(share.RequestRefused, match="different person"):
        request(conn, out, requester_type="law_enforcement", approved_by="priya.ops")
    m = request(conn, out, requester_type="law_enforcement", approved_by="legal.anand")
    df = pd.read_csv(out / m["request_id"] / m["file"])
    assert df.phone.str.startswith("+91").all() and "X" not in df.phone[0]


def test_data_minimisation_and_unknown_requester(ready):
    conn, out = ready
    with pytest.raises(share.RequestRefused, match="at most"):
        request(conn, out, params={"registration_no": "KA01AB1234", "date_from": "2026-01-01",
                                   "date_to": "2026-09-30"})
    with pytest.raises(share.RequestRefused, match="may not use"):
        request(conn, out, requester_type="marketing")


def test_refused_requests_are_audited(ready):
    conn, out = ready
    request(conn, out)
    with pytest.raises(share.RequestRefused):
        request(conn, out, requester_type="marketing")
    outcomes = sorted(r[0] for r in conn.execute("SELECT outcome FROM audit_log"))
    assert outcomes == ["fulfilled", "refused"]


def test_sharing_blocked_after_critical_dq_failure(conn, tmp_path):
    conn.execute("UPDATE trips SET rating = 9 WHERE trip_id = (SELECT MIN(trip_id) FROM trips WHERE rating IS NOT NULL)")
    dq.run(conn)
    with pytest.raises(share.RequestRefused, match="critical"):
        request(conn, tmp_path)


def test_templates_only_reference_registered_pii():
    registry = privacy.load_registry()
    for name, tpl in share.load_templates().items():
        for col, src in tpl["pii_source"].items():
            assert col in registry[src], f"{name}: {src}.{col} is not in the PII registry"
        assert (share.REQUEST_SQL_DIR / tpl["sql"]).exists()
