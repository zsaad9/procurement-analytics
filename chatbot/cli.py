"""
Command-line chatbot.

    python chatbot/cli.py "What share of FY2025 awards in Africa used open international competition?"
    python chatbot/cli.py --offline            # interactive, rule-based planner (no API key)
    python chatbot/cli.py --sql "SELECT ..."   # run your own SQL through the same guardrails
"""
import argparse
import sys

from engine import DuckDBBackend, ProcurementQA, DatabricksBackend
from llm import RuleBasedPlanner


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("question", nargs="*")
    ap.add_argument("--offline", action="store_true", help="force the rule-based planner (no API calls)")
    ap.add_argument("--backend", choices=["duckdb", "databricks"], default="duckdb")
    ap.add_argument("--db", default=None, help="path to warehouse.duckdb")
    ap.add_argument("--sql", default=None, help="run a SQL query through the guardrails")
    a = ap.parse_args()

    backend = DatabricksBackend() if a.backend == "databricks" else (DuckDBBackend(a.db) if a.db else DuckDBBackend())
    qa = ProcurementQA(backend=backend)
    if a.offline:
        qa.planner = qa.rules

    if a.sql:
        try:
            sql, df = qa.run_safe(a.sql)
            print(sql, "\n")
            print(df.to_markdown(index=False))
        except Exception as e:
            print(f"BLOCKED/ERROR: {e}")
            sys.exit(1)
        return

    if a.question:
        print(qa.ask(" ".join(a.question)).to_markdown())
        return
    print(f"Procurement Q&A ({qa.planner.name} planner). Empty line to quit.")
    while True:
        q = input("\n? ").strip()
        if not q:
            break
        print(qa.ask(q).to_markdown())


if __name__ == "__main__":
    main()
