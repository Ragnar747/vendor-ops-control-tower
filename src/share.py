"""
Data-sharing request engine.

Turns a request from a regulator, an authority, an auditor or an internal team into
a correct, minimal, privacy-safe file, and records it in an audit log.

  1. Pick an approved TEMPLATE (rules/request_templates.json). Free SQL is never run.
  2. Check the requester type is allowed for that template.
  3. Check the parameters: required, correct type, date range not longer than allowed
     (data minimisation: you only get the period you need).
  4. Law-enforcement requests need a legal reference AND approval by a second person.
  5. Data-quality gate: refuse if the latest DQ run had a critical failure.
  6. Run the template's SQL with bound parameters (no string building, no injection).
  7. Keep only the columns this requester type may receive; mask, pseudonymise or
     drop every PII column unless the policy explicitly allows it in clear.
  8. Write the file + a manifest (who, what, why, row count, columns, SHA-256 checksum).
  9. Record everything in audit_log, including refused requests.

Command line (self-service, no SQL needed):
  python src/share.py list
  python src/share.py run --template trips_by_vehicle --requester-type regulator \\
      --reference RTO/2026/118 --requested-by ops.analyst \\
      --param registration_no=KA41XX3932 --param date_from=2026-09-01 --param date_to=2026-09-30
  python src/share.py stats       # which requests recur most: candidates for automation
"""

import argparse
import hashlib
import json
from datetime import date, datetime

import pandas as pd

import config
import database
import privacy

TEMPLATES_PATH = config.ROOT / "rules" / "request_templates.json"
REQUEST_SQL_DIR = config.SQL_DIR / "requests"

AUDIT_SCHEMA = """
CREATE TABLE IF NOT EXISTS audit_log (
    request_id     TEXT PRIMARY KEY,
    created_at     TEXT,
    template       TEXT,
    requester_type TEXT,
    reference      TEXT,
    requested_by   TEXT,
    approved_by    TEXT,
    params_json    TEXT,
    outcome        TEXT,      -- fulfilled / refused
    reason         TEXT,
    rows_shared    INTEGER,
    columns_shared TEXT,
    pii_treatments TEXT,
    file_path      TEXT,
    sha256         TEXT,
    dq_run_id      TEXT
);
"""


class RequestRefused(ValueError):
    """The request breaks a rule; nothing is shared."""


def load_templates(path=None):
    return json.loads((path or TEMPLATES_PATH).read_text(encoding="utf-8"))["templates"]


def _new_request_id(template, params, now):
    h = hashlib.sha256(f"{template}{sorted(params.items())}{now.isoformat()}".encode()).hexdigest()[:6]
    return f"REQ-{now:%Y%m%d-%H%M%S}-{h}"


def _check_params(tpl, params):
    missing = [p for p in tpl["params"] if not params.get(p)]
    if missing:
        raise RequestRefused(f"missing parameters: {', '.join(missing)}")
    extra = [p for p in params if p not in tpl["params"]]
    if extra:
        raise RequestRefused(f"unknown parameters: {', '.join(extra)}")
    dates = {}
    for name, kind in tpl["params"].items():
        if kind == "date":
            try:
                dates[name] = date.fromisoformat(params[name])
            except ValueError:
                raise RequestRefused(f"{name} must be a date like 2026-09-30") from None
    if "date_from" in dates and "date_to" in dates:
        span = (dates["date_to"] - dates["date_from"]).days + 1
        if span < 1:
            raise RequestRefused("date_from is after date_to")
        if tpl.get("max_days") and span > tpl["max_days"]:
            raise RequestRefused(f"date range is {span} days; this template allows at most {tpl['max_days']} "
                                 "(share only the period the request needs)")


def _check_dq(conn):
    has = conn.execute("SELECT 1 FROM sqlite_master WHERE name='dq_results'").fetchone()
    if not has:
        raise RequestRefused("no data-quality run found; run the pipeline first")
    run_id, failed = conn.execute("""
        SELECT run_id, SUM(status='fail' AND severity='critical') FROM dq_results
        WHERE run_id = (SELECT MAX(run_id) FROM dq_results) GROUP BY run_id""").fetchone()
    if failed:
        raise RequestRefused(f"latest data-quality run {run_id} has {failed} critical failure(s)")
    return run_id


def _audit(conn, row):
    conn.executescript(AUDIT_SCHEMA)
    cols = list(row)
    conn.execute(f"INSERT INTO audit_log ({', '.join(cols)}) VALUES ({', '.join('?' for _ in cols)})",
                 [row[c] for c in cols])
    conn.commit()


def fulfil(conn, template, params, requester_type, reference, requested_by,
           approved_by=None, out_dir=None, now=None, templates=None):
    """Run one request. Returns the manifest dict. Raises RequestRefused (and logs it) if not allowed."""
    now = now or datetime.now()
    templates = templates or load_templates()
    request_id = _new_request_id(template, params, now)
    base = {"request_id": request_id, "created_at": now.isoformat(timespec="seconds"), "template": template,
            "requester_type": requester_type, "reference": reference, "requested_by": requested_by,
            "approved_by": approved_by, "params_json": json.dumps(params, sort_keys=True)}
    try:
        if template not in templates:
            raise RequestRefused(f"unknown template '{template}'")
        tpl = templates[template]
        policy = tpl["policies"].get(requester_type)
        if policy is None:
            raise RequestRefused(f"requester type '{requester_type}' may not use '{template}'")
        if not reference or not requested_by:
            raise RequestRefused("every request needs a reference and the name of who asked for it")
        if policy.get("requires_legal_reference") and len(reference.strip()) < 6:
            raise RequestRefused("this request type needs a valid legal reference (e.g. notice number)")
        if policy.get("requires_approval"):
            if not approved_by:
                raise RequestRefused("this request type needs approval by a second person")
            if approved_by == requested_by:
                raise RequestRefused("the approver must be a different person from the requester")
        _check_params(tpl, params)
        dq_run = _check_dq(conn)

        sql = (REQUEST_SQL_DIR / tpl["sql"]).read_text(encoding="utf-8")
        df = pd.read_sql(sql, conn, params=params)
        df = df[[c for c in policy["columns"] if c in df.columns]]

        # PII: build a registry for this output from the source tables' rules
        full = privacy.load_registry()
        out_reg = {"_out": {col: full[src][col] for col, src in tpl["pii_source"].items()
                            if src in full and col in full[src]}}
        df, treatments = privacy.apply_policy(df, "_out", keep_clear=set(policy["keep_clear"]),
                                              registry=out_reg)

        folder = (out_dir or config.SHARED_DIR) / request_id
        folder.mkdir(parents=True, exist_ok=True)
        path = folder / f"{template}.csv"
        df.to_csv(path, index=False)
        digest = hashlib.sha256(path.read_bytes()).hexdigest()
        manifest = {**base, "params": params, "title": tpl["title"], "rows": len(df), "columns": list(df.columns),
                    "pii_treatments": {c: t for _, c, t in treatments},
                    "kept_clear": [c for c in policy["keep_clear"] if c in df.columns],
                    "file": path.name, "sha256": digest, "dq_run_id": dq_run}
        manifest.pop("params_json")
        (folder / "manifest.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")
        _audit(conn, {**base, "outcome": "fulfilled", "reason": None, "rows_shared": len(df),
                      "columns_shared": ",".join(df.columns), "pii_treatments": json.dumps(manifest["pii_treatments"]),
                      "file_path": str(path), "sha256": digest, "dq_run_id": dq_run})
        return manifest
    except RequestRefused as e:
        _audit(conn, {**base, "outcome": "refused", "reason": str(e), "rows_shared": 0})
        raise


def stats(conn):
    """Recurring request types: the ones worth automating or turning into self-service."""
    conn.executescript(AUDIT_SCHEMA)
    return pd.read_sql("""
        SELECT template, requester_type,
               COUNT(*) AS requests,
               SUM(outcome='fulfilled') AS fulfilled,
               SUM(outcome='refused')   AS refused,
               MAX(created_at)          AS last_request
        FROM audit_log GROUP BY template, requester_type
        ORDER BY requests DESC""", conn)


def main():
    ap = argparse.ArgumentParser(description="Data-sharing requests")
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("list")
    sub.add_parser("stats")
    r = sub.add_parser("run")
    r.add_argument("--template", required=True)
    r.add_argument("--requester-type", required=True)
    r.add_argument("--reference", required=True)
    r.add_argument("--requested-by", required=True)
    r.add_argument("--approved-by")
    r.add_argument("--param", action="append", default=[], help="name=value (repeat)")
    a = ap.parse_args()

    conn = database.connect()
    if a.cmd == "list":
        for name, t in load_templates().items():
            print(f"{name}: {t['title']}\n  params: {', '.join(t['params'])}\n"
                  f"  requester types: {', '.join(t['policies'])}\n")
    elif a.cmd == "stats":
        print(stats(conn).to_string(index=False))
    else:
        params = dict(p.split("=", 1) for p in a.param)
        try:
            m = fulfil(conn, a.template, params, a.requester_type, a.reference, a.requested_by, a.approved_by)
            print(f"{m['request_id']}: {m['rows']} rows -> {config.SHARED_DIR / m['request_id'] / m['file']}")
            print(f"columns: {', '.join(m['columns'])}\nPII treatments: {m['pii_treatments']}\nsha256: {m['sha256']}")
        except RequestRefused as e:
            print(f"REFUSED (logged): {e}")


if __name__ == "__main__":
    main()
