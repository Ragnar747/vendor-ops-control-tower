"""
Clean the raw trips and build dashboard-ready tables.

  data/raw/        messy input (from generate_data.py, or real exports later)
  data/clean/      what Power BI reads

Each fix is counted in data/clean/data_quality_report.csv, so you can say
exactly what the pipeline caught.

Run:  python src/clean_data.py
"""

from datetime import date
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
RAW_DIR = ROOT / "data" / "raw"
CLEAN_DIR = ROOT / "data" / "clean"
TODAY = date(2026, 11, 13)

VALID_STATUS = {"completed", "cancelled_by_vendor", "cancelled_by_rider"}
ON_TIME_MINUTES = 10  # pickup within 10 min of schedule = on time
MIN_TRIPS_FOR_RANKING = 30  # ignore vendors with too few trips on a route

# Vendor score weights (must add up to 1). Same as the DAX measure in docs.
WEIGHTS = {"completion": 0.35, "on_time": 0.30, "rating": 0.25, "no_complaint": 0.10}


def clean_trips(raw):
    report = []
    t = raw.copy()

    # 1. Tidy vendor IDs: " v07 " -> "V07"
    before = (~t.vendor_id.str.fullmatch(r"V\d{2}")).sum()
    t["vendor_id"] = t.vendor_id.str.strip().str.upper()
    report.append(("validity", "vendor_id formatting fixed", int(before)))

    # 2. Standardise status spelling: "CANCELLED BY VENDOR" -> "cancelled_by_vendor"
    before = (~t.status.isin(VALID_STATUS)).sum()
    t["status"] = t.status.str.strip().str.lower().str.replace(" ", "_")
    report.append(("consistency", "status spelling standardised", int(before)))

    # 3. Remove exact duplicate trips (the same trip sent twice)
    before = len(t)
    t = t.drop_duplicates(subset="trip_id", keep="first")
    report.append(("uniqueness", "duplicate trips removed", before - len(t)))

    # 4. Impossible ratings -> blank (a rating must be 1-5)
    bad = t.rating.notna() & ~t.rating.between(1, 5)
    t.loc[bad, "rating"] = None
    report.append(("validity", "impossible ratings blanked", int(bad.sum())))

    # 5. Negative fares are typing errors -> make positive, and count them
    bad = t.fare_inr < 0
    t.loc[bad, "fare_inr"] = t.loc[bad, "fare_inr"].abs()
    report.append(("accuracy", "negative fares corrected", int(bad.sum())))

    # 6. Anything still invalid is set aside, never silently loaded
    invalid = ~t.status.isin(VALID_STATUS)
    report.append(("validity", "rows quarantined", int(invalid.sum())))
    quarantine = t[invalid]
    t = t[~invalid].copy()

    # Derived columns for the dashboard
    for col in ["booked_at", "scheduled_pickup", "actual_pickup", "dropoff_at"]:
        t[col] = pd.to_datetime(t[col])
    t["trip_date"] = t.scheduled_pickup.dt.date
    t["weekday"] = t.scheduled_pickup.dt.day_name()
    t["is_weekend"] = t.scheduled_pickup.dt.day_of_week >= 4  # Fri-Sun, the busy days
    t["pickup_hour"] = t.scheduled_pickup.dt.hour
    t["month"] = t.scheduled_pickup.dt.to_period("M").astype(str)
    t["pickup_delay_min"] = (
        t.actual_pickup - t.scheduled_pickup
    ).dt.total_seconds() / 60
    t["on_time"] = t.pickup_delay_min <= ON_TIME_MINUTES
    t["trip_minutes"] = (t.dropoff_at - t.actual_pickup).dt.total_seconds() / 60
    t["lead_time_days"] = (t.scheduled_pickup - t.booked_at).dt.total_seconds() / 86400

    report_df = pd.DataFrame(report, columns=["dimension", "check", "rows_affected"])
    return t.sort_values("trip_id").reset_index(drop=True), quarantine, report_df


def vendor_scores(trips, routes, vendors):
    """Score every vendor on every route they serve. This is the dashboard's 'answer key'."""
    g = trips.groupby(["route_id", "vendor_id"])
    done = trips[trips.status == "completed"].groupby(["route_id", "vendor_id"])
    s = pd.DataFrame(
        {
            "trips": g.size(),
            "completion_rate": g.apply(lambda x: (x.status == "completed").mean()),
            "vendor_cancel_rate": g.apply(
                lambda x: (x.status == "cancelled_by_vendor").mean()
            ),
            "on_time_rate": done.on_time.mean(),
            "avg_rating": done.rating.mean(),
            "complaint_rate": done.complaint.mean(),
            "revenue_inr": done.fare_inr.sum(),
        }
    ).reset_index()
    s["vendor_score"] = 100 * (
        WEIGHTS["completion"] * s.completion_rate
        + WEIGHTS["on_time"] * s.on_time_rate
        + WEIGHTS["rating"] * (s.avg_rating - 1) / 4
        + WEIGHTS["no_complaint"] * (1 - s.complaint_rate)
    )
    s["eligible_for_ranking"] = s.trips >= MIN_TRIPS_FOR_RANKING
    s["rank_on_route"] = (
        s[s.eligible_for_ranking]
        .groupby("route_id")
        .vendor_score.rank(ascending=False, method="min")
    )
    s = s.merge(routes[["route_id", "route_name"]], on="route_id").merge(
        vendors[["vendor_id", "vendor_name"]], on="vendor_id"
    )
    return s.sort_values(["route_id", "rank_on_route"]).round(4)


def document_alerts(vehicles, drivers):
    """Every document that has expired or expires within 30 days."""
    rows = []
    for _, v in vehicles.iterrows():
        for doc in ["permit_expiry", "insurance_expiry", "fitness_expiry"]:
            rows.append((v.vendor_id, v.vehicle_id, doc.replace("_expiry", ""), v[doc]))
    for _, d in drivers.iterrows():
        rows.append((d.vendor_id, d.driver_id, "driving_licence", d.licence_expiry))
    a = pd.DataFrame(rows, columns=["vendor_id", "asset_id", "document", "expiry_date"])
    a["expiry_date"] = pd.to_datetime(a.expiry_date).dt.date
    a["days_left"] = a.expiry_date.map(lambda d: (d - TODAY).days)
    a = a[a.days_left <= 30].copy()
    a["status"] = a.days_left.map(
        lambda d: (
            "EXPIRED"
            if d < 0
            else "Expires in 7 days"
            if d <= 7
            else "Expires in 30 days"
        )
    )
    return a.sort_values("days_left").reset_index(drop=True)


def main():
    CLEAN_DIR.mkdir(parents=True, exist_ok=True)
    raw = pd.read_csv(RAW_DIR / "trips_raw.csv")
    routes = pd.read_csv(RAW_DIR / "routes.csv")
    vendors = pd.read_csv(RAW_DIR / "vendors.csv")
    vehicles = pd.read_csv(RAW_DIR / "vehicles.csv")
    drivers = pd.read_csv(RAW_DIR / "drivers.csv")

    trips, quarantine, report = clean_trips(raw)
    scores = vendor_scores(trips, routes, vendors)
    alerts = document_alerts(vehicles, drivers)

    trips.to_csv(CLEAN_DIR / "trips.csv", index=False)
    quarantine.to_csv(CLEAN_DIR / "quarantine.csv", index=False)
    report.to_csv(CLEAN_DIR / "data_quality_report.csv", index=False)
    scores.to_csv(CLEAN_DIR / "vendor_route_scores.csv", index=False)
    alerts.to_csv(CLEAN_DIR / "document_alerts.csv", index=False)
    for name in ["routes", "vendors", "vehicles", "drivers"]:
        pd.read_csv(RAW_DIR / f"{name}.csv").to_csv(
            CLEAN_DIR / f"{name}.csv", index=False
        )

    print(report.to_string(index=False))
    print(f"\nclean trips: {len(trips)} · document alerts: {len(alerts)}")


if __name__ == "__main__":
    main()
