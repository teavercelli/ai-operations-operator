"""Safe, reusable business queries for the Olist database."""

from __future__ import annotations

import csv
import sqlite3
from datetime import datetime
from pathlib import Path
from typing import Any


DEFAULT_DATABASE = Path(__file__).resolve().parents[1] / "data" / "olist.db"
DEFAULT_REPORT = Path(__file__).resolve().parents[1] / "reports" / "delivery_delays.csv"


class _ManagedConnection(sqlite3.Connection):
    """Close query connections when their transaction context exits."""

    def __exit__(self, exc_type: Any, exc_value: Any, traceback: Any) -> Any:
        try:
            return super().__exit__(exc_type, exc_value, traceback)
        finally:
            self.close()


def connect(database: Path = DEFAULT_DATABASE) -> sqlite3.Connection:
    """Open the database with dictionary-like rows."""

    connection = sqlite3.connect(database, factory=_ManagedConnection)
    connection.row_factory = sqlite3.Row
    return connection


def get_order(order_id: str, database: Path = DEFAULT_DATABASE) -> dict[str, Any] | None:
    """Return one order with its customer, items, payments, and reviews."""

    with connect(database) as connection:
        order = connection.execute(
            """
            SELECT
                o.*,
                c.customer_unique_id,
                c.customer_zip_code_prefix,
                c.customer_city,
                c.customer_state
            FROM orders AS o
            JOIN customers AS c ON c.customer_id = o.customer_id
            WHERE o.order_id = ?
            """,
            (order_id,),
        ).fetchone()
        if order is None:
            return None

        items = connection.execute(
            """
            SELECT oi.*, p.product_category_name, s.seller_city, s.seller_state
            FROM order_items AS oi
            LEFT JOIN products AS p ON p.product_id = oi.product_id
            LEFT JOIN sellers AS s ON s.seller_id = oi.seller_id
            WHERE oi.order_id = ?
            ORDER BY oi.order_item_id
            """,
            (order_id,),
        ).fetchall()
        payments = connection.execute(
            "SELECT * FROM order_payments WHERE order_id = ? ORDER BY payment_sequential",
            (order_id,),
        ).fetchall()
        reviews = connection.execute(
            "SELECT * FROM order_reviews WHERE order_id = ? ORDER BY review_creation_date",
            (order_id,),
        ).fetchall()

    return {
        "order": dict(order),
        "items": [dict(item) for item in items],
        "payments": [dict(payment) for payment in payments],
        "reviews": [dict(review) for review in reviews],
    }


def search_orders(
    status: str | None = None,
    limit: int = 20,
    database: Path = DEFAULT_DATABASE,
) -> list[dict[str, Any]]:
    """Find recent orders, optionally filtered by order status."""

    if limit < 1 or limit > 100:
        raise ValueError("limit must be between 1 and 100")
    query = """
        SELECT order_id, customer_id, order_status,
               order_purchase_timestamp, order_delivered_customer_date,
               order_estimated_delivery_date
        FROM orders
    """
    parameters: list[Any] = []
    if status:
        query += " WHERE order_status = ?"
        parameters.append(status)
    query += " ORDER BY order_purchase_timestamp DESC LIMIT ?"
    parameters.append(limit)

    with connect(database) as connection:
        return [dict(row) for row in connection.execute(query, parameters)]


def sales_summary(database: Path = DEFAULT_DATABASE) -> dict[str, Any]:
    """Return the headline sales and order metrics."""

    with connect(database) as connection:
        summary = connection.execute(
            """
            SELECT
                COUNT(*) AS total_orders,
                COUNT(DISTINCT c.customer_unique_id) AS unique_customers,
                MIN(order_purchase_timestamp) AS first_order,
                MAX(order_purchase_timestamp) AS last_order,
                SUM(CASE WHEN order_status = 'delivered' THEN 1 ELSE 0 END) AS delivered_orders
            FROM orders AS o
            JOIN customers AS c ON c.customer_id = o.customer_id
            """
        ).fetchone()
        payments = connection.execute(
            """
            SELECT COALESCE(SUM(payment_value), 0) AS payment_total,
                   COALESCE(AVG(payment_value), 0) AS average_payment
            FROM order_payments
            """
        ).fetchone()
        statuses = connection.execute(
            """
            SELECT order_status, COUNT(*) AS order_count
            FROM orders
            GROUP BY order_status
            ORDER BY order_count DESC
            """
        ).fetchall()

    result = dict(summary)
    result.update(dict(payments))
    result["statuses"] = [dict(row) for row in statuses]
    return result


def delayed_orders(limit: int | None = 20, database: Path = DEFAULT_DATABASE) -> list[dict[str, Any]]:
    """Find delivered orders whose delivery date passed the estimate."""

    if limit is not None and (limit < 1 or limit > 100):
        raise ValueError("limit must be between 1 and 100")
    query = """
        SELECT order_id, customer_id, order_status,
               order_delivered_customer_date, order_estimated_delivery_date,
               ROUND(julianday(order_delivered_customer_date) -
                     julianday(order_estimated_delivery_date), 1) AS days_late
        FROM orders
        WHERE order_status = 'delivered'
          AND order_delivered_customer_date IS NOT NULL
          AND order_estimated_delivery_date IS NOT NULL
          AND order_delivered_customer_date > order_estimated_delivery_date
        ORDER BY days_late DESC
    """
    parameters: tuple[Any, ...] = ()
    if limit is not None:
        query += " LIMIT ?"
        parameters = (limit,)
    with connect(database) as connection:
        rows = connection.execute(query, parameters).fetchall()
    return [dict(row) for row in rows]


def delivery_report(database: Path = DEFAULT_DATABASE) -> dict[str, Any]:
    """Return operational delivery-delay KPIs and the most delayed orders."""

    with connect(database) as connection:
        metrics = connection.execute(
            """
            WITH delivered AS (
                SELECT
                    julianday(order_delivered_customer_date) -
                    julianday(order_estimated_delivery_date) AS days_late
                FROM orders
                WHERE order_status = 'delivered'
                  AND order_delivered_customer_date IS NOT NULL
                  AND order_estimated_delivery_date IS NOT NULL
            )
            SELECT
                COUNT(*) AS delivered_orders,
                SUM(CASE WHEN days_late > 0 THEN 1 ELSE 0 END) AS late_orders,
                ROUND(AVG(CASE WHEN days_late > 0 THEN days_late END), 1) AS average_days_late,
                ROUND(MAX(days_late), 1) AS maximum_days_late
            FROM delivered
            """
        ).fetchone()

    result = dict(metrics)
    result["late_rate_percent"] = round(
        (result["late_orders"] / result["delivered_orders"]) * 100, 1
    )
    result["top_delayed_orders"] = delayed_orders(limit=20, database=database)
    return result


def export_delivery_report(
    output_path: Path = DEFAULT_REPORT,
    database: Path = DEFAULT_DATABASE,
) -> Path:
    """Export delayed-order details as a CSV report."""

    rows = delayed_orders(limit=100, database=database)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with output_path.open("w", encoding="utf-8", newline="") as file:
        writer = csv.DictWriter(file, fieldnames=rows[0].keys() if rows else ["order_id"])
        writer.writeheader()
        writer.writerows(rows)
    return output_path


def get_delivery_delay_evidence(
    order_id: str,
    database: Path = DEFAULT_DATABASE,
) -> dict[str, Any]:
    """Return verified facts for one delayed delivered order."""

    order_result = get_order(order_id, database=database)
    if order_result is None:
        raise ValueError(f"Order not found: {order_id}")

    order = order_result["order"]
    if order["order_status"] != "delivered":
        raise ValueError("A DELIVERY_DELAY case requires a delivered order")
    delivered_at = order.get("order_delivered_customer_date")
    estimated_at = order.get("order_estimated_delivery_date")
    if not delivered_at or not estimated_at:
        raise ValueError("Order does not have both delivery dates")

    delivered_date = datetime.fromisoformat(delivered_at)
    estimated_date = datetime.fromisoformat(estimated_at)
    days_late = (delivered_date - estimated_date).total_seconds() / 86400
    if days_late <= 0:
        raise ValueError("Order is not late")

    with connect(database) as connection:
        customer_history = connection.execute(
            """
            SELECT
                COUNT(*) AS customer_order_count,
                SUM(CASE WHEN order_status = 'delivered' THEN 1 ELSE 0 END) AS customer_delivered_count,
                MIN(order_purchase_timestamp) AS customer_first_order,
                MAX(order_purchase_timestamp) AS customer_last_order
            FROM orders
            WHERE customer_id = ?
            """,
            (order["customer_id"],),
        ).fetchone()

    payment_total = round(
        sum(float(payment.get("payment_value") or 0) for payment in order_result["payments"]),
        2,
    )
    return {
        "source": "olist.db",
        "facts": {
            "order_id": order["order_id"],
            "order_status": order["order_status"],
            "purchase_timestamp": order["order_purchase_timestamp"],
            "estimated_delivery_date": estimated_at,
            "actual_delivery_date": delivered_at,
            "days_late": round(days_late, 1),
            "customer_id": order["customer_id"],
            "customer_unique_id": order["customer_unique_id"],
            "customer_city": order["customer_city"],
            "customer_state": order["customer_state"],
            "items_count": len(order_result["items"]),
            "payment_total": payment_total,
            "payment_count": len(order_result["payments"]),
            "review_count": len(order_result["reviews"]),
            "customer_order_count": customer_history["customer_order_count"],
            "customer_delivered_count": customer_history["customer_delivered_count"],
            "customer_first_order": customer_history["customer_first_order"],
            "customer_last_order": customer_history["customer_last_order"],
        },
        "items": [
            {
                "product_id": item.get("product_id"),
                "product_category_name": item.get("product_category_name"),
                "price": item.get("price"),
                "freight_value": item.get("freight_value"),
            }
            for item in order_result["items"]
        ],
        "payments": [
            {
                "payment_type": payment.get("payment_type"),
                "payment_installments": payment.get("payment_installments"),
                "payment_value": payment.get("payment_value"),
            }
            for payment in order_result["payments"]
        ],
        "reviews": [
            {
                "review_score": review.get("review_score"),
                "review_comment_title": review.get("review_comment_title"),
                "review_comment_message": review.get("review_comment_message"),
            }
            for review in order_result["reviews"]
        ],
    }


def first_order_id(database: Path = DEFAULT_DATABASE) -> str:
    """Return a deterministic example order for demos and smoke tests."""

    with connect(database) as connection:
        row = connection.execute(
            "SELECT order_id FROM orders ORDER BY order_purchase_timestamp LIMIT 1"
        ).fetchone()
    if row is None:
        raise RuntimeError("The orders table is empty")
    return str(row[0])
