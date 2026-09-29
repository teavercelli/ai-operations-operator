"""CLI for creating, investigating, and approving Operations Cases."""

from __future__ import annotations

import argparse
import json
import logging

from delivery_delay_workflow import approve_case, create_and_investigate_case, reject_case
from operations_case_store import audit_entries, get_case


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--order-id", help="create and investigate a DELIVERY_DELAY case")
    parser.add_argument("--approve", metavar="CASE_ID", help="approve and simulate a pending case")
    parser.add_argument("--reject", metavar="CASE_ID", help="reject a pending case")
    parser.add_argument("--audit", metavar="CASE_ID", help="show audit entries for a case")
    args = parser.parse_args()

    if args.order_id:
        print(json.dumps(create_and_investigate_case(args.order_id), ensure_ascii=False, indent=2, default=str))
    elif args.approve:
        print(json.dumps(approve_case(args.approve), ensure_ascii=False, indent=2, default=str))
    elif args.reject:
        print(json.dumps(reject_case(args.reject), ensure_ascii=False, indent=2, default=str))
    elif args.audit:
        print(json.dumps(audit_entries(args.audit), ensure_ascii=False, indent=2, default=str))
    else:
        parser.print_help()


if __name__ == "__main__":
    main()
