# Five ideas for an intercity vendor programme

Built and tested on synthetic data. Each idea comes with what the prototype measured.
These are suggestions to consider, not claims about any real company's operations.

## 1. Reassign cancelled trips to a backup vendor, instantly
**Measured (simulation, festival weekend):** riders let down per day on Bangalore→Mysore
fell from about **1.9 to 0.3**; on Mysore→Bangalore from **2.2 to 0.1**.
**Why it works:** most failures on these routes are cancellations, not a lack of cabs.
Spare capacity already exists; it just isn't used when a vendor drops a trip.

## 2. Treat capacity and reliability as different problems
**Measured:** on Delhi→Agra and Mumbai→Pune, about **14 riders a day** got no cab at all
on a simulated festival weekend, and no allocation rule helped, because every vendor
was full. **Action:** onboard extra vendors on those corridors *before* festival season;
reassignment rules won't fix a capacity gap.

## 3. Reconcile vendor trip logs automatically, every week
**Measured:** across two weeks of logs, **₹41,261** of claims were flagged before
payment: duplicate claims, trips that didn't exist, inflated fares and a cancelled trip
claimed as completed. The same check also found a vendor that **under-reported 6 trips**
and may be owed money. Automatic checks protect both sides.

## 4. Accept vendor data in any format, but standardise it on arrival
**Measured:** 61 of 64 emails were processed with no manual work, across three different
CSV layouts and plain-text emails. Duplicates were skipped, spam was ignored, and the one
unreadable email was flagged for a person. Vendors keep their habits; the pipeline adapts.

## 5. Send every vendor its own scorecard
Weekly emails with each vendor's score and rank per route, plus any issues found.
Patterns the dashboard revealed (a vendor that cancels on weekends, one getting worse
every month) are much cheaper to fix in week 2 than in month 5.

---
*All data in this project is synthetic. Assumptions are listed in `docs/ANSWER_KEY.md`
and are settings in the code, so they can be changed and re-tested.*
