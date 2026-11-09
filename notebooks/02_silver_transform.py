# Databricks notebook source
# MAGIC %md
# MAGIC # 02 · Silver: clean, standardise, deduplicate
# MAGIC
# MAGIC | Step | Rule |
# MAGIC |---|---|
# MAGIC | Text hygiene | trim; collapse repeated whitespace and line breaks; keep original description in `contract_description_raw` |
# MAGIC | Placeholders | `''`, `null` (supplier country / supplier), Supplier ID `0`, reference numbers `N/A`, `-`, `0` → NULL. **`NA` = Namibia is kept.** |
# MAGIC | Types | dates `MM/dd/yyyy` → `DATE`; amount → `DECIMAL(18,2)`; years → `INT` |
# MAGIC | Fiscal year | `wb_fiscal_year` = year(signing date) + 1 if month ≥ 7 else year (WB FY = 1 Jul–30 Jun); compared with source `fiscal_year` |
# MAGIC | Region | 8 source names → official name + short code (AFE, AFW, EAP, ECA, LCR, MNA, SAR, OTH) |
# MAGIC | Borrower | missing codes repaired for Cote d'Ivoire (CI) and Somalia (SO); `borrower_type` = Country vs Regional / multi-country |
# MAGIC | Procurement method | 19 raw values → 18 canonical names (double-space variant merged) + abbreviation, method group, competition tier |
# MAGIC | Global practice | semicolon list → array of standard labels (legacy labels mapped) |
# MAGIC | Supplier origin | Domestic / Foreign / International organization (supplier country `World`: UN agencies etc.) / Unknown supplier country / Not applicable (regional borrower) |
# MAGIC | Dedup 1 | natural key (`wb_contract_number`, `supplier_id`) — keep one row (latest as-of date) |
# MAGIC | Dedup 2 | `is_probable_duplicate`: same project, supplier, amount, signing date and normalised description under a different contract number; first contract number kept |
# MAGIC | Outliers | `is_amount_outlier`: log10(amount) outside [Q1 − 3·IQR, Q3 + 3·IQR] within procurement category (flag only) |

# COMMAND ----------

# MAGIC %run ./00_config

# COMMAND ----------

from pyspark.sql import functions as F, Window as W
from pyspark.sql.types import DecimalType

b = spark.table(T("bronze_contract_awards"))
bronze_rows = b.count()

def clean(c):
    """trim + collapse any run of whitespace (incl. line breaks) to one space; empty -> NULL"""
    v = F.trim(F.regexp_replace(F.col(c), r"\s+", " "))
    return F.when(v == "", None).otherwise(v)

def null_if_in(expr, values):
    return F.when(F.lower(expr).isin([x.lower() for x in values]), None).otherwise(expr)

# COMMAND ----------

# MAGIC %md ### Reference mappings

# COMMAND ----------

REGION_MAP = [  # source name, code, standard name
    ("Eastern and Southern Africa", "AFE", "Eastern and Southern Africa"),
    ("Western and Central Africa", "AFW", "Western and Central Africa"),
    ("East Asia and Pacific", "EAP", "East Asia and Pacific"),
    ("Europe and Central Asia", "ECA", "Europe and Central Asia"),
    ("Latin America and Caribbean", "LCR", "Latin America and Caribbean"),
    ("Middle East, North Africa, Afghanistan, and Pakistan", "MNA",
     "Middle East, North Africa, Afghanistan and Pakistan"),
    ("South Asia", "SAR", "South Asia"),
    ("Other", "OTH", "Other / Global"),
]

# canonical method, abbreviation, method group, competition tier
METHOD_MAP = [
    ("Request for Bids", "RFB", "Open competitive (goods/works/NCS)", "Open competitive"),
    ("Request for Proposals", "RFP", "Open competitive (goods/works/NCS)", "Open competitive"),
    ("E-Auctions", "EA", "Open competitive (goods/works/NCS)", "Open competitive"),
    ("Quality And Cost-Based Selection", "QCBS", "Competitive selection of consulting firms", "Open competitive"),
    ("Quality Based Selection", "QBS", "Competitive selection of consulting firms", "Open competitive"),
    ("Fixed Budget Selection", "FBS", "Competitive selection of consulting firms", "Open competitive"),
    ("Least Cost Selection", "LCS", "Competitive selection of consulting firms", "Open competitive"),
    ("Consultant Qualification Selection", "CQS", "Competitive selection of consulting firms", "Open competitive"),
    ("Request for Quotations", "RFQ", "Request for Quotations (limited competition)", "Limited competitive"),
    ("Individual Consultant Selection", "ICS", "Individual consultant selection", "Individual consultant (not classifiable)"),
    ("Direct Selection", "DS", "Direct selection", "Direct (non-competitive)"),
    ("UN Agencies (Direct)", "UN", "Direct selection", "Direct (non-competitive)"),
    ("Community Driven Development", "CDD", "Other arrangements", "Other arrangement"),
    ("Force Account", "FA", "Other arrangements", "Other arrangement"),
    ("Commercial Practices", "CP", "Other arrangements", "Other arrangement"),
    ("Non-Profit Organizations", "NPO", "Other arrangements", "Other arrangement"),
    ("Public Private Partnership", "PPP", "Other arrangements", "Other arrangement"),
    ("Procurement Agents", "PA", "Other arrangements", "Other arrangement"),
]

CATEGORY_MAP = [("Goods", "GO"), ("Works", "WK"), ("Consultant Services", "CS"), ("Non-consulting Services", "NC")]

PRACTICE_MAP = {  # legacy / variant label -> standard label
    "Water, Sanitation": "Water/Sanit/Waste",
    "Energy and Mineral": "Energy & Extractives",
    "Industry, Trade": "Industry & Trade/Ser",
    "Digital Development": "Info & Communication",
    "Social Sustain": "Social Sustainability",
}
COUNTRY_CODE_FIX = {"Cote d'Ivoire": "CI", "Somalia, Federal Republic of": "SO"}

region_df = spark.createDataFrame(REGION_MAP, "region_source string, region_code string, region_name string")
method_df = spark.createDataFrame(METHOD_MAP,
    "procurement_method string, method_abbrev string, method_group string, competition_tier string")
category_df = spark.createDataFrame(CATEGORY_MAP, "procurement_category string, category_code string")
write_table(region_df, "ref_region")
write_table(method_df, "ref_procurement_method")
write_table(category_df, "ref_procurement_category")

# COMMAND ----------

# MAGIC %md ### Clean and type

# COMMAND ----------

def std_practice(x):
    e = x
    for old, new in PRACTICE_MAP.items():
        e = F.when(x == F.lit(old), F.lit(new)).otherwise(e)
    return e

code_fix = F.create_map(*[F.lit(x) for kv in COUNTRY_CODE_FIX.items() for x in kv])

s = (b
     .withColumn("as_of_date", F.to_date(clean("as_of_date"), "MM/dd/yyyy"))
     .withColumn("source_fiscal_year", clean("fiscal_year").cast("int"))
     .withColumn("region_source", clean("region"))
     .withColumn("borrower_country", clean("borrower_country_economy"))
     .withColumn("borrower_country_code_raw", clean("borrower_country_economy_code"))
     .withColumn("project_id", clean("project_id"))
     .withColumn("project_name", clean("project_name"))
     .withColumn("project_global_practice_raw", clean("project_global_practice"))
     .withColumn("procurement_category", clean("procurement_category"))
     .withColumn("procurement_method_raw", F.col("procurement_method"))
     .withColumn("procurement_method", clean("procurement_method"))
     .withColumn("wb_contract_number", clean("wb_contract_number"))
     .withColumn("contract_description_raw", F.col("contract_description"))
     .withColumn("contract_description", clean("contract_description"))
     .withColumn("borrower_contract_reference",
                 null_if_in(clean("borrower_contract_reference_number"), ["N/A", "-", "0"]))
     .withColumn("contract_signing_date", F.to_date(clean("contract_signing_date"), "MM/dd/yyyy"))
     .withColumn("supplier_id", null_if_in(clean("supplier_id"), ["0"]))
     .withColumn("supplier_name", null_if_in(clean("supplier"), ["null"]))
     .withColumn("supplier_country", null_if_in(clean("supplier_country_economy"), ["null"]))
     .withColumn("supplier_country_code", F.when(F.col("supplier_country").isNull(), None)
                 .otherwise(clean("supplier_country_economy_code")))
     .withColumn("amount_usd", clean("supplier_contract_amount_usd").cast(DecimalType(18, 2)))
     .withColumn("review_type", F.coalesce(clean("review_type"), F.lit("Not recorded")))
     .withColumn("source_calendar_year", clean("contract_signed_calendar_year").cast("int"))
     )

s = (s
     .withColumn("borrower_country_code",
                 F.coalesce(F.col("borrower_country_code_raw"), code_fix[F.col("borrower_country")]))
     .withColumn("borrower_type",
                 F.when(F.col("borrower_country_code").isNull() | F.col("borrower_country_code").rlike("^[0-9]"),
                        "Regional / multi-country").otherwise("Country"))
     .withColumn("wb_fiscal_year", F.when(F.month("contract_signing_date") >= 7, F.year("contract_signing_date") + 1)
                 .otherwise(F.year("contract_signing_date")))
     .withColumn("fiscal_quarter", F.concat(F.lit("Q"),
                 (((F.month("contract_signing_date") + 5) % 12) / 3 + 1).cast("int").cast("string")))
     .withColumn("fy_matches_source", F.col("wb_fiscal_year") == F.col("source_fiscal_year"))
     .withColumn("practice_tokens", F.when(F.col("project_global_practice_raw").isNull(), F.array().cast("array<string>"))
                 .otherwise(F.transform(F.split("project_global_practice_raw", ";"), lambda x: F.trim(x))))
     .withColumn("practice_list", F.array_distinct(F.transform("practice_tokens", std_practice)))
     .withColumn("is_individual_consultant", F.col("supplier_id").rlike("^[0-9a-f]{16}$"))
     .withColumn("supplier_origin",
                 F.when(F.col("borrower_type") != "Country", "Not applicable (regional borrower)")
                  .when(F.col("supplier_country").isNull(), "Unknown supplier country")
                  .when(F.col("supplier_country") == "World", "International organization")
                  .when(F.col("supplier_country") == F.col("borrower_country"), "Domestic")
                  .otherwise("Foreign"))
     )

s = (s.join(F.broadcast(region_df), "region_source", "left")
      .join(F.broadcast(method_df), "procurement_method", "left")
      .join(F.broadcast(category_df), "procurement_category", "left"))

# COMMAND ----------

# MAGIC %md ### Deduplicate and flag

# COMMAND ----------

# 1) natural key: one row per contract x supplier (supplier_id may be NULL for 'null' suppliers -> use raw)
s = s.withColumn("_supplier_key", F.coalesce("supplier_id", F.lit("<none>")))
w_nat = W.partitionBy("wb_contract_number", "_supplier_key").orderBy(F.col("as_of_date").desc(), F.col("_ingested_at").desc())
s = s.withColumn("_rn", F.row_number().over(w_nat))
natural_dups = s.filter("_rn > 1").count()
s = s.filter("_rn = 1").drop("_rn")

# 2) probable duplicate entries under different contract numbers
s = s.withColumn("_desc_norm", F.lower(F.coalesce("contract_description", F.lit(""))))
w_prob = W.partitionBy("project_id", "_supplier_key", "amount_usd", "contract_signing_date", "_desc_norm") \
          .orderBy(F.col("wb_contract_number").cast("long"), "wb_contract_number")
s = (s.withColumn("_rk", F.row_number().over(w_prob))
      .withColumn("probable_duplicate_of", F.when(F.col("_rk") > 1, F.first("wb_contract_number").over(w_prob)))
      .withColumn("is_probable_duplicate", F.col("_rk") > 1)
      .drop("_rk", "_desc_norm"))

# 3) joint awards: number of supplier rows on the contract
w_c = W.partitionBy("wb_contract_number")
s = (s.withColumn("contract_supplier_count", F.count(F.lit(1)).over(w_c))
      .withColumn("is_joint_award", F.col("contract_supplier_count") > 1))

# 4) amount outliers within procurement category (log scale, exact percentiles)
logq = (s.filter("amount_usd > 0")
         .groupBy("procurement_category")
         .agg(F.expr("percentile(log10(cast(amount_usd as double)), 0.25)").alias("q1"),
              F.expr("percentile(log10(cast(amount_usd as double)), 0.75)").alias("q3")))
s = (s.join(F.broadcast(logq), "procurement_category", "left")
      .withColumn("_l", F.when(F.col("amount_usd") > 0, F.log10(F.col("amount_usd").cast("double"))))
      .withColumn("is_amount_outlier", F.coalesce(
          (F.col("_l") > F.col("q3") + 3 * (F.col("q3") - F.col("q1"))) |
          (F.col("_l") < F.col("q1") - 3 * (F.col("q3") - F.col("q1"))), F.lit(False)))
      .drop("_l", "q1", "q3", "_supplier_key"))

# COMMAND ----------

silver_cols = [
    "wb_contract_number", "supplier_id", "supplier_name", "is_individual_consultant",
    "supplier_country", "supplier_country_code", "supplier_origin",
    "project_id", "project_name", "practice_list", "project_global_practice_raw",
    "region_code", "region_name", "borrower_country", "borrower_country_code", "borrower_type",
    "procurement_category", "category_code",
    "procurement_method", "method_abbrev", "method_group", "competition_tier", "procurement_method_raw",
    "contract_description", "contract_description_raw", "borrower_contract_reference",
    "contract_signing_date", "wb_fiscal_year", "fiscal_quarter", "source_fiscal_year", "fy_matches_source",
    "source_calendar_year", "as_of_date",
    "amount_usd", "review_type",
    "contract_supplier_count", "is_joint_award", "is_probable_duplicate", "probable_duplicate_of",
    "is_amount_outlier", "_source_file", "_ingested_at",
]
silver = write_table(s.select(*silver_cols), "silver_contract_awards",
                     "Cleaned, typed and standardised contract awards; grain = contract x supplier")

summary = silver.agg(
    F.count("*").alias("rows"),
    F.countDistinct("wb_contract_number").alias("contracts"),
    F.sum("amount_usd").alias("usd"),
    F.sum(F.col("is_probable_duplicate").cast("int")).alias("probable_dup_rows"),
    F.sum(F.when(F.col("is_probable_duplicate"), F.col("amount_usd"))).alias("probable_dup_usd"),
    F.sum(F.col("is_amount_outlier").cast("int")).alias("outlier_rows"),
    F.sum(F.col("method_abbrev").isNull().cast("int")).alias("unmapped_method_rows"),
    F.sum(F.col("region_code").isNull().cast("int")).alias("unmapped_region_rows"),
).first().asDict()
summary.update(bronze_rows=bronze_rows, natural_key_duplicates_removed=natural_dups)
print(summary)
