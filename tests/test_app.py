"""Smoke test of the Streamlit UI (offline planner)."""
import os
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
pytest.importorskip("streamlit")
needs_db = pytest.mark.skipif(not (ROOT / "chatbot/warehouse.duckdb").exists(), reason="build warehouse first")


@needs_db
def test_app_answers_example(monkeypatch):
    from streamlit.testing.v1 import AppTest
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.chdir(ROOT / "chatbot")
    monkeypatch.syspath_prepend(str(ROOT / "chatbot"))
    at = AppTest.from_file(str(ROOT / "chatbot/app.py"), default_timeout=60)
    at.run()
    at.text_input(key="q").input("What share of FY2025 awards in Africa used open international competition?").run()
    assert not at.exception
    assert any("73.8%" in s.value for s in at.success)
    assert any("SELECT" in c.value for c in at.code)
    assert len(at.dataframe) >= 1
