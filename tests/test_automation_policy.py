"""Essential tests for the deterministic automation policy."""

from pathlib import Path
import json
import sys
import tempfile
from types import SimpleNamespace
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from automation_policy import AutomationPolicyConfig, evaluate_automation_policy  # noqa: E402
from delivery_delay_workflow import process_open_case  # noqa: E402
from operations_case_store import audit_entries, create_case, get_case  # noqa: E402
from queries import get_delivery_delay_evidence  # noqa: E402


LOW_ORDER = "eb314576a333adeb296496f38c4c7852"
MEDIUM_ORDER = "cfa4fa27b417971e86d8127cb688712f"
HIGH_ORDER = "95ec4886946c5ae0d453e95648834ac6"


def decision_for(order_id, **overrides):
    facts = get_delivery_delay_evidence(order_id)
    decision = {
        "severity": "low",
        "recommended_action": "monitor_only",
        "rationale": "Decision controllata per il test della policy.",
        "confidence": 0.99,
        "evidence": [f"days_late={facts['facts']['days_late']}", "order_status=delivered"],
        "customer_message": "",
    }
    decision.update(overrides)
    return decision


class ControlledGeminiClient:
    def __init__(self, order_id, decision):
        self.interactions = self
        self.order_id = order_id
        self.decision = decision

    def create(self, **kwargs):
        if not hasattr(self, "calls"):
            self.calls = 0
        self.calls += 1
        if self.calls == 1:
            return SimpleNamespace(
                id="policy_initial",
                steps=[
                    SimpleNamespace(
                        type="function_call",
                        name="get_delivery_delay_evidence",
                        arguments={"order_id": self.order_id},
                        id="policy_tool_call",
                    )
                ],
                output_text="",
            )
        return SimpleNamespace(
            id="policy_decision",
            steps=[],
            output_text=json.dumps(self.decision),
        )


def run_case(order_id, decision, config):
    database = config.pop("database")
    case = create_case(order_id, database=database)
    client = ControlledGeminiClient(order_id, decision)
    result = process_open_case(
        case["case_id"],
        operations_database=database,
        client=client,
        policy_config=AutomationPolicyConfig(**config),
    )
    return case["case_id"], result, audit_entries(case["case_id"], database=database)


class AutomationPolicyTest(unittest.TestCase):
    def test_low_high_confidence_allowed_action_auto_approves_and_closes(self):
        with tempfile.TemporaryDirectory() as directory:
            database = Path(directory) / "operations.db"
            case_id, result, audit = run_case(
                LOW_ORDER,
                decision_for(LOW_ORDER),
                {"enabled": True, "confidence_threshold": 0.95, "allowlisted_actions": frozenset({"monitor_only"}), "database": database},
            )
            self.assertEqual(result["status"], "CLOSED")
            events = [entry["event_type"] for entry in audit]
            self.assertIn("automation_policy_decision", events)
            self.assertIn("automation_policy_auto_approved", events)
            self.assertIn("external_action_simulated", events)
            policy_entry = next(entry for entry in audit if entry["event_type"] == "automation_policy_decision")
            self.assertIn("AUTO_APPROVED", policy_entry["output_json"])
            self.assertIn("low_severity_high_confidence_allowed_action", policy_entry["output_json"])

    def test_low_insufficient_confidence_requires_human(self):
        with tempfile.TemporaryDirectory() as directory:
            database = Path(directory) / "operations.db"
            case_id, result, audit = run_case(
                LOW_ORDER,
                decision_for(LOW_ORDER, confidence=0.80),
                {"enabled": True, "confidence_threshold": 0.95, "allowlisted_actions": frozenset({"monitor_only"}), "database": database},
            )
            self.assertEqual(result["status"], "PENDING_HUMAN_APPROVAL")
            self.assertNotIn("external_action_simulated", [entry["event_type"] for entry in audit])
            policy_entry = next(entry for entry in audit if entry["event_type"] == "automation_policy_decision")
            self.assertIn("HUMAN_APPROVAL_REQUIRED", policy_entry["output_json"])

    def test_medium_and_high_require_human(self):
        for order_id, severity, action in (
            (MEDIUM_ORDER, "medium", "send_customer_message"),
            (HIGH_ORDER, "high", "escalate_to_operations"),
        ):
            with self.subTest(order_id=order_id), tempfile.TemporaryDirectory() as directory:
                database = Path(directory) / "operations.db"
                _, result, audit = run_case(
                    order_id,
                    decision_for(order_id, severity=severity, recommended_action=action, customer_message="Proposta."),
                    {"enabled": True, "confidence_threshold": 0.95, "allowlisted_actions": frozenset({"monitor_only"}), "database": database},
                )
                self.assertEqual(result["status"], "PENDING_HUMAN_APPROVAL")
                self.assertNotIn("external_action_simulated", [entry["event_type"] for entry in audit])

    def test_action_outside_allowlist_requires_human(self):
        with tempfile.TemporaryDirectory() as directory:
            database = Path(directory) / "operations.db"
            _, result, audit = run_case(
                LOW_ORDER,
                decision_for(LOW_ORDER, recommended_action="send_customer_message", customer_message="Proposta."),
                {"enabled": True, "confidence_threshold": 0.95, "allowlisted_actions": frozenset({"monitor_only"}), "database": database},
            )
            self.assertEqual(result["status"], "PENDING_HUMAN_APPROVAL")
            policy_entry = next(entry for entry in audit if entry["event_type"] == "automation_policy_decision")
            self.assertIn("action_not_allowlisted", policy_entry["output_json"])

    def test_evidence_invalid_or_kill_switch_never_auto_executes(self):
        with tempfile.TemporaryDirectory() as directory:
            database = Path(directory) / "operations.db"
            case = create_case(LOW_ORDER, database=database)
            invalid = decision_for(LOW_ORDER, evidence=[])
            with self.assertRaises(ValueError):
                process_open_case(
                    case["case_id"],
                    operations_database=database,
                    client=ControlledGeminiClient(LOW_ORDER, invalid),
                    policy_config=AutomationPolicyConfig(enabled=True),
                )
            self.assertEqual(get_case(case["case_id"], database=database)["status"], "FAILED")
            self.assertNotIn("external_action_simulated", [entry["event_type"] for entry in audit_entries(case["case_id"], database=database)])

        with tempfile.TemporaryDirectory() as directory:
            database = Path(directory) / "operations.db"
            _, result, audit = run_case(
                LOW_ORDER,
                decision_for(LOW_ORDER),
                {"enabled": False, "confidence_threshold": 0.95, "allowlisted_actions": frozenset({"monitor_only"}), "database": database},
            )
            self.assertEqual(result["status"], "PENDING_HUMAN_APPROVAL")
            policy_entry = next(entry for entry in audit if entry["event_type"] == "automation_policy_decision")
            self.assertIn("kill_switch_disabled", policy_entry["output_json"])
            self.assertNotIn("external_action_simulated", [entry["event_type"] for entry in audit])

    def test_policy_directly_rejects_missing_evidence(self):
        result = evaluate_automation_policy(
            decision_for(LOW_ORDER),
            {"facts": {}},
            AutomationPolicyConfig(enabled=True),
        )
        self.assertEqual(result["outcome"], "HUMAN_APPROVAL_REQUIRED")
        self.assertEqual(result["rule"], "evidence_insufficient")


if __name__ == "__main__":
    unittest.main()
