"""
Automated data-quality (DQ) framework.

Rules live in rules/dq_rules.json, not in code: an analyst adds a rule by adding
one line. Each rule runs as one SQL query against the central database and
returns the rows that FAIL it.

Outputs (in the database, kept across runs so quality can be tracked over time):
  dq_results     one row per rule per run: rows checked, rows failed, pass rate, status
  dq_exceptions  the failing rows themselves (up to 50 per rule per run) with the reason

The gate: if any CRITICAL rule fails, gate() raises DQGateError, and data sharing
and exports stop until the data is fixed. Warnings are reported but don't block.

Run:  python src/dq.py
"""

import json
import re
from datetime import datetime

import pandas as pd

import config
import database

RULES_PATH = config.ROOT / "rules" / "dq_rules.json"
MAX_EXCEPTIONS_PER_RULE = 50
_IDENT = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")

SCHEMA = """
CREATE TABLE IF NOT EXISTS dq_results (
    run_id TEXT, rule_id TEXT, table_name TEXT, rule_type TEXT, severity TEXT,
    description TEXT, rows_checked INTEGER, rows_failed INTEGER, pass_rate REAL, status TEXT
);
CREATE TABLE IF NOT EXISTS dq_exceptions (
    run_id TEXT, rule_id TEXT, table_name TEXT, row_key TEXT, failed_value TEXT, reason TEXT
);
"""


class DQGateError(RuntimeError):
    """Raised when a critical data-quality rule fails."""


def _ident(name):
    # table/column names come from the rules file; refuse anything that isn't a plain name
    if not _IDENT.match(str(name)):
        raise ValueError(f"unsafe identifier in DQ rules: {name!r}")
    return name


def load_rules(path=None):
    return json.loads((path or RULES_PATH).read_text(encoding="utf-8"))


def failing_rows_sql(rule, key):
    """Return (sql, params) selecting the key and value of every row that fails the rule."""
    t, k = _ident(rule["table"]), _ident(key)
    kind = rule["type"]
    if kind == "not_null":
        c = _ident(rule["column"])
        return f"SELECT {k}, NULL FROM {t} WHERE {c} IS NULL", []
    if kind == "unique":
        cols = [_ident(c) for c in rule["columns"]]
        joined = ", ".join(cols)
        value = " || '|' || ".join(f"CAST({c} AS TEXT)" for c in cols)
        return (f"SELECT {k}, {value} FROM (SELECT *, COUNT(*) OVER (PARTITION BY {joined}) AS n "
                f"FROM {t}) WHERE n > 1"), []
    if kind == "range":
        c = _ident(rule["column"])
        return f"SELECT {k}, {c} FROM {t} WHERE {c} IS NOT NULL AND ({c} < ? OR {c} > ?)", [rule["min"], rule["max"]]
    if kind == "allowed_values":
        c = _ident(rule["column"])
        marks = ", ".join("?" for _ in rule["values"])
        return f"SELECT {k}, {c} FROM {t} WHERE {c} IS NULL OR {c} NOT IN ({marks})", list(rule["values"])
    if kind == "foreign_key":
        c, rt, rc = _ident(rule["column"]), _ident(rule["ref_table"]), _ident(rule["ref_column"])
        return (f"SELECT {k}, {c} FROM {t} WHERE {c} IS NOT NULL "
                f"AND {c} NOT IN (SELECT {rc} FROM {rt} WHERE {rc} IS NOT NULL)"), []
    if kind == "pattern":
        c = _ident(rule["column"])
        return f"SELECT {k}, {c} FROM {t} WHERE {c} IS NULL OR {c} NOT GLOB ?", [rule["glob"]]
    if kind == "not_future":
        c = _ident(rule["column"])
        return f"SELECT {k}, {c} FROM {t} WHERE date({c}) > date(?)", [config.TODAY.isoformat()]
    if kind == "expression":
        # fail_when is a SQL condition written by the rule author (trusted config, not user input)
        return f"SELECT {k}, NULL FROM {t} WHERE {rule['fail_when']}", []
    raise ValueError(f"unknown rule type: {kind}")


def run(conn, rules_doc=None, run_id=None):
    """Run every rule. Returns the results for this run as a DataFrame."""
    conn.executescript(SCHEMA)
    doc = rules_doc or load_rules()
    run_id = run_id or datetime.now().strftime("%Y%m%d_%H%M%S")
    tables = {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    results, exceptions = [], []

    for rule in doc["rules"]:
        t = rule["table"]
        if t not in tables:
            results.append((run_id, rule["id"], t, rule["type"], rule["severity"], rule["description"],
                            0, 0, None, "skipped_table_missing"))
            continue
        total = conn.execute(f"SELECT COUNT(*) FROM {_ident(t)}").fetchone()[0]
        if rule["type"] == "row_count_min":
            failed = 0 if total >= rule["min"] else 1
            rows = [] if failed == 0 else [(None, total)]
        else:
            sql, params = failing_rows_sql(rule, doc["tables"][t]["key"])
            rows = conn.execute(sql, params).fetchall()
            failed = len(rows)
        pass_rate = 1.0 if total == 0 else round(1 - failed / total, 6)
        status = "pass" if failed == 0 else "fail"
        results.append((run_id, rule["id"], t, rule["type"], rule["severity"], rule["description"],
                        total, failed, pass_rate, status))
        for key, value in rows[:MAX_EXCEPTIONS_PER_RULE]:
            exceptions.append((run_id, rule["id"], t, None if key is None else str(key),
                               None if value is None else str(value), rule["description"]))

    conn.executemany("INSERT INTO dq_results VALUES (?,?,?,?,?,?,?,?,?,?)", results)
    conn.executemany("INSERT INTO dq_exceptions VALUES (?,?,?,?,?,?)", exceptions)
    conn.commit()
    return pd.DataFrame(results, columns=["run_id", "rule_id", "table_name", "rule_type", "severity",
                                          "description", "rows_checked", "rows_failed", "pass_rate", "status"])


def gate(results):
    """Stop the pipeline if any critical rule failed."""
    bad = results[(results.severity == "critical") & (results.status == "fail")]
    if len(bad):
        raise DQGateError("critical data-quality rules failed: " + ", ".join(bad.rule_id))
    return {"rules": len(results), "failed_critical": 0,
            "failed_warning": int(((results.severity == "warning") & (results.status == "fail")).sum())}


def scorecard(conn):
    """Latest run's pass rate per table, for the dashboard."""
    return pd.read_sql("""
        SELECT table_name,
               COUNT(*)                                   AS rules,
               SUM(status = 'fail')                       AS rules_failed,
               SUM(status = 'fail' AND severity='critical') AS critical_failed,
               ROUND(AVG(pass_rate), 4)                   AS avg_pass_rate
        FROM dq_results
        WHERE run_id = (SELECT MAX(run_id) FROM dq_results)
        GROUP BY table_name ORDER BY table_name""", conn)


if __name__ == "__main__":
    c = database.connect()
    res = run(c)
    print(res[["rule_id", "severity", "rows_checked", "rows_failed", "status"]].to_string(index=False))
    print(gate(res))
