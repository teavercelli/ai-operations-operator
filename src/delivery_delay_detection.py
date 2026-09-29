"""Deterministic automatic detection and case creation for DELIVERY_DELAY."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from operations_case_store import (
    DEFAULT_OPERATIONS_DATABASE,
    create_case,
    find_cases_for_order,
    record_audit,
)
from queries import DEFAULT_DATABASE, delayed_orders


DETECTION_TOOL_NAME = "detect_delivery_delay_orders"
DETECTION_CRITERIA = {
    "order_status": "delivered",
    "delivered_customer_date": "not_null",
    "estimated_delivery_date": "not_null",
    "delivered_customer_date": "> estimated_delivery_date",
}


def detect_and_create_delivery_delay_cases(
    *,
    limit: int | None = None,
    max_cases_created: int | None = None,
    database: Path = DEFAULT_DATABASE,
    operations_database: Path = DEFAULT_OPERATIONS_DATABASE,
) -> dict[str, Any]:
    """Scan delayed orders and create one case per new order/type combination.

    The SQL query is deterministic and this function never imports or calls
    Gemini. Existing cases are skipped regardless of their current status,
    including FAILED and CLOSED, because the problem was already processed.
    """

    if limit is not None and (limit < 1 or limit > 100):
        raise ValueError("limit must be between 1 and 100")
    if max_cases_created is not None and (max_cases_created < 1 or max_cases_created > 100):
        raise ValueError("max_cases_created must be between 1 and 100")

    candidates = delayed_orders(limit=limit, database=database)
    summary = {
        "orders_scanned": len(candidates),
        "issues_detected": len(candidates),
        "new_cases_created": 0,
        "duplicates_skipped": 0,
        "errors": 0,
        "error_details": [],
        "created_case_ids": [],
        "skipped_order_ids": [],
        "creation_cap_reached": False,
    }

    for candidate in candidates:
        if max_cases_created is not None and summary["new_cases_created"] >= max_cases_created:
            summary["creation_cap_reached"] = True
            break
        order_id = candidate["order_id"]
        try:
            existing_cases = find_cases_for_order(
                order_id,
                case_type="DELIVERY_DELAY",
                database=operations_database,
            )
            if existing_cases:
                existing_case = existing_cases[0]
                record_audit(
                    existing_case["case_id"],
                    "detector",
                    "duplicate_detection_skipped",
                    tool_name=DETECTION_TOOL_NAME,
                    input_data={"order_id": order_id, "criteria": DETECTION_CRITERIA},
                    output_data={
                        "existing_case_id": existing_case["case_id"],
                        "existing_status": existing_case["status"],
                        "detected_issue": candidate,
                    },
                    database=operations_database,
                )
                summary["duplicates_skipped"] += 1
                summary["skipped_order_ids"].append(order_id)
                continue

            case = create_case(order_id, database=operations_database)
            record_audit(
                case["case_id"],
                "detector",
                "automatic_detection_completed",
                tool_name=DETECTION_TOOL_NAME,
                input_data={"order_id": order_id, "criteria": DETECTION_CRITERIA},
                output_data=candidate,
                database=operations_database,
            )
            summary["new_cases_created"] += 1
            summary["created_case_ids"].append(case["case_id"])
        except Exception as error:  # Keep one bad row from stopping the scan.
            summary["errors"] += 1
            summary["error_details"].append(
                {"order_id": order_id, "error_type": type(error).__name__, "error": str(error)}
            )

    return summary
