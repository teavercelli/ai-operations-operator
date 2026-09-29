"""Opt-in, small live evaluation for the DELIVERY_DELAY LLM step.

This module performs no Gemini calls unless ``--run-live`` is supplied.
It leaves successful cases in PENDING_HUMAN_APPROVAL and never approves them.
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from delivery_delay_workflow import create_and_investigate_case  # noqa: E402
from operations_case_store import get_case  # noqa: E402


CASES = [
    {
        "name": "low_delay",
        "order_id": "eb314576a333adeb296496f38c4c7852",
        "expected_severity": {"low"},
        "expected_action": {"monitor_only"},
        "evidence_anchors": {"days_late", "0.1", "delivered"},
    },
    {
        "name": "medium_delay",
        "order_id": "cfa4fa27b417971e86d8127cb688712f",
        "expected_severity": {"medium", "high"},
        "expected_action": {"send_customer_message", "escalate_to_operations"},
        "evidence_anchors": {"days_late", "7.1", "delivered"},
    },
    {
        "name": "high_delay",
        "order_id": "95ec4886946c5ae0d453e95648834ac6",
        "expected_severity": {"high", "critical"},
        "expected_action": {"send_customer_message", "escalate_to_operations"},
        "evidence_anchors": {"days_late", "30.1", "delivered"},
    },
]

REQUIRED_DECISION_FIELDS = {
    "severity",
    "recommended_action",
    "rationale",
    "confidence",
    "evidence",
    "customer_message",
}


def score_case(case_spec: dict, result: dict, latency_seconds: float) -> dict:
    decision = result
    selected_evidence = decision.get("evidence", {}).get("selected_evidence", [])
    evidence_text = " ".join(str(item).lower() for item in selected_evidence)
    schema_ok = REQUIRED_DECISION_FIELDS.issubset(decision) and decision.get("status") == "PENDING_HUMAN_APPROVAL"
    severity_ok = decision.get("severity") in case_spec["expected_severity"]
    action_ok = decision.get("recommended_action") in case_spec["expected_action"]
    evidence_ok = bool(selected_evidence) and any(anchor in evidence_text for anchor in case_spec["evidence_anchors"])
    confidence_ok = isinstance(decision.get("confidence"), (int, float)) and 0 <= decision["confidence"] <= 1
    return {
        "name": case_spec["name"],
        "order_id": case_spec["order_id"],
        "case_id": decision.get("case_id"),
        "status": decision.get("status"),
        "severity": decision.get("severity"),
        "recommended_action": decision.get("recommended_action"),
        "confidence": decision.get("confidence"),
        "schema_ok": schema_ok,
        "severity_ok": severity_ok,
        "recommended_action_ok": action_ok,
        "evidence_ok": evidence_ok,
        "confidence_ok": confidence_ok,
        "latency_seconds": round(latency_seconds, 3),
        "passed": all((schema_ok, severity_ok, action_ok, evidence_ok, confidence_ok)),
    }


def run_live(cases: list[dict]) -> dict:
    results = []
    for case_spec in cases:
        started = time.perf_counter()
        try:
            case = create_and_investigate_case(case_spec["order_id"])
            result = score_case(case_spec, case, time.perf_counter() - started)
        except Exception as error:  # The report measures failure rate as requested.
            result = {
                "name": case_spec["name"],
                "order_id": case_spec["order_id"],
                "status": "FAILED",
                "error_type": type(error).__name__,
                "error": str(error),
                "latency_seconds": round(time.perf_counter() - started, 3),
                "passed": False,
            }
        results.append(result)
    return {
        "total_cases": len(results),
        "passed_cases": sum(result["passed"] for result in results),
        "failed_cases": sum(not result["passed"] for result in results),
        "failure_rate": round(sum(not result["passed"] for result in results) / len(results), 3) if results else 0,
        "results": results,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run-live", action="store_true", help="allow the three live Gemini calls")
    parser.add_argument("--limit", type=int, choices=range(1, len(CASES) + 1), default=len(CASES))
    args = parser.parse_args()
    if not args.run_live:
        print(
            json.dumps(
                {"prepared": True, "live_calls_executed": 0, "cases": CASES},
                indent=2,
                default=lambda value: sorted(value) if isinstance(value, set) else str(value),
            )
        )
        return 0
    print(json.dumps(run_live(CASES[: args.limit]), ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
