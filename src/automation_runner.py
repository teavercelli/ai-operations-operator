"""Bounded, scheduler-ready one-shot runner for the AI Operations Operator."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from automation_policy import AutomationPolicyConfig
from delivery_delay_detection import detect_and_create_delivery_delay_cases
from delivery_delay_workflow import GeminiCallBudget, process_open_cases
from operations_case_store import DEFAULT_OPERATIONS_DATABASE
from queries import DEFAULT_DATABASE


def _validate_cap(name: str, value: int) -> None:
    if value < 1 or value > 100:
        raise ValueError(f"{name} must be between 1 and 100")


def run_automation_once(
    *,
    max_orders_scanned: int = 10,
    max_cases_created: int = 5,
    max_cases_processed: int = 5,
    max_gemini_calls: int = 10,
    database: Path = DEFAULT_DATABASE,
    operations_database: Path = DEFAULT_OPERATIONS_DATABASE,
    client: Any | None = None,
    policy_config: AutomationPolicyConfig | None = None,
    enable_gemini: bool = True,
) -> dict[str, Any]:
    """Run detection and bounded AI processing exactly once.

    The function is intentionally stateless and idempotent at the case layer,
    so it can be invoked manually or by cron without scheduler infrastructure.
    ``enable_gemini=False`` is used by the public demo UI to guarantee that a
    refresh or button click cannot consume API quota accidentally.
    """

    for name, value in (
        ("max_orders_scanned", max_orders_scanned),
        ("max_cases_created", max_cases_created),
        ("max_cases_processed", max_cases_processed),
        ("max_gemini_calls", max_gemini_calls),
    ):
        _validate_cap(name, value)

    detection = detect_and_create_delivery_delay_cases(
        limit=max_orders_scanned,
        max_cases_created=max_cases_created,
        database=database,
        operations_database=operations_database,
    )

    if not enable_gemini:
        processing = {
            "open_cases_found": 0,
            "processed": 0,
            "pending_human_approval": 0,
            "auto_approved": 0,
            "failed": 0,
            "errors": 0,
            "skipped_gemini_cap": 0,
            "gemini_disabled": True,
            "case_results": [],
        }
        return {
            "mode": "demo_safe_scan_only",
            "limits": {
                "max_orders_scanned": max_orders_scanned,
                "max_cases_created": max_cases_created,
                "max_cases_processed": max_cases_processed,
                "max_gemini_calls": max_gemini_calls,
            },
            "detection": detection,
            "processing": processing,
            "gemini_calls_used": 0,
        }

    budget = GeminiCallBudget(max_gemini_calls)
    processing = process_open_cases(
        limit=max_cases_processed,
        operations_database=operations_database,
        client=client,
        policy_config=policy_config,
        gemini_budget=budget,
    )
    processing["gemini_disabled"] = False
    return {
        "mode": "bounded_once",
        "limits": {
            "max_orders_scanned": max_orders_scanned,
            "max_cases_created": max_cases_created,
            "max_cases_processed": max_cases_processed,
            "max_gemini_calls": max_gemini_calls,
        },
        "detection": detection,
        "processing": processing,
        "gemini_calls_used": budget.used,
    }
