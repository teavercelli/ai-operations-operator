"""End-to-end DELIVERY_DELAY Operations Case workflow."""

from __future__ import annotations

import json
import logging
import re
import time
from collections.abc import Callable
from typing import Any

import httpx
from google import genai
from google.genai import types

from automation_policy import (
    AutomationPolicyConfig,
    SUPPORTED_ACTIONS,
    evaluate_automation_policy,
)
from email_adapter import (
    EmailActionConfig,
    EmailAdapter,
    EmailSendResult,
    build_email_adapter,
    validate_email_recipient,
    validate_customer_message,
)
from operations_case_store import (
    DEFAULT_OPERATIONS_DATABASE,
    audit_entries,
    create_case,
    get_case,
    list_cases,
    record_audit,
    save_decision,
    set_approval,
    transition_case,
)
from queries import DEFAULT_DATABASE, get_delivery_delay_evidence


SEVERITIES = {"low", "medium", "high", "critical"}
ALLOWED_ACTIONS = set(SUPPORTED_ACTIONS)
REQUIRED_FACT_FIELDS = {
    "order_id",
    "order_status",
    "days_late",
    "estimated_delivery_date",
    "actual_delivery_date",
}
MODEL = "gemini-3.8-flash"
GEMINI_TIMEOUT_SECONDS = 45.0
MAX_GEMINI_ATTEMPTS = 2
MAX_TOOL_CALLS = 3
MAX_INVESTIGATION_STEPS = 6
RETRY_BACKOFF_SECONDS = 0.5

logger = logging.getLogger(__name__)


class GeminiWorkflowError(RuntimeError):
    """A Gemini request failed in a known workflow phase."""

    def __init__(self, message: str, *, phase: str, attempts: int = 1):
        super().__init__(message)
        self.phase = phase
        self.attempts = attempts


class GeminiCallBudget:
    """Per-run hard cap for outbound Gemini interaction attempts."""

    def __init__(self, max_calls: int):
        if max_calls < 1:
            raise ValueError("max_calls must be at least 1")
        self.max_calls = max_calls
        self.used = 0

    @property
    def remaining(self) -> int:
        return self.max_calls - self.used

    def consume(self) -> None:
        if self.used >= self.max_calls:
            raise GeminiWorkflowError(
                f"Gemini call budget exhausted ({self.max_calls})",
                phase="run_budget",
                attempts=0,
            )
        self.used += 1

FACT_TOOL = {
    "type": "function",
    "name": "get_delivery_delay_evidence",
    "description": "Recupera facts verificati per un ordine consegnato in ritardo. Non prende decisioni.",
    "parameters": {
        "type": "object",
        "properties": {"order_id": {"type": "string", "description": "ID completo dell'ordine"}},
        "required": ["order_id"],
        "additionalProperties": False,
    },
}

DECISION_PROMPT = """
Sei il decisore di un Operations Case DELIVERY_DELAY.
Usa esclusivamente i facts restituiti dal tool Python.
I facts sono evidenze: non modificarli e non inventare dati.

Devi classificare la severità, proporre una sola azione, motivarla e preparare
un eventuale messaggio in italiano per il cliente.
Non eseguire azioni e non dichiarare che un messaggio è stato inviato.
L'azione sarà sottoposta ad approvazione umana e poi eseguita dal sistema secondo la policy.

Rispondi SOLO con JSON valido, senza markdown, usando esattamente questa forma:
{
  "severity": "low|medium|high|critical",
  "recommended_action": "send_customer_message|contact_customer|escalate_to_operations|monitor_only",
  "rationale": "motivazione basata sui facts",
  "confidence": 0.0,
  "evidence": ["elenco di facts specifici usati nella decisione"],
  "customer_message": "messaggio da proporre al cliente oppure stringa vuota"
}
""".strip()


def _json_from_text(text: str) -> dict[str, Any]:
    cleaned = text.strip()
    if cleaned.startswith("```"):
        cleaned = re.sub(r"^```(?:json)?\s*|\s*```$", "", cleaned, flags=re.IGNORECASE | re.DOTALL)
    try:
        result = json.loads(cleaned)
    except json.JSONDecodeError as error:
        raise ValueError(f"Gemini did not return valid JSON: {error}") from error
    if not isinstance(result, dict):
        raise ValueError("Gemini decision must be a JSON object")
    return result


def validate_decision(decision: dict[str, Any], facts: dict[str, Any]) -> dict[str, Any]:
    fact_values = facts.get("facts") if isinstance(facts, dict) else None
    if not isinstance(fact_values, dict):
        raise ValueError("Verified facts are missing")
    missing_facts = REQUIRED_FACT_FIELDS - fact_values.keys()
    if missing_facts:
        raise ValueError(f"Verified fact fields missing: {sorted(missing_facts)}")
    if fact_values["order_status"] != "delivered":
        raise ValueError("Verified facts must describe a delivered order")
    if not isinstance(fact_values["days_late"], (int, float)) or fact_values["days_late"] <= 0:
        raise ValueError("Verified facts must describe a positive delivery delay")
    required = {"severity", "recommended_action", "rationale", "confidence", "evidence", "customer_message"}
    missing = required - decision.keys()
    if missing:
        raise ValueError(f"Decision fields missing: {sorted(missing)}")
    if decision["severity"] not in SEVERITIES:
        raise ValueError(f"Invalid severity: {decision['severity']}")
    if decision["recommended_action"] not in ALLOWED_ACTIONS:
        raise ValueError(f"Invalid action: {decision['recommended_action']}")
    if not isinstance(decision["rationale"], str) or not decision["rationale"].strip():
        raise ValueError("Decision rationale is required")
    if not isinstance(decision["confidence"], (int, float)) or not 0 <= decision["confidence"] <= 1:
        raise ValueError("Confidence must be between 0 and 1")
    if not isinstance(decision["evidence"], list) or not decision["evidence"]:
        raise ValueError("At least one evidence item is required")
    if not all(isinstance(item, str) and item.strip() for item in decision["evidence"]):
        raise ValueError("Evidence must be a list of non-empty strings")
    if decision["recommended_action"] in {"send_customer_message", "contact_customer"}:
        validate_customer_message(decision["customer_message"])
    if decision["recommended_action"] == "monitor_only" and facts["facts"]["days_late"] > 7:
        raise ValueError("Orders more than 7 days late cannot be marked monitor_only")
    if facts["facts"]["days_late"] > 30 and decision["severity"] == "low":
        raise ValueError("Orders more than 30 days late cannot have low severity")
    return decision


def _is_timeout(error: BaseException) -> bool:
    return isinstance(error, (TimeoutError, httpx.TimeoutException)) or "timeout" in type(error).__name__.lower()


def _emit_event(
    callback: Callable[[str, dict[str, Any], str | None], None] | None,
    event_type: str,
    payload: dict[str, Any],
    error: BaseException | None = None,
) -> None:
    error_text = str(error) if error else None
    logger.info("gemini_event=%s payload=%s error=%s", event_type, payload, error_text)
    if callback:
        callback(event_type, payload, error_text)


def _create_with_retry(
    client: Any,
    *,
    phase: str,
    event_callback: Callable[[str, dict[str, Any], str | None], None] | None,
    gemini_budget: GeminiCallBudget | None = None,
    **request: Any,
) -> Any:
    last_error: BaseException | None = None
    for attempt in range(1, MAX_GEMINI_ATTEMPTS + 1):
        if gemini_budget is not None:
            gemini_budget.consume()
        started = time.perf_counter()
        _emit_event(
            event_callback,
            "gemini_request_started",
            {"phase": phase, "attempt": attempt, "timeout_seconds": GEMINI_TIMEOUT_SECONDS},
        )
        try:
            response = client.interactions.create(
                timeout=GEMINI_TIMEOUT_SECONDS,
                **request,
            )
        except Exception as error:
            last_error = error
            duration_ms = round((time.perf_counter() - started) * 1000, 1)
            event_type = "gemini_timeout" if _is_timeout(error) else "gemini_request_error"
            _emit_event(
                event_callback,
                event_type,
                {"phase": phase, "attempt": attempt, "duration_ms": duration_ms},
                error,
            )
            if attempt >= MAX_GEMINI_ATTEMPTS:
                raise GeminiWorkflowError(
                    f"Gemini {phase} failed after {attempt} attempts: {error}",
                    phase=phase,
                    attempts=attempt,
                ) from error
            _emit_event(
                event_callback,
                "gemini_retry_scheduled",
                {"phase": phase, "attempt": attempt, "next_attempt": attempt + 1},
            )
            time.sleep(RETRY_BACKOFF_SECONDS)
            continue

        duration_ms = round((time.perf_counter() - started) * 1000, 1)
        steps = getattr(response, "steps", []) or []
        _emit_event(
            event_callback,
            "gemini_response_received",
            {
                "phase": phase,
                "attempt": attempt,
                "duration_ms": duration_ms,
                "interaction_id": getattr(response, "id", None),
                "step_count": len(steps),
            },
        )
        return response

    raise GeminiWorkflowError(
        f"Gemini {phase} failed: {last_error}",
        phase=phase,
        attempts=MAX_GEMINI_ATTEMPTS,
    )


def investigate_with_gemini(
    order_id: str,
    *,
    client: Any | None = None,
    model: str = MODEL,
    event_callback: Callable[[str, dict[str, Any], str | None], None] | None = None,
    gemini_budget: GeminiCallBudget | None = None,
) -> tuple[dict[str, Any], dict[str, Any], list[dict[str, Any]]]:
    """Let Gemini call the facts tool and return a validated decision."""

    client = client or genai.Client(
        http_options=types.HttpOptions(
            retry_options=types.HttpRetryOptions(attempts=1),
        )
    )
    interaction = _create_with_retry(
        client,
        phase="initial_interaction",
        event_callback=event_callback,
        gemini_budget=gemini_budget,
        model=model,
        input=f"{DECISION_PROMPT}\n\nInvestiga l'ordine {order_id}.",
        tools=[FACT_TOOL],
    )
    initial_steps = getattr(interaction, "steps", []) or []
    if len(initial_steps) > MAX_INVESTIGATION_STEPS:
        raise GeminiWorkflowError(
            f"Gemini exceeded the investigation step limit: {len(initial_steps)}",
            phase="initial_interaction",
        )
    calls = [step for step in initial_steps if step.type == "function_call"]
    if not calls:
        raise ValueError("Gemini did not call the evidence tool")
    if len(calls) > MAX_TOOL_CALLS:
        raise GeminiWorkflowError(
            f"Gemini exceeded the tool-call limit: {len(calls)}",
            phase="tool_execution",
        )

    tool_calls: list[dict[str, Any]] = []
    function_results: list[dict[str, Any]] = []
    evidence: dict[str, Any] | None = None
    for call in calls:
        arguments = call.arguments if isinstance(call.arguments, dict) else json.loads(call.arguments)
        if call.name != "get_delivery_delay_evidence":
            raise ValueError(f"Unauthorized workflow tool: {call.name}")
        if arguments.get("order_id") != order_id:
            raise ValueError("Gemini requested evidence for an order outside this case")
        _emit_event(
            event_callback,
            "tool_call_requested",
            {"tool_name": call.name, "arguments": arguments, "call_id": call.id},
        )
        evidence = get_delivery_delay_evidence(arguments["order_id"], database=DEFAULT_DATABASE)
        tool_calls.append({"name": call.name, "arguments": arguments, "result": evidence})
        function_results.append(
            {
                "type": "function_result",
                "name": call.name,
                "call_id": call.id,
                "result": [{"type": "text", "text": json.dumps(evidence, ensure_ascii=False, default=str)}],
            }
        )

    final_interaction = _create_with_retry(
        client,
        phase="decision_interaction",
        event_callback=event_callback,
        gemini_budget=gemini_budget,
        model=model,
        previous_interaction_id=interaction.id,
        input=function_results,
        tools=[FACT_TOOL],
    )
    final_steps = getattr(final_interaction, "steps", []) or []
    if len(initial_steps) + len(final_steps) > MAX_INVESTIGATION_STEPS:
        raise GeminiWorkflowError(
            "Gemini exceeded the total investigation step limit",
            phase="decision_interaction",
        )
    decision = _json_from_text(final_interaction.output_text)
    _emit_event(
        event_callback,
        "decision_parsed",
        {"fields": sorted(decision.keys()), "interaction_id": getattr(final_interaction, "id", None)},
    )
    if evidence is None:
        raise ValueError("No evidence returned by the facts tool")
    return validate_decision(decision, evidence), evidence, tool_calls


def _simulate_and_close_case(
    case_id: str,
    *,
    expected_status: str,
    actor: str,
    operations_database=DEFAULT_OPERATIONS_DATABASE,
) -> dict[str, Any]:
    """Execute only the existing simulated action after an approved status."""

    case = get_case(case_id, database=operations_database)
    if case is None or case["status"] != expected_status:
        raise ValueError(f"Simulated action requires status {expected_status}")
    simulated_result = {
        "simulated": True,
        "action": case["recommended_action"],
        "message_would_be_sent": case["customer_message"]
        if case["recommended_action"] == "send_customer_message"
        else None,
    }
    record_audit(
        case_id,
        "system",
        "external_action_simulated",
        output_data=simulated_result,
        database=operations_database,
    )
    transition_case(
        case_id,
        expected_status,
        "SIMULATED_EXECUTED",
        actor=actor,
        event_type="simulated_action_completed",
        output_data=simulated_result,
        database=operations_database,
    )
    return transition_case(
        case_id,
        "SIMULATED_EXECUTED",
        "CLOSED",
        actor="system",
        event_type="case_closed",
        output_data={"simulated": True},
        database=operations_database,
    )


def _fail_approved_action(
    case_id: str,
    *,
    error: str,
    actor: str,
    operations_database=DEFAULT_OPERATIONS_DATABASE,
) -> dict[str, Any]:
    """Leave an approved case FAILED when its external action did not succeed."""

    return transition_case(
        case_id,
        "APPROVED",
        "FAILED",
        actor=actor,
        event_type="external_action_failed_status",
        output_data={"error": error},
        database=operations_database,
    )


def _execute_contact_customer(
    case: dict[str, Any],
    *,
    actor: str,
    email_adapter: EmailAdapter | None,
    email_config: EmailActionConfig | None,
    operations_database=DEFAULT_OPERATIONS_DATABASE,
) -> dict[str, Any]:
    """Validate and execute contact_customer through the provider-neutral adapter."""

    case_id = case["case_id"]
    try:
        config = email_config or EmailActionConfig.from_env()
        adapter = email_adapter or build_email_adapter(config)
    except Exception as error:
        record_audit(
            case_id,
            "email_adapter",
            "external_action_failed",
            input_data={"action": "contact_customer", "provider": "unavailable"},
            success=False,
            error=str(error),
            database=operations_database,
        )
        return _fail_approved_action(
            case_id,
            error=str(error),
            actor=actor,
            operations_database=operations_database,
        )
    recipient = getattr(adapter, "default_recipient", None) or config.recipient or case.get("customer_email")
    try:
        recipient = validate_email_recipient(recipient)
        body = validate_customer_message(case.get("customer_message"))
    except ValueError as error:
        record_audit(
            case_id,
            "email_adapter",
            "external_action_failed",
            input_data={"action": "contact_customer", "provider": getattr(adapter, "provider", "unknown")},
            success=False,
            error=str(error),
            database=operations_database,
        )
        return _fail_approved_action(
            case_id,
            error=str(error),
            actor=actor,
            operations_database=operations_database,
        )

    subject = "Aggiornamento sulla consegna del tuo ordine"
    provider = getattr(adapter, "provider", "unknown")
    record_audit(
        case_id,
        "email_adapter",
        "email_action_attempted",
        tool_name=provider,
        input_data={
            "action": "contact_customer",
            "provider": provider,
            "recipient": recipient,
            "subject": subject,
            "mode": config.mode,
        },
        database=operations_database,
    )
    try:
        result: EmailSendResult = adapter.send(
            recipient=recipient,
            subject=subject,
            body=body,
        )
    except Exception as error:
        record_audit(
            case_id,
            "email_adapter",
            "external_action_failed",
            tool_name=provider,
            input_data={"action": "contact_customer", "recipient": recipient},
            success=False,
            error=f"{type(error).__name__}: {error}",
            database=operations_database,
        )
        return _fail_approved_action(
            case_id,
            error=f"{type(error).__name__}: {error}",
            actor=actor,
            operations_database=operations_database,
        )
    result_data = result.as_dict()
    result_data.update({"action": "contact_customer", "recipient": recipient, "provider": provider})
    record_audit(
        case_id,
        "email_adapter",
        "email_action_result",
        tool_name=provider,
        input_data={"action": "contact_customer", "recipient": recipient},
        output_data=result_data,
        success=result.success,
        error=result.error,
        database=operations_database,
    )
    if not result.success:
        record_audit(
            case_id,
            "email_adapter",
            "external_action_failed",
            tool_name=provider,
            output_data=result_data,
            success=False,
            error=result.error or "Email adapter failed",
            database=operations_database,
        )
        return _fail_approved_action(
            case_id,
            error=result.error or "Email adapter failed",
            actor=actor,
            operations_database=operations_database,
        )

    event_type = "external_action_simulated" if result.simulated else "external_action_executed"
    record_audit(
        case_id,
        "email_adapter",
        event_type,
        tool_name=provider,
        output_data=result_data,
        database=operations_database,
    )
    transition_case(
        case_id,
        "APPROVED",
        "SIMULATED_EXECUTED",
        actor=actor,
        event_type="email_action_completed",
        output_data=result_data,
        database=operations_database,
    )
    return transition_case(
        case_id,
        "SIMULATED_EXECUTED",
        "CLOSED",
        actor="system",
        event_type="case_closed",
        output_data={"external_action": event_type, "provider": provider},
        database=operations_database,
    )


def process_open_case(
    case_id: str,
    *,
    operations_database=DEFAULT_OPERATIONS_DATABASE,
    client: Any | None = None,
    policy_config: AutomationPolicyConfig | None = None,
    gemini_budget: GeminiCallBudget | None = None,
) -> dict[str, Any]:
    """Process one existing DELIVERY_DELAY case from OPEN to approval or FAILED."""

    case = get_case(case_id, database=operations_database)
    if case is None:
        raise ValueError(f"Case not found: {case_id}")
    if case["case_type"] != "DELIVERY_DELAY":
        raise ValueError(f"Unsupported case type: {case['case_type']}")
    if case["status"] != "OPEN":
        raise ValueError(f"Only OPEN cases can be processed; current status is {case['status']}")

    order_id = case["order_id"]
    transition_case(
        case_id,
        "OPEN",
        "INVESTIGATING",
        actor="processor",
        event_type="automatic_ai_processing_started",
        output_data={"order_id": order_id},
        database=operations_database,
    )

    def audit_gemini_event(event_type: str, payload: dict[str, Any], error: str | None) -> None:
        record_audit(
            case_id,
            "gemini",
            event_type,
            input_data=payload,
            output_data=None if error else payload,
            success=error is None,
            error=error,
            database=operations_database,
        )

    try:
        policy_config = policy_config or AutomationPolicyConfig.from_env()
        # Facts remain Python-owned. Gemini only sees the result through the authorized tool.
        facts = get_delivery_delay_evidence(order_id, database=DEFAULT_DATABASE)
        record_audit(
            case_id,
            "python",
            "tool_call_completed",
            tool_name="get_delivery_delay_evidence",
            input_data={"order_id": order_id, "purpose": "automatic_ai_processing"},
            output_data=facts,
            database=operations_database,
        )
        decision, evidence, tool_calls = investigate_with_gemini(
            order_id,
            client=client,
            event_callback=audit_gemini_event,
            gemini_budget=gemini_budget,
        )
        for tool_call in tool_calls:
            record_audit(
                case_id,
                "gemini",
                "tool_call_completed",
                tool_name=tool_call["name"],
                input_data=tool_call["arguments"],
                output_data=tool_call["result"],
                database=operations_database,
            )
        save_decision(case_id, decision, evidence, database=operations_database)
        policy_result = evaluate_automation_policy(decision, evidence, policy_config)
        record_audit(
            case_id,
            "policy",
            "automation_policy_decision",
            input_data={
                "severity": decision["severity"],
                "confidence": decision["confidence"],
                "recommended_action": decision["recommended_action"],
                "policy_config": policy_config.as_dict(),
            },
            output_data=policy_result,
            database=operations_database,
        )
        if policy_result["outcome"] == "AUTO_APPROVED":
            transition_case(
                case_id,
                "INVESTIGATING",
                "AUTO_APPROVED",
                actor="policy",
                event_type="automation_policy_auto_approved",
                output_data=policy_result,
                database=operations_database,
            )
            return _simulate_and_close_case(
                case_id,
                expected_status="AUTO_APPROVED",
                actor="policy",
                operations_database=operations_database,
            )
        return transition_case(
            case_id,
            "INVESTIGATING",
            "PENDING_HUMAN_APPROVAL",
            actor="processor",
            event_type="human_approval_requested",
            output_data={"confidence": decision["confidence"], "facts_checked": facts["facts"]},
            database=operations_database,
        )
    except (Exception, KeyboardInterrupt) as error:
        record_audit(
            case_id,
            "processor",
            "investigation_failed",
            output_data={
                "order_id": order_id,
                "error_type": type(error).__name__,
                "phase": getattr(error, "phase", None),
                "attempts": getattr(error, "attempts", None),
            },
            success=False,
            error=str(error),
            database=operations_database,
        )
        current_case = get_case(case_id, database=operations_database)
        if current_case and current_case["status"] == "INVESTIGATING":
            transition_case(
                case_id,
                "INVESTIGATING",
                "FAILED",
                actor="processor",
                event_type="investigation_failed_status",
                output_data={"error": str(error)},
                database=operations_database,
            )
        raise


def process_open_cases(
    *,
    limit: int | None = None,
    operations_database=DEFAULT_OPERATIONS_DATABASE,
    client: Any | None = None,
    policy_config: AutomationPolicyConfig | None = None,
    gemini_budget: GeminiCallBudget | None = None,
) -> dict[str, Any]:
    """Process only OPEN DELIVERY_DELAY cases, one at a time."""

    if limit is not None and (limit < 1 or limit > 100):
        raise ValueError("limit must be between 1 and 100")
    open_cases = [
        case
        for case in list_cases(status="OPEN", database=operations_database)
        if case["case_type"] == "DELIVERY_DELAY"
    ]
    selected_cases = open_cases if limit is None else open_cases[:limit]
    summary = {
        "open_cases_found": len(open_cases),
        "processed": 0,
        "pending_human_approval": 0,
        "auto_approved": 0,
        "failed": 0,
        "errors": 0,
        "skipped_gemini_cap": 0,
        "case_results": [],
    }
    for case in selected_cases:
        if gemini_budget is not None and gemini_budget.remaining < 2:
            summary["skipped_gemini_cap"] += 1
            summary["case_results"].append(
                {"case_id": case["case_id"], "status": "OPEN", "skipped": "gemini_call_cap"}
            )
            continue
        summary["processed"] += 1
        try:
            processed = process_open_case(
                case["case_id"],
                operations_database=operations_database,
                client=client,
                policy_config=policy_config,
                gemini_budget=gemini_budget,
            )
            if processed["status"] == "PENDING_HUMAN_APPROVAL":
                summary["pending_human_approval"] += 1
            elif processed["status"] == "CLOSED":
                summary["auto_approved"] += 1
            summary["case_results"].append(
                {"case_id": processed["case_id"], "status": processed["status"]}
            )
        except Exception as error:
            current = get_case(case["case_id"], database=operations_database)
            if current and current["status"] == "FAILED":
                summary["failed"] += 1
            else:
                summary["errors"] += 1
            summary["case_results"].append(
                {
                    "case_id": case["case_id"],
                    "status": current["status"] if current else "ERROR",
                    "error_type": type(error).__name__,
                    "error": str(error),
                }
            )
    return summary


def create_and_investigate_case(
    order_id: str,
    *,
    operations_database=DEFAULT_OPERATIONS_DATABASE,
    client: Any | None = None,
    policy_config: AutomationPolicyConfig | None = None,
) -> dict[str, Any]:
    """Create a case, then process that newly created OPEN case."""

    case = create_case(order_id, database=operations_database)
    return process_open_case(
        case["case_id"],
        operations_database=operations_database,
        client=client,
        policy_config=policy_config,
    )


def approve_case(
    case_id: str,
    *,
    approver: str = "human",
    operations_database=DEFAULT_OPERATIONS_DATABASE,
    email_adapter: EmailAdapter | None = None,
    email_config: EmailActionConfig | None = None,
) -> dict[str, Any]:
    case = get_case(case_id, database=operations_database)
    if case is None:
        raise ValueError(f"Case not found: {case_id}")
    if case["status"] != "PENDING_HUMAN_APPROVAL":
        raise ValueError("Only cases pending human approval can be approved")
    set_approval(case_id, approver, database=operations_database)
    approved = transition_case(
        case_id,
        "PENDING_HUMAN_APPROVAL",
        "APPROVED",
        actor=approver,
        event_type="human_approval_granted",
        output_data={"recommended_action": case["recommended_action"]},
        database=operations_database,
    )
    if case["recommended_action"] == "contact_customer":
        return _execute_contact_customer(
            approved,
            actor=approver,
            email_adapter=email_adapter,
            email_config=email_config,
            operations_database=operations_database,
        )
    return _simulate_and_close_case(case_id, expected_status="APPROVED", actor=approver, operations_database=operations_database)


def reject_case(
    case_id: str,
    *,
    approver: str = "human",
    reason: str = "Rejected by human reviewer",
    operations_database=DEFAULT_OPERATIONS_DATABASE,
) -> dict[str, Any]:
    case = get_case(case_id, database=operations_database)
    if case is None or case["status"] != "PENDING_HUMAN_APPROVAL":
        raise ValueError("Only cases pending human approval can be rejected")
    set_approval(case_id, approver, database=operations_database)
    rejected = transition_case(
        case_id,
        "PENDING_HUMAN_APPROVAL",
        "REJECTED",
        actor=approver,
        event_type="human_approval_rejected",
        output_data={"reason": reason},
        database=operations_database,
    )
    record_audit(case_id, approver, "external_action_not_executed", output_data={"reason": reason}, database=operations_database)
    return transition_case(
        case_id,
        "REJECTED",
        "CLOSED",
        actor="system",
        event_type="case_closed",
        output_data={"action_executed": False},
        database=operations_database,
    )
