"""Tests for the chatbot guardrails and the offline planner. Run: pytest -q (after building chatbot/warehouse.duckdb)."""
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "chatbot"))
from guardrails import UnsafeQueryError, validate_sql  # noqa: E402

BLOCKED = [
    "DROP TABLE fact_contract_awards",
    "DELETE FROM fact_contract_awards",
    "UPDATE fact_contract_awards SET amount_usd = 0",
    "INSERT INTO dim_project VALUES ('x')",
    "CREATE TABLE t AS SELECT * FROM vw_awards",
    "SELECT * FROM vw_awards; DROP TABLE dim_project",
    "SELECT * FROM read_csv('/etc/passwd')",
    "SELECT * FROM read_parquet('data/gold/parquet/*.parquet')",
    "COPY fact_contract_awards TO 'out.csv'",
    "ATTACH 'other.db' AS o",
    "PRAGMA database_list",
    "SET enable_external_access = true",
    "SELECT * FROM information_schema.tables",
    "SELECT * FROM secret_table",
    "SELECT getenv('HOME')",
    "INSTALL httpfs",
    "",
]


@pytest.mark.parametrize("sql", BLOCKED)
def test_blocks_unsafe(sql):
    with pytest.raises(UnsafeQueryError):
        validate_sql(sql)


def test_allows_select_and_enforces_limit():
    v = validate_sql("SELECT fiscal_year, SUM(amount_usd) FROM vw_awards GROUP BY 1", max_rows=50)
    assert "LIMIT 50" in v.sql and v.tables == {"vw_awards"}


def test_tightens_large_limit():
    assert "LIMIT 1000" in validate_sql("SELECT * FROM vw_awards LIMIT 999999").sql


def test_cte_and_union_allowed():
    validate_sql("WITH c AS (SELECT wb_contract_number, SUM(amount_usd) v FROM vw_awards GROUP BY 1) SELECT AVG(v) FROM c")
    validate_sql("SELECT 1 AS x FROM dim_project UNION ALL SELECT 2 FROM dim_project")


DB = Path(__file__).resolve().parents[1] / "chatbot" / "warehouse.duckdb"
needs_db = pytest.mark.skipif(not DB.exists(), reason="build chatbot/warehouse.duckdb first")


@pytest.fixture(scope="module")
def qa():
    from engine import DuckDBBackend, ProcurementQA
    q = ProcurementQA(backend=DuckDBBackend(DB))
    q.planner = q.rules
    return q


@needs_db
def test_readonly_connection_rejects_writes(qa):
    with pytest.raises(Exception):
        qa.backend.con.execute("CREATE TABLE x (a INT)")


@needs_db
def test_external_file_access_disabled(qa):
    with pytest.raises(Exception):
        qa.backend.con.execute("SELECT * FROM read_csv('data/contract_awards_raw.csv')")


@needs_db
@pytest.mark.parametrize("question,intent", [
    ("What share of FY2025 awards in Africa used open international competition?", "share"),
    ("Direct selection share by fiscal year", "share"),
    ("Domestic supplier share in South Asia in FY2026", "share"),
    ("Top 10 suppliers in Works since FY2024", "top"),
    ("Median contract value by fiscal year for Goods", "average"),
    ("Total award value by region in FY2025", "total"),
    ("How many contracts did Kenya sign in FY2024?", "total"),
    ("Top 5 foreign supplier countries", "top"),
    ("What share of awards in Kenya went to firms from China?", None),
])
def test_offline_questions_run(qa, question, intent):
    ans = qa.ask(question)
    if intent is None:
        assert ans.blocked or ans.result is not None
        return
    assert ans.error is None and ans.blocked is None, (ans.error, ans.blocked)
    assert ans.result is not None and not ans.result.empty
    assert ans.sql and ans.answer


@needs_db
def test_unanswerable_question_is_refused(qa):
    ans = qa.ask("What was the average number of bidders per contract in FY2024?")
    assert ans.blocked and ans.result is None


@needs_db
def test_example_answer_matches_independent_query(qa):
    ans = qa.ask("What share of FY2025 awards in Africa used open international competition?")
    _, check = qa.run_safe("SELECT SUM(CASE WHEN m.is_open_competitive THEN f.amount_usd ELSE 0 END)/SUM(f.amount_usd) AS s "
                           "FROM fact_contract_awards f JOIN dim_procurement_method m ON f.method_key = m.method_key "
                           "JOIN dim_borrower_country c ON f.borrower_country_key = c.borrower_country_key "
                           "WHERE f.fiscal_year = 2025 AND c.region_code IN ('AFE','AFW')")
    assert abs(float(ans.result.value_share[0]) - float(check.s[0])) < 1e-4


class _FakeMsg:
    def __init__(self, text):
        self.content = [type("B", (), {"type": "text", "text": text})()]


class _FakeClient:
    """Stands in for anthropic.Anthropic: first call plans SQL, second call writes the answer."""
    def __init__(self, plan_json, answer="ok"):
        self.replies = [plan_json, answer]
        self.messages = self

    def create(self, **kw):
        return _FakeMsg(self.replies.pop(0))


@needs_db
def test_llm_path_with_guardrail_block(qa):
    import json
    from llm import ClaudePlanner
    p = ClaudePlanner.__new__(ClaudePlanner)
    p.model, p.dialect = "test", "duckdb"
    p.client = _FakeClient(json.dumps({"sql": "DROP TABLE dim_project", "assumptions": [], "cannot_answer": False}))
    qa.planner = p
    try:
        ans = qa.ask("delete everything")
    finally:
        qa.planner = qa.rules
    assert ans.blocked and "guardrails" in ans.blocked and ans.result is None


@needs_db
def test_llm_path_runs_valid_sql(qa):
    import json
    from llm import ClaudePlanner
    p = ClaudePlanner.__new__(ClaudePlanner)
    p.model, p.dialect = "test", "duckdb"
    p.client = _FakeClient(json.dumps({
        "sql": "SELECT region_code, SUM(amount_usd) v FROM vw_awards WHERE fiscal_year = 2025 GROUP BY 1",
        "detail_sql": "SELECT wb_contract_number, amount_usd FROM vw_awards WHERE fiscal_year = 2025 ORDER BY amount_usd DESC LIMIT 5",
        "assumptions": ["test"], "cannot_answer": False}), answer="Regional totals shown.")
    qa.planner = p
    try:
        ans = qa.ask("value by region FY2025")
    finally:
        qa.planner = qa.rules
    assert ans.error is None and ans.blocked is None
    assert len(ans.result) == 8 and len(ans.detail) == 5 and ans.answer == "Regional totals shown."
