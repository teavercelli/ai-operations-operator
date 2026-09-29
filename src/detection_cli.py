"""CLI for deterministic automatic DELIVERY_DELAY detection."""

from __future__ import annotations

import argparse
import json

from delivery_delay_detection import detect_and_create_delivery_delay_cases


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--limit",
        type=int,
        default=None,
        help="maximum number of detected delayed orders to process (1-100)",
    )
    args = parser.parse_args()
    summary = detect_and_create_delivery_delay_cases(limit=args.limit)
    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
