"""One-shot DELIVERY_DELAY detection followed by OPEN-case AI processing."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from delivery_delay_detection import detect_and_create_delivery_delay_cases
from automation_policy import AutomationPolicyConfig
from delivery_delay_workflow import process_open_cases
from operations_case_store import DEFAULT_OPERATIONS_DATABASE
from queries import DEFAULT_DATABASE


def detect_and_process_delivery_delays(
    *,
    limit: int | None = None,
    database: Path = DEFAULT_DATABASE,
    operations_database: Path = DEFAULT_OPERATIONS_DATABASE,
    client: Any | None = None,
    policy_config: AutomationPolicyConfig | None = None,
) -> dict[str, Any]:
    """Run detection, case creation, and bounded processing once.

    This is deliberately a one-shot command. It does not schedule or repeat
    itself, and it never approves or executes an external action.
    """

    detection = detect_and_create_delivery_delay_cases(
        limit=limit,
        database=database,
        operations_database=operations_database,
    )
    processing = process_open_cases(
        limit=limit,
        operations_database=operations_database,
        client=client,
        policy_config=policy_config,
    )
    return {"detection": detection, "processing": processing}
