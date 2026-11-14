"""
Module 5: trip reconciliation.

Runs sql/reconciliation.sql against the database and exports the results for Power BI.
The logic lives in SQL on purpose: CTEs, LEFT JOINs and window functions
(ROW_NUMBER, RANK) are exactly what operations and data roles test.

Run: python src/reconcile.py
"""

import pandas as pd

import config
import database


def run(conn, tolerance=None):
    tolerance = config.FARE_TOLERANCE_INR if tolerance is None else tolerance
    script = (config.SQL_DIR / "reconciliation.sql").read_text(encoding="utf-8")
    # sqlite runs one statement at a time when parameters are used
    for statement in script.split(";"):
        body = "\n".join(line for line in statement.splitlines()
                         if not line.strip().startswith("--")).strip()
        if body:
            params = {"tolerance": tolerance} if ":tolerance" in body else {}
            conn.execute(body, params)
    conn.commit()
    return pd.read_sql("SELECT * FROM reconciliation_summary", conn)


if __name__ == "__main__":
    connection = database.connect()
    database.load_platform_tables(connection)
    summary = run(connection)
    database.export_tables(connection, ["reconciliation", "reconciliation_summary", "unclaimed_trips"])
    print(summary.head(8).to_string(index=False))
