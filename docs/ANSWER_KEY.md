# Answer key

Use this to check your dashboard. **Try to find the patterns yourself first.**
Finding them in your own dashboard is the point of the exercise, and it's what you'll
describe in interviews.

## Top 5 vendors: Bangalore to Mysore

| Rank | Vendor | Score | Completion | On-time | Avg rating | Trips |
|---|---|---|---|---|---|---|
| 1 | Royal Wheels (V03) | 95.6 | 94.9% | 97.4% | 4.72 | 933 |
| 2 | Kaveri Cabs (V02) | 92.5 | 93.1% | 91.4% | 4.63 | 551 |
| 3 | Shree Travels (V01) | 91.9 | 92.7% | 89.7% | 4.66 | 847 |
| 4 | Chamundi Travels (V21) | 91.0 | 90.9% | 88.4% | 4.67 | 902 |
| 5 | Silicon Valley Cabs (V22) | 86.8 | 88.6% | 81.6% | 4.48 | 564 |

## Top 5 vendors: Mysore to Bangalore

| Rank | Vendor | Score | Completion | On-time | Avg rating | Trips |
|---|---|---|---|---|---|---|
| 1 | Kaveri Cabs (V02) | 92.3 | 93.9% | 90.1% | 4.63 | 495 |
| 2 | Chamundi Travels (V21) | 91.8 | 92.6% | 90.1% | 4.61 | 734 |
| 3 | Shree Travels (V01) | 91.1 | 91.2% | 89.3% | 4.62 | 726 |
| 4 | Silicon Valley Cabs (V22) | 86.6 | 88.4% | 82.5% | 4.41 | 433 |
| 5 | Royal Wheels (V03) | 81.3 | 87.6% | 70.1% | 4.23 | 774 |

Small differences in the last decimal are fine (rounding).

## The four hidden patterns

| Vendor | Pattern | Where to find it | Numbers |
|---|---|---|---|
| **V03 Royal Wheels** | Route specialist: best on Bangalore→Mysore, weak on the return | Page 2, switch the route slicer | #1 (95.6) one way, #5 (81.3) the other |
| **V07 Yamuna Travels** | Weekend overload: fine on weekdays, cancels Fri–Sun | Page 3, cancel rate by `is_weekend` | ~5% weekday vs ~21% weekend |
| **V12 Sabarmati Tours** | Slipping: gets worse every month | Page 3, cancel rate by `month` | ~3% in May → ~18% in Oct |
| **V15 Mysuru Express** | Late but liked: often late, riders still rate highly | Page 3, scatter on-time vs rating | ~55% on time, rating ~4.7 |

## What each pattern would mean for the business
- **Route specialist:** assign V03 more Bangalore→Mysore trips; investigate the return leg
  (maybe drivers rest in Mysore and start late).
- **Weekend overload:** V07's fleet is too small for weekend demand. Cap its weekend
  bookings or onboard backup vendors for Fridays.
- **Slipping:** an early warning. Talk to V12 *now*, before riders complain.
- **Late but liked:** the overall score hides a specific problem. Punctuality coaching
  could make V15 a top vendor.

These one-line recommendations are what turn a dashboard into **business value**.

## Simulation: the main finding

Riders let down per day on a **festival weekend** (+40% demand):

| Route | Current allocation | Score-based | Score-based + backup | Riders with no cab at all (current) |
|---|---|---|---|---|
| Bangalore to Mysore | 1.85 | 1.65 | **0.35** | 0.12 |
| Mysore to Bangalore | 2.24 | 1.85 | **0.09** | 0.01 |
| Delhi to Agra | 15.72 | 15.35 | 15.32 | **13.78** |
| Mumbai to Pune | 17.06 | 17.15 | 16.63 | **13.51** |

(Simulation results vary slightly by run; small differences are fine.)

**Two problems, two fixes:**
- **Bangalore, Lucknow, Ahmedabad routes: a reliability problem.** There are enough
  vehicles, but vendors cancel. Reassigning cancelled trips to a backup vendor removes
  most failures. → *Process fix, no cost.*
- **Delhi→Agra and Mumbai→Pune: a capacity problem.** On festival weekends, about 14
  riders a day get no cab at all, and reassignment can't help because every vendor is
  already full. → *Onboard more vendors before festival season.*

## Email intake and reconciliation

**Intake (64 emails):** 61 processed (53 CSV in three different layouts, 8 plain-text),
1 duplicate skipped (V09 sent the same email twice), 1 flagged for manual review
(V24: no trip data), 1 ignored (unknown sender).

**Reconciliation, ranked by money at risk:**

| Rank | Vendor | Problem | Issues | Amount at risk |
|---|---|---|---|---|
| 1 | V20 | Duplicate claims | 10 | ₹22,074 |
| 2 | V05 | Trips that don't exist on the platform | 6 | ₹14,058 |
| 3 | V11 | Overclaimed fares | 9 | ₹3,623 |
| 4 | V18 | Cancelled trip claimed as completed | 1 | ₹1,506 |
| – | V16 | **Under-reported** 6 completed trips (may be owed money) | 6 unclaimed | – |

**Total payments on hold: ₹41,261.**

**Limitations to state honestly:** capacity assumes 20% of each vendor's fleet is
available for intercity trips, and that a vehicle does 1–3 one-way trips a day
depending on route length (Delhi→Agra's ~4-hour trip allows only 1). If those
assumptions change, so do the numbers; that's why they're settings in `simulate.py`.
