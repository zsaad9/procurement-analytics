"""
Compute every number used in the management brief from the gold tables, save them to
docs/findings_numbers.json, and render docs/findings_brief.md from those numbers (no hand-typed figures).

    python analysis/build_findings.py --db chatbot/warehouse.duckdb
"""
import argparse
import json
from pathlib import Path

import duckdb

ROOT = Path(__file__).resolve().parents[1]
ap = argparse.ArgumentParser()
ap.add_argument("--db", default=ROOT / "chatbot/warehouse.duckdb")
args = ap.parse_args()
con = duckdb.connect(str(args.db), read_only=True)
one = lambda sql: con.execute(sql).fetchone()
rows = lambda sql: con.execute(sql).fetchall()

N = {}
COMPLETE = "is_complete_fy"           # complete fiscal years only (FY2020-FY2026) for multi-year shares
N["fy_first"], N["fy_last_complete"] = one("SELECT MIN(fiscal_year), MAX(fiscal_year) FROM dim_fiscal_year WHERE is_complete_fy")
N["fy_partial"], N["fy_partial_months"], N["fy_partial_last_date"] = one(
    "SELECT fiscal_year, months_covered, CAST(last_signing_date AS VARCHAR) FROM dim_fiscal_year WHERE NOT is_complete_fy")
N["total_usd_all"], N["contracts_all"], N["lines_all"] = map(float, one(
    "SELECT SUM(amount_usd), COUNT(DISTINCT wb_contract_number), COUNT(*) FROM vw_awards"))
N["total_usd_complete"], N["contracts_complete"] = map(float, one(
    f"SELECT SUM(amount_usd), COUNT(DISTINCT wb_contract_number) FROM vw_awards WHERE {COMPLETE}"))

fy = {r[0]: dict(value=float(r[1]), contracts=int(r[2]), median=float(r[3]), avg=float(r[4]), open=float(r[5]),
                 direct=float(r[6]), domestic=float(r[7]), intl=float(r[8]), prior=float(r[9]))
      for r in rows("""SELECT fiscal_year, total_award_value_usd, contract_count, median_contract_value_usd,
                              avg_contract_value_usd, open_competitive_value_share, direct_selection_value_share,
                              domestic_supplier_value_share, intl_org_value_share, prior_review_value_share
                       FROM ind_summary_by_fy ORDER BY fiscal_year""")}
N["by_fy"] = {str(k): v for k, v in fy.items()}

# ---- F1 fewer, larger contracts
N["f1_peak_fy"] = max((k for k in fy if k <= N["fy_last_complete"]), key=lambda k: fy[k]["value"])
N["f1_median_min_fy"] = min((k for k in fy if k <= N["fy_last_complete"]), key=lambda k: fy[k]["median"])
lc = N["fy_last_complete"]
N["f1_count_change_last"] = fy[lc]["contracts"] / fy[lc - 1]["contracts"] - 1
N["f1_value_change_last"] = fy[lc]["value"] / fy[lc - 1]["value"] - 1
N["f1_median_change"] = fy[lc]["median"] / fy[N["f1_median_min_fy"]]["median"] - 1
N["f1_median_change_to_prev"] = fy[lc - 1]["median"] / fy[N["f1_median_min_fy"]]["median"] - 1
tier = {(r[0], r[1]): int(r[2]) for r in rows(
    "SELECT fiscal_year, competition_tier, COUNT(DISTINCT wb_contract_number) FROM vw_awards GROUP BY 1, 2")}
N["f1_rfq_prev"], N["f1_rfq_last"] = tier[(lc - 1, "Limited competitive")], tier[(lc, "Limited competitive")]
N["f1_rfq_change"] = N["f1_rfq_last"] / N["f1_rfq_prev"] - 1
N["f1_rfq_share_of_drop"] = (N["f1_rfq_prev"] - N["f1_rfq_last"]) / (fy[lc - 1]["contracts"] - fy[lc]["contracts"])
N["f1_projects_prev"], N["f1_projects_last"] = (int(one(f"SELECT COUNT(DISTINCT project_id) FROM vw_awards WHERE fiscal_year={y}")[0]) for y in (lc - 1, lc))
h2 = one(f"""SELECT COUNT(DISTINCT CASE WHEN fiscal_year={lc-1} AND month(contract_signing_date) BETWEEN 1 AND 6 THEN wb_contract_number END),
                    COUNT(DISTINCT CASE WHEN fiscal_year={lc} AND month(contract_signing_date) BETWEEN 1 AND 6 THEN wb_contract_number END),
                    COUNT(DISTINCT CASE WHEN fiscal_year={lc-1} AND month(contract_signing_date) >= 7 THEN wb_contract_number END),
                    COUNT(DISTINCT CASE WHEN fiscal_year={lc} AND month(contract_signing_date) >= 7 THEN wb_contract_number END)
             FROM vw_awards""")
N["f1_h1_change"] = h2[3] / h2[2] - 1      # Jul-Dec
N["f1_h2_change"] = h2[1] / h2[0] - 1      # Jan-Jun

# ---- F2 COVID direct-selection spike
covid = {r[0]: (float(r[1]), float(r[2] or 0)) for r in rows("""
    SELECT fiscal_year, SUM(amount_usd),
           SUM(CASE WHEN regexp_matches(lower(coalesce(contract_description,'') || ' ' || project_name),
                                        'covid|vaccin|coronavirus|sars-cov') THEN amount_usd END)
    FROM vw_awards WHERE is_direct GROUP BY 1""")}
N["f2_covid_direct"] = {str(k): {"direct_usd": v[0], "covid_usd": v[1], "covid_share_of_direct": v[1] / v[0]}
                        for k, v in covid.items()}
N["f2_peak_direct_fy"] = max((k for k in fy if k <= lc), key=lambda k: fy[k]["direct"])
N["f2_covid_direct_fy21_22"] = covid[2021][1] + covid[2022][1]
N["f2_direct_fy21_22"] = covid[2021][0] + covid[2022][0]
N["f2_open_max_fy"] = max((k for k in fy if k <= lc), key=lambda k: fy[k]["open"])
N["f2_intl_peak_fy"] = max((k for k in fy if k <= lc), key=lambda k: fy[k]["intl"])

# ---- F3 concentration in few contracts; prior review
r = one(f"""WITH c AS (SELECT wb_contract_number, SUM(amount_usd) v FROM vw_awards WHERE {COMPLETE} GROUP BY 1),
                 r AS (SELECT v, ntile(100) OVER (ORDER BY v DESC) p FROM c)
            SELECT SUM(CASE WHEN p = 1 THEN v END) / SUM(v), SUM(CASE WHEN p > 50 THEN v END) / SUM(v),
                   COUNT(*) FILTER (WHERE p = 1), MIN(v) FILTER (WHERE p = 1) FROM r""")
N["f3_top1pct_share"], N["f3_bottom50_share"], N["f3_top1pct_n"], N["f3_top1pct_threshold"] = float(r[0]), float(r[1]), int(r[2]), float(r[3])
r = one(f"""SELECT COUNT(DISTINCT CASE WHEN review_type='Prior' THEN wb_contract_number END) * 1.0 / COUNT(DISTINCT wb_contract_number),
                   SUM(CASE WHEN review_type='Prior' THEN amount_usd END) / SUM(amount_usd)
            FROM vw_awards WHERE {COMPLETE}""")
N["f3_prior_count_share"], N["f3_prior_value_share"] = float(r[0]), float(r[1])
r = one(f"""SELECT COUNT(DISTINCT CASE WHEN method_key IN ('RFQ','ICS') THEN wb_contract_number END) * 1.0 / COUNT(DISTINCT wb_contract_number),
                   SUM(CASE WHEN method_key IN ('RFQ','ICS') THEN amount_usd END) / SUM(amount_usd)
            FROM vw_awards WHERE {COMPLETE}""")
N["f3_rfq_ics_count_share"], N["f3_rfq_ics_value_share"] = float(r[0]), float(r[1])
N["f3_prior_value_share_range"] = [min(fy[k]["prior"] for k in fy if k <= lc), max(fy[k]["prior"] for k in fy if k <= lc)]

# ---- F4 China (awards to China-registered firms OUTSIDE China; projects in China itself are excluded)
NC = "borrower_country <> 'China'"
r = one(f"""SELECT SUM(CASE WHEN supplier_country='China' THEN amount_usd END),
                   SUM(CASE WHEN supplier_country='China' THEN amount_usd END) / SUM(amount_usd),
                   SUM(CASE WHEN supplier_country='China' AND procurement_category='Works' THEN amount_usd END)
                     / SUM(CASE WHEN procurement_category='Works' THEN amount_usd END),
                   COUNT(DISTINCT CASE WHEN supplier_country='China' THEN wb_contract_number END),
                   COUNT(DISTINCT CASE WHEN supplier_country='China' THEN borrower_country END),
                   SUM(CASE WHEN supplier_country='China' AND procurement_category='Works' THEN amount_usd END)
                     / SUM(CASE WHEN supplier_country='China' THEN amount_usd END)
            FROM vw_awards WHERE {COMPLETE} AND {NC}""")
(N["f4_china_usd"], N["f4_china_share_all"], N["f4_china_share_works"], N["f4_china_contracts"],
 N["f4_china_borrowers"], N["f4_china_works_share_of_own"]) = [float(x) for x in r]
N["f4_china_share_foreign"] = float(one(f"""
    SELECT SUM(CASE WHEN supplier_country='China' THEN amount_usd END) / SUM(amount_usd)
    FROM vw_awards WHERE {COMPLETE} AND supplier_origin='Foreign'""")[0])
top_foreign = rows(f"""SELECT supplier_country, SUM(amount_usd) v FROM vw_awards WHERE {COMPLETE} AND supplier_origin='Foreign'
                       GROUP BY 1 ORDER BY v DESC LIMIT 6""")
N["f4_top_foreign"] = [(c, float(v)) for c, v in top_foreign]
N["f4_china_foreign_usd"] = N["f4_top_foreign"][0][1] if N["f4_top_foreign"][0][0] == "China" else None
N["f4_next5_combined"] = sum(v for _, v in N["f4_top_foreign"][1:6])
N["f4_china_by_region"] = {r[0]: float(r[1]) for r in rows(f"""
    SELECT region_code, SUM(CASE WHEN supplier_country='China' THEN amount_usd END) / SUM(amount_usd)
    FROM vw_awards WHERE {COMPLETE} AND {NC} AND region_code <> 'OTH' GROUP BY 1""")}
N["f4_unknown_chinese_named_usd"] = float(one(f"""
    SELECT COALESCE(SUM(amount_usd), 0) FROM vw_awards WHERE {COMPLETE} AND {NC} AND supplier_origin='Unknown supplier country'
      AND regexp_matches(lower(supplier_name), 'china|sinohydro|chinese|sino')""")[0])
N["f4_china_share_by_fy"] = {str(r[0]): float(r[1]) for r in rows(f"""
    SELECT fiscal_year, SUM(CASE WHEN supplier_country='China' THEN amount_usd END) / SUM(amount_usd)
    FROM vw_awards WHERE {NC} GROUP BY 1 ORDER BY 1""")}
N["f4_china_domestic_usd"] = float(one(f"SELECT COALESCE(SUM(amount_usd),0) FROM vw_awards WHERE {COMPLETE} AND borrower_country='China' AND supplier_country='China'")[0])

# ---- F5 domestic share by region
DOM = "SUM(CASE WHEN supplier_origin='Domestic' THEN amount_usd END) / SUM(CASE WHEN supplier_origin IN ('Domestic','Foreign','International organization') THEN amount_usd END)"
N["f5_domestic_all"] = float(one(f"SELECT {DOM} FROM vw_awards WHERE {COMPLETE}")[0])
N["f5_domestic_by_region"] = {r[0]: (r[1], float(r[2])) for r in rows(
    f"SELECT region_code, region_name, {DOM} FROM vw_awards WHERE {COMPLETE} AND region_code <> 'OTH' GROUP BY 1, 2 ORDER BY 3")}
N["f5_domestic_by_region_cat"] = {f"{r[0]}|{r[1]}": float(r[2]) for r in rows(
    f"SELECT region_code, procurement_category, {DOM} FROM vw_awards WHERE {COMPLETE} AND region_code <> 'OTH' GROUP BY 1, 2")}
N["f5_dom_range"] = [min(fy[k]["domestic"] for k in fy if k <= lc), max(fy[k]["domestic"] for k in fy if k <= lc)]
N["f5_region_value_share"] = {r[0]: float(r[1]) for r in rows(
    f"SELECT region_code, SUM(amount_usd) / (SELECT SUM(amount_usd) FROM vw_awards WHERE {COMPLETE}) FROM vw_awards WHERE {COMPLETE} GROUP BY 1")}

# ---- data caveats
dq_path = ROOT / "data/gold/parquet/dq_results.parquet"
if dq_path.exists():
    d = duckdb.sql(f"SELECT check_name, records_flagged FROM '{dq_path.as_posix()}'").fetchall()
    N["dq"] = {k: int(v) for k, v in d}
    N["dq_probable_dup_rows"] = N["dq"].get("probable_duplicate_entry")
vals = [fy[k]["value"] for k in fy if k <= lc]
N["f1_value_min"], N["f1_value_max"] = min(vals), max(vals)
N["f1_value_min_fy"] = min((k for k in fy if k <= lc), key=lambda k: fy[k]["value"])

assert N["f4_top_foreign"][0][0] == "China" and N["f4_china_foreign_usd"] > N["f4_next5_combined"], "F4 claim no longer holds"
assert N["f1_count_change_last"] < 0 and N["f1_median_change"] > 0, "F1 claim no longer holds"
assert N["f2_open_max_fy"] == lc, "F2 claim (open share at period high) no longer holds"
(ROOT / "docs/findings_numbers.json").write_text(json.dumps(N, indent=2, default=str))

# ------------------------------------------------------------------------------------------- render brief
bn = lambda v: f"USD {v/1e9:,.1f} bn"
pct = lambda v: f"{v*100:.1f}%"
pp = lambda v: f"{v*100:.0f}%"
dom = N["f5_domestic_by_region"]
dom_sorted = sorted(dom.items(), key=lambda kv: kv[1][1])
low, high = dom_sorted[0], dom_sorted[-1]
cbr = N["f4_china_by_region"]
top_china_regions = sorted(cbr.items(), key=lambda kv: kv[1], reverse=True)[:2]
REGION_NAMES = {k: v[0] for k, v in dom.items()}
second = N["f4_top_foreign"][1]
f1y0 = N["f1_median_min_fy"]

brief = f"""# Contract awards in World Bank Investment Project Financing: five trends, FY{N['fy_first']}–FY{lc}

*Briefing for senior management · source: World Bank Finances One, dataset DS00005 (from STEP), as of 9 Nov 2026 ·
all figures computed by `analysis/build_findings.py` from the gold tables. Complete fiscal years FY{N['fy_first']}–FY{lc}
unless stated: {bn(N['total_usd_complete'])} across {N['contracts_complete']:,.0f} contracts. FY{N['fy_partial']} (data to
{N['fy_partial_last_date']}) is excluded from multi-year comparisons.*

**1. Contracts are getting fewer and larger.**
Annual award value ranged from {bn(N['f1_value_min'])} (FY{N['f1_value_min_fy']}) to a peak of {bn(N['f1_value_max'])} (FY{N['f1_peak_fy']}). FY{lc} recorded {bn(fy[lc]['value'])}
(down {pct(-N['f1_value_change_last'])} on FY{lc-1}) while the number of contracts fell {pct(-N['f1_count_change_last'])}
to {fy[lc]['contracts']:,}. The median contract rose from USD {fy[f1y0]['median']:,.0f} in FY{f1y0} to
USD {fy[lc]['median']:,.0f} in FY{lc} (+{pp(N['f1_median_change'])}); it had already risen {pp(N['f1_median_change_to_prev'])}
by FY{lc-1}, so this is a multi-year shift, not a one-year blip. Small Request-for-Quotation contracts account for
{pp(N['f1_rfq_share_of_drop'])} of the FY{lc} drop in count ({N['f1_rfq_prev']:,} → {N['f1_rfq_last']:,}). *Check:* the
FY{lc} fall is {'steeper' if N['f1_h2_change'] < N['f1_h1_change'] else 'no steeper'} in January–June ({pct(N['f1_h2_change'])}) than in July–December ({pct(N['f1_h1_change'])}).
{'That pattern could reflect contracts not yet entered in STEP as well as a real decline, so' if N['f1_h2_change'] < N['f1_h1_change'] else 'So'} the count should be re-checked after the next data refresh.

**2. The COVID-era surge in direct selection has unwound; open competition is at a period high.**
Direct selection took {pct(fy[2021]['direct'])} of award value in FY2021 and {pct(fy[2022]['direct'])} in FY2022, versus
{pct(fy[2020]['direct'])} in FY2020. Contracts whose description or project name mentions COVID-19 or vaccines account for {bn(N['f2_covid_direct_fy21_22'])}
of the {bn(N['f2_direct_fy21_22'])} directly awarded in those two years. By FY{lc} direct selection was down to
{pct(fy[lc]['direct'])} and the open-competitive share reached {pct(fy[lc]['open'])}, the highest of any complete year
(low: {pct(min(fy[k]['open'] for k in fy if k <= lc))} in FY2021). Awards to UN agencies and other international
organisations peaked at {pct(fy[N['f2_intl_peak_fy']]['intl'])} of value in FY{N['f2_intl_peak_fy']}.

**3. Value is extremely concentrated, and prior review already follows the money.**
The largest 1% of contracts ({N['f3_top1pct_n']:,} contracts, each USD {N['f3_top1pct_threshold']/1e6:,.1f} m or more) carry
{pct(N['f3_top1pct_share'])} of award value; the smaller half of all contracts carries {pct(N['f3_bottom50_share'])}.
Prior review covers {pct(N['f3_prior_count_share'])} of contracts but {pct(N['f3_prior_value_share'])} of value. Request for
Quotations and Individual Consultant Selection make up {pct(N['f3_rfq_ics_count_share'])} of contracts but only
{pct(N['f3_rfq_ics_value_share'])} of value. Implication: value-based oversight is well targeted; analytics on
the high-volume, low-value tail (e.g. split purchases, repeat awards) needs different tools, such as pattern
detection rather than case-by-case review.

**4. Firms registered in China are the largest foreign supplier group, mostly in civil works.**
Outside China's own projects, Chinese-registered firms won {bn(N['f4_china_usd'])}: {pct(N['f4_china_share_all'])} of
award value and {pct(N['f4_china_share_works'])} of Works value in those countries, through
{N['f4_china_contracts']:,.0f} contracts in {N['f4_china_borrowers']:.0f} borrower countries or regional programmes;
{pct(N['f4_china_works_share_of_own'])} of their value is Works. Among firms competing outside their home country,
they won {pct(N['f4_china_share_foreign'])} of value, more than the next five supplier countries combined
({bn(N['f4_next5_combined'])}; second is {second[0]} with {bn(second[1])}). Their share of regional award value (excluding China) is highest in
{REGION_NAMES.get(top_china_regions[0][0], top_china_regions[0][0])} ({pct(top_china_regions[0][1])}) and
{REGION_NAMES.get(top_china_regions[1][0], top_china_regions[1][0])} ({pct(top_china_regions[1][1])}). This is a lower
bound: a further {bn(N['f4_unknown_chinese_named_usd'])} went to suppliers with Chinese names but no recorded country.

**5. Domestic firms win {pct(N['f5_domestic_all'])} of value overall, but this ranges from {pct(low[1][1])} to {pct(high[1][1])} by region.**
The domestic share (value to firms registered in the borrower country, as a share of value to all identified suppliers)
ranged between {pct(N['f5_dom_range'][0])} and {pct(N['f5_dom_range'][1])} across fiscal years. It is lowest in
{low[1][0]} ({pct(low[1][1])}), the largest region by award value ({pct(N['f5_region_value_share'][low[0]])} of the total),
and highest in {high[1][0]} ({pct(high[1][1])}). In {low[1][0]}, domestic firms win
{pct(N['f5_domestic_by_region_cat'][low[0] + '|Works'])} of Works value. Where local contracting capacity
is the policy aim, this is the gap to target.

**Caveats.** Excludes subcontracts and cofinancing. Joint-venture values are split equally among members by the publisher.
There is no field for international vs. national competition, number of bids or estimated cost, so competition
intensity and price efficiency cannot be measured. {N['dq_probable_dup_rows']:,} probable duplicate entries were removed and
{N['dq']['outlier:amount_iqr_by_category']:,} extreme-value records were flagged but kept (see `docs/data_profile.md`, `dq_results`). Supplier country is the
country of registration, not where the work is done.
"""
(ROOT / "docs/findings_brief.md").write_text(brief)
print(brief)

summary = f"""- **Fewer, larger contracts.** Median contract value rose from USD {fy[f1y0]['median']:,.0f} (FY{f1y0}) to USD {fy[lc]['median']:,.0f} (FY{lc}); FY{lc} contract count fell {pct(-N['f1_count_change_last'])} while value fell {pct(-N['f1_value_change_last'])}.
- **The COVID-era spike in direct selection has unwound.** {pct(fy[2021]['direct'])} of value in FY2021 → {pct(fy[lc]['direct'])} in FY{lc}; open-competitive share {pct(fy[lc]['open'])} in FY{lc}, the highest complete year.
- **Value is concentrated.** The largest 1% of contracts carry {pct(N['f3_top1pct_share'])} of value; prior review covers {pct(N['f3_prior_count_share'])} of contracts but {pct(N['f3_prior_value_share'])} of value.
- **Chinese firms lead foreign suppliers.** {pct(N['f4_china_share_foreign'])} of value won by foreign firms; {pct(N['f4_china_share_works'])} of Works value outside China.
- **Domestic share {pct(N['f5_domestic_all'])}**, from {pct(low[1][1])} ({low[1][0]}) to {pct(high[1][1])} ({high[1][0]}).
"""
(ROOT / "docs/key_findings_summary.md").write_text(summary)
print(summary)
