"""
Tests for the simulation. Run with:  pytest
"""

import sys
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

import simulate  # noqa: E402


def test_allocate_never_exceeds_capacity():
    assigned, unserved = simulate.allocate(100, np.array([5.0, 3.0, 2.0]), np.array([10, 20, 30]))
    assert (assigned <= np.array([10, 20, 30])).all()
    assert assigned.sum() == 60 and unserved == 40


def test_allocate_keeps_every_booking():
    assigned, unserved = simulate.allocate(37, np.array([1.0, 1.0, 1.0]), np.array([50, 50, 50]))
    assert assigned.sum() + unserved == 37 and unserved == 0


def test_allocate_follows_weights_when_capacity_is_plenty():
    assigned, _ = simulate.allocate(100, np.array([3.0, 1.0]), np.array([1000, 1000]))
    assert assigned[0] == 75 and assigned[1] == 25


def tiny_vendors(cancel=(0.2, 0.2)):
    return pd.DataFrame({
        "vendor_id": ["A", "B"], "trips": [60, 40], "cancel_rate": list(cancel),
        "on_time_rate": [0.9, 0.8], "vendor_score": [90.0, 70.0], "capacity": [40, 40],
    })


def run_many(policy, n=2000, seed=1):
    rng = np.random.default_rng(seed)
    days = [simulate.simulate_day(rng, 30, 0.05, tiny_vendors(), policy) for _ in range(n)]
    return np.array(days)


def test_backup_reassignment_completes_more_trips():
    plain = run_many("score")
    backup = run_many("score_backup")
    assert backup[:, 1].mean() > plain[:, 1].mean()      # completed
    assert backup[:, 2].mean() < plain[:, 2].mean()      # vendor-cancelled


def test_counts_never_negative_or_more_than_bookings():
    res = run_many("score_backup", n=500)
    bookings, completed, vcancel, unserved, on_time = res.T
    assert (completed >= 0).all() and (vcancel >= 0).all() and (unserved >= 0).all()
    assert (completed + vcancel + unserved <= bookings).all()
    assert (on_time <= completed).all()


def test_same_seed_gives_same_answer():
    assert (run_many("share", n=50, seed=3) == run_many("share", n=50, seed=3)).all()
