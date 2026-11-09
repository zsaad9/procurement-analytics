# Databricks notebook source
# MAGIC %md
# MAGIC # 05 · Procurement indicators
# MAGIC
# MAGIC Ten indicators, defined in `docs/indicators.md` (definition, formula, limitations). Each is computed here in
# MAGIC Spark SQL from the gold star schema and written to an `ind_*` table. `ind_summary_by_fy` gathers the scalar
# MAGIC indicators per fiscal year; it is the reference the Power BI DAX measures are reconciled against.
# MAGIC
# MAGIC | ID | Indicator |
# MAGIC |---|---|
# MAGIC | I1 | Total award value (USD) |
# MAGIC | I2 | Number of contracts awarded |
# MAGIC | I3 | Average and median contract value |
# MAGIC | I4 | Procurement method mix (share of value and count by competition tier / method group) |
# MAGIC | I5 | Open competitive share of award value |
# MAGIC | I6 | Direct selection share (value and count) |
# MAGIC | I7 | Domestic supplier share of award value (+ foreign supplier origin) |
# MAGIC | I8 | Supplier concentration: top-10 firms' share of value, HHI |
# MAGIC | I9 | Prior-review share of award value |
# MAGIC | I10 | Regional and sector (global practice) distribution |

# COMMAND ----------

# MAGIC %run ./00_config

# COMMAND ----------

fact, vw = T("fact_contract_awards"), T("vw_awards")
bridge = T("bridge_project_practice")

def run(name, sql, show=True):
    df = spark.sql(sql)
    write_table(df, name)
    if show:
        spark.table(T(name)).show(60, truncate=False)
    return spark.table(T(name))

# COMMAND ----------

# MAGIC %md ### I1–I3, I5, I6, I7, I9 — scalar indicators by fiscal year

# COMMAND ----------

run("ind_summary_by_fy", f"""
WITH contracts AS (           -- contract grain: JV member rows summed back to full contract value
  SELECT fiscal_year, wb_contract_number, SUM(amount_usd) AS contract_value
  FROM {fact} GROUP BY fiscal_year, wb_contract_number
),
c AS (
  SELECT fiscal_year, AVG(contract_value) AS avg_contract_value_usd,
         percentile(CAST(contract_value AS DOUBLE), 0.5) AS median_contract_value_usd
  FROM contracts GROUP BY fiscal_year
),
a AS (
  SELECT fiscal_year,
    SUM(amount_usd)                                   AS total_award_value_usd,                        -- I1
    COUNT(DISTINCT wb_contract_number)                AS contract_count,                               -- I2
    COUNT(*)                                          AS award_line_count,
    SUM(CASE WHEN is_open_competitive THEN amount_usd END) / SUM(amount_usd)        AS open_competitive_value_share,   -- I5
    SUM(CASE WHEN is_direct THEN amount_usd END) / SUM(amount_usd)                  AS direct_selection_value_share,   -- I6
    COUNT(DISTINCT CASE WHEN is_direct THEN wb_contract_number END) / COUNT(DISTINCT wb_contract_number)
                                                                                    AS direct_selection_count_share,   -- I6
    SUM(CASE WHEN supplier_origin = 'Domestic' THEN amount_usd END)
      / SUM(CASE WHEN supplier_origin IN ('Domestic','Foreign','International organization') THEN amount_usd END)
                                                                                    AS domestic_supplier_value_share,  -- I7
    SUM(CASE WHEN supplier_origin = 'International organization' THEN amount_usd END)
      / SUM(CASE WHEN supplier_origin IN ('Domestic','Foreign','International organization') THEN amount_usd END)
                                                                                    AS intl_org_value_share,           -- I7
    SUM(CASE WHEN review_type = 'Prior' THEN amount_usd END) / SUM(amount_usd)       AS prior_review_value_share,       -- I9
    MAX(is_complete_fy) AS is_complete_fy
  FROM {vw} GROUP BY fiscal_year
)
SELECT a.fiscal_year, a.is_complete_fy, a.total_award_value_usd, a.contract_count, a.award_line_count,
       c.avg_contract_value_usd, c.median_contract_value_usd,
       a.open_competitive_value_share, a.direct_selection_value_share, a.direct_selection_count_share,
       a.domestic_supplier_value_share, a.intl_org_value_share, a.prior_review_value_share
FROM a JOIN c USING (fiscal_year)
ORDER BY fiscal_year
""")

# COMMAND ----------

# MAGIC %md ### I3 by procurement category (contract size depends heavily on category)

# COMMAND ----------

run("ind_contract_size_by_category", f"""
WITH contracts AS (
  SELECT procurement_category, fiscal_year, wb_contract_number, SUM(amount_usd) AS contract_value
  FROM {vw} GROUP BY procurement_category, fiscal_year, wb_contract_number
)
SELECT procurement_category, fiscal_year, COUNT(*) AS contract_count, SUM(contract_value) AS total_value_usd,
       AVG(contract_value) AS avg_contract_value_usd,
       percentile(CAST(contract_value AS DOUBLE), 0.5) AS median_contract_value_usd
FROM contracts GROUP BY procurement_category, fiscal_year ORDER BY procurement_category, fiscal_year
""", show=False)

# COMMAND ----------

# MAGIC %md ### I4 — method mix by competition tier and method group

# COMMAND ----------

run("ind_method_mix", f"""
SELECT fiscal_year, competition_tier, method_group, method_name,
       SUM(amount_usd) AS value_usd,
       COUNT(DISTINCT wb_contract_number) AS contract_count,
       SUM(amount_usd) / SUM(SUM(amount_usd)) OVER (PARTITION BY fiscal_year) AS value_share,
       COUNT(DISTINCT wb_contract_number) / SUM(COUNT(DISTINCT wb_contract_number)) OVER (PARTITION BY fiscal_year) AS count_share
FROM {vw} GROUP BY fiscal_year, competition_tier, method_group, method_name
ORDER BY fiscal_year, value_usd DESC
""", show=False)
# note: count_share sums distinct contracts per method; a contract has exactly one method, so shares add to 1.

run("ind_method_mix_by_category", f"""
SELECT procurement_category, competition_tier,
       SUM(amount_usd) AS value_usd, COUNT(DISTINCT wb_contract_number) AS contract_count,
       SUM(amount_usd) / SUM(SUM(amount_usd)) OVER (PARTITION BY procurement_category) AS value_share_within_category
FROM {vw} GROUP BY procurement_category, competition_tier ORDER BY procurement_category, value_usd DESC
""")

# COMMAND ----------

# MAGIC %md ### I7 — supplier origin (domestic / foreign) and top foreign supplier countries

# COMMAND ----------

run("ind_supplier_origin", f"""
SELECT fiscal_year, region_name, supplier_origin, SUM(amount_usd) AS value_usd,
       COUNT(DISTINCT wb_contract_number) AS contract_count
FROM {vw} GROUP BY fiscal_year, region_name, supplier_origin
ORDER BY fiscal_year, region_name, supplier_origin
""", show=False)

run("ind_foreign_supplier_countries", f"""
SELECT supplier_country, SUM(amount_usd) AS value_usd, COUNT(DISTINCT wb_contract_number) AS contract_count,
       SUM(amount_usd) / SUM(SUM(amount_usd)) OVER () AS share_of_foreign_value,
       COUNT(DISTINCT borrower_country) AS borrower_countries_served
FROM {vw} WHERE supplier_origin = 'Foreign'
GROUP BY supplier_country ORDER BY value_usd DESC LIMIT 25
""")

# COMMAND ----------

# MAGIC %md ### I8 — supplier concentration (firms only; anonymised individuals and unknown suppliers excluded)

# COMMAND ----------

run("ind_supplier_concentration", f"""
WITH s AS (
  SELECT fiscal_year, supplier_key, SUM(amount_usd) AS v
  FROM {vw} WHERE NOT is_individual_consultant AND supplier_key <> 'UNKNOWN'
  GROUP BY fiscal_year, supplier_key
),
r AS (
  SELECT *, ROW_NUMBER() OVER (PARTITION BY fiscal_year ORDER BY v DESC) AS rk,
         v / SUM(v) OVER (PARTITION BY fiscal_year) AS sh
  FROM s
)
SELECT fiscal_year, COUNT(*) AS supplier_count, SUM(v) AS firm_value_usd,
       SUM(CASE WHEN rk <= 10 THEN sh END)  AS top10_supplier_value_share,
       SUM(CASE WHEN rk <= 100 THEN sh END) AS top100_supplier_value_share,
       SUM(sh * sh) * 10000                 AS hhi
FROM r GROUP BY fiscal_year ORDER BY fiscal_year
""")

run("ind_top_suppliers", f"""
SELECT supplier_key, MAX(supplier_name) AS supplier_name, MAX(supplier_country) AS supplier_country,
       SUM(amount_usd) AS value_usd, COUNT(DISTINCT wb_contract_number) AS contract_count,
       COUNT(DISTINCT borrower_country) AS borrower_countries,
       SUM(CASE WHEN is_direct THEN amount_usd ELSE 0 END) / SUM(amount_usd) AS direct_selection_share
FROM {vw} WHERE NOT is_individual_consultant AND supplier_key <> 'UNKNOWN'
GROUP BY supplier_key ORDER BY value_usd DESC LIMIT 25
""")

# COMMAND ----------

# MAGIC %md ### I10 — regional and sector distribution

# COMMAND ----------

run("ind_region", f"""
SELECT fiscal_year, region_code, region_name, SUM(amount_usd) AS value_usd,
       COUNT(DISTINCT wb_contract_number) AS contract_count,
       SUM(amount_usd) / SUM(SUM(amount_usd)) OVER (PARTITION BY fiscal_year) AS value_share,
       SUM(CASE WHEN is_open_competitive THEN amount_usd END) / SUM(amount_usd) AS open_competitive_value_share,
       SUM(CASE WHEN is_direct THEN amount_usd END) / SUM(amount_usd) AS direct_selection_value_share
FROM {vw} GROUP BY fiscal_year, region_code, region_name ORDER BY fiscal_year, value_usd DESC
""", show=False)

run("ind_sector", f"""
SELECT f.fiscal_year, b.global_practice,
       SUM(f.amount_usd * b.allocation_weight) AS allocated_value_usd,
       SUM(f.amount_usd * b.allocation_weight) / SUM(SUM(f.amount_usd * b.allocation_weight)) OVER (PARTITION BY f.fiscal_year) AS value_share
FROM {fact} f JOIN {bridge} b ON f.project_id = b.project_id
GROUP BY f.fiscal_year, b.global_practice ORDER BY f.fiscal_year, allocated_value_usd DESC
""", show=False)

# COMMAND ----------

for t in ["ind_summary_by_fy", "ind_contract_size_by_category", "ind_method_mix", "ind_method_mix_by_category",
          "ind_supplier_origin", "ind_foreign_supplier_countries", "ind_supplier_concentration", "ind_top_suppliers",
          "ind_region", "ind_sector"]:
    print(f"{t:34} {spark.table(T(t)).count():>6} rows")
