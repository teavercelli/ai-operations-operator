"""Controlled final-build paths using real Olist rows and no external calls."""

from pathlib import Path
import json
import shutil
import sqlite3
import sys
import tempfile
from types import SimpleNamespace
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from automation_policy import AutomationPolicyConfig  # noqa: E402
from automation_runner import run_automation_once  # noqa: E402
from delivery_delay_workflow import approve_case  # noqa: E402
from email_adapter import DryRunEmailAdapter  # noqa: E402
from operations_case_store import audit_entries  # noqa: E402
from queries import DEFAULT_DATABASE, delayed_orders  # noqa: E402


class ControlledDecisionClient:
    def __init__(self, order_id, decision):
        self.interactions = self
        self.order_id = order_id
        self.decision = decision
        self.calls = 0

    def create(self, **kwargs):
        self.calls += 1
        if self.calls == 1:
            return SimpleNamespace(
                id="final_initial",
                steps=[
                    SimpleNamespace(
                        type="function_call",
                        name="get_delivery_delay_evidence",
                        arguments={"order_id": self.order_id},
                        id="final_tool_call",
                    )
                ],
                output_text="",
            )
        return SimpleNamespace(
            id="final_decision",
            steps=[],
            output_text=json.dumps(self.decision),
        )


def make_source_with_one_order(directory, order_id):
    source = Path(directory) / "olist-subset.db"
    shutil.copy(DEFAULT_DATABASE, source)
    with sqlite3.connect(source) as connection:
        connection.execute("DELETE FROM orders WHERE order_id != ?", (order_id,))
    return source


class FinalEndToEndTest(unittest.TestCase):
    def test_a_safe_autonomous_case_closes_after_simulated_policy_action(self):
        low_order = next(row for row in delayed_orders(limit=None) if row["days_late"] <= 7)
        decision = {
            "severity": "low",
            "recommended_action": "monitor_only",
            "rationale": "Ritardo contenuto, monitoraggio sufficiente.",
            "confidence": 0.99,
            "evidence": ["order_status=delivered", "days_late<=7"],
            "customer_message": "",
        }
        with tempfile.TemporaryDirectory() as directory:
            source = make_source_with_one_order(directory, low_order["order_id"])
            operations = Path(directory) / "operations.db"
            result = run_automation_once(
                max_orders_scanned=1,
                max_cases_created=1,
                max_cases_processed=1,
                max_gemini_calls=2,
                database=source,
                operations_database=operations,
                client=ControlledDecisionClient(low_order["order_id"], decision),
                policy_config=AutomationPolicyConfig(
                    enabled=True,
                    confidence_threshold=0.95,
                    allowlisted_actions=frozenset({"monitor_only"}),
                ),
            )
            self.assertEqual(result["processing"]["auto_approved"], 1)
            self.assertEqual(result["processing"]["case_results"][0]["status"], "CLOSED")
            events = [entry["event_type"] for entry in audit_entries(result["processing"]["case_results"][0]["case_id"], database=operations)]
            self.assertIn("automation_policy_auto_approved", events)
            self.assertIn("external_action_simulated", events)
            self.assertIn("case_closed", events)

    def test_b_human_contact_customer_approval_closes_only_simulated_action(self):
        delayed_order = delayed_orders(limit=1)[0]
        decision = {
            "severity": "critical",
            "recommended_action": "contact_customer",
            "rationale": "Il ritardo richiede contatto umano.",
            "confidence": 0.94,
            "evidence": ["order_status=delivered", "days_late>0"],
            "customer_message": "Ci scusiamo per il ritardo nella consegna.",
        }
        with tempfile.TemporaryDirectory() as directory:
            source = make_source_with_one_order(directory, delayed_order["order_id"])
            operations = Path(directory) / "operations.db"
            result = run_automation_once(
                max_orders_scanned=1,
                max_cases_created=1,
                max_cases_processed=1,
                max_gemini_calls=2,
                database=source,
                operations_database=operations,
                client=ControlledDecisionClient(delayed_order["order_id"], decision),
                policy_config=AutomationPolicyConfig(enabled=True),
            )
            self.assertEqual(result["processing"]["pending_human_approval"], 1)
            case_id = result["processing"]["case_results"][0]["case_id"]
            pending_events = [entry["event_type"] for entry in audit_entries(case_id, database=operations)]
            self.assertIn("human_approval_requested", pending_events)
            closed = approve_case(
                case_id,
                operations_database=operations,
                email_adapter=DryRunEmailAdapter(default_recipient="qa@example.com"),
            )
            self.assertEqual(closed["status"], "CLOSED")
            events = [entry["event_type"] for entry in audit_entries(case_id, database=operations)]
            self.assertIn("human_approval_granted", events)
            self.assertIn("email_action_result", events)
            self.assertIn("external_action_simulated", events)
            self.assertNotIn("external_action_executed", events)


if __name__ == "__main__":
    unittest.main()
