# Data governance: quality, privacy and data sharing

Three controls sit between the raw data and anything that leaves the system.

```
raw data ─► clean ─► central DB ─► SQL marts ─► DQ rules ──(gate)──► reports, exports,
                         │                                          data-sharing requests
                  PII stays here                                  (PII registry applied)
```

## 1. Data quality framework (`src/dq.py`, `rules/dq_rules.json`)

Rules are configuration, not code: adding a check means adding one line to the JSON file.
Every rule runs as one SQL query that returns the failing rows.

| Rule type | Fields | Fails when |
|---|---|---|
| `row_count_min` | `min` | the table has fewer rows |
| `not_null` | `column` | the value is blank |
| `unique` | `columns` | the same combination appears twice |
| `range` | `column`, `min`, `max` | the value is outside the range (blank allowed) |
| `allowed_values` | `column`, `values` | the value isn't in the list |
| `foreign_key` | `column`, `ref_table`, `ref_column` | the value doesn't exist in the reference table |
| `pattern` | `column`, `glob` | the value doesn't match the pattern |
| `not_future` | `column` | the date is after "today" |
| `expression` | `fail_when` | the SQL condition is true (for business rules) |

- **Severity:** `critical` rules block the run before anything is sent, reconciled or
  shared. `warning` rules are reported and tracked but don't block.
- **Outputs:** `dq_results` (one row per rule per run, with the pass rate, kept over time)
  and `dq_exceptions` (the failing rows and the reason, up to 50 per rule per run).
- **Current state:** 19 rules; all critical rules pass. Two warnings fail on purpose:
  20 duplicate claims and 6 claims for trips that don't exist. The reconciliation step
  then handles both.
- **A lesson kept in the rules:** the first fare rule ("fare must be positive") failed
  4,648 trips. They were all cancelled trips, correctly charged ₹0. The rule was wrong,
  not the data, so it became two business rules: completed trips have a positive fare,
  and cancelled trips have a fare of 0.

## 2. Privacy (`src/privacy.py`, `rules/pii_registry.json`)

**Personal data stays in the core database.** Whenever data leaves it, every column in the
PII registry is treated:

| Treatment | Example | Used for |
|---|---|---|
| `mask_phone` | +91 9876543210 → +91 98XXXXXX10 | driver phone |
| `mask_licence` | KA0120190012345 → KA01XXXXXXX2345 | driving licence |
| `mask_registration` | KA41AB3932 → KA41XXXX32 | vehicle registration |
| `mask_email` | v01@vendors.example.com → v**@vendors.example.com | email senders |
| `pseudonymise` | V01-DR01 → DRV_a7bc65990125 | driver and vehicle IDs |
| `redact_text` | "call 9876543210" → "call [PHONE]" | free text (email subjects) |
| `drop` | column removed | driver names, file paths |

- **Pseudonymisation** uses HMAC-SHA256 with a secret salt (`VENDOR_PSEUDO_SALT`). The same
  ID always gives the same token, so counts and joins still work, but the real ID can't be
  recovered without the salt.
- **Free-text redaction** catches phone numbers (with or without spaces), emails, licence
  and registration numbers. **Known limit:** names inside free text are not detected; that
  needs a named-entity model and is a planned next step.
- **Before any AI or external service:** text must pass through `redact_text()` first.
- The driver contact table is **synthetic** (made-up names and numbers), generated with its
  own random seed so it changes none of the existing results.

## 3. Data-sharing requests (`src/share.py`, `rules/request_templates.json`)

A request can only run an approved **template**, never free SQL. Each template defines,
for each type of requester, which columns may be shared and which may stay unmasked.

| Check | Rule |
|---|---|
| Who | Requester type must be allowed for the template |
| Why | Every request needs a reference and a named requester |
| Two-person rule | Law-enforcement requests need a legal reference and approval by a *different* person |
| Minimisation | Date ranges are capped (e.g. 92 days); only needed columns are shared |
| Quality | Refused if the latest DQ run had a critical failure |
| Safety | Parameters are bound, never pasted into SQL |
| Traceability | Output file + `manifest.json` (who, what, why, rows, columns, PII treatments, SHA-256) and a row in `audit_log`, **including refused requests** |

`python src/share.py stats` lists the most frequent request types: the ones worth
turning into self-service or full automation.

Fictional example requests and how each became a technical spec: [REQUEST_SPECS.md](REQUEST_SPECS.md).
