"""
Render docs/data_dictionary.md: column descriptions (maintained here) + data type, row count, null count and an
example value read from the gold Parquet exports, so the dictionary always matches the data.
"""
from pathlib import Path

import duckdb

ROOT = Path(__file__).resolve().parents[1]
G = ROOT / "data/gold/parquet"

TABLES = {
    "fact_contract_awards": ("Fact. One row per contract × supplier (award line). Probable duplicate entries are "
                             "excluded. Grain key: award_line_id.", {
        "award_line_id": "Surrogate key: `wb_contract_number-supplier_key`. Unique.",
        "wb_contract_number": "World Bank contract number from STEP. A contract has one row per supplier; count contracts with COUNT(DISTINCT).",
        "project_id": "IPF project ID (P-code). FK → dim_project.",
        "borrower_country_key": "Borrower country code, or `X-<NAME>` for regional groupings without a code. FK → dim_borrower_country.",
        "supplier_key": "STEP Supplier ID; `UNKNOWN` where the source ID was `0`. FK → dim_supplier.",
        "supplier_country_key": "Supplier country code; `UNK` when missing or `null` in source. FK → dim_supplier_country.",
        "method_key": "Procurement method abbreviation (RFB, RFQ, QCBS, DS ...). FK → dim_procurement_method.",
        "category_key": "GO / WK / CS / NC. FK → dim_procurement_category.",
        "fiscal_year": "World Bank fiscal year of the signing date (Jul–Jun; FY2025 = Jul 2024–Jun 2025). Equals source `Fiscal Year` for all rows (checked).",
        "signing_date_key": "yyyymmdd integer. FK → dim_date.",
        "contract_signing_date": "Contract signing date.",
        "fiscal_quarter": "Q1 = Jul–Sep … Q4 = Apr–Jun.",
        "contract_description": "Contract description, whitespace and line breaks collapsed. Mixed languages (EN/FR/ES/PT…).",
        "review_type": "Prior / Post / Not recorded (blank in source).",
        "supplier_origin": "Domestic (supplier country = borrower country), Foreign, International organization (supplier country `World`), Unknown supplier country, Not applicable (regional borrower).",
        "amount_usd": "Supplier contract amount in USD as published. JV contracts: contract value split equally across members by the publisher.",
        "contract_supplier_count": "Number of supplier rows on the contract (>1 = joint award).",
        "is_joint_award": "contract_supplier_count > 1.",
        "is_individual_consultant": "Supplier is an anonymised individual consultant (16-character hashed ID).",
        "is_amount_outlier": "log10(amount) outside [Q1 − 3·IQR, Q3 + 3·IQR] within procurement category. Flag only; rows are kept.",
    }),
    "dim_project": ("One row per IPF project.", {
        "project_id": "PK.", "project_name": "Project name.",
        "borrower_country_key": "Borrower of the project.", "region_code": "World Bank region code.",
        "practice_count": "Number of distinct global practices listed (0 = not specified).",
        "practice_first_listed": "First practice in the source list (order meaning not documented by the publisher).",
        "practices": "All practices, `; `-separated, legacy labels mapped to current ones.",
    }),
    "bridge_project_practice": ("Project ↔ global practice (many-to-many) with allocation weights.", {
        "project_id": "FK → dim_project.", "global_practice": "Standardised practice label; `Not specified` if blank.",
        "allocation_weight": "1 / number of practices of the project. Weights sum to 1 per project.",
    }),
    "dim_borrower_country": ("Borrower country/economy or regional grouping, with World Bank region.", {
        "borrower_country_key": "PK. ISO-like code from source (CI and SO repaired), or `X-<NAME>`.",
        "borrower_country": "Name as published (e.g. `Turkiye`, `Congo, Democratic Republic of`).",
        "borrower_country_code": "Code from source (NULL for regional groupings).",
        "borrower_type": "Country, or Regional / multi-country (blank or numeric-prefixed codes such as 3W).",
        "region_code": "AFE, AFW, EAP, ECA, LCR, MNA, SAR, OTH.",
        "region_name": "Current World Bank region name. MNA includes Afghanistan and Pakistan for all years.",
    }),
    "dim_supplier_country": ("Country/economy of the supplier as recorded in STEP.", {
        "supplier_country_key": "PK (code, or `UNK`). `NA` = Namibia.",
        "supplier_country": "Name; `Unknown` for missing; `World` = international organisations.",
        "supplier_country_code": "Code as published (WB legacy codes, e.g. DR Congo `ZR`, Yemen `RY`).",
        "is_unknown": "True for the `UNK` member.",
    }),
    "dim_supplier": ("One row per STEP Supplier ID.", {
        "supplier_key": "PK (STEP Supplier ID).",
        "is_individual_consultant": "Anonymised individual (one ID per award; cannot be tracked across contracts).",
        "supplier_name": "Most frequent name used with this ID; `Individual consultant (anonymised)` for individuals.",
        "supplier_country_key": "Most frequent known country for this ID.",
    }),
    "dim_procurement_method": ("18 canonical procurement methods with grouping.", {
        "method_key": "PK abbreviation.", "method_name": "Canonical name (double-space variant of CQS merged).",
        "method_group": "Analytical group (see docs/indicators.md I4).",
        "competition_tier": "Open competitive / Limited competitive / Individual consultant (not classifiable) / Direct (non-competitive) / Other arrangement.",
        "tier_sort": "Sort order for competition_tier.",
        "is_open_competitive": "competition_tier = Open competitive.", "is_direct": "competition_tier = Direct.",
    }),
    "dim_procurement_category": ("Procurement category.", {
        "category_key": "PK: GO, WK, CS, NC.", "category_name": "Goods, Works, Consultant Services, Non-consulting Services.",
    }),
    "dim_fiscal_year": ("World Bank fiscal years present in the data.", {
        "fiscal_year": "PK.", "fy_label": "`FY2025`.", "fy_start_date": "1 July of the previous calendar year.",
        "fy_end_date": "30 June.", "is_complete_fy": "fy_end_date before the data as-of date.",
        "months_covered": "12 for complete years; months with data for the partial year.",
        "first_signing_date": "Earliest signing date in the FY.", "last_signing_date": "Latest signing date in the FY.",
    }),
    "dim_date": ("Daily calendar from 1 Jul 2019 to the as-of date, with fiscal attributes.", {
        "date_key": "PK yyyymmdd.", "date": "Date.", "calendar_year": "", "month_number": "1–12.",
        "month_name": "Jan…Dec.", "fiscal_year": "FK → dim_fiscal_year.", "fiscal_month_number": "Jul = 1 … Jun = 12.",
        "fiscal_quarter": "Q1–Q4.", "fy_month_label": "`FY2025-01` (= Jul 2024).",
    }),
}

con = duckdb.connect()
out = ["# Data dictionary: gold layer\n",
       "Generated by `analysis/render_data_dictionary.py` from the gold Parquet exports (types, row counts, nulls and "
       "examples are read from the data). Catalog location on Databricks: `workspace.wb_procurement.<table>`.\n",
       "Also available: `vw_awards` (fact joined to all dimensions, used by the chatbot), `silver_contract_awards` "
       "(all rows incl. probable duplicates, with `is_probable_duplicate` / `probable_duplicate_of`), `ind_*` "
       "indicator tables (see `docs/indicators.md`) and `dq_results` (one row per data-quality check per run).\n"]
for t, (desc, cols) in TABLES.items():
    p = (G / f"{t}.parquet").as_posix()
    n = con.execute(f"SELECT COUNT(*) FROM '{p}'").fetchone()[0]
    schema = con.execute(f"DESCRIBE SELECT * FROM '{p}'").fetchall()
    out += [f"## {t}\n", f"{desc} Rows: **{n:,}**.\n",
            "| Column | Type | Nulls | Example | Description |", "|---|---|---:|---|---|"]
    for name, typ, *_ in schema:
        nulls = con.execute(f'SELECT COUNT(*) - COUNT("{name}") FROM \'{p}\'').fetchone()[0]
        ex = con.execute(f'SELECT CAST("{name}" AS VARCHAR) FROM \'{p}\' WHERE "{name}" IS NOT NULL LIMIT 1').fetchone()
        ex = (ex[0] if ex else "").replace("|", "/")[:40]
        out.append(f"| `{name}` | {typ} | {nulls:,} | {ex} | {cols.get(name, '')} |")
    missing = set(cols) - {s[0] for s in schema}
    assert not missing, f"documented columns not in {t}: {missing}"
    out.append("")

out += ["## Assumptions and data limitations\n",
        "**Publisher caveats**",
        "- Awards to subcontractors are excluded.",
        "- Cofinancing is excluded.",
        "- Joint-venture contract values are split equally across JV members; the per-supplier `amount_usd` is not the "
        "member's real share. Sum a contract's rows to get its value.\n",
        "**Modelling assumptions**",
        "- Fiscal year = World Bank FY (1 Jul–30 Jun) of the signing date; it matches the source column on every row.",
        "- Probable duplicate entries (same project, supplier, amount, signing date and normalised description under a "
        "different contract number) are removed from the fact; the lowest contract number is kept. They remain in Silver.",
        "- Domestic = supplier country name equals borrower country name. Not defined for regional borrowers.",
        "- `World` as supplier country is treated as an international organisation, not a foreign country.",
        "- Global practice allocation is an equal split across a project's listed practices.",
        "- Cote d'Ivoire and Somalia borrower codes are filled (CI, SO) from the supplier-side code list.",
        "- Region names follow the current World Bank structure for all years.\n",
        "**Known limitations**",
        "- No market approach (international vs national), bid counts, estimated cost or award criteria: competition "
        "intensity and price efficiency cannot be measured.",
        "- Individual consultants are anonymised (one ID per award), so repeat hiring of individuals is invisible.",
        "- A company group can have several Supplier IDs; supplier concentration is a lower bound.",
        "- Supplier country is the registration country, not the location of the work.",
        "- The latest fiscal year is partial, and recent months can be incomplete because of STEP data-entry lag.",
        "- Values are at signing in USD; amendments, cancellations and exchange-rate effects after signing are not shown.",
        "- 653 source rows have no supplier country (USD 1.74 bn), concentrated in a few large contracts.",
        ]
(ROOT / "docs/data_dictionary.md").write_text("\n".join(out) + "\n")
print("\n".join(out[:40]))
