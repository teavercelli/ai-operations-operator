"""Safe email-action tests; every send uses a fake or blocked adapter."""

from pathlib import Path
import json
import sys
import tempfile
from types import SimpleNamespace
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from automation_policy import AutomationPolicyConfig, evaluate_automation_policy  # noqa: E402
from delivery_delay_workflow import approve_case, process_open_case  # noqa: E402
from email_adapter import EmailActionConfig, EmailSendResult  # noqa: E402
from operations_case_store import audit_entries, create_case, get_case  # noqa: E402


ORDER_ID = "1b3190b2dfa9d789e1f14c05b647a14a"


class ContactDecisionClient:
    def __init__(self, message="Il tuo ordine è in ritardo. Ci scusiamo per l'attesa."):
        self.interactions = self
        self.calls = 0
        self.message = message

    def create(self, **kwargs):
        self.calls += 1
        if self.calls == 1:
            return SimpleNamespace(
                id="contact_initial",
                steps=[
                    SimpleNamespace(
                        type="function_call",
                        name="get_delivery_delay_evidence",
                        arguments={"order_id": ORDER_ID},
                        id="contact_tool_call",
                    )
                ],
                output_text="",
            )
        return SimpleNamespace(
            id="contact_decision",
            steps=[],
            output_text=json.dumps(
                {
                    "severity": "critical",
                    "recommended_action": "contact_customer",
                    "rationale": "Il cliente deve essere informato del ritardo verificato.",
                    "confidence": 0.91,
                    "evidence": ["days_late=189.0", "order_status=delivered"],
                    "customer_message": self.message,
                }
            ),
        )


class FakeEmailAdapter:
    provider = "fake"

    def __init__(self, *, success=True, recipient="qa@example.com", error=None):
        self.success = success
        self.default_recipient = recipient
        self.error = error
        self.calls = []

    def send(self, *, recipient, subject, body):
        self.calls.append({"recipient": recipient, "subject": subject, "body": body})
        return EmailSendResult(
            success=self.success,
            simulated=True,
            provider=self.provider,
            timestamp="2026-09-29T12:00:00+00:00",
            message_id="fake-message-1" if self.success else None,
            error=self.error,
        )


def process_contact(database, message=None, policy=None):
    case = create_case(ORDER_ID, database=database)
    decision_message = (
        "Il tuo ordine è in ritardo. Ci scusiamo per l'attesa."
        if message is None
        else message
    )
    result = process_open_case(
        case["case_id"],
        operations_database=database,
        client=ContactDecisionClient(decision_message),
        policy_config=policy or AutomationPolicyConfig(enabled=True),
    )
    return case["case_id"], result


class EmailActionTest(unittest.TestCase):
    def test_contact_customer_is_not_in_auto_execution_allowlist(self):
        result = evaluate_automation_policy(
            {
                "severity": "low",
                "recommended_action": "contact_customer",
                "confidence": 0.99,
                "evidence": ["days_late=2"],
            },
            {"facts": {"order_status": "delivered"}},
            AutomationPolicyConfig(enabled=True),
        )
        self.assertEqual(result["outcome"], "HUMAN_APPROVAL_REQUIRED")
        self.assertEqual(result["rule"], "action_not_allowlisted")

    def test_contact_customer_is_never_auto_executed(self):
        with tempfile.TemporaryDirectory() as directory:
            database = Path(directory) / "operations.db"
            case_id, result = process_contact(database)
            self.assertEqual(result["status"], "PENDING_HUMAN_APPROVAL")
            policy = next(
                entry for entry in audit_entries(case_id, database=database)
                if entry["event_type"] == "automation_policy_decision"
            )
            self.assertIn("HUMAN_APPROVAL_REQUIRED", policy["output_json"])
            self.assertNotIn("AUTO_APPROVED", policy["output_json"])

    def test_approved_contact_customer_uses_fake_adapter_and_closes_in_simulation(self):
        with tempfile.TemporaryDirectory() as directory:
            database = Path(directory) / "operations.db"
            case_id, _ = process_contact(database)
            adapter = FakeEmailAdapter()
            result = approve_case(case_id, operations_database=database, email_adapter=adapter)
            self.assertEqual(result["status"], "CLOSED")
            self.assertEqual(len(adapter.calls), 1)
            self.assertEqual(adapter.calls[0]["recipient"], "qa@example.com")
            self.assertIn("Il tuo ordine è in ritardo", adapter.calls[0]["body"])
            events = [entry["event_type"] for entry in audit_entries(case_id, database=database)]
            self.assertIn("human_approval_granted", events)
            self.assertIn("email_action_result", events)
            self.assertIn("external_action_simulated", events)
            self.assertIn("case_closed", events)
            result_audit = next(
                entry for entry in audit_entries(case_id, database=database)
                if entry["event_type"] == "email_action_result"
            )
            self.assertIn("qa@example.com", result_audit["input_json"])
            self.assertIn('"provider": "fake"', result_audit["output_json"])
            self.assertIn('"timestamp": "2026-09-29T12:00:00+00:00"', result_audit["output_json"])

    def test_failed_email_does_not_close_case(self):
        with tempfile.TemporaryDirectory() as directory:
            database = Path(directory) / "operations.db"
            case_id, _ = process_contact(database)
            adapter = FakeEmailAdapter(success=False, error="provider rejected message")
            result = approve_case(case_id, operations_database=database, email_adapter=adapter)
            self.assertEqual(result["status"], "FAILED")
            self.assertEqual(len(adapter.calls), 1)
            events = [entry["event_type"] for entry in audit_entries(case_id, database=database)]
            self.assertIn("external_action_failed", events)
            self.assertNotIn("case_closed", events)

    def test_missing_customer_message_fails_before_adapter_call(self):
        with tempfile.TemporaryDirectory() as directory:
            database = Path(directory) / "operations.db"
            case = create_case(ORDER_ID, database=database)
            with self.assertRaises(ValueError):
                process_open_case(
                    case["case_id"],
                    operations_database=database,
                    client=ContactDecisionClient(message=""),
                )
            self.assertEqual(get_case(case["case_id"], database=database)["status"], "FAILED")

    def test_missing_recipient_fails_without_calling_adapter(self):
        with tempfile.TemporaryDirectory() as directory:
            database = Path(directory) / "operations.db"
            case_id, _ = process_contact(database)
            adapter = FakeEmailAdapter(recipient=None)
            result = approve_case(case_id, operations_database=database, email_adapter=adapter)
            self.assertEqual(result["status"], "FAILED")
            self.assertEqual(adapter.calls, [])

    def test_global_external_action_kill_switch_blocks_live_adapter(self):
        with tempfile.TemporaryDirectory() as directory:
            database = Path(directory) / "operations.db"
            case_id, _ = process_contact(database)
            result = approve_case(
                case_id,
                operations_database=database,
                email_config=EmailActionConfig(
                    mode="live",
                    external_actions_enabled=False,
                    recipient="qa@example.com",
                    sender="operator@example.com",
                ),
            )
            self.assertEqual(result["status"], "FAILED")
            events = audit_entries(case_id, database=database)
            self.assertNotIn("external_action_executed", [entry["event_type"] for entry in events])
            self.assertTrue(any(entry["error"] and "disabled" in entry["error"] for entry in events))

    def test_live_configuration_without_smtp_setup_fails_before_network(self):
        with tempfile.TemporaryDirectory() as directory:
            database = Path(directory) / "operations.db"
            case_id, _ = process_contact(database)
            result = approve_case(
                case_id,
                operations_database=database,
                email_config=EmailActionConfig(
                    mode="live",
                    external_actions_enabled=True,
                    recipient="qa@example.com",
                    sender="operator@example.com",
                ),
            )
            self.assertEqual(result["status"], "FAILED")
            self.assertTrue(
                any(
                    entry["error"] and "SMTP_HOST" in entry["error"]
                    for entry in audit_entries(case_id, database=database)
                )
            )


if __name__ == "__main__":
    unittest.main()
