"""
Tests for email intake, SQL reconciliation and notifications.
Each test uses a temporary in-memory database and hand-made emails.
Run with:  pytest
"""

import io
import sys
from email.message import EmailMessage
from pathlib import Path

import pandas as pd
import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

import config  # noqa: E402
import database  # noqa: E402
import intake  # noqa: E402
import notify  # noqa: E402
import reconcile  # noqa: E402

CONTACTS = {"v01@vendors.example.com": "V01", "v02@vendors.example.com": "V02"}


def make_email(sender, message_id, body="Hello", csv_text=None):
    msg = EmailMessage()
    msg["From"], msg["To"], msg["Subject"] = sender, "ops@example.com", "Trip log"
    msg["Date"], msg["Message-ID"] = "Sun, 25 Oct 2026 20:00:00 +0530", message_id
    msg.set_content(body)
    if csv_text:
        msg.add_attachment(csv_text.encode(), maintype="text", subtype="csv", filename="log.csv")
    return bytes(msg)


@pytest.fixture
def conn(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "BRONZE_EMAIL_DIR", tmp_path / "bronze")
    c = database.connect(":memory:")
    pd.DataFrame({
        "trip_id": ["T000001", "T000002", "T000003", "T000004", "T000005"],
        "vendor_id": ["V01", "V01", "V01", "V02", "V01"],
        "status": ["completed", "completed", "cancelled_by_vendor", "completed", "completed"],
        "fare_inr": [2000, 2100, 0, 1900, 2200],
        "trip_date": ["2026-10-20"] * 5,
    }).to_sql("trips", c, index=False)
    return c


# ---------------- intake ----------------
def test_three_csv_styles_are_standardised():
    for header, fare in [("trip_id,trip_date,route,status,fare_inr", "2000"),
                         ("Trip No,Trip Date,Route,Trip Status,Amount (Rs)", "2000.00"),
                         ("TRIP_ID,DATE,FROM-TO,STATUS,FARE", '"Rs 2,000"')]:
        df = pd.read_csv(io.StringIO(f"{header}\nT000001,2026-10-20,A to B,Completed,{fare}\n"))
        out = intake.standardise(df)
        assert out.iloc[0].to_dict() == {"trip_id": "T000001", "trip_date": "2026-10-20",
                                         "claimed_status": "completed", "claimed_fare_inr": 2000.0}


def test_text_email_is_parsed(conn):
    body = "Hi,\nTrip T000001 on 2026-10-20: completed, fare Rs 2,000\nTrip T000002 on 2026-10-20: completed, fare Rs 2,100\n"
    status = intake.process(make_email("V01@vendors.example.com", "<a@x>", body), conn, CONTACTS)
    assert status == "processed"
    assert conn.execute("SELECT COUNT(*) FROM vendor_trip_logs").fetchone()[0] == 2


def test_same_email_twice_is_skipped(conn):
    raw = make_email("v01@vendors.example.com", "<b@x>", csv_text="trip_id,trip_date,status,fare_inr\nT000001,2026-10-20,completed,2000\n")
    assert intake.process(raw, conn, CONTACTS) == "processed"
    assert intake.process(raw, conn, CONTACTS) == "skipped_duplicate"
    assert conn.execute("SELECT COUNT(*) FROM vendor_trip_logs").fetchone()[0] == 1


def test_unknown_sender_ignored_and_unreadable_flagged(conn):
    assert intake.process(make_email("spam@else.com", "<c@x>"), conn, CONTACTS) == "ignored_unknown_sender"
    assert intake.process(make_email("v01@vendors.example.com", "<d@x>", "Details on Monday"),
                          conn, CONTACTS) == "needs_manual_review"


# ---------------- reconciliation ----------------
def test_reconciliation_catches_every_problem(conn):
    claims = pd.DataFrame([
        ("V01", "T000001", "2026-10-20", "completed", 2000, "<m1>", "csv"),   # matched
        ("V01", "T000002", "2026-10-20", "completed", 2600, "<m1>", "csv"),   # overclaimed by 500
        ("V01", "T000003", "2026-10-20", "completed", 2100, "<m1>", "csv"),   # was cancelled
        ("V01", "T999999", "2026-10-20", "completed", 2300, "<m1>", "csv"),   # doesn't exist
        ("V01", "T000004", "2026-10-20", "completed", 1900, "<m1>", "csv"),   # V02's trip
        ("V01", "T000001", "2026-10-20", "completed", 2000, "<m2>", "csv"),   # duplicate
    ], columns=["vendor_id", "trip_id", "trip_date", "claimed_status", "claimed_fare_inr",
                "source_message_id", "source_type"])
    claims.to_sql("vendor_trip_logs", conn, if_exists="append", index=False)
    reconcile.run(conn, tolerance=10)

    r = pd.read_sql("SELECT trip_id, source_message_id, result, amount_at_risk_inr FROM reconciliation", conn)
    got = {(t, m): res for t, m, res, _ in r.itertuples(index=False)}
    assert got[("T000001", "<m1>")] == "matched"
    assert got[("T000002", "<m1>")] == "fare_overclaimed"
    assert got[("T000003", "<m1>")] == "status_mismatch"
    assert got[("T999999", "<m1>")] == "trip_not_on_platform"
    assert got[("T000004", "<m1>")] == "trip_belongs_to_other_vendor"
    assert got[("T000001", "<m2>")] == "duplicate_claim"
    assert r.amount_at_risk_inr.sum() == 500 + 2100 + 2300 + 1900 + 2000

    # T000005 was completed by V01 but never claimed
    assert pd.read_sql("SELECT trip_id FROM unclaimed_trips", conn).trip_id.tolist() == ["T000005"]


def test_small_fare_difference_within_tolerance_is_matched(conn):
    pd.DataFrame([("V01", "T000001", "2026-10-20", "completed", 2008, "<m1>", "csv")],
                 columns=["vendor_id", "trip_id", "trip_date", "claimed_status", "claimed_fare_inr",
                          "source_message_id", "source_type"]).to_sql("vendor_trip_logs", conn,
                                                                      if_exists="append", index=False)
    reconcile.run(conn, tolerance=10)
    assert pd.read_sql("SELECT result FROM reconciliation", conn).result.tolist() == ["matched"]


# ---------------- notifications ----------------
def test_emails_saved_to_outbox_and_not_sent(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "OUTBOX_DIR", tmp_path / "outbox")
    monkeypatch.setattr(config, "SEND_EMAILS", False)
    msg = notify.build_email("v01@vendors.example.com", "Test", "<p>Hi</p>", "Hi")
    assert notify.deliver([("weekly", "V01", msg)]) == 1
    assert (tmp_path / "outbox" / "weekly" / "V01.eml").exists()
