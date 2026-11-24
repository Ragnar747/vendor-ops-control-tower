-- Expired and soon-to-expire documents for one vendor.
-- Parameters: :vendor_id
SELECT
    a.vendor_id,
    v.vendor_name,
    a.asset_id,
    a.document,
    a.expiry_date,
    a.days_left,
    a.status
FROM document_alerts a
JOIN vendors v ON v.vendor_id = a.vendor_id
WHERE a.vendor_id = :vendor_id
ORDER BY a.days_left;
