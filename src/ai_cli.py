"""Interactive CLI for the Gemini-powered Olist Operator."""

from __future__ import annotations

import argparse

from operator_cli import answer as local_answer
from queries import export_delivery_report
from ai_operator import ask


def is_fast_question(question: str) -> bool:
    normalized = question.lower()
    return any(
        phrase in normalized
        for phrase in (
            "riepilogo delle vendite",
            "riepilogo vendite",
            "ordini in ritardo",
            "ordini sono in ritardo",
            "ultimi ordini",
        )
    )


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--question", help="esegue una domanda e termina")
    parser.add_argument("--model", default="gemini-3.8-flash")
    parser.add_argument(
        "--export-delivery-report",
        action="store_true",
        help="esporta i 100 ordini più in ritardo in reports/delivery_delays.csv",
    )
    args = parser.parse_args()

    try:
        if args.export_delivery_report:
            print(f"Report creato: {export_delivery_report()}")
            return
        if args.question:
            if is_fast_question(args.question):
                print(local_answer(args.question))
            else:
                print(ask(args.question, model=args.model))
            return

        print("AI Operations Operator — digita 'esci' per terminare.")
        while True:
            question = input("\n> ").strip()
            if question.lower() in {"esci", "exit", "quit"}:
                break
            if question:
                if is_fast_question(question):
                    print(local_answer(question))
                else:
                    print(ask(question, model=args.model))
    except Exception as error:
        print("Impossibile contattare Gemini.")
        print(f"Dettaglio: {error}")
        print("Verifica che GEMINI_API_KEY sia configurata nell'ambiente.")


if __name__ == "__main__":
    main()
