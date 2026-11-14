"""
Monte Carlo "what-if" simulation for each route.

Question: on a given kind of day, how many bookings get completed, how many fail
because a vendor cancels, and how many riders get no cab at all, and how does that
change with demand spikes, a vendor going offline, or a smarter allocation policy?

Inputs are ESTIMATED FROM THE CLEAN TRIP DATA (not guessed):
  - bookings per day on each route (weekday vs weekend)
  - each vendor's share of bookings, cancellation rate and on-time rate
  - each vendor's fleet size (from vendors.csv)

Assumptions (stated so they can be challenged; change them below):
  - 20% of a vendor's fleet is available for intercity bookings on a corridor per day
  - a vehicle can do N trips a day in one direction, depending on route length
  - a vendor cancellation is a failed trip, unless the policy reassigns it

Output: data/clean/simulation_results.csv  (one row per route x scenario x policy)
Run:    python src/simulate.py
"""

from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
CLEAN_DIR = ROOT / "data" / "clean"

RUNS = 1000                     # simulated days per combination
SEED = 7
FLEET_SHARE_FOR_INTERCITY = 0.20
WORKING_MINUTES = 14 * 60       # a vehicle's usable hours in a day

SCENARIOS = {
    # name: (day type, demand multiplier, take the biggest vendor offline?)
    "Normal weekday": ("weekday", 1.0, False),
    "Normal weekend": ("weekend", 1.0, False),
    "Festival weekend (+40% demand)": ("weekend", 1.4, False),
    "Weekend, biggest vendor offline": ("weekend", 1.0, True),
}
POLICIES = {
    "Current allocation": "share",            # same split as today
    "Score-based allocation": "score",        # more bookings to better vendors
    "Score-based + backup reassignment": "score_backup",
}


def estimate_inputs(trips, vendors, routes, scores):
    """Turn six months of trips into simulation inputs per route and vendor."""
    trips = trips.copy()
    trips["day_type"] = np.where(trips.is_weekend, "weekend", "weekday")
    days = trips.groupby("day_type").trip_date.nunique()

    demand = (trips.groupby(["route_id", "day_type"]).size() / days).rename("bookings_per_day")
    rider_cancel = trips.groupby("route_id").status.apply(lambda s: (s == "cancelled_by_rider").mean())

    g = trips.groupby(["route_id", "vendor_id", "day_type"])
    vstats = pd.DataFrame({
        "trips": g.size(),
        "cancel_rate": g.status.apply(lambda s: (s == "cancelled_by_vendor").mean()),
    }).reset_index()
    done = trips[trips.status == "completed"]
    on_time = done.groupby(["route_id", "vendor_id"]).on_time.mean().rename("on_time_rate")
    vstats = vstats.merge(on_time.reset_index(), on=["route_id", "vendor_id"], how="left")
    vstats = vstats.merge(vendors[["vendor_id", "fleet_size"]], on="vendor_id")
    vstats = vstats.merge(scores[["route_id", "vendor_id", "vendor_score"]],
                          on=["route_id", "vendor_id"], how="left")
    vstats = vstats.merge(routes[["route_id", "expected_minutes"]], on="route_id")

    # a vehicle's trips per day in one direction (it has to come back)
    per_vehicle = np.maximum(1, WORKING_MINUTES // (2 * vstats.expected_minutes))
    vstats["capacity"] = np.maximum(1, np.round(vstats.fleet_size * FLEET_SHARE_FOR_INTERCITY
                                                * per_vehicle)).astype(int)
    return demand, rider_cancel, vstats


def allocate(bookings, weights, capacity):
    """Split bookings by weight, respecting each vendor's capacity. Returns (assigned, unserved)."""
    assigned = np.zeros(len(weights), dtype=int)
    remaining = bookings
    open_ = capacity > 0
    while remaining > 0 and open_.any():
        w = np.where(open_, weights, 0)
        w = w / w.sum()
        share = np.floor(remaining * w).astype(int)
        # hand out the rounding leftovers to the largest weights
        leftover = remaining - share.sum()
        for i in np.argsort(-w)[:leftover]:
            share[i] += 1
        room = capacity - assigned
        share = np.minimum(share, room)
        if share.sum() == 0:
            break
        assigned += share
        remaining -= share.sum()
        open_ = (capacity - assigned) > 0
    return assigned, remaining


def simulate_day(rng, demand_mean, rider_cancel, v, policy):
    bookings = rng.poisson(demand_mean)
    if policy == "share":
        weights = v.trips.to_numpy(float)
    else:
        weights = np.nan_to_num(v.vendor_score.to_numpy(float), nan=50.0) ** 3
    capacity = v.capacity.to_numpy()
    assigned, unserved = allocate(bookings, weights, capacity)

    rider_cancelled = rng.binomial(assigned, rider_cancel)
    active = assigned - rider_cancelled
    vendor_cancelled = rng.binomial(active, v.cancel_rate.to_numpy())
    completed = active - vendor_cancelled

    if policy == "score_backup" and vendor_cancelled.sum() > 0:
        # each cancelled trip is offered once to vendors with spare capacity
        spare = capacity - assigned
        moved, _ = allocate(int(vendor_cancelled.sum()), weights, spare)
        rescued_cancel = rng.binomial(moved, v.cancel_rate.to_numpy())
        completed = completed + (moved - rescued_cancel)
        vendor_cancelled_total = vendor_cancelled.sum() - (moved.sum() - rescued_cancel.sum())
    else:
        vendor_cancelled_total = vendor_cancelled.sum()

    on_time = rng.binomial(np.maximum(completed, 0), v.on_time_rate.fillna(0.8).to_numpy()).sum()
    return bookings, int(completed.sum()), int(vendor_cancelled_total), int(unserved), int(on_time)


def run(trips, vendors, routes, scores, runs=RUNS, seed=SEED):
    rng = np.random.default_rng(seed)
    demand, rider_cancel, vstats = estimate_inputs(trips, vendors, routes, scores)
    rows = []
    for route_id, route_name in routes[["route_id", "route_name"]].itertuples(index=False):
        for scen, (day_type, mult, drop_biggest) in SCENARIOS.items():
            v = vstats[(vstats.route_id == route_id) & (vstats.day_type == day_type)].reset_index(drop=True)
            dropped = ""
            if drop_biggest:
                biggest = v.capacity.idxmax()
                dropped = v.loc[biggest, "vendor_id"]
                v = v.drop(index=biggest).reset_index(drop=True)
            mean_demand = demand[(route_id, day_type)] * mult
            for pol_name, pol in POLICIES.items():
                res = np.array([simulate_day(rng, mean_demand, rider_cancel[route_id], v, pol)
                                for _ in range(runs)])
                bookings, completed, vcancel, unserved, on_time = res.T
                failed = vcancel + unserved
                rows.append({
                    "route_id": route_id, "route_name": route_name,
                    "scenario": scen, "policy": pol_name, "vendor_offline": dropped,
                    "avg_bookings": bookings.mean(),
                    "avg_completed": completed.mean(),
                    "avg_vendor_cancelled": vcancel.mean(),
                    "avg_no_cab_available": unserved.mean(),
                    "completion_rate": completed.sum() / bookings.sum(),
                    "on_time_rate": on_time.sum() / max(completed.sum(), 1),
                    "riders_let_down_avg": failed.mean(),
                    "riders_let_down_p95": np.percentile(failed, 95),   # a bad day
                    "chance_of_any_no_cab": (unserved > 0).mean(),
                })
    return pd.DataFrame(rows).round(4)


def main():
    trips = pd.read_csv(CLEAN_DIR / "trips.csv")
    vendors = pd.read_csv(CLEAN_DIR / "vendors.csv")
    routes = pd.read_csv(CLEAN_DIR / "routes.csv")
    scores = pd.read_csv(CLEAN_DIR / "vendor_route_scores.csv")
    results = run(trips, vendors, routes, scores)
    results.to_csv(CLEAN_DIR / "simulation_results.csv", index=False)
    show = results[results.route_name == "Bangalore to Mysore"]
    print(show[["scenario", "policy", "avg_bookings", "completion_rate",
                "avg_no_cab_available", "riders_let_down_avg", "riders_let_down_p95"]]
          .to_string(index=False))


if __name__ == "__main__":
    main()
