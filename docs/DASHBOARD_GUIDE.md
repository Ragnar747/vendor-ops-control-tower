# Power BI dashboard guide

Power BI Desktop is free for Windows: install it from the **Microsoft Store**
(search "Power BI Desktop").

## 1. Load the data
**Home → Get data → Text/CSV**, load these files from `data/clean/`:

| File | What it is | Rows |
|---|---|---|
| `trips.csv` | One row per trip (the main table) | ~40,500 |
| `vendors.csv` | One row per vendor | 31 |
| `routes.csv` | One row per route | 10 |
| `document_alerts.csv` | Documents expired or expiring within 30 days | ~210 |
| `data_quality_report.csv` | What the cleaning step fixed | 6 |
| `simulation_results.csv` | What-if results: route × scenario × policy | 120 |
| `reconciliation.csv` | Every vendor claim, checked against the platform | ~2,700 |
| `reconciliation_summary.csv` | One row per vendor, ranked by money at risk | 31 |
| `unclaimed_trips.csv` | Completed trips vendors didn't report | 6 |
| `email_log.csv` | Every email the intake saw, and what happened to it | 64 |

All of these are created by `python run_all.py`.

In Power Query, check that `on_time` and `is_weekend` are **True/False**, and that
`rating`, `fare_inr`, `pickup_delay_min` are **decimal numbers**.

## 2. Relationships (Model view)
Drag to connect, one-to-many:
- `vendors[vendor_id]` → `trips[vendor_id]`
- `routes[route_id]` → `trips[route_id]`
- `vendors[vendor_id]` → `document_alerts[vendor_id]`

This is a **star schema**: one fact table (trips) in the middle, descriptive
tables around it. Say that word in interviews.

## 3. Measures (Modeling → New measure)
Create these one at a time. Each line is one measure.

```DAX
Trips = COUNTROWS(trips)

Completed Trips = CALCULATE([Trips], trips[status] = "completed")

Completion Rate = DIVIDE([Completed Trips], [Trips])

Vendor Cancel Rate =
    DIVIDE(CALCULATE([Trips], trips[status] = "cancelled_by_vendor"), [Trips])

On-Time Rate =
    DIVIDE(
        CALCULATE([Trips], trips[status] = "completed", trips[on_time] = TRUE()),
        [Completed Trips])

Avg Rating = CALCULATE(AVERAGE(trips[rating]), trips[status] = "completed")

Complaint Rate =
    DIVIDE(CALCULATE(SUM(trips[complaint]), trips[status] = "completed"), [Completed Trips])

Revenue = CALCULATE(SUM(trips[fare_inr]), trips[status] = "completed")

Vendor Score =
    100 * (
        0.35 * [Completion Rate]
      + 0.30 * [On-Time Rate]
      + 0.25 * DIVIDE([Avg Rating] - 1, 4)
      + 0.10 * (1 - [Complaint Rate])
    )

-- Only rank vendors with enough trips (small samples mislead)
Ranked Score = IF([Trips] >= 30, [Vendor Score])

Vendor Rank =
    IF(
        HASONEVALUE(vendors[vendor_name]),
        RANKX(ALLSELECTED(vendors[vendor_name]), [Ranked Score], , DESC)
    )
```

Format the rates as **Percentage** (Measure tools → Format), and the score and rating
with 1 decimal place.

**Why these weights?** Finishing the trip matters most (35%), then being on time (30%),
then what riders felt (25%), then complaints (10%). They're a judgement call. In
interviews, say you chose them and why, and that they're easy to change.

## 4. Pages

### Page 1: Route overview
- **Slicers:** `routes[route_name]`, `trips[month]`, `trips[category]`, `trips[is_weekend]`
- **Cards:** Trips · Completion Rate · On-Time Rate · Avg Rating · Revenue
- **Column chart:** Trips by `weekday` (shows the Friday peak)
- **Matrix heatmap:** rows `weekday`, columns `pickup_hour`, values `Trips`, with
  background-colour conditional formatting. Shows *when* demand peaks.

### Page 2: Top 5 vendors by route (the main idea)
- **Slicer:** `routes[route_name]` (single select), so the user picks e.g. *Bangalore to Mysore*
- **Table:** `vendor_name`, Vendor Rank, Vendor Score, Completion Rate, On-Time Rate,
  Avg Rating, Trips
  - Filter pane → `vendor_name` → Filter type **Top N** → Show items **Top 5**
    → By value: **Ranked Score**
  - Conditional formatting: data bars on Vendor Score
- **Bar chart:** Vendor Score by `vendor_name`, same Top 5 filter
- **Creative extra:** **Modeling → New parameter → Numeric range** for each weight,
  so the user can move sliders and watch the ranking change ("what if punctuality
  mattered more?").

### Page 3: Vendor deep dive (drill-through)
- Add `vendors[vendor_name]` to the **Drill-through** well, so right-clicking a
  vendor on Page 2 opens this page for that vendor.
- **Line chart:** Vendor Cancel Rate and On-Time Rate by `month` (finds the slipping vendor)
- **Clustered column:** Vendor Cancel Rate by `is_weekend` (finds the weekend problem)
- **Scatter:** On-Time Rate (x) vs Avg Rating (y), one dot per vendor (finds the
  "late but liked" vendor)
- **Bar:** Trips by `cancel_reason`

### Page 4: Compliance alerts
- **Cards:** count of `document_alerts` by status (EXPIRED / 7 days / 30 days)
- **Table:** vendor_name, asset_id, document, expiry_date, days_left, status, with
  red/amber/yellow conditional formatting on `status`

### Page 5: Data quality
- **Table** of `data_quality_report`: shows what the pipeline caught
  (e.g. "324 duplicate trips removed"). This proves the data can be trusted.

### Page 6: What-if simulator
Load `simulation_results.csv` too. It is a separate table, with no relationship needed.

- **Slicers** (single select): `route_name`, `scenario`
- **Clustered bar chart:** `riders_let_down_avg` by `policy`
  (which policy lets fewest riders down?)
- **Table:** policy · avg_bookings · completion_rate · avg_vendor_cancelled ·
  avg_no_cab_available · riders_let_down_p95, with data bars on the last two
- **Card:** `vendor_offline` (which vendor was removed in that scenario)
- **Text box** explaining the two columns people misread:
  - *riders let down* = vendor cancelled **or** no cab at all
  - *p95* = a bad day: only 1 simulated day in 20 is worse than this

Try *Festival weekend* on **Bangalore to Mysore**, then on **Delhi to Agra**.
The best fix is different, and explaining *why* is the strongest thing you can
say about this project.

### Page 7: Payments and email intake
Load `reconciliation.csv`, `reconciliation_summary.csv`, `unclaimed_trips.csv` and
`email_log.csv`. Relate `vendors[vendor_id]` → `reconciliation[vendor_id]`.

```DAX
Amount at Risk = SUM(reconciliation[amount_at_risk_inr])
Claims Checked = COUNTROWS(reconciliation)
Match Rate = DIVIDE(CALCULATE([Claims Checked], reconciliation[result] = "matched"), [Claims Checked])
Emails Processed = CALCULATE(COUNTROWS(email_log), email_log[status] = "processed")
```

- **Cards:** Amount at Risk · Claims Checked · Match Rate · Emails Processed
- **Bar chart:** Amount at Risk by `vendor_name` (who needs a call first?)
- **Donut:** Claims Checked by `result` (what kind of problems?)
- **Table:** `reconciliation` filtered to `result` ≠ "matched": the exact trips to review
- **Table:** `email_log` status counts (processed / manual review / ignored)

## 5. Check your work
Compare Page 2 for *Bangalore to Mysore* with `docs/ANSWER_KEY.md`.
If your top 5 matches, your measures are right.

## 6. Sharing
Publishing to the Power BI web service usually needs a work or school email, so for
a portfolio: commit the `.pbix` file to GitHub, add screenshots to the README, and
record a 2-minute walkthrough video.
