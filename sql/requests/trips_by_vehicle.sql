-- All trips made by one vehicle in a date range.
-- Parameters: :registration_no, :date_from, :date_to
SELECT
    t.trip_id,
    t.trip_date,
    r.route_name,
    t.status,
    t.scheduled_pickup,
    t.actual_pickup,
    t.dropoff_at,
    v.vendor_name,
    t.vehicle_id,
    vh.registration_no,
    t.driver_id,
    dc.driver_name,
    dc.phone,
    dc.licence_no
FROM trips t
JOIN vehicles vh          ON vh.vehicle_id = t.vehicle_id
JOIN routes r             ON r.route_id    = t.route_id
JOIN vendors v            ON v.vendor_id   = t.vendor_id
LEFT JOIN driver_contacts dc ON dc.driver_id = t.driver_id
WHERE vh.registration_no = :registration_no
  AND t.trip_date BETWEEN :date_from AND :date_to
ORDER BY t.scheduled_pickup;
