"""End-to-end tests for the DELIVERY_DELAY Operations Case workflow."""

from pathlib import Path
import json
import sys
import tempfile
from types import SimpleNamespace
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from delivery_delay_workflow import GeminiWorkflowError, approve_case, create_and_investigate_case
from operations_case_store import audit_entries, get_case, list_cases


DELAYED_ORDER_ID = "1b3190b2dfa9d789e1f14c05b647a14a"


class FakeGeminiClient:
    def __init__(self):
        self.interactions = self
        self.calls = []

    def create(self, **kwargs):
        self.calls.append(kwargs)
        self.last_timeout = kwargs.get("timeout")
        if len(self.calls) == 1:
            return SimpleNamespace(
                id="interaction_case_test",
                steps=[
                    SimpleNamespace(
                        type="function_call",
                        name="get_delivery_delay_evidence",
                        arguments={"order_id": DELAYED_ORDER_ID},
                        id="fact_call_test",
                    )
                ],
                output_text="",
            )
        return SimpleNamespace(
            output_text=json.dumps(
                {
                    "severity": "critical",
                    "recommended_action": "send_customer_message",
                    "rationale": "Il ritardo è molto elevato rispetto alla data stimata.",
                    "confidence": 0.97,
                    "evidence": ["days_late=189.0", "order_status=delivered"],
                    "customer_message": "Ci dispiace per il forte ritardo nella consegna del suo ordine.",
                }
            )
        )


class TimeoutGeminiClient:
    def __init__(self):
        self.interactions = self
        self.calls = []

    def create(self, **kwargs):
        self.calls.append(kwargs)
        raise TimeoutError("simulated Gemini timeout")


class DeliveryDelayWorkflowTest(unittest.TestCase):
    def test_real_delayed_order_lifecycle_and_audit(self):
        with tempfile.TemporaryDirectory() as directory:
            operations_database = Path(directory) / "operations.db"
            client = FakeGeminiClient()
            case = create_and_investigate_case(
                DELAYED_ORDER_ID,
                operations_database=operations_database,
                client=client,
            )
            self.assertEqual(case["status"], "PENDING_HUMAN_APPROVAL")
            self.assertEqual(case["case_type"], "DELIVERY_DELAY")
            self.assertEqual(case["severity"], "critical")
            self.assertEqual(case["recommended_action"], "send_customer_message")
            self.assertEqual(case["confidence"], 0.97)
            self.assertIn("facts", case["evidence"])
            self.assertIn("selected_evidence", case["evidence"])

            audit = audit_entries(case["case_id"], database=operations_database)
            events = [entry["event_type"] for entry in audit]
            self.assertIn("tool_call_completed", events)
            self.assertIn("decision_recorded", events)
            self.assertIn("human_approval_requested", events)
            self.assertGreaterEqual(events.count("tool_call_completed"), 2)
            self.assertTrue(all(call["timeout"] > 0 for call in client.calls))

            closed = approve_case(case["case_id"], operations_database=operations_database)
            self.assertEqual(closed["status"], "CLOSED")
            audit = audit_entries(case["case_id"], database=operations_database)
            self.assertIn("external_action_simulated", [entry["event_type"] for entry in audit])
            self.assertTrue(any(entry["output_json"] and "simulated" in entry["output_json"] for entry in audit))

    def test_timeout_marks_case_failed_without_external_action(self):
        with tempfile.TemporaryDirectory() as directory:
            operations_database = Path(directory) / "operations.db"
            client = TimeoutGeminiClient()
            with self.assertRaises(GeminiWorkflowError):
                create_and_investigate_case(
                    DELAYED_ORDER_ID,
                    operations_database=operations_database,
                    client=client,
                )

            case = list_cases(database=operations_database)[0]
            self.assertEqual(case["status"], "FAILED")
            self.assertEqual(len(client.calls), 2)
            audit = audit_entries(case["case_id"], database=operations_database)
            events = [entry["event_type"] for entry in audit]
            self.assertIn("gemini_timeout", events)
            self.assertIn("investigation_failed", events)
            self.assertNotIn("external_action_simulated", events)


if __name__ == "__main__":
    unittest.main()
