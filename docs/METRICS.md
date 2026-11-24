# Metrics dictionary

Every reported number has exactly one definition, implemented once in SQL
([sql/marts.sql](../sql/marts.sql)). Weights and thresholds live in the
`metric_settings` table, written from `src/clean_data.py`, so they can't drift apart.
`marts.check_consistency()` runs on every pipeline run and fails if the SQL and the
Python ever disagree.

| Metric | Definition | Population | Where |
|---|---|---|---|
| Bookings | Count of trips | All trips | `mart_route_daily` |
| Completion rate | Completed trips ÷ all trips | All trips | `mart_vendor_route_scores`, `mart_route_daily` |
| Vendor cancellation rate | Trips cancelled by the vendor ÷ all trips | All trips | `mart_vendor_route_scores` |
| On-time rate | Pickups within 10 minutes of the scheduled time ÷ completed trips | Completed trips | all marts |
| Average rating | Mean rider rating (1–5); blank ratings ignored | Completed trips | `mart_vendor_route_scores` |
| Complaint rate | Trips with a complaint ÷ completed trips | Completed trips | `mart_vendor_route_scores` |
| Revenue | Sum of fares | Completed trips | `mart_vendor_route_scores` |
| Vendor score | 100 × (0.35 × completion + 0.30 × on-time + 0.25 × (rating − 1) ÷ 4 + 0.10 × (1 − complaint rate)) | Vendor × route | `mart_vendor_route_scores` |
| Eligible for ranking | At least 30 trips on the route | Vendor × route | `mart_vendor_route_scores` |
| Rank on route | `RANK()` of vendor score among eligible vendors on the route (ties share a rank) | Eligible vendors | `mart_vendor_route_scores`, `mart_route_top5` |
| 30-day rolling rates | Completion and on-time rates over the last 30 **calendar** days, inclusive (`RANGE` window on `julianday`, so quiet days still count) | Vendor × day | `mart_vendor_rolling_30d` |
| Amount at risk | Money that would be overpaid if a claim were accepted as sent | Vendor claims | `reconciliation` |

## Edge cases decided on purpose
- **Cancelled trips** have a fare of 0 and no rating; they count in completion rate but
  not in on-time, rating or complaint rates.
- **Missing ratings** are ignored, not counted as zero.
- **Vendors below 30 trips** on a route are scored but not ranked, so one lucky week
  can't put a vendor at the top.
