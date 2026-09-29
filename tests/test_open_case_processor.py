"""Essential tests for automatic processing of existing OPEN cases."""

from pathlib import Path
import json
import sys
import tempfile
from types import SimpleNamespace
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from delivery_delay_workflow import (  # noqa: E402
    GeminiWorkflowError,
    approve_case,
    process_open_case,
    process_open_cases,
)
from operations_case_store import audit_entries, create_case, get_case  # noqa: E402
from operations_orchestrator import detect_and_process_delivery_delays  # noqa: E402


ORDER_ID = "1b3190b2dfa9d789e1f14c05b647a14a"


class FakeGeminiClient:
    def __init__(self):
        self.interactions = self
        self.calls = []

    def create(self, **kwargs):
        self.calls.append(kwargs)
        if len(self.calls) == 1:
            return SimpleNamespace(
                id="processor_initial",
                steps=[
                    SimpleNamespace(
                        type="function_call",
                        name="get_delivery_delay_evidence",
                        arguments={"order_id": ORDER_ID},
                        id="processor_tool_call",
                    )
                ],
                output_text="",
            )
        return SimpleNamespace(
            id="processor_decision",
            steps=[],
            output_text=json.dumps(
                {
                    "severity": "critical",
                    "recommended_action": "send_customer_message",
                    "rationale": "Il ritardo è molto elevato.",
                    "confidence": 0.95,
                    "evidence": ["days_late=189.0", "order_status=delivered"],
                    "customer_message": "Ci dispiace per il ritardo nella consegna.",
                }
            ),
        )


class TimeoutGeminiClient:
    def __init__(self):
        self.interactions = self

    def create(self, **kwargs):
        raise TimeoutError("processor timeout")


class OpenCaseProcessorTest(unittest.TestCase):
    def test_existing_open_case_reaches_human_approval(self):
        with tempfile.TemporaryDirectory() as directory:
            database = Path(directory) / "operations.db"
            case = create_case(ORDER_ID, database=database)
            processed = process_open_case(
                case["case_id"],
                operations_database=database,
                client=FakeGeminiClient(),
            )
            self.assertEqual(processed["status"], "PENDING_HUMAN_APPROVAL")
            events = [entry["event_type"] for entry in audit_entries(case["case_id"], database=database)]
            self.assertIn("automatic_ai_processing_started", events)
            self.assertIn("tool_call_completed", events)
            self.assertIn("decision_recorded", events)
            self.assertIn("human_approval_requested", events)
            self.assertNotIn("external_action_simulated", events)

    def test_one_shot_orchestrator_detects_then_processes(self):
        with tempfile.TemporaryDirectory() as directory:
            database = Path(directory) / "operations.db"
            result = detect_and_process_delivery_delays(
                limit=1,
                operations_database=database,
                client=FakeGeminiClient(),
            )
            self.assertEqual(result["detection"]["new_cases_created"], 1)
            self.assertEqual(result["processing"]["open_cases_found"], 1)
            self.assertEqual(result["processing"]["processed"], 1)
            self.assertEqual(result["processing"]["pending_human_approval"], 1)
            self.assertEqual(result["processing"]["failed"], 0)

    def test_timeout_fails_existing_case_and_processed_cases_are_not_reentered(self):
        with tempfile.TemporaryDirectory() as directory:
            database = Path(directory) / "operations.db"
            case = create_case(ORDER_ID, database=database)
            with self.assertRaises(GeminiWorkflowError):
                process_open_case(
                    case["case_id"],
                    operations_database=database,
                    client=TimeoutGeminiClient(),
                )
            self.assertEqual(get_case(case["case_id"], database=database)["status"], "FAILED")
            events = [entry["event_type"] for entry in audit_entries(case["case_id"], database=database)]
            self.assertNotIn("external_action_simulated", events)
            with self.assertRaisesRegex(ValueError, "Only OPEN cases"):
                process_open_case(case["case_id"], operations_database=database, client=FakeGeminiClient())

    def test_pending_case_cannot_be_processed_or_approved_twice(self):
        with tempfile.TemporaryDirectory() as directory:
            database = Path(directory) / "operations.db"
            case = create_case(ORDER_ID, database=database)
            process_open_case(case["case_id"], operations_database=database, client=FakeGeminiClient())
            with self.assertRaisesRegex(ValueError, "Only OPEN cases"):
                process_open_case(case["case_id"], operations_database=database, client=FakeGeminiClient())
            closed = approve_case(case["case_id"], operations_database=database)
            self.assertEqual(closed["status"], "CLOSED")


if __name__ == "__main__":
    unittest.main()
