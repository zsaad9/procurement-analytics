# Databricks notebook source
# MAGIC %md
# MAGIC # 04 · Automated data-quality checks
# MAGIC
# MAGIC Each check returns the number of records it flags. Results are appended to `dq_results` (one row per check per
# MAGIC run) so quality can be tracked across refreshes.
# MAGIC
# MAGIC * **severity = critical**: the pipeline fails if any record is flagged (e.g. duplicate keys, negative amounts,
# MAGIC   broken joins).
# MAGIC * **severity = warning**: flagged records are kept and documented (e.g. unknown supplier country).
# MAGIC * **severity = info**: known characteristics of the source, reported for transparency (status `INFO`).

# COMMAND ----------

# MAGIC %run ./00_config

# COMMAND ----------

from datetime import datetime, timezone
from pyspark.sql import functions as F

bronze = spark.table(T("bronze_contract_awards"))
silver = spark.table(T("silver_contract_awards"))
fact = spark.table(T("fact_contract_awards"))
as_of = silver.agg(F.max("as_of_date")).first()[0]
RUN_TS = datetime.now(timezone.utc)

results = []

def _status(severity, flagged):
    if flagged == 0:
        return "PASS"
    return {"critical": "FAIL", "warning": "WARN"}.get(severity, "INFO")

def check(layer, name, dimension, severity, df, flagged_condition, description):
    total = df.count()
    flagged = df.filter(flagged_condition).count()
    results.append(dict(layer=layer, check_name=name, dimension=dimension, severity=severity,
                        records_checked=total, records_flagged=flagged,
                        pct_flagged=round(100.0 * flagged / total, 4) if total else 0.0,
                        status=_status(severity, flagged),
                        description=description))

def check_value(layer, name, dimension, severity, checked, flagged, description):
    results.append(dict(layer=layer, check_name=name, dimension=dimension, severity=severity,
                        records_checked=checked, records_flagged=flagged,
                        pct_flagged=round(100.0 * flagged / checked, 4) if checked else 0.0,
                        status=_status(severity, flagged),
                        description=description))

# COMMAND ----------

# MAGIC %md ### Completeness

# COMMAND ----------

required = {  # silver column -> severity
    "wb_contract_number": "critical", "project_id": "critical", "contract_signing_date": "critical",
    "amount_usd": "critical", "procurement_method": "critical", "procurement_category": "critical",
    "region_code": "critical", "borrower_country": "critical",
    "supplier_id": "warning", "supplier_name": "warning", "supplier_country": "warning",
    "borrower_country_code": "info", "contract_description": "info",
}
for col, sev in required.items():
    check("silver", f"not_null:{col}", "completeness", sev, silver, F.col(col).isNull(), f"{col} is missing")
check("silver", "not_null:review_type", "completeness", "warning", silver, F.col("review_type") == "Not recorded",
      "review type missing in source (set to 'Not recorded')")
check("silver", "not_empty:global_practice", "completeness", "info", silver, F.size("practice_list") == 0,
      "project global practice is blank in source")

# COMMAND ----------

# MAGIC %md ### Uniqueness

# COMMAND ----------

dup_award = (fact.groupBy("award_line_id").count().filter("count > 1")
                 .agg(F.coalesce(F.sum("count"), F.lit(0))).first()[0])
check_value("gold", "unique:award_line_id(contract,supplier)", "uniqueness", "critical", fact.count(), dup_award,
            "fact rows sharing the same contract number + supplier")

contract_level = ["project_id", "procurement_method", "procurement_category", "contract_signing_date", "review_type"]
incons = (silver.groupBy("wb_contract_number")
          .agg(*[F.countDistinct(c).alias(c) for c in contract_level])
          .filter(" OR ".join(f"{c} > 1" for c in contract_level)).count())
check_value("silver", "consistent:contract_attributes", "uniqueness", "critical",
            silver.select("wb_contract_number").distinct().count(), incons,
            "contracts whose rows disagree on project, method, category, date or review type")
check("silver", "probable_duplicate_entry", "uniqueness", "warning", silver, F.col("is_probable_duplicate"),
      "same project, supplier, amount, date and description under another contract number (excluded from gold)")
for name in ["dim_project:project_id", "dim_supplier:supplier_key", "dim_borrower_country:borrower_country_key",
             "dim_supplier_country:supplier_country_key", "dim_procurement_method:method_key",
             "dim_fiscal_year:fiscal_year", "dim_date:date_key"]:
    tbl, key = name.split(":")
    d = spark.table(T(tbl))
    check_value("gold", f"unique:{name}", "uniqueness", "critical", d.count(),
                d.count() - d.select(key).distinct().count(), f"duplicate keys in {tbl}")

# COMMAND ----------

# MAGIC %md ### Validity

# COMMAND ----------

check("silver", "valid:signing_date_in_range", "validity", "critical", silver,
      (F.col("contract_signing_date") < F.lit(FIRST_VALID_DATE)) | (F.col("contract_signing_date") > F.lit(as_of)),
      f"signing date before {FIRST_VALID_DATE} or after the as-of date {as_of}")
check("silver", "valid:fiscal_year_matches_source", "validity", "critical", silver, ~F.col("fy_matches_source"),
      "WB fiscal year derived from signing date differs from source Fiscal Year")
check("silver", "valid:calendar_year_matches_source", "validity", "warning", silver,
      F.year("contract_signing_date") != F.col("source_calendar_year"), "calendar year differs from source")
check("silver", "valid:amount_non_negative", "validity", "critical", silver, F.col("amount_usd") < 0, "negative amount")
check("silver", "valid:amount_non_zero", "validity", "warning", silver, F.col("amount_usd") == 0, "zero amount")
check("silver", "valid:amount_at_least_10_usd", "validity", "info", silver, F.col("amount_usd") < 10,
      "amount below USD 10 (possible unit or currency-conversion error)")
check("silver", "valid:method_mapped", "validity", "critical", silver, F.col("method_abbrev").isNull(),
      "procurement method not in reference mapping")
check("silver", "valid:category_mapped", "validity", "critical", silver, F.col("category_code").isNull(),
      "procurement category not in reference mapping")
check("silver", "valid:region_mapped", "validity", "critical", silver, F.col("region_code").isNull(),
      "region not in reference mapping")
check("silver", "outlier:amount_iqr_by_category", "validity", "info", silver, F.col("is_amount_outlier"),
      "log10(amount) outside Q1-3*IQR..Q3+3*IQR within category (flag only)")

# COMMAND ----------

# MAGIC %md ### Reconciliation and referential integrity

# COMMAND ----------

b_n, s_n = bronze.count(), silver.count()
check_value("silver", "reconcile:row_count_bronze_vs_silver", "reconciliation", "critical", b_n, abs(b_n - s_n),
            "rows lost or created between bronze and silver")
b_usd = bronze.agg(F.sum(F.col("supplier_contract_amount_usd").cast("decimal(18,2)"))).first()[0]
s_usd = silver.agg(F.sum("amount_usd")).first()[0]
check_value("silver", "reconcile:amount_bronze_vs_silver", "reconciliation", "critical", 1,
            int(abs(b_usd - s_usd) > 0.01), f"bronze USD {b_usd:,.2f} vs silver USD {s_usd:,.2f}")
expected_fact = silver.filter(~F.col("is_probable_duplicate")).count() if EXCLUDE_PROBABLE_DUPLICATES else s_n
check_value("gold", "reconcile:fact_rows_vs_silver", "reconciliation", "critical", expected_fact,
            abs(expected_fact - fact.count()), "fact rows = silver rows minus probable duplicates")

fk = [("project_id", "dim_project", "project_id"), ("borrower_country_key", "dim_borrower_country", "borrower_country_key"),
      ("supplier_key", "dim_supplier", "supplier_key"), ("supplier_country_key", "dim_supplier_country", "supplier_country_key"),
      ("method_key", "dim_procurement_method", "method_key"), ("category_key", "dim_procurement_category", "category_key"),
      ("fiscal_year", "dim_fiscal_year", "fiscal_year"), ("signing_date_key", "dim_date", "date_key")]
for fcol, dim, dcol in fk:
    orphans = fact.join(spark.table(T(dim)).select(F.col(dcol).alias("_k")), F.col(fcol) == F.col("_k"), "left_anti").count()
    check_value("gold", f"fk:{fcol}->{dim}", "referential integrity", "critical", fact.count(), orphans,
                f"fact rows with no match in {dim}")

# COMMAND ----------

dq = spark.createDataFrame(results).withColumn("run_ts", F.lit(RUN_TS)).withColumn("as_of_date", F.lit(as_of))
dq = dq.select("run_ts", "as_of_date", "layer", "check_name", "dimension", "severity", "status",
               "records_checked", "records_flagged", "pct_flagged", "description")
(dq.write.mode("append" if IS_DATABRICKS else "overwrite").format(TABLE_FORMAT)
   .option("mergeSchema", "true").saveAsTable(T("dq_results")))

summary = dq.orderBy(F.expr("CASE status WHEN 'FAIL' THEN 0 WHEN 'WARN' THEN 1 WHEN 'INFO' THEN 2 ELSE 3 END"), "layer", "check_name")
summary.select("status", "severity", "layer", "check_name", "records_checked", "records_flagged", "pct_flagged").show(100, truncate=False)
print(dq.groupBy("status").count().collect())

failed = [r["check_name"] for r in results if r["status"] == "FAIL"]
assert not failed, f"Critical data-quality checks failed: {failed}"
