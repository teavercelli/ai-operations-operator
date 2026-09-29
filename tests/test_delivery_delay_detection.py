"""Essential tests for automatic DELIVERY_DELAY detection."""

from pathlib import Path
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from delivery_delay_detection import detect_and_create_delivery_delay_cases  # noqa: E402
from operations_case_store import audit_entries, create_case, list_cases  # noqa: E402


TOP_DELAYED_ORDER = "1b3190b2dfa9d789e1f14c05b647a14a"


class DeliveryDelayDetectionTest(unittest.TestCase):
    def test_creation_is_idempotent_and_does_not_call_gemini(self):
        with tempfile.TemporaryDirectory() as directory:
            operations_database = Path(directory) / "operations.db"
            first = detect_and_create_delivery_delay_cases(
                limit=5,
                operations_database=operations_database,
            )
            second = detect_and_create_delivery_delay_cases(
                limit=5,
                operations_database=operations_database,
            )

            self.assertEqual(first["orders_scanned"], 5)
            self.assertEqual(first["issues_detected"], 5)
            self.assertEqual(first["new_cases_created"], 5)
            self.assertEqual(first["duplicates_skipped"], 0)
            self.assertEqual(first["errors"], 0)
            self.assertEqual(second["new_cases_created"], 0)
            self.assertEqual(second["duplicates_skipped"], 5)
            self.assertEqual(len(list_cases(database=operations_database)), 5)
            self.assertTrue(all(case["status"] == "OPEN" for case in list_cases(database=operations_database)))

            for case_id in first["created_case_ids"]:
                events = [entry["event_type"] for entry in audit_entries(case_id, database=operations_database)]
                self.assertIn("case_created", events)
                self.assertIn("automatic_detection_completed", events)
                self.assertIn("duplicate_detection_skipped", events)
                self.assertNotIn("external_action_simulated", events)

    def test_existing_case_is_skipped(self):
        with tempfile.TemporaryDirectory() as directory:
            operations_database = Path(directory) / "operations.db"
            existing = create_case(TOP_DELAYED_ORDER, database=operations_database)
            summary = detect_and_create_delivery_delay_cases(
                limit=1,
                operations_database=operations_database,
            )

            self.assertEqual(summary["new_cases_created"], 0)
            self.assertEqual(summary["duplicates_skipped"], 1)
            self.assertEqual(summary["created_case_ids"], [])
            self.assertEqual(len(list_cases(database=operations_database)), 1)
            events = [entry["event_type"] for entry in audit_entries(existing["case_id"], database=operations_database)]
            self.assertIn("duplicate_detection_skipped", events)


if __name__ == "__main__":
    unittest.main()
