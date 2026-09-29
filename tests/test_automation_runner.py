"""Tests for bounded scheduler-ready runner behavior."""

from pathlib import Path
import json
import sys
import tempfile
from types import SimpleNamespace
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from automation_runner import run_automation_once  # noqa: E402
from automation_policy import AutomationPolicyConfig  # noqa: E402
from operations_case_store import list_cases  # noqa: E402
from queries import delayed_orders  # noqa: E402


class RunnerGeminiClient:
    def __init__(self, order_id):
        self.interactions = self
        self.order_id = order_id
        self.calls = 0

    def create(self, **kwargs):
        self.calls += 1
        if self.calls == 1:
            return SimpleNamespace(
                id="runner_initial",
                steps=[
                    SimpleNamespace(
                        type="function_call",
                        name="get_delivery_delay_evidence",
                        arguments={"order_id": self.order_id},
                        id="runner_tool_call",
                    )
                ],
                output_text="",
            )
        return SimpleNamespace(
            id="runner_decision",
            steps=[],
            output_text=json.dumps(
                {
                    "severity": "critical",
                    "recommended_action": "contact_customer",
                    "rationale": "Il ritardo richiede un contatto umano con il cliente.",
                    "confidence": 0.94,
                    "evidence": ["order_status=delivered", "days_late>0"],
                    "customer_message": "Ci scusiamo per il ritardo nella consegna.",
                }
            ),
        )


class AutomationRunnerTest(unittest.TestCase):
    def test_scan_only_is_bounded_and_idempotent(self):
        order_id = delayed_orders(limit=1)[0]["order_id"]
        with tempfile.TemporaryDirectory() as directory:
            database = Path(directory) / "operations.db"
            first = run_automation_once(
                max_orders_scanned=1,
                max_cases_created=1,
                max_cases_processed=1,
                max_gemini_calls=1,
                operations_database=database,
                enable_gemini=False,
            )
            self.assertEqual(first["mode"], "demo_safe_scan_only")
            self.assertEqual(first["gemini_calls_used"], 0)
            self.assertEqual(first["detection"]["new_cases_created"], 1)
            self.assertEqual(len(list_cases(database=database)), 1)

            second = run_automation_once(
                max_orders_scanned=1,
                max_cases_created=1,
                max_cases_processed=1,
                max_gemini_calls=1,
                operations_database=database,
                enable_gemini=False,
            )
            self.assertEqual(second["detection"]["new_cases_created"], 0)
            self.assertEqual(second["detection"]["duplicates_skipped"], 1)
            self.assertEqual(len(list_cases(database=database)), 1)
            self.assertEqual(order_id, list_cases(database=database)[0]["order_id"])

    def test_bounded_runner_processes_open_case_with_controlled_client(self):
        order_id = delayed_orders(limit=1)[0]["order_id"]
        with tempfile.TemporaryDirectory() as directory:
            database = Path(directory) / "operations.db"
            result = run_automation_once(
                max_orders_scanned=1,
                max_cases_created=1,
                max_cases_processed=1,
                max_gemini_calls=2,
                operations_database=database,
                client=RunnerGeminiClient(order_id),
                policy_config=AutomationPolicyConfig(enabled=False),
            )
            self.assertEqual(result["mode"], "bounded_once")
            self.assertEqual(result["gemini_calls_used"], 2)
            self.assertEqual(result["processing"]["processed"], 1)
            self.assertEqual(result["processing"]["pending_human_approval"], 1)
            self.assertEqual(result["processing"]["failed"], 0)


if __name__ == "__main__":
    unittest.main()
