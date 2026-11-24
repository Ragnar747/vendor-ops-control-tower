"""
All settings in one place.

Passwords are NEVER written in code. For real email, set them as environment
variables in the terminal before running (see docs/EMAIL_SETUP.md):
    $env:VENDOR_IMAP_USER = "you@gmail.com"
    $env:VENDOR_IMAP_PASSWORD = "your 16-character app password"
"""

import os
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = ROOT / "data"
RAW_DIR = DATA_DIR / "raw"                 # generated / exported source files
CLEAN_DIR = DATA_DIR / "clean"             # cleaned tables + CSV exports for Power BI
INBOX_DIR = DATA_DIR / "inbox"             # demo mailbox: .eml files
BRONZE_EMAIL_DIR = DATA_DIR / "bronze" / "emails"   # every email saved unchanged
OUTBOX_DIR = DATA_DIR / "outbox"           # emails the system would send
LOG_DIR = DATA_DIR / "logs"
SHARED_DIR = DATA_DIR / "shared"           # files produced for data-sharing requests
DB_PATH = DATA_DIR / "control_tower.db"    # the central SQLite database
SQL_DIR = ROOT / "sql"

TODAY = date(2026, 11, 13)                 # fixed "today" so results are repeatable

# ---------------- email intake ----------------
MAILBOX = os.environ.get("VENDOR_MAILBOX", "local")   # "local" (demo folder) or "imap"
IMAP_HOST = os.environ.get("VENDOR_IMAP_HOST", "imap.gmail.com")
IMAP_USER = os.environ.get("VENDOR_IMAP_USER", "")
IMAP_PASSWORD = os.environ.get("VENDOR_IMAP_PASSWORD", "")
IMAP_FOLDER = os.environ.get("VENDOR_IMAP_FOLDER", "INBOX")
VENDOR_EMAIL_DOMAIN = "vendors.example.com"   # demo vendors' email domain

# ---------------- outgoing email ----------------
SEND_EMAILS = os.environ.get("VENDOR_SEND_EMAILS", "false").lower() == "true"
SMTP_HOST = os.environ.get("VENDOR_SMTP_HOST", "smtp.gmail.com")
SMTP_PORT = int(os.environ.get("VENDOR_SMTP_PORT", "587"))
OPS_TEAM_EMAIL = "vendor-ops@example.com"
MANAGER_EMAIL = "ops-manager@example.com"

# ---------------- reconciliation ----------------
FARE_TOLERANCE_INR = 10       # differences up to Rs 10 count as a match
