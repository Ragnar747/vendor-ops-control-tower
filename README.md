# Vendor Ops Control Tower

An end-to-end automation pipeline and Power BI dashboard for running an **intercity cab
vendor programme**: from vendor emails arriving in an inbox to decisions a manager can
act on, with one command.

> All data is **synthetic**, generated to be realistic using public information about
> intercity cab services in India (popular routes, distances, fare levels, weekend peaks).
> No real company data is used.

## Monday, 9 am
Overnight, the pipeline read every vendor email, standardised three different file
layouts, skipped a duplicate and flagged an unreadable one. It reconciled 2,700 vendor
claims against platform records and put **₹41,261** of suspicious claims on hold. It
emailed reminders about expiring vehicle documents, sent every vendor its weekly
scorecard, and warned that **Delhi→Agra will run short of cabs on festival weekends**.
The manager's day starts with decisions, not data entry.

## Modules

| # | Module | File |
|---|---|---|
| 1 | **Email intake:** reads vendor emails (CSV attachments or plain text), saves each unchanged, skips duplicates, flags unreadable ones | `src/intake.py` |
| 2 | **Data quality:** cleans, validates, quarantines, and reports every fix | `src/clean_data.py` |
| 3 | **Central database:** one SQLite file holding every table | `src/database.py` |
| 4 | **Vendor scorecard:** scores and ranks vendors on every route | `src/clean_data.py` |
| 5 | **Trip reconciliation:** vendor claims vs platform records, in SQL (CTEs, window functions) | `sql/reconciliation.sql` |
| 6 | **Compliance alerts:** expiring documents → reminder emails | `src/notify.py` |
| 7 | **What-if simulation:** Monte Carlo: festival demand, vendor offline, allocation policies | `src/simulate.py` |
| 8 | **Weekly reports:** a scorecard per vendor + a manager summary | `src/notify.py` |
| 9 | **One command:** runs everything in order, with a log | `run_all.py` |
| 10 | **Power BI dashboard:** 7 pages | `docs/DASHBOARD_GUIDE.md` |

```
Vendor emails ─► Intake ─► Clean + validate ─► SQLite database
                                                     │
      ┌──────────────┬───────────────┬───────────────┼────────────────┐
      ▼              ▼               ▼               ▼                ▼
  Scorecard   Reconciliation   Compliance      Simulation      Weekly reports
      └──────────────┴───────────────┴───────────────┴────────────────┘
                                     ▼
                           Power BI dashboard
```

## Key findings (synthetic data)
- **Reliability vs capacity:** on Bangalore→Mysore, reassigning cancelled trips to a
  backup vendor cut riders let down on a festival weekend from ~1.9 to ~0.3 a day. On
  Delhi→Agra, ~14 riders a day got no cab at all, and the fix is more vendors, not better rules.
- **Payments:** ₹41,261 of claims flagged across duplicate claims, non-existent trips,
  inflated fares and a cancelled trip claimed as completed; one vendor under-reported
  6 trips and may be owed money.
- **Vendor patterns:** a route specialist, a vendor that collapses on weekends, and one
  getting worse every month.

More in [docs/IDEAS.md](docs/IDEAS.md).

## Run it
```
pip install -r requirements.txt
python run_all.py --fresh      # everything from scratch (~45 s)
python run_all.py              # later runs: processes only new emails
pytest                         # 21 tests
```
Build the dashboard: [docs/DASHBOARD_GUIDE.md](docs/DASHBOARD_GUIDE.md) ·
Connect a real Gmail inbox: [docs/EMAIL_SETUP.md](docs/EMAIL_SETUP.md)

## Design choices
- **Raw emails are saved unchanged** before anything else, so any result can be traced
  back and reprocessed.
- **Idempotent:** running twice never loads the same email or claim twice.
- **Nothing is sent by default:** emails go to `data/outbox/` to be checked first.
- **No passwords in code:** mailbox credentials come from environment variables.
- **Assumptions are settings**, not hidden in the logic (score weights, fare tolerance,
  fleet availability).

## Tech
Python (pandas, NumPy, email/IMAP/SMTP from the standard library) · SQLite · SQL (CTEs,
window functions) · Monte Carlo simulation · Power BI (DAX, star schema, drill-through) ·
pytest · Git. Everything free and open source except Power BI Desktop (free).
