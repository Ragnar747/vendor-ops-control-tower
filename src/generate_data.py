"""
Generate a realistic FAKE dataset for an intercity cab vendor programme.

Everything here is synthetic. Public facts used to make it realistic:
- popular routes: Mumbai-Pune, Delhi-Agra, Bangalore-Mysore, Lucknow-Kanpur,
  Ahmedabad-Vadodara
- Bangalore-Mysore ~144 km, ~3 h; fares from Rs 1,980 (Go), 2,160 (Sedan), 3,721 (XL)
- rides on demand or reserved up to 30 days ahead
- weekends (led by Fridays) are busiest; early morning and 2-3 pm are popular

Hidden patterns for the dashboard to discover (see docs/ANSWER_KEY.md):
- V07 "Weekend Overload": fine on weekdays, many cancellations Fri-Sun
- V12 "Slipping": good at first, gets worse every month
- V03 "Route Specialist": excellent on Bangalore->Mysore, weak on Mysore->Bangalore
- V15 "Late but Liked": often late, but riders rate drivers highly

Output: data/raw/*.csv  (trips_raw.csv deliberately contains data-quality issues)
Run:    python src/generate_data.py
"""

from datetime import date, datetime, timedelta
from pathlib import Path

import numpy as np
import pandas as pd

SEED = 42
START = date(2026, 5, 1)
END = date(2026, 10, 31)
TODAY = date(2026, 11, 13)          # for document-expiry checks
RAW_DIR = Path(__file__).resolve().parent.parent / "data" / "raw"

# (origin, destination, approx km, approx minutes, base trips per day)
CORRIDORS = [
    ("Bangalore", "Mysore", 144, 180, 26),
    ("Mumbai", "Pune", 150, 180, 34),
    ("Delhi", "Agra", 230, 240, 22),
    ("Lucknow", "Kanpur", 90, 120, 12),
    ("Ahmedabad", "Vadodara", 110, 120, 14),
]

# Rs per km, from Bangalore-Mysore public fares (1980/144, 2160/144, 3721/144)
CATEGORIES = {"Go Intercity": 13.75, "Sedan Intercity": 15.0, "XL Intercity": 25.84}
CATEGORY_SHARE = [0.55, 0.32, 0.13]

CANCEL_REASONS_VENDOR = ["No driver available", "Vehicle breakdown",
                         "Driver did not reach", "Vendor declined late"]
CANCEL_REASONS_RIDER = ["Change of plans", "Found other transport", "Long wait"]

VENDOR_NAMES = [
    "Shree Travels", "Kaveri Cabs", "Royal Wheels", "Deccan Tours", "Sahyadri Cabs",
    "Konkan Car Rentals", "Yamuna Travels", "Taj Route Cabs", "Indraprastha Fleet",
    "Awadh Travels", "Ganga Cabs", "Sabarmati Tours", "Narmada Wheels", "Garden City Cabs",
    "Mysuru Express", "Pune Pioneers", "Agra Connect", "Kanpur Kabs", "Gujarat Roadways Pvt",
    "Western Ghats Travels", "Chamundi Travels", "Silicon Valley Cabs", "Lonavala Links",
    "Fatehpur Fleet", "Capital Cabs", "Nawab Travels", "Gomti Cabs", "Navrang Travels",
    "Kankaria Cabs", "Baroda Wheels", "Udyog Travels",
]
# region of each vendor (index into CORRIDORS): 6-7 vendors per corridor
VENDOR_REGION = [0, 0, 0, 1, 1, 1, 2, 2, 2, 3, 3, 4, 4, 0, 0, 1, 2, 3, 4, 1,
                 0, 0, 1, 2, 2, 3, 3, 3, 4, 4, 4]

# Quality profile per vendor: (on-time prob, vendor-cancel prob, rating mean, complaint prob)
GOOD = (0.90, 0.03, 4.75, 0.02)
AVERAGE = (0.80, 0.06, 4.50, 0.04)
WEAK = (0.65, 0.11, 4.20, 0.08)
PROFILES = [GOOD, GOOD, AVERAGE, AVERAGE, GOOD, WEAK, AVERAGE, GOOD, AVERAGE,
            AVERAGE, WEAK, GOOD, AVERAGE, WEAK, AVERAGE, AVERAGE, GOOD, AVERAGE, WEAK, AVERAGE,
            GOOD, AVERAGE, AVERAGE, WEAK, GOOD, AVERAGE, GOOD, WEAK, AVERAGE, GOOD, AVERAGE]


def make_routes():
    rows = []
    for i, (a, b, km, mins, demand) in enumerate(CORRIDORS):
        for direction, (o, d) in enumerate([(a, b), (b, a)]):
            rows.append({
                "route_id": f"R{2 * i + direction + 1:02d}",
                "origin": o, "destination": d,
                "route_name": f"{o} to {d}",
                "distance_km": km, "expected_minutes": mins,
                "corridor": i, "base_daily_trips": demand if direction == 0 else int(demand * 0.85),
            })
    return pd.DataFrame(rows)


def make_vendors(rng):
    rows = []
    for i, name in enumerate(VENDOR_NAMES):
        region = VENDOR_REGION[i]
        rows.append({
            "vendor_id": f"V{i + 1:02d}",
            "vendor_name": name,
            "base_city": CORRIDORS[region][0],
            "corridor": region,
            "onboarded_on": START - timedelta(days=int(rng.integers(30, 700))),
            "fleet_size": int(rng.integers(6, 30)),
        })
    return pd.DataFrame(rows)


def make_fleet(rng, vendors):
    vehicles, drivers = [], []
    for _, v in vendors.iterrows():
        for k in range(v.fleet_size):
            vid = f"{v.vendor_id}-VH{k + 1:02d}"
            category = rng.choice(list(CATEGORIES), p=CATEGORY_SHARE)
            # expiry dates spread around "today" so some are expired / expiring soon
            vehicles.append({
                "vehicle_id": vid, "vendor_id": v.vendor_id, "category": category,
                "registration_no": f"KA{rng.integers(1, 99):02d}XX{rng.integers(1000, 9999)}"
                if v.corridor == 0 else f"XX{rng.integers(1, 99):02d}YY{rng.integers(1000, 9999)}",
                "permit_expiry": TODAY + timedelta(days=int(rng.integers(-20, 400))),
                "insurance_expiry": TODAY + timedelta(days=int(rng.integers(-10, 365))),
                "fitness_expiry": TODAY + timedelta(days=int(rng.integers(-5, 500))),
            })
            drivers.append({
                "driver_id": f"{v.vendor_id}-DR{k + 1:02d}", "vendor_id": v.vendor_id,
                "licence_expiry": TODAY + timedelta(days=int(rng.integers(-15, 900))),
            })
    return pd.DataFrame(vehicles), pd.DataFrame(drivers)


def quality_for(vendor_id, route_name, when, profile):
    """Return the vendor's quality on this trip, applying the hidden patterns."""
    on_time, cancel, rating, complaint = profile
    weekend = when.weekday() >= 4  # Fri, Sat, Sun
    if vendor_id == "V07" and weekend:                       # Weekend Overload
        cancel, on_time = 0.22, 0.60
    if vendor_id == "V12":                                    # Slipping
        months_in = (when.year - START.year) * 12 + when.month - START.month
        cancel = 0.02 + 0.03 * months_in
        on_time = max(0.5, 0.92 - 0.06 * months_in)
        rating = 4.8 - 0.1 * months_in
    if vendor_id == "V03":                                    # Route Specialist
        if route_name == "Bangalore to Mysore":
            on_time, cancel, rating, complaint = 0.97, 0.01, 4.9, 0.01
        else:
            on_time, cancel, rating, complaint = 0.70, 0.09, 4.3, 0.06
    if vendor_id == "V15":                                    # Late but Liked
        on_time, rating = 0.55, 4.85
    return on_time, cancel, rating, complaint


def make_trips(rng, routes, vendors, vehicles, drivers):
    rows = []
    trip_no = 0
    vendor_profile = dict(zip(vendors.vendor_id, PROFILES))
    for _, r in routes.iterrows():
        operators = vendors[vendors.corridor == r.corridor].vendor_id.tolist()
        # bigger fleets get more trips
        weights = vendors.set_index("vendor_id").loc[operators, "fleet_size"].to_numpy(float)
        weights /= weights.sum()
        day = START
        while day <= END:
            demand = r.base_daily_trips * (1.35 if day.weekday() == 4 else
                                           1.25 if day.weekday() >= 5 else 1.0)
            for _ in range(rng.poisson(demand)):
                trip_no += 1
                vid = rng.choice(operators, p=weights)
                on_time_p, cancel_p, rating_mu, complaint_p = quality_for(
                    vid, r.route_name, day, vendor_profile[vid])

                hour = rng.choice([5, 6, 7, 8, 10, 12, 14, 15, 17, 19, 21],
                                  p=[.10, .16, .13, .08, .07, .07, .13, .10, .07, .05, .04])
                scheduled = datetime(day.year, day.month, day.day, hour, int(rng.integers(0, 60)))
                reserve = rng.random() < 0.4
                booked = scheduled - (timedelta(days=int(rng.integers(1, 31))) if reserve
                                      else timedelta(minutes=int(rng.integers(10, 90))))
                fleet = vehicles[vehicles.vendor_id == vid]
                vehicle = fleet.iloc[int(rng.integers(len(fleet)))]
                driver_id = vehicle.vehicle_id.replace("VH", "DR")

                u = rng.random()
                if u < cancel_p:
                    status, reason = "cancelled_by_vendor", rng.choice(CANCEL_REASONS_VENDOR)
                elif u < cancel_p + 0.05:
                    status, reason = "cancelled_by_rider", rng.choice(CANCEL_REASONS_RIDER)
                else:
                    status, reason = "completed", None

                actual_pickup = dropoff = rating = None
                complaint = 0
                fare = round(r.distance_km * CATEGORIES[vehicle.category] * rng.uniform(0.95, 1.15))
                if status == "completed":
                    delay = rng.integers(-5, 10) if rng.random() < on_time_p else rng.integers(11, 60)
                    actual_pickup = scheduled + timedelta(minutes=int(delay))
                    weekend_slow = 1.10 if day.weekday() >= 4 else 1.0
                    duration = r.expected_minutes * weekend_slow * rng.uniform(0.9, 1.25)
                    dropoff = actual_pickup + timedelta(minutes=int(duration))
                    if rng.random() < 0.7:  # not every rider leaves a rating
                        rating = int(np.clip(round(rng.normal(rating_mu, 0.6)), 1, 5))
                    complaint = int(rng.random() < complaint_p)
                else:
                    fare = 0

                rows.append({
                    "trip_id": f"T{trip_no:06d}", "route_id": r.route_id, "vendor_id": vid,
                    "vehicle_id": vehicle.vehicle_id, "driver_id": driver_id,
                    "category": vehicle.category,
                    "booking_type": "reserve" if reserve else "on_demand",
                    "booked_at": booked, "scheduled_pickup": scheduled,
                    "actual_pickup": actual_pickup, "dropoff_at": dropoff,
                    "status": status, "cancel_reason": reason,
                    "fare_inr": fare, "rating": rating, "complaint": complaint,
                })
            day += timedelta(days=1)
    return pd.DataFrame(rows)


def add_quality_issues(rng, trips):
    """Make the raw file messy, like real vendor data. The cleaning script must fix this."""
    t = trips.copy()
    n = len(t)
    # 1. ~0.8% duplicate rows (same trip sent twice)
    dupes = t.sample(int(n * 0.008), random_state=SEED)
    # 2. inconsistent status spelling
    idx = rng.choice(n, int(n * 0.01), replace=False)
    t.loc[idx, "status"] = t.loc[idx, "status"].str.upper().str.replace("_", " ")
    # 3. some vendor IDs in lowercase with spaces
    idx = rng.choice(n, int(n * 0.005), replace=False)
    t.loc[idx, "vendor_id"] = " " + t.loc[idx, "vendor_id"].str.lower() + " "
    # 4. a few impossible ratings
    idx = rng.choice(t.index[t.rating.notna()], 15, replace=False)
    t.loc[idx, "rating"] = rng.choice([0, 6, 7, 9], 15)
    # 5. a few negative fares (typing errors)
    idx = rng.choice(t.index[t.fare_inr > 0], 10, replace=False)
    t.loc[idx, "fare_inr"] = -t.loc[idx, "fare_inr"]
    return pd.concat([t, dupes]).sample(frac=1, random_state=SEED).reset_index(drop=True)


def main():
    rng = np.random.default_rng(SEED)
    RAW_DIR.mkdir(parents=True, exist_ok=True)
    routes = make_routes()
    vendors = make_vendors(rng)
    vehicles, drivers = make_fleet(rng, vendors)
    trips = make_trips(rng, routes, vendors, vehicles, drivers)
    trips_raw = add_quality_issues(rng, trips)

    routes.drop(columns=["corridor", "base_daily_trips"]).to_csv(RAW_DIR / "routes.csv", index=False)
    vendors.drop(columns=["corridor"]).to_csv(RAW_DIR / "vendors.csv", index=False)
    vehicles.to_csv(RAW_DIR / "vehicles.csv", index=False)
    drivers.to_csv(RAW_DIR / "drivers.csv", index=False)
    trips_raw.to_csv(RAW_DIR / "trips_raw.csv", index=False)
    print(f"routes {len(routes)} · vendors {len(vendors)} · vehicles {len(vehicles)} · "
          f"drivers {len(drivers)} · raw trip rows {len(trips_raw)} (true trips {len(trips)})")


if __name__ == "__main__":
    main()
