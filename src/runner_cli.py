"""Run one bounded AI Operations Operator cycle."""

from __future__ import annotations

import argparse
import json
import logging

from automation_runner import run_automation_once


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--max-orders-scanned", type=int, default=10)
    parser.add_argument("--max-cases-created", type=int, default=5)
    parser.add_argument("--max-cases-processed", type=int, default=5)
    parser.add_argument("--max-gemini-calls", type=int, default=10)
    parser.add_argument(
        "--scan-only",
        action="store_true",
        help="detect/create cases without calling Gemini (safe demo mode)",
    )
    args = parser.parse_args()
    result = run_automation_once(
        max_orders_scanned=args.max_orders_scanned,
        max_cases_created=args.max_cases_created,
        max_cases_processed=args.max_cases_processed,
        max_gemini_calls=args.max_gemini_calls,
        enable_gemini=not args.scan_only,
    )
    print(json.dumps(result, ensure_ascii=False, indent=2, default=str))


if __name__ == "__main__":
    main()
