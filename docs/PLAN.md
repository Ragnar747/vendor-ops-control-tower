# 14-day plan: Sat 14 – Fri 27 Nov 2026

About 2–3 hours a day. One task per day; if a day slips, shift the rest.
The code is already written and tested. Your job is to **understand every part well
enough to explain it**, and to **build the dashboard**. Both matter in interviews.

On **Day 1**, also do the 10-minute Google Earth Engine sign-up for the heat project,
since its approval can take time.

## Week 1: understand the pipeline

| Day | Date | Task | Done when |
|---|---|---|---|
| 1 | Sat 14 Nov | Setup: venv, `pip install`, `python run_all.py --fresh`, `pytest`; new GitHub repo; install Power BI Desktop | 21 tests pass; repo on GitHub |
| 2 | Sun 15 Nov | Read `generate_data.py` + `clean_data.py` | You can explain each cleaning step |
| 3 | Mon 16 Nov | Read `generate_emails.py` + `intake.py`; open a few `.eml` files in `data/inbox` | You can explain how a CSV *and* a text email become rows |
| 4 | Tue 17 Nov | Read `sql/reconciliation.sql` slowly; run parts of it yourself in SQLite Viewer | You can explain ROW_NUMBER, the LEFT JOIN and RANK |
| 5 | Wed 18 Nov | Read `simulate.py` + `notify.py`; open emails in `data/outbox` | You can explain the two festival findings |
| 6 | Thu 19 Nov | Read `run_all.py` + the tests; break something on purpose and watch a test fail | You understand why tests matter |
| 7 | Fri 20 Nov | Catch-up + write 5 lines in a learning log | Everything above done |

## Week 2: dashboard and publishing

| Day | Date | Task | Done when |
|---|---|---|---|
| 8 | Sat 21 Nov | Power BI: load data, relationships, all measures | Cards show sensible numbers |
| 9 | Sun 22 Nov | Pages 1–2 (route overview, top 5 by route) | Top 5 matches the answer key |
| 10 | Mon 23 Nov | Pages 3–5 (deep dive, compliance, data quality) | You find the four vendor patterns yourself |
| 11 | Tue 24 Nov | Pages 6–7 (simulator, payments + intake) | ₹41,261 on hold shows correctly |
| 12 | Wed 25 Nov | Polish + screenshots into the README | A dashboard you'd show an employer |
| 13 | Thu 26 Nov | 3-minute demo video + practise explaining it out loud | You can present it without notes |
| 14 | Fri 27 Nov | Publish: GitHub, LinkedIn post; send to your contact with a short feedback request | Shared |

Then the **Indore heat project starts Sat 28 Nov**.
