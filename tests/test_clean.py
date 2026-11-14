"""
Tests for the cleaning step. Run with:  pytest
"""

import sys
from pathlib import Path

import pandas as pd
import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

import clean_data  # noqa: E402


def messy_trips():
    base = {
        "route_id": "R01", "vehicle_id": "V01-VH01", "driver_id": "V01-DR01",
        "category": "Go Intercity", "booking_type": "reserve",
        "booked_at": "2026-05-01 06:00:00", "scheduled_pickup": "2026-05-02 06:00:00",
        "actual_pickup": "2026-05-02 06:05:00", "dropoff_at": "2026-05-02 09:00:00",
        "cancel_reason": None, "complaint": 0,
    }
    rows = [
        {**base, "trip_id": "T1", "vendor_id": "V01", "status": "completed", "fare_inr": 2000, "rating": 5},
        {**base, "trip_id": "T1", "vendor_id": "V01", "status": "completed", "fare_inr": 2000, "rating": 5},  # duplicate
        {**base, "trip_id": "T2", "vendor_id": " v02 ", "status": "completed", "fare_inr": 2100, "rating": 4},
        {**base, "trip_id": "T3", "vendor_id": "V01", "status": "CANCELLED BY VENDOR", "fare_inr": 0, "rating": None},
        {**base, "trip_id": "T4", "vendor_id": "V01", "status": "completed", "fare_inr": -1990, "rating": 9},
        {**base, "trip_id": "T5", "vendor_id": "V01", "status": "lost", "fare_inr": 0, "rating": None},
    ]
    return pd.DataFrame(rows)


@pytest.fixture
def cleaned():
    return clean_data.clean_trips(messy_trips())


def test_duplicates_removed(cleaned):
    trips, _, _ = cleaned
    assert trips.trip_id.is_unique


def test_vendor_ids_fixed(cleaned):
    trips, _, _ = cleaned
    assert set(trips.vendor_id) == {"V01", "V02"}


def test_status_spelling_fixed(cleaned):
    trips, _, _ = cleaned
    assert set(trips.status) <= clean_data.VALID_STATUS
    assert "cancelled_by_vendor" in set(trips.status)


def test_impossible_rating_blanked_and_fare_positive(cleaned):
    trips, _, _ = cleaned
    t4 = trips[trips.trip_id == "T4"].iloc[0]
    assert pd.isna(t4.rating)
    assert t4.fare_inr == 1990


def test_unknown_status_quarantined_not_loaded(cleaned):
    trips, quarantine, _ = cleaned
    assert "T5" not in set(trips.trip_id)
    assert "T5" in set(quarantine.trip_id)


def test_report_counts_every_fix(cleaned):
    _, _, report = cleaned
    counts = dict(zip(report.check, report.rows_affected))
    assert counts["duplicate trips removed"] == 1
    assert counts["rows quarantined"] == 1


def test_on_time_uses_ten_minute_rule(cleaned):
    trips, _, _ = cleaned
    t1 = trips[trips.trip_id == "T1"].iloc[0]
    assert t1.pickup_delay_min == 5 and bool(t1.on_time)


@pytest.mark.skipif(not (ROOT / "data/clean/vendor_route_scores.csv").exists(),
                    reason="run generate_data.py and clean_data.py first")
def test_hidden_pattern_route_specialist():
    """V03 should top Bangalore->Mysore but not the return trip."""
    s = pd.read_csv(ROOT / "data/clean/vendor_route_scores.csv")
    to_mysore = s[(s.route_name == "Bangalore to Mysore") & s.eligible_for_ranking]
    back = s[(s.route_name == "Mysore to Bangalore") & s.eligible_for_ranking]
    assert to_mysore.sort_values("vendor_score").iloc[-1].vendor_id == "V03"
    assert back.sort_values("vendor_score").iloc[-1].vendor_id != "V03"
