"""
Privacy controls: PII registry, masking, pseudonymisation and free-text redaction.

Principle: personal data stays in the core database. Whenever data LEAVES it
(Power BI exports, reports, data-sharing requests, or text sent to any external
service such as an AI model), every PII column is treated according to
rules/pii_registry.json:

  mask_phone         +91 9876543210      -> +91 98XXXXXX10
  mask_licence       KA0120190012345     -> KA01XXXXXXX2345
  mask_registration  KA41XX3932          -> KA41XXXX32
  mask_email         v01@vendors.com     -> v**@vendors.com
  pseudonymise       V01-DR01            -> DRV_3f9a1c0b7e2d  (same input -> same output,
                                            so joins and counts still work, but the real
                                            ID can't be read back without the secret salt)
  redact_text        "call 9876543210"   -> "call [PHONE]"
  drop               column removed

The driver contact table is synthetic (made-up names and numbers), created here
with its own random seed so that adding it changes none of the existing results.

Run:  python src/privacy.py
"""

import hashlib
import hmac
import json
import os
import re

import numpy as np
import pandas as pd

import config
import database

REGISTRY_PATH = config.ROOT / "rules" / "pii_registry.json"
DEMO_SALT = "demo-salt-not-for-production"
CITY_STATE = {"Bangalore": "KA", "Mumbai": "MH", "Delhi": "DL", "Lucknow": "UP", "Ahmedabad": "GJ"}

FIRST = ["Ravi", "Suresh", "Mahesh", "Anil", "Prakash", "Ramesh", "Vijay", "Manoj", "Sanjay", "Deepak",
         "Arun", "Raju", "Imran", "Salim", "Gurpreet", "Harish", "Naveen", "Kiran", "Ajay", "Mohan"]
LAST = ["Kumar", "Sharma", "Gowda", "Patil", "Yadav", "Singh", "Reddy", "Khan", "Patel", "Verma",
        "Naik", "Shetty", "Joshi", "Mishra", "Pillai"]

PHONE_RE = re.compile(r"(?<!\d)(?:\+91[\s-]?)?[6-9]\d{4}[\s-]?\d{5}(?!\d)")
EMAIL_RE = re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}")
LICENCE_RE = re.compile(r"\b[A-Z]{2}\d{2}\s?\d{4}\s?\d{7}\b")
REGISTRATION_RE = re.compile(r"\b[A-Z]{2}\s?\d{1,2}\s?[A-Z]{1,3}\s?\d{4}\b")


# ---------------- synthetic personal data ----------------
def generate_driver_contacts(drivers, vendors, seed=747):
    """Made-up names, phone numbers and licence numbers for every driver."""
    rng = np.random.default_rng(seed)
    city = drivers.merge(vendors[["vendor_id", "base_city"]], on="vendor_id", how="left").base_city
    n = len(drivers)
    states = city.map(CITY_STATE).fillna("XX")
    return pd.DataFrame({
        "driver_id": drivers.driver_id.values,
        "vendor_id": drivers.vendor_id.values,
        "driver_name": [f"{rng.choice(FIRST)} {rng.choice(LAST)}" for _ in range(n)],
        "phone": [f"+91 {rng.integers(6, 10)}{rng.integers(0, 10**9):09d}" for _ in range(n)],
        "licence_no": [f"{s}{rng.integers(1, 99):02d}{rng.integers(2005, 2024)}{rng.integers(0, 10**7):07d}"
                       for s in states],
    })


# ---------------- treatments ----------------
def mask_phone(v):
    if not isinstance(v, str):
        return v
    digits = re.sub(r"\D", "", v)[-10:]
    if len(digits) < 10:
        return "[PHONE]"
    return f"+91 {digits[:2]}XXXXXX{digits[-2:]}"


def mask_licence(v):
    if not isinstance(v, str) or len(v) < 8:
        return v
    s = v.replace(" ", "")
    return s[:4] + "X" * (len(s) - 8) + s[-4:]


def mask_registration(v):
    if not isinstance(v, str) or len(v) < 6:
        return v
    s = v.replace(" ", "")
    return s[:4] + "X" * (len(s) - 6) + s[-2:]


def mask_email(v):
    if not isinstance(v, str) or "@" not in v:
        return v
    local, domain = v.split("@", 1)
    return local[:1] + "*" * max(len(local) - 1, 1) + "@" + domain


def _salt():
    return os.environ.get("VENDOR_PSEUDO_SALT", DEMO_SALT)


def pseudonymise(v, prefix="ID"):
    if v is None or (isinstance(v, float) and np.isnan(v)):
        return v
    digest = hmac.new(_salt().encode(), str(v).encode(), hashlib.sha256).hexdigest()[:12]
    return f"{prefix}_{digest}"


def redact_text(text):
    """Replace phone numbers, emails, licence and registration numbers inside free text."""
    if not isinstance(text, str):
        return text
    text = EMAIL_RE.sub("[EMAIL]", text)
    text = LICENCE_RE.sub("[LICENCE]", text)
    text = REGISTRATION_RE.sub("[VEHICLE_REG]", text)
    text = PHONE_RE.sub("[PHONE]", text)
    return text


TREATMENTS = {
    "mask_phone": mask_phone,
    "mask_licence": mask_licence,
    "mask_registration": mask_registration,
    "mask_email": mask_email,
    "redact_text": redact_text,
}
PREFIX = {"driver_id": "DRV", "vehicle_id": "VEH"}


def load_registry(path=None):
    return json.loads((path or REGISTRY_PATH).read_text(encoding="utf-8"))["columns"]


def apply_policy(df, table, keep_clear=(), registry=None):
    """Return a copy of df with every registered PII column treated.
    keep_clear: columns a request is explicitly allowed to receive unmasked."""
    registry = registry if registry is not None else load_registry()
    out = df.copy()
    log = []
    for col, rule in registry.get(table, {}).items():
        if col not in out.columns or col in keep_clear:
            continue
        t = rule["treatment"]
        if t == "drop":
            out = out.drop(columns=col)
        elif t == "pseudonymise":
            out[col] = out[col].map(lambda v, p=PREFIX.get(col, "ID"): pseudonymise(v, p))
        else:
            out[col] = out[col].map(TREATMENTS[t])
        log.append((table, col, t))
    return out, log


def export_redacted(conn, tables, out_dir=None):
    """Export tables for Power BI with the PII registry applied."""
    out_dir = out_dir or config.CLEAN_DIR
    out_dir.mkdir(parents=True, exist_ok=True)
    treated = []
    for name in tables:
        df = pd.read_sql(f"SELECT * FROM {name}", conn)
        df, log = apply_policy(df, name)
        df.to_csv(out_dir / f"{name}.csv", index=False)
        treated += log
    return treated


def load_contacts(conn):
    drivers = pd.read_sql("SELECT * FROM drivers", conn)
    vendors = pd.read_sql("SELECT * FROM vendors", conn)
    contacts = generate_driver_contacts(drivers, vendors)
    contacts.to_sql("driver_contacts", conn, if_exists="replace", index=False)
    conn.commit()
    return len(contacts)


def run(conn):
    rows = load_contacts(conn)
    if _salt() == DEMO_SALT:
        print("note: using the demo pseudonymisation salt; set VENDOR_PSEUDO_SALT for real data")
    return {"driver_contacts": rows}


if __name__ == "__main__":
    c = database.connect()
    print(run(c))
    sample = pd.read_sql("SELECT * FROM driver_contacts LIMIT 3", c)
    print(sample.to_string(index=False))
    print(apply_policy(sample, "driver_contacts")[0].to_string(index=False))
