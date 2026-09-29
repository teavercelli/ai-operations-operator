"""Basic integrity checks for the imported Olist database."""

from pathlib import Path
import sqlite3
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import MagicMock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from queries import (
    delivery_report,
    delayed_orders,
    export_delivery_report,
    first_order_id,
    get_order,
    sales_summary,
    search_orders,
)
from ai_operator import TOOLS, ask, dispatch_tool


DATABASE = Path(__file__).resolve().parents[1] / "data" / "olist.db"
EXPECTED_TABLES = {
    "customers",
    "geolocation",
    "order_items",
    "order_payments",
    "order_reviews",
    "orders",
    "products",
    "sellers",
    "category_translation",
}


class DatabaseIntegrityTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        if not DATABASE.exists():
            raise AssertionError(f"Database not found: {DATABASE}")
        cls.connection = sqlite3.connect(DATABASE)

    @classmethod
    def tearDownClass(cls):
        cls.connection.close()

    def test_expected_tables_exist(self):
        tables = {
            row[0]
            for row in self.connection.execute(
                "SELECT name FROM sqlite_master WHERE type = 'table'"
            )
        }
        self.assertTrue(EXPECTED_TABLES.issubset(tables))

    def test_core_tables_have_rows(self):
        for table in ("customers", "orders", "order_items", "products"):
            count = self.connection.execute(f'SELECT COUNT(*) FROM "{table}"').fetchone()[0]
            self.assertGreater(count, 0, table)

    def test_order_relationships_are_queryable(self):
        result = self.connection.execute(
            """
            SELECT COUNT(*)
            FROM orders AS o
            JOIN customers AS c ON c.customer_id = o.customer_id
            JOIN order_items AS oi ON oi.order_id = o.order_id
            """
        ).fetchone()[0]
        self.assertGreater(result, 0)

    def test_query_tools_return_business_data(self):
        order = get_order(first_order_id())
        self.assertIsNotNone(order)
        self.assertGreater(len(order["items"]), 0)

        summary = sales_summary()
        self.assertGreater(summary["total_orders"], 0)
        self.assertGreater(summary["payment_total"], 0)

        self.assertEqual(len(search_orders(limit=5)), 5)
        self.assertLessEqual(len(delayed_orders(limit=5)), 5)

    def test_ai_tools_are_allowlisted_and_strict(self):
        names = {tool["name"] for tool in TOOLS}
        self.assertEqual(
            names,
            {
                "get_order",
                "get_sales_summary",
                "get_delayed_orders",
                "get_delivery_report",
                "get_recent_orders",
            },
        )
        self.assertTrue(all(tool["type"] == "function" for tool in TOOLS))
        summary = dispatch_tool("get_sales_summary", {})
        self.assertGreater(summary["total_orders"], 0)

    def test_delivery_report_and_export(self):
        report = delivery_report()
        self.assertGreater(report["delivered_orders"], 0)
        self.assertGreater(report["late_orders"], 0)
        self.assertGreater(report["late_rate_percent"], 0)
        self.assertLessEqual(len(report["top_delayed_orders"]), 20)

        with tempfile.TemporaryDirectory() as directory:
            output_path = Path(directory) / "delivery_delays.csv"
            export_delivery_report(output_path)
            self.assertTrue(output_path.exists())
            self.assertGreater(output_path.stat().st_size, 0)

    def test_ai_tool_call_loop(self):
        fake_client = MagicMock()
        fake_client.interactions.create.side_effect = [
            SimpleNamespace(
                id="interaction_test",
                steps=[
                    SimpleNamespace(
                        type="function_call",
                        name="get_sales_summary",
                        arguments={},
                        id="call_test",
                    )
                ],
                output_text="",
            ),
            SimpleNamespace(output_text="Ecco il riepilogo delle vendite."),
        ]

        with patch("ai_operator.genai.Client", return_value=fake_client):
            result = ask("Qual è il riepilogo delle vendite?")

        self.assertEqual(result, "Ecco il riepilogo delle vendite.")
        self.assertEqual(fake_client.interactions.create.call_count, 2)


if __name__ == "__main__":
    unittest.main()
