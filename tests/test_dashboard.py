"""The dashboard's embedded numbers must match the pipeline's indicator tables."""
import json
import re
from pathlib import Path

import duckdb
import pytest

ROOT = Path(__file__).resolve().parents[1]
HTML = ROOT / "docs/index.html"
pytestmark = pytest.mark.skipif(not HTML.exists(), reason="run dashboard/build_dashboard.py first")


@pytest.fixture(scope="module")
def data():
    m = re.search(r"const DATA = (\{.*?\});\n", HTML.read_text(encoding="utf-8"), re.S)
    return json.loads(m.group(1))


def test_fy_kpis_match_indicator_table(data):
    ind = duckdb.sql(f"SELECT * FROM '{(ROOT / 'data/gold/parquet/ind_summary_by_fy.parquet').as_posix()}'").df()
    for _, r in ind.iterrows():
        k = data["c"][f"{int(r.fiscal_year)}|ALL|ALL"]["k"]
        assert abs(k[0] - float(r.total_award_value_usd)) <= 1
        assert k[1] == int(r.contract_count)
        assert abs(k[2] - float(r.median_contract_value_usd)) <= 1
        for i, col in [(3, "open_competitive_value_share"), (4, "direct_selection_value_share"),
                       (5, "domestic_supplier_value_share"), (6, "prior_review_value_share")]:
            assert abs(k[i] - float(getattr(r, col))) < 1e-4


def test_all_years_total_matches_findings(data):
    n = json.loads((ROOT / "docs/findings_numbers.json").read_text())
    k = data["c"]["ALL|ALL|ALL"]["k"]
    assert abs(k[0] - n["total_usd_complete"]) <= 1 and k[1] == int(n["contracts_complete"])


def test_parts_add_up(data):
    for key, c in data["c"].items():
        total = c["k"][0]
        assert abs(sum(t[0] for t in c["tier"]) - total) <= 10, key
        assert abs(sum(c["origin"]) - total) <= 10, key
        assert sum(t[1] for t in c["tier"]) == c["k"][1], key
