"""
Modules 6 and 8: automatic emails.

  - Compliance reminders: one email per vendor listing documents that have expired
    or expire within 30 days.
  - Weekly scorecards: one email per vendor with its scores, ranks and any
    reconciliation issues.
  - Manager summary: one email with what needs attention this week.

By default nothing is sent: every email is saved to data/outbox/ as an .eml file you
can open and check. To really send, see docs/EMAIL_SETUP.md (VENDOR_SEND_EMAILS=true).

Run: python src/notify.py
"""

import smtplib
from email.message import EmailMessage
from email.utils import format_datetime
from datetime import datetime

import pandas as pd

import config
import database

STYLE = ("font-family:Arial,sans-serif;font-size:14px;color:#222",
         "border-collapse:collapse", "border:1px solid #ccc;padding:4px 8px")


def table_html(df):
    _, tbl, cell = STYLE
    head = "".join(f"<th style='{cell};background:#f2f2f2'>{c}</th>" for c in df.columns)
    rows = "".join("<tr>" + "".join(f"<td style='{cell}'>{v}</td>" for v in r) + "</tr>"
                   for r in df.astype(str).itertuples(index=False))
    return f"<table style='{tbl}'><tr>{head}</tr>{rows}</table>"


def build_email(to, subject, html, text):
    msg = EmailMessage()
    msg["From"] = config.OPS_TEAM_EMAIL
    msg["To"] = to
    msg["Subject"] = subject
    msg["Date"] = format_datetime(datetime(config.TODAY.year, config.TODAY.month, config.TODAY.day, 9, 0))
    msg.set_content(text)
    msg.add_alternative(f"<div style='{STYLE[0]}'>{html}</div>", subtype="html")
    return msg


def compliance_reminders(conn, contacts):
    alerts = pd.read_sql("SELECT * FROM document_alerts", conn)
    messages = []
    for vendor_id, docs in alerts.groupby("vendor_id"):
        docs = docs.sort_values("days_left")[["asset_id", "document", "expiry_date", "days_left", "status"]]
        expired = (docs.status == "EXPIRED").sum()
        subject = (f"ACTION NEEDED: {expired} expired document(s)" if expired
                   else "Reminder: documents expiring soon") + f" - {vendor_id}"
        intro = ("Some of your vehicle or driver documents have expired or will expire within "
                 "30 days. Vehicles with expired documents cannot be assigned trips.")
        html = f"<p>Hello,</p><p>{intro}</p>{table_html(docs)}<p>Please upload renewed documents.</p>"
        text = intro + "\n\n" + docs.to_string(index=False)
        messages.append(("compliance", vendor_id, build_email(contacts[vendor_id], subject, html, text)))
    return messages


def weekly_scorecards(conn, contacts):
    scores = pd.read_sql("""
        SELECT vendor_id, route_name, trips, rank_on_route AS rank,
               ROUND(vendor_score, 1) AS score,
               ROUND(100 * completion_rate, 1) AS completion_pct,
               ROUND(100 * on_time_rate, 1) AS on_time_pct,
               ROUND(avg_rating, 2) AS avg_rating
        FROM vendor_route_scores""", conn)
    recon = pd.read_sql("SELECT * FROM reconciliation_summary", conn).set_index("vendor_id")
    messages = []
    for vendor_id, s in scores.groupby("vendor_id"):
        s = s.drop(columns="vendor_id")
        html = f"<p>Hello,</p><p>Your performance for the last six months, by route:</p>{table_html(s)}"
        text = s.to_string(index=False)
        if vendor_id in recon.index and recon.loc[vendor_id, "issues"] > 0:
            r = recon.loc[vendor_id]
            note = (f"We found {int(r.issues)} issue(s) in your trip logs "
                    f"(Rs {r.amount_at_risk_inr:,.0f} under review). Our team will contact you.")
            html += f"<p><b>{note}</b></p>"
            text += "\n\n" + note
        if vendor_id in recon.index and recon.loc[vendor_id, "unclaimed_completed_trips"] > 0:
            note = (f"{int(recon.loc[vendor_id, 'unclaimed_completed_trips'])} completed trip(s) were "
                    "missing from your logs. Please check: you may be owed payment.")
            html += f"<p><b>{note}</b></p>"
            text += "\n" + note
        messages.append(("weekly", vendor_id,
                         build_email(contacts[vendor_id], f"Your weekly scorecard - {vendor_id}", html, text)))
    return messages


def manager_summary(conn):
    recon = pd.read_sql("""SELECT vendor_id, issues, amount_at_risk_inr, unclaimed_completed_trips
                           FROM reconciliation_summary
                           WHERE issues > 0 OR unclaimed_completed_trips > 0
                           ORDER BY risk_rank""", conn)
    alerts = pd.read_sql("SELECT status, COUNT(*) AS documents FROM document_alerts GROUP BY status", conn)
    sim = pd.read_sql("""SELECT route_name, ROUND(avg_no_cab_available, 1) AS riders_with_no_cab_per_day
                         FROM simulation_results
                         WHERE scenario LIKE 'Festival%' AND policy = 'Current allocation'
                           AND avg_no_cab_available >= 1
                         ORDER BY avg_no_cab_available DESC""", conn)
    gains = pd.read_sql("""
        WITH f AS (SELECT route_name, policy, riders_let_down_avg FROM simulation_results
                   WHERE scenario LIKE 'Festival%')
        SELECT a.route_name,
               ROUND(a.riders_let_down_avg, 1) AS let_down_now,
               ROUND(b.riders_let_down_avg, 1) AS with_backup_reassignment
        FROM f a JOIN f b ON a.route_name = b.route_name
        WHERE a.policy = 'Current allocation' AND b.policy = 'Score-based + backup reassignment'
        ORDER BY a.riders_let_down_avg - b.riders_let_down_avg DESC LIMIT 5""", conn)
    emails = pd.read_sql("SELECT status, COUNT(*) AS emails FROM email_log GROUP BY status", conn)

    total_risk = recon.amount_at_risk_inr.sum()
    html = (f"<h3>Vendor operations: week summary</h3>"
            f"<p><b>1. Payments on hold:</b> Rs {total_risk:,.0f} across {len(recon)} vendor(s).</p>"
            f"{table_html(recon)}"
            f"<p><b>2. Compliance:</b></p>{table_html(alerts)}"
            f"<p><b>3. Festival weekend risk</b> (no cab available, current set-up):</p>{table_html(sim)}"
            f"<p>Fix: onboard more vendors on these routes before the festival.</p>"
            f"<p><b>4. Quick win:</b> backup reassignment of cancelled trips (simulated):</p>{table_html(gains)}"
            f"<p><b>5. Email intake:</b></p>{table_html(emails)}")
    text = (f"Payments on hold: Rs {total_risk:,.0f}\n\n{recon.to_string(index=False)}\n\n"
            f"{alerts.to_string(index=False)}\n\n{sim.to_string(index=False)}\n\n"
            f"{gains.to_string(index=False)}\n\n{emails.to_string(index=False)}")
    return [("manager", "summary", build_email(config.MANAGER_EMAIL, "Vendor ops: this week's summary", html, text))]


def deliver(messages):
    """Save every email to the outbox; send only if SEND_EMAILS is switched on."""
    for kind, name, msg in messages:
        folder = config.OUTBOX_DIR / kind
        folder.mkdir(parents=True, exist_ok=True)
        (folder / f"{name}.eml").write_bytes(bytes(msg))
    if config.SEND_EMAILS:
        with smtplib.SMTP(config.SMTP_HOST, config.SMTP_PORT) as smtp:
            smtp.starttls()
            smtp.login(config.IMAP_USER, config.IMAP_PASSWORD)
            for _, _, msg in messages:
                smtp.send_message(msg)
    return len(messages)


def run(conn):
    contacts = dict(pd.read_csv(config.CLEAN_DIR / "vendor_contacts.csv").values)
    messages = compliance_reminders(conn, contacts) + weekly_scorecards(conn, contacts) + manager_summary(conn)
    count = deliver(messages)
    kinds = pd.Series([k for k, _, _ in messages]).value_counts().to_dict()
    return {"emails": count, **kinds, "sent": config.SEND_EMAILS}


if __name__ == "__main__":
    print(run(database.connect()))
