"""
Question-answering engine: plan (question -> SQL) -> guardrails -> read-only execution -> answer + evidence.

Backends
* DuckDBBackend (default, tested): local file built by build_db.py, opened read_only with external access disabled.
* DatabricksBackend (optional): runs against the gold tables through a Databricks SQL warehouse using
  databricks-sql-connector. Use a token whose principal has only SELECT on the schema.
"""
import os
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path

import pandas as pd

from guardrails import UnsafeQueryError, validate_sql
from llm import ClaudePlanner, Plan, RuleBasedPlanner

DEFAULT_DB = Path(os.environ.get("WB_DB_PATH", Path(__file__).resolve().parent / "warehouse.duckdb"))


class DuckDBBackend:
    dialect = "duckdb"

    def __init__(self, db_path=DEFAULT_DB, timeout_s: int = 20):
        import duckdb
        if not Path(db_path).exists():
            raise FileNotFoundError(f"{db_path} not found. Run: python chatbot/build_db.py")
        # read_only: no writes possible; enable_external_access=false: no reading other files / URLs
        self.con = duckdb.connect(str(db_path), read_only=True, config={"enable_external_access": False})
        self.timeout_s = timeout_s

    def query(self, sql: str) -> pd.DataFrame:
        timer = threading.Timer(self.timeout_s, self.con.interrupt)
        timer.start()
        try:
            return self.con.execute(sql).df()
        finally:
            timer.cancel()

    def distinct(self, col: str, table: str) -> list[str]:
        return [r[0] for r in self.con.execute(f"SELECT DISTINCT {col} FROM {table} WHERE {col} IS NOT NULL").fetchall()]


class DatabricksBackend:
    dialect = "databricks"

    def __init__(self, catalog="workspace", schema="wb_procurement", timeout_s: int = 60):
        from databricks import sql as dbsql
        self.conn = dbsql.connect(server_hostname=os.environ["DATABRICKS_SERVER_HOSTNAME"],
                                  http_path=os.environ["DATABRICKS_HTTP_PATH"],
                                  access_token=os.environ["DATABRICKS_TOKEN"], catalog=catalog, schema=schema)
        self.timeout_s = timeout_s

    def query(self, sql: str) -> pd.DataFrame:
        with self.conn.cursor() as cur:
            cur.execute(sql)
            cols = [d[0] for d in cur.description]
            return pd.DataFrame(cur.fetchall(), columns=cols)

    def distinct(self, col: str, table: str) -> list[str]:
        return self.query(f"SELECT DISTINCT {col} FROM {table} WHERE {col} IS NOT NULL")[col].tolist()


@dataclass
class Answer:
    question: str
    answer: str = ""
    sql: str | None = None
    detail_sql: str | None = None
    result: pd.DataFrame | None = None
    detail: pd.DataFrame | None = None
    assumptions: list = field(default_factory=list)
    planner: str = ""
    blocked: str | None = None
    error: str | None = None
    elapsed_s: float = 0.0

    def to_markdown(self) -> str:
        out = [f"**Q:** {self.question}", ""]
        out.append(f"**A:** {self.answer or self.blocked or self.error}")
        if self.assumptions:
            out += ["", "**Assumptions**"] + [f"- {a}" for a in self.assumptions]
        if self.sql:
            out += ["", "**SQL used**", "```sql", self.sql, "```"]
        if self.result is not None:
            out += ["", "**Result**", self.result.head(50).to_markdown(index=False)]
        if self.detail is not None and not self.detail.empty:
            out += ["", f"**Underlying award lines** (top {min(len(self.detail), 10)} of {len(self.detail)} shown)",
                    self.detail.head(10).drop(columns=["contract_description"], errors="ignore").to_markdown(index=False)]
        out += ["", f"_planner: {self.planner} · {self.elapsed_s:.2f}s_"]
        return "\n".join(out)


class ProcurementQA:
    def __init__(self, backend=None, planner=None, max_rows: int = 1000):
        self.backend = backend or DuckDBBackend()
        if planner is None:
            planner = ClaudePlanner(dialect=self.backend.dialect) if os.environ.get("ANTHROPIC_API_KEY") else None
        self.rules = RuleBasedPlanner(self.backend.distinct("borrower_country", "dim_borrower_country"),
                                      self.backend.distinct("supplier_country", "dim_supplier_country"))
        self.planner = planner or self.rules
        self.max_rows = max_rows

    def run_safe(self, sql: str, max_rows: int | None = None) -> tuple[str, pd.DataFrame]:
        v = validate_sql(sql, dialect=self.backend.dialect, max_rows=max_rows or self.max_rows)
        return v.sql, self.backend.query(v.sql)

    def ask(self, question: str) -> Answer:
        t0 = time.time()
        ans = Answer(question=question, planner=self.planner.name)
        plan: Plan = self.planner.plan(question)
        error = None
        for attempt in range(2):  # one self-correction round for the LLM planner
            if plan.cannot_answer or not plan.sql:
                ans.blocked = plan.reason or "The question cannot be answered from this dataset."
                ans.elapsed_s = time.time() - t0
                return ans
            try:
                ans.sql, ans.result = self.run_safe(plan.sql)
                break
            except UnsafeQueryError as e:
                ans.blocked = f"Query blocked by guardrails: {e}"
                ans.sql = plan.sql
                ans.elapsed_s = time.time() - t0
                return ans
            except Exception as e:  # SQL error: let the LLM fix it once
                error = f"{type(e).__name__}: {e}"
                if attempt == 0 and isinstance(self.planner, ClaudePlanner):
                    plan = self.planner.plan(question, previous_error=f"SQL:\n{plan.sql}\nError: {error}")
                    continue
                ans.error, ans.sql = error, plan.sql
                ans.elapsed_s = time.time() - t0
                return ans
        ans.assumptions = plan.assumptions
        if plan.detail_sql:
            try:
                ans.detail_sql, ans.detail = self.run_safe(plan.detail_sql, max_rows=100)
            except Exception as e:
                ans.assumptions = ans.assumptions + [f"Underlying-records query skipped: {e}"]
        if isinstance(self.planner, ClaudePlanner):
            ans.answer = self.planner.summarize(question, ans.sql, ans.result.head(50).to_markdown(index=False),
                                                ans.assumptions)
        else:
            ans.answer = RuleBasedPlanner.summarize(question, ans.sql, ans.result, plan)
        ans.elapsed_s = time.time() - t0
        return ans
