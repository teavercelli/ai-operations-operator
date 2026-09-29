"""Conservative, deterministic automation policy for validated AI decisions."""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from typing import Any


SUPPORTED_ACTIONS = frozenset(
    {"send_customer_message", "contact_customer", "escalate_to_operations", "monitor_only"}
)
LOW_RISK_ACTIONS = frozenset({"monitor_only"})


@dataclass(frozen=True)
class AutomationPolicyConfig:
    """Demo policy configuration; values require business validation in production."""

    enabled: bool = False
    confidence_threshold: float = 0.95
    allowlisted_actions: frozenset[str] = field(default_factory=lambda: LOW_RISK_ACTIONS)

    def __post_init__(self) -> None:
        if not 0 <= self.confidence_threshold <= 1:
            raise ValueError("confidence_threshold must be between 0 and 1")
        unknown = set(self.allowlisted_actions) - set(SUPPORTED_ACTIONS)
        if unknown:
            raise ValueError(f"Unsupported policy actions: {sorted(unknown)}")
        unsafe = set(self.allowlisted_actions) - set(LOW_RISK_ACTIONS)
        if unsafe:
            raise ValueError(f"Only low-risk actions may be allowlisted for auto-execution: {sorted(unsafe)}")

    @classmethod
    def from_env(cls) -> "AutomationPolicyConfig":
        enabled = os.getenv("AI_OPERATOR_AUTO_EXECUTION_ENABLED", "false").lower() in {
            "1",
            "true",
            "yes",
            "on",
        }
        threshold = float(os.getenv("AI_OPERATOR_AUTO_EXECUTION_CONFIDENCE_THRESHOLD", "0.95"))
        requested_actions = {
            action.strip()
            for action in os.getenv("AI_OPERATOR_AUTO_EXECUTION_ALLOWLIST", "monitor_only").split(",")
            if action.strip()
        }
        return cls(
            enabled=enabled,
            confidence_threshold=threshold,
            allowlisted_actions=frozenset(requested_actions),
        )

    def as_dict(self) -> dict[str, Any]:
        return {
            "enabled": self.enabled,
            "confidence_threshold": self.confidence_threshold,
            "allowlisted_actions": sorted(self.allowlisted_actions),
        }


def evaluate_automation_policy(
    decision: dict[str, Any],
    evidence: dict[str, Any],
    config: AutomationPolicyConfig,
) -> dict[str, Any]:
    """Return a deterministic policy result for an already validated decision."""

    selected_evidence = decision.get("evidence")
    facts = evidence.get("facts") if isinstance(evidence, dict) else None
    if not isinstance(selected_evidence, list) or not selected_evidence or not isinstance(facts, dict) or not facts:
        return {
            "outcome": "HUMAN_APPROVAL_REQUIRED",
            "rule": "evidence_insufficient",
            "reason": "Validated facts and selected evidence are required before any automation.",
        }
    if not config.enabled:
        return {
            "outcome": "HUMAN_APPROVAL_REQUIRED",
            "rule": "kill_switch_disabled",
            "reason": "Automatic execution is disabled by configuration.",
        }
    if decision.get("severity") != "low":
        return {
            "outcome": "HUMAN_APPROVAL_REQUIRED",
            "rule": "severity_not_low",
            "reason": "Only LOW severity is eligible for the demo auto-execution policy.",
        }
    if not isinstance(decision.get("confidence"), (int, float)) or decision["confidence"] < config.confidence_threshold:
        return {
            "outcome": "HUMAN_APPROVAL_REQUIRED",
            "rule": "confidence_below_threshold",
            "reason": f"Confidence must be at least {config.confidence_threshold:.2f} for this demo policy.",
        }
    if decision.get("recommended_action") not in config.allowlisted_actions:
        return {
            "outcome": "HUMAN_APPROVAL_REQUIRED",
            "rule": "action_not_allowlisted",
            "reason": "The recommended action is not in the explicit low-risk automation allowlist.",
        }
    return {
        "outcome": "AUTO_APPROVED",
        "rule": "low_severity_high_confidence_allowed_action",
        "reason": "LOW severity, sufficient confidence, valid evidence, and allowlisted action.",
    }
