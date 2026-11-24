"""
Build the reporting marts (sql/marts.sql): the single source of truth for every
number the dashboard, reports and data-sharing requests use.

The score weights and thresholds are copied from clean_data.py into a
metric_settings table, so the SQL and the Python can never disagree about them.
check_consistency() proves it: the SQL vendor scores must equal the pandas ones.

Run:  python src/marts.py
"""

import pandas as pd

import clean_data
import config
import database

MART_TABLES = ["mart_vendor_route_scores", "mart_route_top5",
               "mart_route_daily", "mart_vendor_rolling_30d"]


def write_settings(conn):
    rows = [
        ("w_completion", clean_data.WEIGHTS["completion"]),
        ("w_on_time", clean_data.WEIGHTS["on_time"]),
        ("w_rating", clean_data.WEIGHTS["rating"]),
        ("w_no_complaint", clean_data.WEIGHTS["no_complaint"]),
        ("min_trips_for_ranking", clean_data.MIN_TRIPS_FOR_RANKING),
        ("on_time_minutes", clean_data.ON_TIME_MINUTES),
    ]
    pd.DataFrame(rows, columns=["name", "value"]).to_sql(
        "metric_settings", conn, if_exists="replace", index=False)


def build(conn):
    """Create all mart tables. Returns {table: row count}."""
    write_settings(conn)
    conn.executescript((config.SQL_DIR / "marts.sql").read_text(encoding="utf-8"))
    conn.commit()
    return {t: conn.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0] for t in MART_TABLES}


def check_consistency(conn, tolerance=1e-6):
    """SQL scores must match the pandas scores the dashboard was built on."""
    sql = pd.read_sql("SELECT route_id, vendor_id, vendor_score, rank_on_route "
                      "FROM mart_vendor_route_scores", conn)
    py = pd.read_sql("SELECT route_id, vendor_id, vendor_score, rank_on_route "
                     "FROM vendor_route_scores", conn)
    m = sql.merge(py, on=["route_id", "vendor_id"], suffixes=("_sql", "_py"), how="outer")
    if m.vendor_score_sql.isna().any() or m.vendor_score_py.isna().any():
        raise AssertionError("SQL and pandas scores cover different vendor-route pairs")
    # pandas rounds to 4 decimals before saving; compare at that precision
    diff = (m.vendor_score_sql.round(4) - m.vendor_score_py).abs().max()
    ranks_equal = m.rank_on_route_sql.fillna(-1).eq(m.rank_on_route_py.fillna(-1)).all()
    if diff > max(tolerance, 1e-4) or not ranks_equal:
        raise AssertionError(f"SQL and pandas disagree (max score diff {diff}, ranks equal {ranks_equal})")
    return {"pairs_checked": len(m), "max_score_diff": float(diff), "ranks_equal": bool(ranks_equal)}


def run(conn):
    counts = build(conn)
    counts["consistency"] = check_consistency(conn)
    return counts


if __name__ == "__main__":
    print(run(database.connect()))
