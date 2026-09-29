"""Gemini-powered operator using only the approved Olist query tools."""

from __future__ import annotations

import json
from typing import Any

from google import genai

from queries import delivery_report, delayed_orders, get_order, search_orders, sales_summary


DEFAULT_MODEL = "gemini-3.8-flash"

SYSTEM_INSTRUCTIONS = """
Sei l'AI Operations Operator per il dataset e-commerce Olist.
Rispondi in italiano, in modo chiaro e operativo.
Usa sempre gli strumenti disponibili per domande sui dati: non inventare numeri.
Non scrivere SQL e non fingere di avere accesso a dati diversi da quelli restituiti dagli strumenti.
Se una domanda non è supportata dagli strumenti, dillo chiaramente e indica cosa puoi verificare.
Quando riporti metriche, specifica brevemente cosa misurano.
""".strip()


def _empty_parameters() -> dict[str, Any]:
    return {
        "type": "object",
        "properties": {},
        "required": [],
        "additionalProperties": False,
    }


TOOLS = [
    {
        "type": "function",
        "name": "get_order",
        "description": "Recupera un ordine con cliente, articoli, pagamenti e recensioni.",
        "parameters": {
            "type": "object",
            "properties": {"order_id": {"type": "string", "description": "ID completo dell'ordine"}},
            "required": ["order_id"],
            "additionalProperties": False,
        },
    },
    {
        "type": "function",
        "name": "get_sales_summary",
        "description": "Calcola il riepilogo generale di ordini, clienti e pagamenti.",
        "parameters": _empty_parameters(),
    },
    {
        "type": "function",
        "name": "get_delayed_orders",
        "description": "Trova gli ordini consegnati dopo la data stimata, fino a 20 risultati.",
        "parameters": _empty_parameters(),
    },
    {
        "type": "function",
        "name": "get_delivery_report",
        "description": "Calcola KPI operativi sulle consegne in ritardo e restituisce i casi più critici.",
        "parameters": _empty_parameters(),
    },
    {
        "type": "function",
        "name": "get_recent_orders",
        "description": "Restituisce gli ultimi 10 ordini acquistati.",
        "parameters": _empty_parameters(),
    },
]


def dispatch_tool(name: str, arguments: dict[str, Any]) -> Any:
    """Execute one allow-listed tool requested by the model."""

    if name == "get_order":
        order_id = arguments.get("order_id")
        if not isinstance(order_id, str) or not order_id:
            raise ValueError("order_id must be a non-empty string")
        result = get_order(order_id)
        return result or {"found": False, "order_id": order_id}
    if name == "get_sales_summary":
        return sales_summary()
    if name == "get_delayed_orders":
        return delayed_orders()
    if name == "get_delivery_report":
        return delivery_report()
    if name == "get_recent_orders":
        return search_orders(limit=10)
    raise ValueError(f"Tool non autorizzato: {name}")


def ask(question: str, model: str = DEFAULT_MODEL) -> str:
    """Ask Gemini a question and execute its tool calls locally."""

    client = genai.Client()

    for _ in range(5):
        interaction = client.interactions.create(
            model=model,
            input=f"{SYSTEM_INSTRUCTIONS}\n\nDomanda dell'utente: {question}",
            tools=TOOLS,
        )

        calls = [step for step in interaction.steps if step.type == "function_call"]
        if not calls:
            return interaction.output_text

        function_results = []
        for call in calls:
            try:
                arguments = call.arguments
                if isinstance(arguments, str):
                    arguments = json.loads(arguments)
                result = dispatch_tool(call.name, arguments)
                output = json.dumps(result, ensure_ascii=False, default=str)
            except (ValueError, TypeError, json.JSONDecodeError) as error:
                output = json.dumps({"error": str(error)}, ensure_ascii=False)
            function_results.append(
                {
                    "type": "function_result",
                    "name": call.name,
                    "call_id": call.id,
                    "result": [{"type": "text", "text": output}],
                }
            )
        final_interaction = client.interactions.create(
            model=model,
            previous_interaction_id=interaction.id,
            input=function_results,
            tools=TOOLS,
        )
        return final_interaction.output_text

    raise RuntimeError("Il modello ha superato il numero massimo di chiamate agli strumenti")
