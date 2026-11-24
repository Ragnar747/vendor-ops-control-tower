-- Every claim a vendor made in a date range and how it reconciled.
-- Parameters: :vendor_id, :date_from, :date_to
SELECT
    vendor_id,
    trip_id,
    trip_date,
    claimed_status,
    platform_status,
    claimed_fare_inr,
    platform_fare,
    result,
    amount_at_risk_inr
FROM reconciliation
WHERE vendor_id = :vendor_id
  AND trip_date BETWEEN :date_from AND :date_to
ORDER BY trip_date, trip_id;
