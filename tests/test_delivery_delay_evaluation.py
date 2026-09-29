"""Small deterministic guardrail evaluation for DELIVERY_DELAY.

This suite never creates a Gemini client and never makes network calls.
"""

from pathlib import Path
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from delivery_delay_workflow import (  # noqa: E402
    GeminiWorkflowError,
    approve_case,
    create_and_investigate_case,
    validate_decision,
)
from operations_case_store import (  # noqa: E402
    audit_entries,
    create_case,
    get_case,
    list_cases,
    transition_case,
)
from queries import get_delivery_delay_evidence  # noqa: E402


LOW_DELAY_ORDER = "eb314576a333adeb296496f38c4c7852"
MEDIUM_DELAY_ORDER = "cfa4fa27b417971e86d8127cb688712f"
HIGH_DELAY_ORDER = "95ec4886946c5ae0d453e95648834ac6"
NON_LATE_ORDER = "0607f0efea4b566f1eb8f7d3c2397320"
CANCELED_ORDER = "1b9ecfe83cdc259250e1a8aca174f0ad"
MISSING_DATE_ORDER = "2d1e2d5bf4dc7227b3bfebb81328c15f"


def valid_decision(**overrides):
    decision = {
        "severity": "medium",
        "recommended_action": "send_customer_message",
        "rationale": "Decision grounded in verified delivery facts.",
        "confidence": 0.85,
        "evidence": ["days_late=7.1", "order_status=delivered"],
        "customer_message": "Ci dispiace per il ritardo nella consegna.",
    }
    decision.update(overrides)
    return decision


class TimeoutGeminiClient:
    def __init__(self):
        self.interactions = self
        self.calls = []

    def create(self, **kwargs):
        self.calls.append(kwargs)
        raise TimeoutError("evaluation timeout")


class DeliveryDelayDeterministicEvaluation(unittest.TestCase):
    def test_real_orders_cover_low_medium_high_delay_bands(self):
        cases = [
            (LOW_DELAY_ORDER, "low", 0, 7, "monitor_only"),
            (MEDIUM_DELAY_ORDER, "medium", 7, 30, "send_customer_message"),
            (HIGH_DELAY_ORDER, "high", 30, None, "escalate_to_operations"),
        ]
        for order_id, severity, lower_bound, upper_bound, action in cases:
            with self.subTest(order_id=order_id):
                evidence = get_delivery_delay_evidence(order_id)
                days_late = evidence["facts"]["days_late"]
                self.assertGreater(days_late, lower_bound)
                if upper_bound is not None:
                    self.assertLessEqual(days_late, upper_bound)
                self.assertEqual(evidence["facts"]["order_status"], "delivered")
                decision = valid_decision(severity=severity, recommended_action=action)
                self.assertEqual(validate_decision(decision, evidence), decision)

    def test_non_late_order_is_rejected(self):
        with self.assertRaisesRegex(ValueError, "not late"):
            get_delivery_delay_evidence(NON_LATE_ORDER)

    def test_canceled_order_is_rejected(self):
        with self.assertRaisesRegex(ValueError, "requires a delivered order"):
            get_delivery_delay_evidence(CANCELED_ORDER)

    def test_missing_delivery_data_is_rejected(self):
        with self.assertRaisesRegex(ValueError, "both delivery dates"):
            get_delivery_delay_evidence(MISSING_DATE_ORDER)

    def test_missing_verified_facts_are_rejected(self):
        incomplete_facts = {"facts": {"order_id": HIGH_DELAY_ORDER}}
        with self.assertRaisesRegex(ValueError, "Verified fact fields missing"):
            validate_decision(valid_decision(), incomplete_facts)

    def test_missing_evidence_is_rejected(self):
        evidence = get_delivery_delay_evidence(MEDIUM_DELAY_ORDER)
        with self.assertRaisesRegex(ValueError, "At least one evidence"):
            validate_decision(valid_decision(evidence=[]), evidence)

    def test_invalid_severity_action_and_confidence_are_rejected(self):
        evidence = get_delivery_delay_evidence(MEDIUM_DELAY_ORDER)
        invalid_decisions = [
            ("severity", "(?i)invalid severity"),
            ("recommended_action", "(?i)invalid action"),
            ("confidence", "(?i)confidence"),
        ]
        for field, expected_error in invalid_decisions:
            with self.subTest(field=field):
                value = {
                    "severity": "unknown",
                    "recommended_action": "delete_order",
                    "confidence": 1.2,
                }[field]
                with self.assertRaisesRegex(ValueError, expected_error):
                    validate_decision(valid_decision(**{field: value}), evidence)

    def test_invalid_state_transition_is_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            database = Path(directory) / "operations.db"
            case = create_case(HIGH_DELAY_ORDER, database=database)
            with self.assertRaisesRegex(ValueError, "Transition not allowed"):
                transition_case(
                    case["case_id"],
                    "OPEN",
                    "CLOSED",
                    actor="evaluation",
                    event_type="invalid_transition_attempt",
                    database=database,
                )
            self.assertEqual(get_case(case["case_id"], database=database)["status"], "OPEN")

    def test_action_cannot_run_without_human_approval(self):
        with tempfile.TemporaryDirectory() as directory:
            database = Path(directory) / "operations.db"
            case = create_case(HIGH_DELAY_ORDER, database=database)
            transition_case(
                case["case_id"],
                "OPEN",
                "INVESTIGATING",
                actor="evaluation",
                event_type="investigation_started",
                database=database,
            )
            with self.assertRaisesRegex(ValueError, "pending human approval"):
                approve_case(case["case_id"], operations_database=database)
            self.assertEqual(get_case(case["case_id"], database=database)["status"], "INVESTIGATING")
            events = [entry["event_type"] for entry in audit_entries(case["case_id"], database=database)]
            self.assertNotIn("external_action_simulated", events)

    def test_timeout_marks_case_failed_without_external_action(self):
        with tempfile.TemporaryDirectory() as directory:
            database = Path(directory) / "operations.db"
            with self.assertRaises(GeminiWorkflowError):
                create_and_investigate_case(
                    HIGH_DELAY_ORDER,
                    operations_database=database,
                    client=TimeoutGeminiClient(),
                )
            case = list_cases(database=database)[0]
            self.assertEqual(case["status"], "FAILED")
            events = [entry["event_type"] for entry in audit_entries(case["case_id"], database=database)]
            self.assertIn("gemini_timeout", events)
            self.assertIn("investigation_failed", events)
            self.assertNotIn("external_action_simulated", events)


if __name__ == "__main__":
    unittest.main()
