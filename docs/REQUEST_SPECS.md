# From request to technical specification

Three **fictional** requests, written the way they might arrive, and how each was turned
into a precise, reviewable specification. All data is synthetic.

---

## Request 1: transport authority (regulator)

> "Following a complaint, please provide details of all trips made by vehicle
> XX69YY3726 during September 2026."

**Ambiguities resolved before writing any SQL**
- "Details": which ones? Trip, time, route and operator, not driver identity. The
  authority regulates vehicles and operators, not individual drivers.
- "September": scheduled pickup dates 1–30 September inclusive.
- Cancelled trips: included, with their status, because the complaint may concern a no-show.

**Specification**

| Item | Decision |
|---|---|
| Template | `trips_by_vehicle` |
| Filter | `registration_no` = given value; `trip_date` between 2026-09-01 and 2026-09-30 |
| Columns | trip ID, date, route, status, scheduled / actual pickup, drop-off, vendor name, registration |
| Unmasked | registration number (the authority supplied it) |
| Excluded | driver ID, name, phone, licence |
| Limits | max 92 days |
| Approval | single requester; reference required |

```
python src/share.py run --template trips_by_vehicle --requester-type regulator \
  --reference RTO/KA/2026/118 --requested-by priya.ops \
  --param registration_no=XX69YY3726 --param date_from=2026-09-01 --param date_to=2026-09-30
```

---

## Request 2: police notice (law enforcement)

> "Under notice PS/BLR/NOTICE/4471, provide the trips and driver details for vehicle
> XX69YY3726 in September 2026."

**Specification:** the same template as Request 1, with the law-enforcement policy.

| Item | Decision |
|---|---|
| Extra columns | driver name, phone, licence number, **unmasked**, because the notice requires identity |
| Legal reference | mandatory, recorded in the manifest and audit log |
| Two-person rule | approved by a second, named person (e.g. legal); requester ≠ approver |
| Refused if | no approval, same person approves, date range > 92 days, or latest DQ run failed |

---

## Request 3: payment audit (auditor)

> "We're reviewing vendor V07's October claims. What did they claim and what was paid?"

**Specification**

| Item | Decision |
|---|---|
| Template | `vendor_payment_audit` |
| Filter | `vendor_id` = V07; claim dates 1–31 October 2026 |
| Columns | each claim with platform status, both fares, reconciliation result, amount at risk |
| PII | none in output |
| Source | the `reconciliation` table built by `sql/reconciliation.sql` |

---

## Pattern: what makes a request "automatable"

After a few weeks, `python src/share.py stats` shows which templates are requested most.
A request type moves to self-service when it is frequent, its filters are always the same
kind (an ID plus a date range), and its policy needs no case-by-case judgement. Requests
needing legal review (Request 2) keep the two-person rule even when automated.
