"""Persistence and append-only audit logging for Operations Cases."""

from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from uuid import uuid4


DEFAULT_OPERATIONS_DATABASE = Path(__file__).resolve().parents[1] / "data" / "operations.db"

ALLOWED_TRANSITIONS = {
    "OPEN": {"INVESTIGATING"},
    "INVESTIGATING": {"PENDING_HUMAN_APPROVAL", "AUTO_APPROVED", "FAILED"},
    "PENDING_HUMAN_APPROVAL": {"APPROVED", "REJECTED"},
    "APPROVED": {"SIMULATED_EXECUTED", "FAILED"},
    "AUTO_APPROVED": {"SIMULATED_EXECUTED", "FAILED"},
    "REJECTED": {"CLOSED"},
    "SIMULATED_EXECUTED": {"CLOSED"},
    "FAILED": set(),
    "CLOSED": set(),
}


class _ManagedConnection(sqlite3.Connection):
    """Commit or roll back transactions and always close the connection."""

    def __exit__(self, exc_type: Any, exc_value: Any, traceback: Any) -> Any:
        try:
            return super().__exit__(exc_type, exc_value, traceback)
        finally:
            self.close()


def now_utc() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def connect(database: Path = DEFAULT_OPERATIONS_DATABASE) -> sqlite3.Connection:
    database.parent.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(database, factory=_ManagedConnection)
    connection.row_factory = sqlite3.Row
    initialize(connection)
    return connection


def initialize(connection: sqlite3.Connection) -> None:
    connection.executescript(
        """
        CREATE TABLE IF NOT EXISTS operations_cases (
            case_id TEXT PRIMARY KEY,
            case_type TEXT NOT NULL,
            order_id TEXT NOT NULL,
            status TEXT NOT NULL,
            severity TEXT,
            recommended_action TEXT,
            rationale TEXT,
            confidence REAL,
            evidence_json TEXT,
            customer_message TEXT,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            approved_by TEXT
        );

        CREATE TABLE IF NOT EXISTS case_events (
            event_id INTEGER PRIMARY KEY AUTOINCREMENT,
            case_id TEXT NOT NULL,
            timestamp TEXT NOT NULL,
            event_type TEXT NOT NULL,
            summary TEXT NOT NULL,
            metadata_json TEXT NOT NULL
        );

        CREATE TABLE IF NOT EXISTS audit_log (
            audit_id INTEGER PRIMARY KEY AUTOINCREMENT,
            case_id TEXT NOT NULL,
            timestamp TEXT NOT NULL,
            actor TEXT NOT NULL,
            event_type TEXT NOT NULL,
            tool_name TEXT,
            input_json TEXT,
            output_json TEXT,
            from_status TEXT,
            to_status TEXT,
            success INTEGER NOT NULL,
            error TEXT
        );
        """
    )
    connection.commit()


def _json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, default=str, sort_keys=True)


def record_audit(
    case_id: str,
    actor: str,
    event_type: str,
    *,
    tool_name: str | None = None,
    input_data: Any = None,
    output_data: Any = None,
    from_status: str | None = None,
    to_status: str | None = None,
    success: bool = True,
    error: str | None = None,
    database: Path = DEFAULT_OPERATIONS_DATABASE,
) -> None:
    timestamp = now_utc()
    with connect(database) as connection:
        connection.execute(
            """
            INSERT INTO audit_log
            (case_id, timestamp, actor, event_type, tool_name, input_json, output_json,
             from_status, to_status, success, error)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                case_id,
                timestamp,
                actor,
                event_type,
                tool_name,
                _json(input_data),
                _json(output_data),
                from_status,
                to_status,
                int(success),
                error,
            ),
        )
        connection.execute(
            """
            INSERT INTO case_events (case_id, timestamp, event_type, summary, metadata_json)
            VALUES (?, ?, ?, ?, ?)
            """,
            (case_id, timestamp, event_type, error or event_type, _json(output_data)),
        )


def create_case(order_id: str, database: Path = DEFAULT_OPERATIONS_DATABASE) -> dict[str, Any]:
    timestamp = now_utc()
    case = {
        "case_id": f"case_{uuid4().hex[:12]}",
        "case_type": "DELIVERY_DELAY",
        "order_id": order_id,
        "status": "OPEN",
        "severity": None,
        "recommended_action": None,
        "rationale": None,
        "confidence": None,
        "evidence": None,
        "customer_message": None,
        "created_at": timestamp,
        "updated_at": timestamp,
        "approved_by": None,
    }
    with connect(database) as connection:
        connection.execute(
            """
            INSERT INTO operations_cases
            (case_id, case_type, order_id, status, severity, recommended_action, rationale,
             confidence, evidence_json, customer_message, created_at, updated_at, approved_by)
            VALUES (:case_id, :case_type, :order_id, :status, :severity, :recommended_action,
                    :rationale, :confidence, :evidence_json, :customer_message, :created_at,
                    :updated_at, :approved_by)
            """,
            {**case, "evidence_json": None},
        )
    record_audit(case["case_id"], "system", "case_created", output_data=case, to_status="OPEN", database=database)
    return case


def get_case(case_id: str, database: Path = DEFAULT_OPERATIONS_DATABASE) -> dict[str, Any] | None:
    with connect(database) as connection:
        row = connection.execute("SELECT * FROM operations_cases WHERE case_id = ?", (case_id,)).fetchone()
    if row is None:
        return None
    case = dict(row)
    case["evidence"] = json.loads(case["evidence_json"]) if case["evidence_json"] else None
    case.pop("evidence_json", None)
    return case


def list_cases(
    status: str | None = None,
    database: Path = DEFAULT_OPERATIONS_DATABASE,
) -> list[dict[str, Any]]:
    query = "SELECT * FROM operations_cases"
    parameters: tuple[Any, ...] = ()
    if status:
        query += " WHERE status = ?"
        parameters = (status,)
    query += " ORDER BY updated_at DESC"
    with connect(database) as connection:
        rows = connection.execute(query, parameters).fetchall()
    return [get_case(row["case_id"], database=database) for row in rows]


def find_cases_for_order(
    order_id: str,
    case_type: str = "DELIVERY_DELAY",
    database: Path = DEFAULT_OPERATIONS_DATABASE,
) -> list[dict[str, Any]]:
    """Return all cases already associated with an order and issue type."""

    with connect(database) as connection:
        rows = connection.execute(
            """
            SELECT case_id
            FROM operations_cases
            WHERE order_id = ? AND case_type = ?
            ORDER BY updated_at DESC
            """,
            (order_id, case_type),
        ).fetchall()
    return [get_case(row["case_id"], database=database) for row in rows]


def transition_case(
    case_id: str,
    expected_status: str,
    new_status: str,
    *,
    actor: str,
    event_type: str,
    output_data: Any = None,
    database: Path = DEFAULT_OPERATIONS_DATABASE,
) -> dict[str, Any]:
    case = get_case(case_id, database=database)
    if case is None:
        raise ValueError(f"Case not found: {case_id}")
    if case["status"] != expected_status:
        raise ValueError(f"Invalid case transition: {case['status']} -> {new_status}")
    if new_status not in ALLOWED_TRANSITIONS.get(expected_status, set()):
        raise ValueError(f"Transition not allowed: {expected_status} -> {new_status}")
    timestamp = now_utc()
    with connect(database) as connection:
        connection.execute(
            "UPDATE operations_cases SET status = ?, updated_at = ? WHERE case_id = ?",
            (new_status, timestamp, case_id),
        )
    record_audit(
        case_id,
        actor,
        event_type,
        output_data=output_data,
        from_status=expected_status,
        to_status=new_status,
        database=database,
    )
    return get_case(case_id, database=database)  # type: ignore[return-value]


def save_decision(
    case_id: str,
    decision: dict[str, Any],
    evidence: dict[str, Any],
    database: Path = DEFAULT_OPERATIONS_DATABASE,
) -> dict[str, Any]:
    timestamp = now_utc()
    with connect(database) as connection:
        connection.execute(
            """
            UPDATE operations_cases
            SET severity = ?, recommended_action = ?, rationale = ?, confidence = ?,
                evidence_json = ?, customer_message = ?, updated_at = ?
            WHERE case_id = ?
            """,
            (
                decision["severity"],
                decision["recommended_action"],
                decision["rationale"],
                decision["confidence"],
                _json({"facts": evidence, "selected_evidence": decision["evidence"]}),
                decision["customer_message"],
                timestamp,
                case_id,
            ),
        )
    record_audit(
        case_id,
        "gemini",
        "decision_recorded",
        output_data=decision,
        database=database,
    )
    return get_case(case_id, database=database)  # type: ignore[return-value]


def set_approval(case_id: str, approver: str, database: Path = DEFAULT_OPERATIONS_DATABASE) -> None:
    with connect(database) as connection:
        connection.execute(
            "UPDATE operations_cases SET approved_by = ?, updated_at = ? WHERE case_id = ?",
            (approver, now_utc(), case_id),
        )


def audit_entries(case_id: str, database: Path = DEFAULT_OPERATIONS_DATABASE) -> list[dict[str, Any]]:
    with connect(database) as connection:
        rows = connection.execute(
            "SELECT * FROM audit_log WHERE case_id = ? ORDER BY audit_id", (case_id,)
        ).fetchall()
    return [dict(row) for row in rows]


def all_audit_entries(
    *,
    limit: int = 200,
    database: Path = DEFAULT_OPERATIONS_DATABASE,
) -> list[dict[str, Any]]:
    """Return the most recent audit entries for the Control Center feed."""

    if limit < 1 or limit > 1000:
        raise ValueError("limit must be between 1 and 1000")
    with connect(database) as connection:
        rows = connection.execute(
            "SELECT * FROM audit_log ORDER BY audit_id DESC LIMIT ?", (limit,)
        ).fetchall()
    return [dict(row) for row in rows]


def update_customer_message(
    case_id: str,
    message: str,
    *,
    actor: str = "human",
    database: Path = DEFAULT_OPERATIONS_DATABASE,
) -> dict[str, Any]:
    """Edit the proposed message while a case is awaiting approval."""

    if not isinstance(message, str) or not message.strip():
        raise ValueError("Customer message cannot be empty")
    case = get_case(case_id, database=database)
    if case is None or case["status"] != "PENDING_HUMAN_APPROVAL":
        raise ValueError("Only pending cases can have their customer message edited")
    with connect(database) as connection:
        connection.execute(
            "UPDATE operations_cases SET customer_message = ?, updated_at = ? WHERE case_id = ?",
            (message.strip(), now_utc(), case_id),
        )
    record_audit(
        case_id,
        actor,
        "customer_message_updated",
        output_data={"message_length": len(message.strip())},
        database=database,
    )
    return get_case(case_id, database=database)  # type: ignore[return-value]
