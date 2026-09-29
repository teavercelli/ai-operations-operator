"""CLI for one-shot DELIVERY_DELAY detection plus OPEN-case processing."""

from __future__ import annotations

import argparse
import json
import logging

from operations_orchestrator import detect_and_process_delivery_delays


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--limit", type=int, default=None, help="maximum cases detected and processed (1-100)")
    args = parser.parse_args()
    print(json.dumps(detect_and_process_delivery_delays(limit=args.limit), ensure_ascii=False, indent=2, default=str))


if __name__ == "__main__":
    main()
