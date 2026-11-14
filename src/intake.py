"""
Module 1: email intake.

Reads vendor emails, saves each one unchanged (bronze), extracts the trip log from a
CSV attachment or from the email text, and stores the rows in the database.

  - An email already processed (same Message-ID) is skipped: no double-loading.
  - Emails from unknown senders are logged and ignored.
  - Emails with no readable trip data are flagged for a person to check.

Two mailbox sources:
  - "local": .eml files in data/inbox/ (the demo; works offline)
  - "imap":  a real mailbox such as Gmail (see docs/EMAIL_SETUP.md)

Run: python src/intake.py
"""

import email
import imaplib
import io
import re
from email import policy
from email.utils import parseaddr, parsedate_to_datetime

import pandas as pd

import config
import database

# Every way vendors name a column -> our standard name
COLUMN_MAP = {
    "trip_id": "trip_id", "trip no": "trip_id", "trip_no": "trip_id", "trip id": "trip_id",
    "trip_date": "trip_date", "trip date": "trip_date", "date": "trip_date",
    "status": "claimed_status", "trip status": "claimed_status",
    "fare_inr": "claimed_fare_inr", "amount (rs)": "claimed_fare_inr", "fare": "claimed_fare_inr",
    "amount": "claimed_fare_inr",
    "route": "route", "from-to": "route",
}
# "Trip T012345 on 2026-10-20: completed, fare Rs 2,150"
TEXT_LINE = re.compile(
    r"Trip\s+(?P<trip_id>T\d{6,7})\s+on\s+(?P<trip_date>\d{4}-\d{2}-\d{2})\s*:\s*"
    r"(?P<claimed_status>[A-Za-z_ ]+?)\s*,\s*fare\s*Rs\.?\s*(?P<claimed_fare_inr>[\d,]+(?:\.\d+)?)",
    re.IGNORECASE)


# ---------------- mailbox sources ----------------
def local_messages(folder=None):
    """Yield raw emails from a folder of .eml files (the offline demo)."""
    folder = folder or config.INBOX_DIR
    for path in sorted(folder.glob("*.eml")):
        yield path.read_bytes()


def imap_messages():
    """Yield raw emails from a real mailbox. Read-only: nothing is deleted or marked."""
    if not (config.IMAP_USER and config.IMAP_PASSWORD):
        raise SystemExit("Set VENDOR_IMAP_USER and VENDOR_IMAP_PASSWORD first (docs/EMAIL_SETUP.md).")
    with imaplib.IMAP4_SSL(config.IMAP_HOST) as box:
        box.login(config.IMAP_USER, config.IMAP_PASSWORD)
        box.select(config.IMAP_FOLDER, readonly=True)
        _, ids = box.search(None, f'(FROM "@{config.VENDOR_EMAIL_DOMAIN}")')
        for num in ids[0].split():
            _, data = box.fetch(num, "(RFC822)")
            yield data[0][1]


# ---------------- parsing ----------------
def clean_fare(value):
    """'Rs 2,150' / '2150.00' / 2150 -> 2150.0"""
    text = re.sub(r"[^\d.]", "", str(value))
    return float(text) if text else None


def standardise(df):
    df = df.rename(columns=lambda c: COLUMN_MAP.get(str(c).strip().lower(), str(c).strip().lower()))
    needed = ["trip_id", "trip_date", "claimed_status", "claimed_fare_inr"]
    missing = [c for c in needed if c not in df.columns]
    if missing:
        raise ValueError(f"unknown columns, missing {missing}")
    df = df[needed].copy()
    df["trip_id"] = df.trip_id.astype(str).str.strip().str.upper()
    df["trip_date"] = pd.to_datetime(df.trip_date).dt.strftime("%Y-%m-%d")
    df["claimed_status"] = df.claimed_status.astype(str).str.strip().str.lower().str.replace(" ", "_")
    df["claimed_fare_inr"] = df.claimed_fare_inr.map(clean_fare)
    return df


def extract_rows(msg):
    """Return (rows DataFrame, source_type). Tries CSV attachments, then the email text."""
    for part in msg.iter_attachments():
        name = (part.get_filename() or "").lower()
        if name.endswith(".csv"):
            content = part.get_content()
            text = content if isinstance(content, str) else content.decode("utf-8")
            return standardise(pd.read_csv(io.StringIO(text))), "csv"
    body = msg.get_body(preferencelist=("plain",))
    text = body.get_content() if body else ""
    found = [m.groupdict() for m in TEXT_LINE.finditer(text)]
    if found:
        return standardise(pd.DataFrame(found)), "text"
    return pd.DataFrame(), "none"


def vendor_for(sender, contacts):
    return contacts.get(parseaddr(sender)[1].lower())


def process(raw, conn, contacts):
    """Process one raw email. Returns its status."""
    msg = email.message_from_bytes(raw, policy=policy.default)
    message_id = (msg["Message-ID"] or "").strip()
    if conn.execute("SELECT 1 FROM email_log WHERE message_id = ?", (message_id,)).fetchone():
        return "skipped_duplicate"

    config.BRONZE_EMAIL_DIR.mkdir(parents=True, exist_ok=True)
    safe = re.sub(r"[^A-Za-z0-9._-]", "_", message_id.strip("<>"))
    raw_path = config.BRONZE_EMAIL_DIR / f"{safe}.eml"
    raw_path.write_bytes(raw)                                     # bronze: unchanged copy

    sender = msg["From"] or ""
    vendor_id = vendor_for(sender, contacts)
    received = parsedate_to_datetime(msg["Date"]).isoformat() if msg["Date"] else None
    rows, source = pd.DataFrame(), "none"
    if vendor_id is None:
        status = "ignored_unknown_sender"
    else:
        try:
            rows, source = extract_rows(msg)
            status = "processed" if len(rows) else "needs_manual_review"
        except Exception as err:                                  # unreadable file
            status = f"needs_manual_review: {err}"

    conn.execute("INSERT INTO email_log VALUES (?,?,?,?,?,?,?,?,?)",
                 (message_id, vendor_id, sender, msg["Subject"], received, source,
                  len(rows), status.split(":")[0], str(raw_path)))
    if len(rows):
        rows.insert(0, "vendor_id", vendor_id)
        rows["source_message_id"] = message_id
        rows["source_type"] = source
        rows.to_sql("vendor_trip_logs", conn, if_exists="append", index=False)
    conn.commit()
    return status.split(":")[0]


def run(conn, messages=None):
    contacts_df = pd.read_csv(config.CLEAN_DIR / "vendor_contacts.csv")
    contacts = dict(zip(contacts_df.email.str.lower(), contacts_df.vendor_id))
    if messages is None:
        messages = imap_messages() if config.MAILBOX == "imap" else local_messages()
    summary = {}
    for raw in messages:
        status = process(raw, conn, contacts)
        summary[status] = summary.get(status, 0) + 1
    return summary


if __name__ == "__main__":
    connection = database.connect()
    print(run(connection))
