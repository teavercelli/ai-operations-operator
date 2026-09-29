"""Import the Olist CSV files into a local SQLite database.

The importer deliberately keeps the source columns intact. That makes the
database a faithful local copy of the public dataset while still giving us
typed numeric fields for analysis.
"""

from __future__ import annotations

import argparse
import csv
import re
import sqlite3
from pathlib import Path
from typing import Iterable, Mapping, Sequence


PROJECT_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_DATA_DIR = PROJECT_ROOT / "data"
DEFAULT_DATABASE = DEFAULT_DATA_DIR / "olist.db"

CSV_TABLES = {
    "olist_customers_dataset.csv": "customers",
    "olist_geolocation_dataset.csv": "geolocation",
    "olist_order_items_dataset.csv": "order_items",
    "olist_order_payments_dataset.csv": "order_payments",
    "olist_order_reviews_dataset.csv": "order_reviews",
    "olist_orders_dataset.csv": "orders",
    "olist_products_dataset.csv": "products",
    "olist_sellers_dataset.csv": "sellers",
    "product_category_name_translation.csv": "category_translation",
}

CORE_CSV_TABLES = {
    filename: table
    for filename, table in CSV_TABLES.items()
    if table not in {"geolocation", "category_translation"}
}

INTEGER_RE = re.compile(r"^[+-]?\d+$")
REAL_RE = re.compile(r"^[+-]?(?:\d+\.\d*|\d*\.\d+)(?:[eE][+-]?\d+)?$")


def quote_identifier(identifier: str) -> str:
    """Safely quote a SQLite identifier such as a table or column name."""

    return '"' + identifier.replace('"', '""') + '"'


def infer_sqlite_type(values: Iterable[str]) -> str:
    """Infer a small, useful SQLite type from non-empty CSV values."""

    non_empty = [value for value in values if value != ""]
    if not non_empty:
        return "TEXT"
    if all(INTEGER_RE.fullmatch(value) for value in non_empty):
        return "INTEGER"
    if all(INTEGER_RE.fullmatch(value) or REAL_RE.fullmatch(value) for value in non_empty):
        return "REAL"
    return "TEXT"


def convert_value(value: str, sqlite_type: str):
    if value == "":
        return None
    if sqlite_type == "INTEGER":
        return int(value)
    if sqlite_type == "REAL":
        return float(value)
    return value


def load_csv(csv_path: Path) -> tuple[list[str], list[dict[str, str]], list[str]]:
    """Read a CSV and return columns, rows, and inferred SQLite types."""

    with csv_path.open("r", encoding="utf-8-sig", newline="") as file:
        reader = csv.DictReader(file)
        if not reader.fieldnames:
            raise ValueError(f"CSV has no header: {csv_path.name}")

        columns = [column.strip() for column in reader.fieldnames]
        rows = [
            {column: (row.get(original) or "").strip() for original, column in zip(reader.fieldnames, columns)}
            for row in reader
        ]

    types = [infer_sqlite_type(row[column] for row in rows) for column in columns]
    return columns, rows, types


def create_table(connection: sqlite3.Connection, table: str, columns: Sequence[str], types: Sequence[str]) -> None:
    definitions = ", ".join(
        f"{quote_identifier(column)} {sqlite_type}" for column, sqlite_type in zip(columns, types)
    )
    connection.execute(f"CREATE TABLE {quote_identifier(table)} ({definitions})")


def import_table(connection: sqlite3.Connection, csv_path: Path, table: str) -> int:
    columns, rows, types = load_csv(csv_path)
    create_table(connection, table, columns, types)

    column_sql = ", ".join(quote_identifier(column) for column in columns)
    placeholders = ", ".join("?" for _ in columns)
    insert_sql = f"INSERT INTO {quote_identifier(table)} ({column_sql}) VALUES ({placeholders})"
    values = (
        tuple(convert_value(row[column], sqlite_type) for column, sqlite_type in zip(columns, types))
        for row in rows
    )
    connection.executemany(insert_sql, values)
    return len(rows)


def create_indexes(connection: sqlite3.Connection) -> None:
    """Add indexes used by the first order/customer analysis queries."""

    indexes = {
        "idx_orders_customer_id": ("orders", "customer_id"),
        "idx_order_items_order_id": ("order_items", "order_id"),
        "idx_order_items_product_id": ("order_items", "product_id"),
        "idx_order_items_seller_id": ("order_items", "seller_id"),
        "idx_order_payments_order_id": ("order_payments", "order_id"),
        "idx_order_reviews_order_id": ("order_reviews", "order_id"),
    }
    for index_name, (table, column) in indexes.items():
        existing_columns = {
            row[1] for row in connection.execute(f"PRAGMA table_info({quote_identifier(table)})")
        }
        if column in existing_columns:
            connection.execute(
                f"CREATE INDEX {quote_identifier(index_name)} ON "
                f"{quote_identifier(table)} ({quote_identifier(column)})"
            )


def build_database(
    data_dir: Path = DEFAULT_DATA_DIR,
    database_path: Path = DEFAULT_DATABASE,
    csv_tables: Mapping[str, str] | None = None,
) -> dict[str, int]:
    """Build the SQLite database and return imported row counts by table."""

    tables_to_import = dict(csv_tables or CSV_TABLES)
    missing = [filename for filename in tables_to_import if not (data_dir / filename).exists()]
    if missing:
        raise FileNotFoundError("Missing CSV files: " + ", ".join(missing))
    if database_path.exists():
        raise FileExistsError(
            f"Database already exists: {database_path}. Use --replace to rebuild it."
        )

    database_path.parent.mkdir(parents=True, exist_ok=True)
    counts: dict[str, int] = {}
    connection = sqlite3.connect(database_path)
    try:
        connection.execute("PRAGMA foreign_keys = ON")
        connection.execute("PRAGMA journal_mode = OFF")
        connection.execute("PRAGMA synchronous = OFF")
        connection.execute("PRAGMA temp_store = MEMORY")
        for filename, table in tables_to_import.items():
            counts[table] = import_table(connection, data_dir / filename, table)
        create_indexes(connection)
        connection.commit()
    finally:
        connection.close()
    return counts


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data-dir", type=Path, default=DEFAULT_DATA_DIR)
    parser.add_argument("--database", type=Path, default=DEFAULT_DATABASE)
    parser.add_argument(
        "--replace",
        action="store_true",
        help="replace an existing SQLite database with a fresh import",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    if args.replace and args.database.exists():
        args.database.unlink()
    counts = build_database(args.data_dir, args.database)
    print(f"Created {args.database}")
    for table, count in counts.items():
        print(f"  {table:20} {count:>7,} rows")


if __name__ == "__main__":
    main()
