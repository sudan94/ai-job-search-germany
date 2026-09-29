"""CLI entry point: `python -m app.run_daily`.

Works whether cron, Windows Task Scheduler or a human calls it.  Exits non-zero
when the run failed, so a scheduler can alert on it.

    python -m app.run_daily              # run now
    python -m app.run_daily --if-due     # run only if today's slot was missed
    python -m app.run_daily --no-backlog # only jobs fetched in this run
"""

from __future__ import annotations

import argparse
import json
import logging
import sys

from app.config import settings
from app.db import init_db, session_scope
from app.pipeline.run import run_pipeline
from app.scheduler import needs_catch_up
from app.settings_store import ensure_settings

logger = logging.getLogger("run_daily")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Run the daily job scan.")
    parser.add_argument(
        "--if-due",
        action="store_true",
        help="Do nothing if a run already happened after today's scheduled time.",
    )
    parser.add_argument(
        "--no-backlog",
        action="store_true",
        help="Skip previously stored jobs that were never analysed.",
    )
    parser.add_argument("--trigger", default="cli", help="Label recorded in the run log.")
    parser.add_argument("--json", action="store_true", help="Print the run summary as JSON.")
    args = parser.parse_args(argv)

    logging.basicConfig(
        level=getattr(logging, settings.log_level.upper(), logging.INFO),
        format="%(asctime)s %(levelname)-8s %(name)s: %(message)s",
    )

    init_db()
    with session_scope() as db:
        config = ensure_settings(db)

        if args.if_due and not needs_catch_up(config):
            logger.info("Today's run already happened; nothing to do.")
            return 0

        run = run_pipeline(db, trigger=args.trigger, include_backlog=not args.no_backlog)
        summary = {
            "run_id": run.id,
            "status": run.status,
            "fetched": run.fetched,
            "new": run.new_jobs,
            "duplicates": run.duplicates,
            "language_dropped": run.language_dropped,
            "similarity_dropped": run.similarity_dropped,
            "scored": run.scored,
            "passed": run.passed,
            "errors": run.error_list,
        }

    if args.json:
        print(json.dumps(summary, indent=2))
    else:
        print(
            f"Run {summary['run_id']}: {summary['status']} | "
            f"fetched {summary['fetched']}, new {summary['new']}, "
            f"scored {summary['scored']}, passed {summary['passed']}"
        )
        for error in summary["errors"]:
            print(f"  ! {error}")

    return 0 if summary["status"] in ("success", "partial") else 1


if __name__ == "__main__":
    sys.exit(main())
