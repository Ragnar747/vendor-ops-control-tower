"""
The central SQLite database: one file, data/control_tower.db.

Platform tables (trips, vendors, routes, ...) are reloaded from data/clean on each
run. Intake tables (email_log, vendor_trip_logs) keep growing, and an email that
was already processed is never processed twice.
"""

import sqlite3

import pandas as pd

import config

PLATFORM_TABLES = ["trips", "vendors", "routes", "vehicles", "drivers",
                   "vendor_route_scores", "document_alerts", "data_quality_report",
                   "simulation_results"]

INTAKE_SCHEMA = """
CREATE TABLE IF NOT EXISTS email_log (
    message_id      TEXT PRIMARY KEY,      -- unique per email: stops double-processing
    vendor_id       TEXT,
    sender          TEXT,
    subject         TEXT,
    received_at     TEXT,
    source_type     TEXT,                  -- csv / text / none
    rows_extracted  INTEGER,
    status          TEXT,                  -- processed / ignored_unknown_sender / needs_manual_review
    raw_path        TEXT
);
CREATE TABLE IF NOT EXISTS vendor_trip_logs (
    vendor_id         TEXT NOT NULL,
    trip_id           TEXT NOT NULL,
    trip_date         TEXT,
    claimed_status    TEXT,
    claimed_fare_inr  REAL,
    source_message_id TEXT NOT NULL REFERENCES email_log(message_id),
    source_type       TEXT
);
"""


def connect(path=None):
    path = path or config.DB_PATH
    if str(path) != ":memory:":
        config.DATA_DIR.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(path)
    conn.executescript(INTAKE_SCHEMA)
    return conn


def load_platform_tables(conn, clean_dir=None):
    """Copy every clean CSV into the database (replacing the old version)."""
    clean_dir = clean_dir or config.CLEAN_DIR
    counts = {}
    for name in PLATFORM_TABLES:
        path = clean_dir / f"{name}.csv"
        if path.exists():
            df = pd.read_csv(path)
            df.to_sql(name, conn, if_exists="replace", index=False)
            counts[name] = len(df)
    conn.commit()
    return counts


def export_tables(conn, names, out_dir=None):
    """Write database tables to CSV so Power BI can read them."""
    out_dir = out_dir or config.CLEAN_DIR
    for name in names:
        pd.read_sql(f"SELECT * FROM {name}", conn).to_csv(out_dir / f"{name}.csv", index=False)
