"""
Vendor Ops Control Tower: run the whole pipeline with one command.

  python run_all.py            normal run (reuses existing data, processes new emails only)
  python run_all.py --fresh    start from scratch: new data, empty database, new demo mailbox

Steps:
  1. generate platform data (only if missing, or with --fresh)
  2. clean + score                       (clean_data.py)
  3. what-if simulation                  (simulate.py)
  4. load the central database           (database.py)
  5. demo mailbox (only if empty)        (generate_emails.py)
  6. email intake                        (intake.py)
  7. trip reconciliation in SQL          (reconcile.py)
  8. compliance reminders + reports      (notify.py)
  9. export tables for Power BI

Every run writes a log to data/logs/. To run it every morning on Windows, see
docs/EMAIL_SETUP.md (Task Scheduler).
"""

import argparse
import logging
import shutil
import sys
import time
import warnings
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT / "src"))
warnings.filterwarnings("ignore")

import config  # noqa: E402


def setup_log():
    config.LOG_DIR.mkdir(parents=True, exist_ok=True)
    path = config.LOG_DIR / f"run_{datetime.now():%Y%m%d_%H%M%S}.log"
    logging.basicConfig(level=logging.INFO, format="%(asctime)s  %(message)s", datefmt="%H:%M:%S",
                        handlers=[logging.FileHandler(path, encoding="utf-8"), logging.StreamHandler()])
    return path


def step(number, name, func):
    start = time.time()
    logging.info(f"[{number}/9] {name} ...")
    result = func()
    shown = "" if result is None else (f"({len(result)} rows)" if hasattr(result, "columns") else result)
    logging.info(f"      done in {time.time() - start:.1f}s {shown}")
    return result


def fresh_start():
    for folder in [config.RAW_DIR, config.CLEAN_DIR, config.INBOX_DIR,
                   config.BRONZE_EMAIL_DIR.parent, config.OUTBOX_DIR]:
        shutil.rmtree(folder, ignore_errors=True)
    config.DB_PATH.unlink(missing_ok=True)


def main():
    parser = argparse.ArgumentParser(description="Vendor Ops Control Tower")
    parser.add_argument("--fresh", action="store_true", help="start from scratch")
    args = parser.parse_args()

    log_path = setup_log()
    logging.info("Vendor Ops Control Tower: starting")
    if args.fresh:
        fresh_start()
        logging.info("fresh start: old data removed")

    import clean_data, database, generate_data, generate_emails, intake, notify, reconcile, simulate

    try:
        if not (config.RAW_DIR / "trips_raw.csv").exists():
            step(1, "generate platform data", generate_data.main)
        else:
            logging.info("[1/9] platform data already exists, skipped")
        step(2, "clean + score", clean_data.main)
        step(3, "what-if simulation", simulate.main)
        conn = database.connect()
        step(4, "load central database", lambda: database.load_platform_tables(conn))
        if config.MAILBOX == "local" and not any(config.INBOX_DIR.glob("*.eml")):
            step(5, "create demo mailbox", generate_emails.main)
        else:
            logging.info("[5/9] mailbox ready, skipped")
        step(6, "email intake", lambda: intake.run(conn))
        summary = step(7, "trip reconciliation (SQL)", lambda: reconcile.run(conn))
        step(8, "compliance reminders + weekly reports", lambda: notify.run(conn))
        step(9, "export for Power BI", lambda: database.export_tables(
            conn, ["reconciliation", "reconciliation_summary", "unclaimed_trips", "email_log"]))
    except Exception:
        logging.exception("FAILED: see the error above")
        sys.exit(1)

    at_risk = summary.amount_at_risk_inr.sum()
    logging.info(f"Finished. Payments on hold: Rs {at_risk:,.0f}. Outbox: {config.OUTBOX_DIR}")
    logging.info(f"Log saved to {log_path}")


if __name__ == "__main__":
    main()
