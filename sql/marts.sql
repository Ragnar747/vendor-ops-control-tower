-- =====================================================================
-- Reporting marts: the single source of truth for every reported number
-- =====================================================================
-- Every metric shown in Power BI, the weekly reports or a data-sharing
-- request is defined HERE, once, in SQL. Definitions are documented in
-- docs/METRICS.md. Score weights and thresholds live in the
-- metric_settings table (written by marts.py from clean_data.py), so a
-- setting is changed in one place only.
--
-- Layers
--   trips (cleaned platform table)          staging
--   int_vendor_day                          intermediate
--   mart_vendor_route_scores                mart: vendor score per route
--   mart_route_top5                         mart: leaderboard per route
--   mart_route_daily                        mart: route health per day
--   mart_vendor_rolling_30d                 mart: 30-day rolling vendor trend
-- =====================================================================

-- ---------------------------------------------------------------------
-- Vendor score per route
-- score = 100 x ( w_completion   x completion rate          (all trips)
--               + w_on_time      x on-time rate             (completed trips)
--               + w_rating       x (avg rating - 1) / 4      (completed trips)
--               + w_no_complaint x (1 - complaint rate) )   (completed trips)
-- Only vendors with at least min_trips_for_ranking trips on a route are ranked.
-- ---------------------------------------------------------------------
DROP TABLE IF EXISTS mart_vendor_route_scores;
CREATE TABLE mart_vendor_route_scores AS
WITH settings AS (
    SELECT
        MAX(CASE WHEN name = 'w_completion'          THEN value END) AS w_completion,
        MAX(CASE WHEN name = 'w_on_time'             THEN value END) AS w_on_time,
        MAX(CASE WHEN name = 'w_rating'              THEN value END) AS w_rating,
        MAX(CASE WHEN name = 'w_no_complaint'        THEN value END) AS w_no_complaint,
        MAX(CASE WHEN name = 'min_trips_for_ranking' THEN value END) AS min_trips
    FROM metric_settings
),
agg AS (
    SELECT
        route_id,
        vendor_id,
        COUNT(*)                                                     AS trips,
        AVG(status = 'completed')                                    AS completion_rate,
        AVG(status = 'cancelled_by_vendor')                          AS vendor_cancel_rate,
        AVG(CASE WHEN status = 'completed' THEN on_time END)         AS on_time_rate,
        AVG(CASE WHEN status = 'completed' THEN rating END)          AS avg_rating,
        AVG(CASE WHEN status = 'completed' THEN complaint END)       AS complaint_rate,
        SUM(CASE WHEN status = 'completed' THEN fare_inr ELSE 0 END) AS revenue_inr
    FROM trips
    GROUP BY route_id, vendor_id
),
scored AS (
    SELECT
        a.*,
        100.0 * (  s.w_completion   * a.completion_rate
                 + s.w_on_time      * a.on_time_rate
                 + s.w_rating       * (a.avg_rating - 1) / 4.0
                 + s.w_no_complaint * (1 - a.complaint_rate))        AS vendor_score,
        a.trips >= s.min_trips                                       AS eligible_for_ranking
    FROM agg a CROSS JOIN settings s
),
ranked AS (
    -- window function: rank eligible vendors within each route
    SELECT
        route_id, vendor_id,
        RANK() OVER (PARTITION BY route_id ORDER BY vendor_score DESC) AS rank_on_route
    FROM scored
    WHERE eligible_for_ranking
)
SELECT
    sc.*,
    r.rank_on_route,
    ro.route_name,
    v.vendor_name
FROM scored sc
LEFT JOIN ranked r USING (route_id, vendor_id)
JOIN routes  ro USING (route_id)
JOIN vendors v  USING (vendor_id)
ORDER BY sc.route_id, r.rank_on_route;

-- ---------------------------------------------------------------------
-- Top 5 vendors per route (what the dashboard's route picker shows)
-- ---------------------------------------------------------------------
DROP TABLE IF EXISTS mart_route_top5;
CREATE TABLE mart_route_top5 AS
SELECT route_id, route_name, rank_on_route, vendor_id, vendor_name, trips,
       ROUND(vendor_score, 2) AS vendor_score
FROM mart_vendor_route_scores
WHERE rank_on_route <= 5
ORDER BY route_id, rank_on_route;

-- ---------------------------------------------------------------------
-- Route health per day
-- ---------------------------------------------------------------------
DROP TABLE IF EXISTS mart_route_daily;
CREATE TABLE mart_route_daily AS
SELECT
    route_id,
    trip_date,
    COUNT(*)                                              AS bookings,
    SUM(status = 'completed')                             AS completed,
    SUM(status = 'cancelled_by_vendor')                   AS vendor_cancellations,
    AVG(status = 'completed')                             AS completion_rate,
    AVG(CASE WHEN status = 'completed' THEN on_time END)  AS on_time_rate
FROM trips
GROUP BY route_id, trip_date
ORDER BY route_id, trip_date;

-- ---------------------------------------------------------------------
-- Vendor trend: rolling 30-calendar-day on-time and completion rates.
-- RANGE over julianday() counts calendar days, so days without trips
-- still count towards the 30-day window (ROWS would not).
-- ---------------------------------------------------------------------
DROP TABLE IF EXISTS int_vendor_day;
CREATE TABLE int_vendor_day AS
SELECT
    vendor_id,
    trip_date,
    COUNT(*)                                                    AS bookings,
    SUM(status = 'completed')                                   AS completed,
    SUM(CASE WHEN status = 'completed' THEN on_time ELSE 0 END) AS completed_on_time
FROM trips
GROUP BY vendor_id, trip_date;

DROP TABLE IF EXISTS mart_vendor_rolling_30d;
CREATE TABLE mart_vendor_rolling_30d AS
WITH windowed AS (
    SELECT
        vendor_id,
        trip_date,
        SUM(bookings) OVER w           AS bookings_30d,
        SUM(completed) OVER w          AS completed_30d,
        SUM(completed_on_time) OVER w  AS on_time_30d
    FROM int_vendor_day
    WINDOW w AS (
        PARTITION BY vendor_id
        ORDER BY julianday(trip_date)
        RANGE BETWEEN 29 PRECEDING AND CURRENT ROW
    )
)
SELECT
    vendor_id,
    trip_date,
    bookings_30d,
    1.0 * completed_30d / bookings_30d           AS completion_rate_30d,
    1.0 * on_time_30d / NULLIF(completed_30d, 0) AS on_time_rate_30d
FROM windowed
ORDER BY vendor_id, trip_date;
