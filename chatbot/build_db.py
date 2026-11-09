"""
Build the chatbot's local DuckDB warehouse from the gold Parquet exports.

    python chatbot/build_db.py --gold data/gold/parquet --out chatbot/warehouse.duckdb

Creates one table per gold Parquet file plus the flattened `vw_awards` view (same definition as the
Databricks view in notebooks/03_gold_model.py). The chatbot then opens this file READ-ONLY.
"""
import argparse
import os
from pathlib import Path

import duckdb

TABLES = ["fact_contract_awards", "dim_project", "bridge_project_practice", "dim_borrower_country",
          "dim_supplier_country", "dim_supplier", "dim_procurement_method", "dim_procurement_category",
          "dim_fiscal_year", "ind_summary_by_fy"]

VW_AWARDS = """
CREATE OR REPLACE VIEW vw_awards AS
SELECT f.award_line_id, f.wb_contract_number, f.fiscal_year, y.is_complete_fy, f.contract_signing_date,
       f.fiscal_quarter, f.contract_description, f.amount_usd, f.contract_supplier_count, f.is_joint_award,
       f.is_amount_outlier, f.review_type, f.supplier_origin,
       p.project_id, p.project_name, p.practices, p.practice_first_listed,
       c.borrower_country, c.borrower_country_code, c.borrower_type, c.region_code, c.region_name,
       m.method_key, m.method_name, m.method_group, m.competition_tier, m.is_open_competitive, m.is_direct,
       k.category_name AS procurement_category,
       s.supplier_key, s.supplier_name, s.is_individual_consultant,
       sc.supplier_country, sc.supplier_country_code
FROM fact_contract_awards f
JOIN dim_project p              ON f.project_id = p.project_id
JOIN dim_borrower_country c     ON f.borrower_country_key = c.borrower_country_key
JOIN dim_procurement_method m   ON f.method_key = m.method_key
JOIN dim_procurement_category k ON f.category_key = k.category_key
JOIN dim_supplier s             ON f.supplier_key = s.supplier_key
JOIN dim_supplier_country sc    ON f.supplier_country_key = sc.supplier_country_key
JOIN dim_fiscal_year y          ON f.fiscal_year = y.fiscal_year
"""


def build(gold: Path, out: Path):
    if out.exists():
        out.unlink()
    con = duckdb.connect(str(out))
    for t in TABLES:
        src = gold / f"{t}.parquet"
        con.execute(f"CREATE TABLE {t} AS SELECT * FROM read_parquet('{src.as_posix()}')")
    con.execute(VW_AWARDS)
    n = con.execute("SELECT COUNT(*) FROM vw_awards").fetchone()[0]
    con.close()
    print(f"Built {out} ({out.stat().st_size/1e6:.1f} MB); vw_awards rows: {n:,}")


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    root = Path(__file__).resolve().parents[1]
    ap.add_argument("--gold", default=os.environ.get("WB_GOLD_DIR", root / "data/gold/parquet"), type=Path)
    ap.add_argument("--out", default=root / "chatbot/warehouse.duckdb", type=Path)
    a = ap.parse_args()
    build(a.gold, a.out)
