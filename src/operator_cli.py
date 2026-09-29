"""Small command-line interface for the first Olist Operator tools."""

from __future__ import annotations

import argparse
import re
from typing import Any

from queries import delivery_report, delayed_orders, get_order, sales_summary, search_orders


ORDER_ID_RE = re.compile(r"\b[a-f0-9]{32}\b", re.IGNORECASE)


def answer(question: str) -> str:
    """Map a small set of natural-language requests to safe tools."""

    normalized = question.lower().strip()
    order_match = ORDER_ID_RE.search(normalized)
    if order_match:
        result = get_order(order_match.group(0))
        if result is None:
            return "Non ho trovato questo ordine."
        order = result["order"]
        return (
            f"Ordine {order['order_id']}\n"
            f"Stato: {order['order_status']}\n"
            f"Acquistato: {order['order_purchase_timestamp']}\n"
            f"Consegna: {order['order_delivered_customer_date'] or 'non disponibile'}\n"
            f"Articoli: {len(result['items'])}\n"
            f"Pagamenti: {len(result['payments'])}"
        )

    if any(word in normalized for word in ("ritardo", "ritardi", "in ritardo", "delayed")):
        report = delivery_report()
        lines = [
            "Report consegne:",
            f"- Ordini consegnati: {report['delivered_orders']:,}",
            f"- Ordini in ritardo: {report['late_orders']:,} ({report['late_rate_percent']}%)",
            f"- Ritardo medio tra gli ordini in ritardo: {report['average_days_late']} giorni",
            f"- Ritardo massimo: {report['maximum_days_late']} giorni",
            "",
            "Ordini più critici (primi 20):",
        ]
        lines.extend(f"- {row['order_id']}: {row['days_late']} giorni" for row in report["top_delayed_orders"])
        return "\n".join(lines)

    if any(word in normalized for word in ("vendite", "fatturato", "ricavi", "sales", "revenue")):
        summary = sales_summary()
        return (
            f"Ordini: {summary['total_orders']:,}\n"
            f"Clienti unici: {summary['unique_customers']:,}\n"
            f"Pagamenti: R${summary['payment_total']:,.2f}\n"
            f"Pagamento medio: R${summary['average_payment']:,.2f}\n"
            f"Periodo: {summary['first_order']} → {summary['last_order']}"
        )

    if "ordini" in normalized or "orders" in normalized:
        rows = search_orders(limit=10)
        lines = ["Ultimi 10 ordini:"]
        lines.extend(f"- {row['order_id']}: {row['order_status']}" for row in rows)
        return "\n".join(lines)

    return (
        "Posso aiutarti con: vendite, ultimi ordini, ordini in ritardo, "
        "oppure con un ordine specifico usando il suo ID."
    )


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--question", help="esegue una domanda e termina")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    if args.question:
        print(answer(args.question))
        return

    print("AI Operations Operator — digita 'esci' per terminare.")
    while True:
        try:
            question = input("\n> ").strip()
        except (EOFError, KeyboardInterrupt):
            print()
            break
        if question.lower() in {"esci", "exit", "quit"}:
            break
        if question:
            print(answer(question))


if __name__ == "__main__":
    main()
