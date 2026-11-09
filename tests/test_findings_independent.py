"""
Independent check of the published numbers: recompute the key figures straight from the RAW CSV with pandas
(no Spark, no gold tables) and compare them with docs/findings_numbers.json produced by the pipeline.

Skipped if data/contract_awards_raw.csv is absent.
"""
import json
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

ROOT = Path(__file__).resolve().parents[1]
RAW = ROOT / "data/contract_awards_raw.csv"
pytestmark = pytest.mark.skipif(not RAW.exists(), reason="raw CSV not present")

OPEN = {"Request for Bids", "Request for Proposals", "E-Auctions", "Quality And Cost-Based Selection",
        "Quality Based Selection", "Fixed Budget Selection", "Least Cost Selection", "Consultant Qualification Selection"}
DIRECT = {"Direct Selection", "UN Agencies (Direct)"}
AFRICA_E = "Eastern and Southern Africa"


@pytest.fixture(scope="module")
def d():
    df = pd.read_csv(RAW, dtype=str, keep_default_na=False, encoding="utf-8-sig")
    df["amt"] = df["Supplier Contract Amount (USD)"].astype(float)
    df["fy"] = df["Fiscal Year"].astype(int)
    df["method"] = df["Procurement Method"].str.split().str.join(" ")
    # same probable-duplicate rule as Silver (keep lowest contract number)
    df["desc_n"] = df["Contract Description"].str.split().str.join(" ").str.lower()
    df["sid"] = df["Supplier ID"].replace("0", "<none>")
    df = df.sort_values("WB Contract Number", key=lambda s: s.astype(int))
    dup = df.duplicated(["Project ID", "sid", "Supplier Contract Amount (USD)", "Contract Signing Date", "desc_n"])
    df = df[~dup].copy()
    sc = df["Supplier Country / Economy"].replace({"null": ""})
    regional = df["Borrower Country / Economy Code"].str.match(r"^\d") | (
        (df["Borrower Country / Economy Code"] == "") & ~df["Borrower Country / Economy"].isin(
            ["Cote d'Ivoire", "Somalia, Federal Republic of"]))
    df["origin"] = np.select(
        [regional, sc == "", sc == "World", sc == df["Borrower Country / Economy"]],
        ["NA", "Unknown", "Intl", "Domestic"], "Foreign")
    df["sc"] = sc
    return df


@pytest.fixture(scope="module")
def N():
    return json.loads((ROOT / "docs/findings_numbers.json").read_text())


def close(a, b, tol=5e-4):
    return abs(float(a) - float(b)) <= tol * max(1.0, abs(float(b)))


def test_rows_after_dedup(d):
    assert len(d) == 295_989


def test_fy_totals_and_counts(d, N):
    for fy in range(2020, 2028):
        x = d[d.fy == fy]
        assert close(x.amt.sum(), N["by_fy"][str(fy)]["value"], 1e-9)
        assert x["WB Contract Number"].nunique() == N["by_fy"][str(fy)]["contracts"]


def test_medians(d, N):
    for fy in (2021, 2025, 2026):
        v = d[d.fy == fy].groupby("WB Contract Number").amt.sum()
        assert close(v.median(), N["by_fy"][str(fy)]["median"], 1e-6)


def test_method_shares(d, N):
    for fy in (2020, 2021, 2022, 2026):
        x = d[d.fy == fy]
        assert close(x[x.method.isin(DIRECT)].amt.sum() / x.amt.sum(), N["by_fy"][str(fy)]["direct"])
        assert close(x[x.method.isin(OPEN)].amt.sum() / x.amt.sum(), N["by_fy"][str(fy)]["open"])


def test_concentration_and_prior_review(d, N):
    x = d[d.fy <= 2026]
    v = x.groupby("WB Contract Number").amt.sum().sort_values(ascending=False)
    n1 = int(np.ceil(len(v) / 100))  # ntile(100): first bucket has ceil(n/100) rows
    assert close(v.iloc[:n1].sum() / v.sum(), N["f3_top1pct_share"], 1e-3)
    pr = x[x["Review type"] == "Prior"]
    assert close(pr.amt.sum() / x.amt.sum(), N["f3_prior_value_share"])
    assert close(pr["WB Contract Number"].nunique() / x["WB Contract Number"].nunique(), N["f3_prior_count_share"])


def test_china(d, N):
    x = d[(d.fy <= 2026)]
    foreign = x[x.origin == "Foreign"]
    assert close(foreign[foreign.sc == "China"].amt.sum() / foreign.amt.sum(), N["f4_china_share_foreign"])
    nc = x[x["Borrower Country / Economy"] != "China"]
    w = nc[nc["Procurement Category"] == "Works"]
    assert close(w[w.sc == "China"].amt.sum() / w.amt.sum(), N["f4_china_share_works"])


def test_domestic(d, N):
    x = d[(d.fy <= 2026) & d.origin.isin(["Domestic", "Foreign", "Intl"])]
    assert close(x[x.origin == "Domestic"].amt.sum() / x.amt.sum(), N["f5_domestic_all"])
    e = x[x.Region == AFRICA_E]
    assert close(e[e.origin == "Domestic"].amt.sum() / e.amt.sum(), N["f5_domestic_by_region"]["AFE"][1])
