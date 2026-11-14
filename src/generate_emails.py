"""
Create a FAKE vendor mailbox (.eml files) for the last two weeks of trips.

Each vendor emails a weekly trip log. Like real life, they don't all do it the same way:
  - three different CSV column styles
  - some vendors write the trips in the email text instead of attaching a file

Hidden problems for the pipeline to catch (see docs/ANSWER_KEY.md):
  - V11 overclaims fares on some trips
  - V18 reports some of its cancelled trips as "completed"
  - V05 lists trips that don't exist on the platform
  - V16 forgets to report some completed trips (it may be owed money)
  - V20 lists some trips twice
  - V09 sends its second weekly email twice (same email)
  - one email comes from an unknown sender
  - one vendor email has no readable trip data at all

Run: python src/generate_emails.py      (needs data/clean/trips.csv)
"""

from datetime import date, datetime, timedelta
from email.message import EmailMessage
from email.utils import format_datetime

import numpy as np
import pandas as pd

import config

WEEKS = [date(2026, 10, 24), date(2026, 10, 31)]     # week-ending dates
TEXT_VENDORS = {"V07", "V14", "V21", "V28"}          # write trips in the email body

STYLES = {
    # style: (column names, how the fare is written)
    "A": (["trip_id", "trip_date", "route", "status", "fare_inr"], lambda f: f"{f:.0f}"),
    "B": (["Trip No", "Trip Date", "Route", "Trip Status", "Amount (Rs)"], lambda f: f"{f:.2f}"),
    "C": (["TRIP_ID", "DATE", "FROM-TO", "STATUS", "FARE"], lambda f: f"Rs {f:,.0f}"),
}


def vendor_email(vendor_id):
    return f"{vendor_id.lower()}@{config.VENDOR_EMAIL_DOMAIN}"


def style_for(vendor_id):
    return "ABC"[int(vendor_id[1:]) % 3]


def build_log(rng, vendor_id, week_trips, phantom_start):
    """The trips this vendor *claims*: normally its completed trips, plus planted errors."""
    done = week_trips[week_trips.status == "completed"]
    rows = [(t.trip_id, t.trip_date, t.route_name, "completed", float(t.fare_inr))
            for t in done.itertuples()]

    if vendor_id == "V11":            # overclaims fares on ~15% of trips
        for i in rng.choice(len(rows), max(1, len(rows) // 7), replace=False):
            r = rows[i]
            rows[i] = (*r[:4], r[4] + float(rng.integers(250, 601)))
    if vendor_id == "V18":            # reports its own cancellations as completed
        for t in week_trips[week_trips.status == "cancelled_by_vendor"].itertuples():
            rows.append((t.trip_id, t.trip_date, t.route_name, "completed",
                         float(rng.integers(1500, 3000))))
    if vendor_id == "V05":            # trips that don't exist
        for k in range(3):
            rows.append((f"T9{phantom_start + k:05d}", str(week_trips.trip_date.max()),
                         week_trips.route_name.iloc[0], "completed", float(rng.integers(1800, 2600))))
    if vendor_id == "V16" and len(rows) > 3:   # forgets to report some trips
        for i in sorted(rng.choice(len(rows), 3, replace=False), reverse=True):
            rows.pop(i)
    if vendor_id == "V20" and rows:   # duplicate lines
        rows += [rows[i] for i in rng.choice(len(rows), min(5, len(rows)), replace=False)]
    return rows


def make_message(sender, subject, sent_at, message_id, body, attachment=None):
    msg = EmailMessage()
    msg["From"] = sender
    msg["To"] = config.OPS_TEAM_EMAIL
    msg["Subject"] = subject
    msg["Date"] = format_datetime(sent_at)
    msg["Message-ID"] = message_id
    msg.set_content(body)
    if attachment:
        filename, text = attachment
        msg.add_attachment(text.encode("utf-8"), maintype="text", subtype="csv", filename=filename)
    return msg


def main():
    rng = np.random.default_rng(11)
    trips = pd.read_csv(config.CLEAN_DIR / "trips.csv")
    routes = pd.read_csv(config.CLEAN_DIR / "routes.csv")
    vendors = pd.read_csv(config.CLEAN_DIR / "vendors.csv")
    trips = trips.merge(routes[["route_id", "route_name"]], on="route_id")

    config.INBOX_DIR.mkdir(parents=True, exist_ok=True)
    for old in config.INBOX_DIR.glob("*.eml"):
        old.unlink()

    contacts = pd.DataFrame({"vendor_id": vendors.vendor_id,
                             "email": vendors.vendor_id.map(vendor_email)})
    contacts.to_csv(config.CLEAN_DIR / "vendor_contacts.csv", index=False)

    count, phantom = 0, 0
    for week_end in WEEKS:
        week_start = week_end - timedelta(days=6)
        in_week = trips[(trips.trip_date >= str(week_start)) & (trips.trip_date <= str(week_end))]
        for vendor_id in vendors.vendor_id:
            rows = build_log(rng, vendor_id, in_week[in_week.vendor_id == vendor_id], phantom)
            phantom += 3
            sent_at = datetime(week_end.year, week_end.month, week_end.day, 20, 0) \
                + timedelta(days=1, minutes=int(rng.integers(0, 600)))
            message_id = f"<{vendor_id}-{week_end}@{config.VENDOR_EMAIL_DOMAIN}>"
            subject = f"Weekly trip log - {vendor_id} - week ending {week_end}"
            greeting = f"Hello team,\n\nPlease find our trip log for the week ending {week_end}.\n"

            if vendor_id == "V24" and week_end == WEEKS[1]:
                # a vendor email with nothing machine-readable in it
                msg = make_message(vendor_email(vendor_id), subject, sent_at, message_id,
                                   greeting + "Our accountant will send the details on Monday.\n\nRegards")
            elif vendor_id in TEXT_VENDORS:
                lines = [f"Trip {t} on {d}: {s}, fare Rs {f:,.0f}" for t, d, _, s, f in rows]
                msg = make_message(vendor_email(vendor_id), subject, sent_at, message_id,
                                   greeting + "\n" + "\n".join(lines) + "\n\nRegards")
            else:
                cols, fare_fmt = STYLES[style_for(vendor_id)]
                csv_df = pd.DataFrame([(t, d, r, s, fare_fmt(f)) for t, d, r, s, f in rows], columns=cols)
                msg = make_message(vendor_email(vendor_id), subject, sent_at, message_id,
                                   greeting + "\nRegards",
                                   (f"{vendor_id}_trips_{week_end}.csv", csv_df.to_csv(index=False)))

            path = config.INBOX_DIR / f"{week_end}_{vendor_id}.eml"
            path.write_bytes(bytes(msg))
            count += 1
            if vendor_id == "V09" and week_end == WEEKS[1]:     # sent twice by mistake
                (config.INBOX_DIR / f"{week_end}_{vendor_id}_resent.eml").write_bytes(bytes(msg))
                count += 1

    spam = make_message("offers@cheap-cabs.example.net", "Special offer for fleet owners!",
                        datetime(2026, 11, 1, 9, 0), "<offer-1@cheap-cabs.example.net>",
                        "Buy tyres at 50% off.")
    (config.INBOX_DIR / "2026-11-01_unknown_sender.eml").write_bytes(bytes(spam))
    print(f"{count + 1} emails written to {config.INBOX_DIR}")


if __name__ == "__main__":
    main()
