-- =====================================================================
-- Trip reconciliation: what vendors CLAIM vs what the PLATFORM recorded
-- =====================================================================
-- Every claimed trip gets one result:
--   matched                       claim agrees with the platform
--   duplicate_claim               the same trip claimed more than once
--   trip_not_on_platform          trip ID doesn't exist
--   trip_belongs_to_other_vendor  trip exists but was another vendor's
--   status_mismatch               claimed completed, platform says otherwise
--   fare_overclaimed              claimed fare higher than platform fare
--   fare_underclaimed             claimed fare lower than platform fare
-- amount_at_risk_inr = money that would be overpaid if the claim were accepted.
-- :tolerance is the allowed fare difference in rupees.

DROP TABLE IF EXISTS reconciliation;

CREATE TABLE reconciliation AS
WITH claims AS (
    SELECT
        vendor_id, trip_id, trip_date, claimed_status, claimed_fare_inr, source_message_id,
        -- window function: number each claim of the same trip by the same vendor
        ROW_NUMBER() OVER (
            PARTITION BY vendor_id, trip_id
            ORDER BY source_message_id
        ) AS claim_no
    FROM vendor_trip_logs
),
platform AS (
    SELECT trip_id, vendor_id AS platform_vendor_id, status AS platform_status, fare_inr AS platform_fare
    FROM trips
),
checked AS (
    SELECT
        c.*,
        p.platform_vendor_id, p.platform_status, p.platform_fare,
        CASE
            WHEN c.claim_no > 1                                   THEN 'duplicate_claim'
            WHEN p.trip_id IS NULL                                THEN 'trip_not_on_platform'
            WHEN p.platform_vendor_id <> c.vendor_id              THEN 'trip_belongs_to_other_vendor'
            WHEN c.claimed_status = 'completed'
                 AND p.platform_status <> 'completed'             THEN 'status_mismatch'
            WHEN c.claimed_fare_inr > p.platform_fare + :tolerance THEN 'fare_overclaimed'
            WHEN c.claimed_fare_inr < p.platform_fare - :tolerance THEN 'fare_underclaimed'
            ELSE 'matched'
        END AS result
    FROM claims c
    LEFT JOIN platform p ON p.trip_id = c.trip_id
)
SELECT
    vendor_id, trip_id, trip_date, claimed_status, platform_status,
    claimed_fare_inr, platform_fare, source_message_id, result,
    CASE
        WHEN result IN ('duplicate_claim', 'trip_not_on_platform',
                        'trip_belongs_to_other_vendor', 'status_mismatch')
                                       THEN claimed_fare_inr
        WHEN result = 'fare_overclaimed' THEN claimed_fare_inr - platform_fare
        ELSE 0
    END AS amount_at_risk_inr
FROM checked;


-- Completed platform trips the vendor did NOT claim (they may be owed money),
-- only for vendors and dates covered by the logs.
DROP TABLE IF EXISTS unclaimed_trips;

CREATE TABLE unclaimed_trips AS
WITH coverage AS (
    SELECT vendor_id, MIN(trip_date) AS first_day, MAX(trip_date) AS last_day
    FROM vendor_trip_logs
    GROUP BY vendor_id
)
SELECT t.vendor_id, t.trip_id, t.trip_date, t.fare_inr AS platform_fare
FROM trips t
JOIN coverage cv
  ON cv.vendor_id = t.vendor_id
 AND t.trip_date BETWEEN cv.first_day AND cv.last_day
WHERE t.status = 'completed'
  AND NOT EXISTS (
        SELECT 1 FROM vendor_trip_logs l
        WHERE l.trip_id = t.trip_id AND l.vendor_id = t.vendor_id
  );


-- One row per vendor, ranked by money at risk (window function RANK).
DROP TABLE IF EXISTS reconciliation_summary;

CREATE TABLE reconciliation_summary AS
WITH per_vendor AS (
    SELECT
        vendor_id,
        COUNT(*)                                             AS claims,
        SUM(result = 'matched')                              AS matched,
        SUM(result <> 'matched')                             AS issues,
        SUM(result = 'fare_overclaimed')                     AS fare_overclaimed,
        SUM(result = 'status_mismatch')                      AS status_mismatch,
        SUM(result = 'trip_not_on_platform')                 AS not_on_platform,
        SUM(result = 'duplicate_claim')                      AS duplicates,
        ROUND(SUM(amount_at_risk_inr), 0)                    AS amount_at_risk_inr
    FROM reconciliation
    GROUP BY vendor_id
)
SELECT
    p.*,
    COALESCE(u.unclaimed, 0)                                 AS unclaimed_completed_trips,
    ROUND(100.0 * p.matched / p.claims, 1)                   AS match_rate_pct,
    RANK() OVER (ORDER BY p.amount_at_risk_inr DESC)         AS risk_rank
FROM per_vendor p
LEFT JOIN (SELECT vendor_id, COUNT(*) AS unclaimed FROM unclaimed_trips GROUP BY vendor_id) u
  ON u.vendor_id = p.vendor_id
ORDER BY risk_rank;
