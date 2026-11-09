# Databricks notebook source
# MAGIC %md
# MAGIC # 03 · Gold: star schema for analysis and Power BI
# MAGIC
# MAGIC ```
# MAGIC                    dim_fiscal_year ── dim_date
# MAGIC                           │
# MAGIC dim_project ─┐            │            ┌─ dim_procurement_method
# MAGIC (bridge_     ├── fact_contract_awards ─┼─ dim_procurement_category
# MAGIC  project_    │  (contract x supplier)  ├─ dim_supplier
# MAGIC  practice)   │                         └─ dim_supplier_country
# MAGIC dim_borrower_country (incl. region) ─┘
# MAGIC ```
# MAGIC * **Grain of the fact**: one row per contract × supplier (joint-venture members have one row each, value split
# MAGIC   equally by the publisher). Contract counts must use `COUNT(DISTINCT wb_contract_number)`.
# MAGIC * Rows flagged `is_probable_duplicate` in Silver are excluded when `EXCLUDE_PROBABLE_DUPLICATES = True`.
# MAGIC * Keys are readable natural codes (e.g. `RFB`, `KE`, `FY2025`) so that SQL written by people and by the
# MAGIC   chatbot stays legible.
# MAGIC * `vw_awards` is a flattened view (fact + all dimensions) used by the chatbot and ad-hoc SQL.

# COMMAND ----------

# MAGIC %run ./00_config

# COMMAND ----------

from pyspark.sql import functions as F, Window as W

silver = spark.table(T("silver_contract_awards"))
base = silver.filter(~F.col("is_probable_duplicate")) if EXCLUDE_PROBABLE_DUPLICATES else silver
as_of = silver.agg(F.max("as_of_date")).first()[0]

slug = lambda c: F.upper(F.regexp_replace(F.col(c), r"[^A-Za-z0-9]+", "-"))
base = (base
        .withColumn("borrower_country_key", F.coalesce(F.col("borrower_country_code"), F.concat(F.lit("X-"), slug("borrower_country"))))
        .withColumn("supplier_country_key", F.coalesce(F.col("supplier_country_code"), F.lit("UNK")))
        .withColumn("supplier_key", F.coalesce(F.col("supplier_id"), F.lit("UNKNOWN"))))

def mode_of(df, key, col, alias):
    """most frequent non-null value of `col` per `key` (ties broken alphabetically)"""
    w = W.partitionBy(key).orderBy(F.col("n").desc(), F.col(col))
    return (df.filter(F.col(col).isNotNull()).groupBy(key, col).agg(F.count("*").alias("n"))
              .withColumn("r", F.row_number().over(w)).filter("r = 1").select(key, F.col(col).alias(alias)))

# COMMAND ----------

# MAGIC %md ### Dimensions

# COMMAND ----------

# dim_fiscal_year
fy = (base.groupBy(F.col("wb_fiscal_year").alias("fiscal_year"))
          .agg(F.min("contract_signing_date").alias("first_signing_date"),
               F.max("contract_signing_date").alias("last_signing_date"))
          .withColumn("fy_label", F.concat(F.lit("FY"), F.col("fiscal_year")))
          .withColumn("fy_start_date", F.make_date(F.col("fiscal_year") - 1, F.lit(7), F.lit(1)))
          .withColumn("fy_end_date", F.make_date(F.col("fiscal_year"), F.lit(6), F.lit(30)))
          .withColumn("is_complete_fy", F.col("fy_end_date") < F.lit(as_of))
          .withColumn("months_covered", F.when(F.col("is_complete_fy"), 12)
                      .otherwise(F.months_between(F.last_day("last_signing_date"), F.col("fy_start_date")).cast("int") + 1))
          .select("fiscal_year", "fy_label", "fy_start_date", "fy_end_date", "is_complete_fy", "months_covered",
                  "first_signing_date", "last_signing_date"))
write_table(fy, "dim_fiscal_year", "World Bank fiscal years (1 Jul - 30 Jun) present in the data")

# dim_date (daily, FY attributes for time intelligence)
dmin, dmax = base.agg(F.min("contract_signing_date"), F.max("contract_signing_date")).first()
dates = (spark.sql(f"SELECT explode(sequence(to_date('{FIRST_VALID_DATE}'), to_date('{max(dmax, as_of)}'), interval 1 day)) AS date")
         .withColumn("date_key", F.date_format("date", "yyyyMMdd").cast("int"))
         .withColumn("calendar_year", F.year("date"))
         .withColumn("month_number", F.month("date"))
         .withColumn("month_name", F.date_format("date", "MMM"))
         .withColumn("fiscal_year", F.when(F.month("date") >= 7, F.year("date") + 1).otherwise(F.year("date")))
         .withColumn("fiscal_month_number", (F.month("date") + 5) % 12 + 1)
         .withColumn("fiscal_quarter", F.concat(F.lit("Q"), (((F.month("date") + 5) % 12) / 3 + 1).cast("int").cast("string")))
         .withColumn("fy_month_label", F.concat(F.lit("FY"), F.col("fiscal_year"), F.lit("-"), F.lpad(F.col("fiscal_month_number").cast("string"), 2, "0"))))
write_table(dates.select("date_key", "date", "calendar_year", "month_number", "month_name", "fiscal_year",
                         "fiscal_month_number", "fiscal_quarter", "fy_month_label"), "dim_date")

# dim_borrower_country (country / regional grouping, with region attributes)
dim_country = (base.groupBy("borrower_country_key")
               .agg(F.first("borrower_country", True).alias("borrower_country"),
                    F.first("borrower_country_code", True).alias("borrower_country_code"),
                    F.first("borrower_type", True).alias("borrower_type"),
                    F.first("region_code", True).alias("region_code"),
                    F.first("region_name", True).alias("region_name"),
                    F.countDistinct("region_code").alias("_n_regions")))
assert dim_country.filter("_n_regions > 1").count() == 0, "a borrower maps to more than one region"
write_table(dim_country.drop("_n_regions"), "dim_borrower_country", "Borrower country or regional grouping with WB region")

# dim_supplier_country
dim_sc = (base.groupBy("supplier_country_key")
          .agg(F.coalesce(F.first("supplier_country", True), F.lit("Unknown")).alias("supplier_country"),
               F.first("supplier_country_code", True).alias("supplier_country_code"))
          .withColumn("is_unknown", F.col("supplier_country_key") == "UNK"))
write_table(dim_sc, "dim_supplier_country", "Country/economy of registration of the supplier as recorded in STEP")

# dim_procurement_method
dim_method = (spark.table(T("ref_procurement_method"))
              .withColumnRenamed("method_abbrev", "method_key")
              .withColumnRenamed("procurement_method", "method_name")
              .withColumn("is_open_competitive", F.col("competition_tier") == "Open competitive")
              .withColumn("is_direct", F.col("competition_tier") == "Direct (non-competitive)")
              .withColumn("tier_sort", F.when(F.col("competition_tier") == "Open competitive", 1)
                          .when(F.col("competition_tier") == "Limited competitive", 2)
                          .when(F.col("competition_tier").startswith("Individual"), 3)
                          .when(F.col("competition_tier").startswith("Direct"), 4).otherwise(5))
              .select("method_key", "method_name", "method_group", "competition_tier", "tier_sort",
                      "is_open_competitive", "is_direct"))
write_table(dim_method, "dim_procurement_method")

# dim_procurement_category
write_table(spark.table(T("ref_procurement_category"))
            .select(F.col("category_code").alias("category_key"), F.col("procurement_category").alias("category_name")),
            "dim_procurement_category")

# dim_supplier
sup_name = mode_of(base, "supplier_key", "supplier_name", "supplier_name")
sup_ctry = mode_of(base.filter(F.col("supplier_country_key") != "UNK"), "supplier_key", "supplier_country_key", "supplier_country_key")
dim_sup = (base.groupBy("supplier_key").agg(F.max(F.col("is_individual_consultant").cast("int")).cast("boolean").alias("is_individual_consultant"))
           .join(sup_name, "supplier_key", "left").join(sup_ctry, "supplier_key", "left")
           .withColumn("supplier_name", F.when(F.col("is_individual_consultant"), F.lit("Individual consultant (anonymised)"))
                       .otherwise(F.coalesce("supplier_name", F.lit("Unknown supplier"))))
           .withColumn("supplier_country_key", F.coalesce("supplier_country_key", F.lit("UNK"))))
write_table(dim_sup, "dim_supplier", "Supplier (STEP Supplier ID). Individuals are anonymised: one ID per award")

# dim_project + bridge_project_practice
proj = (base.groupBy("project_id")
        .agg(F.first("project_name", True).alias("project_name"),
             F.first("borrower_country_key", True).alias("borrower_country_key"),
             F.first("region_code", True).alias("region_code"),
             F.first("practice_list", True).alias("practice_list")))
proj = (proj
        .withColumn("practice_count", F.size("practice_list"))
        .withColumn("practice_first_listed", F.when(F.size("practice_list") > 0, F.element_at("practice_list", 1))
                    .otherwise(F.lit("Not specified")))
        .withColumn("practices", F.when(F.size("practice_list") > 0, F.array_join("practice_list", "; "))
                    .otherwise(F.lit("Not specified"))))
write_table(proj.drop("practice_list"), "dim_project", "IPF project with borrower, region and global practice(s)")
bridge = (proj.select("project_id", F.when(F.size("practice_list") > 0, F.col("practice_list"))
                      .otherwise(F.array(F.lit("Not specified"))).alias("pl"))
          .select("project_id", F.explode("pl").alias("global_practice"),
                  (F.lit(1.0) / F.size("pl")).alias("allocation_weight")))
write_table(bridge, "bridge_project_practice",
            "Project to global practice; allocation_weight = 1/number of practices (equal split, sums to 1 per project)")

# COMMAND ----------

# MAGIC %md ### Fact

# COMMAND ----------

fact = base.select(
    F.concat_ws("-", "wb_contract_number", "supplier_key").alias("award_line_id"),
    "wb_contract_number",
    "project_id",
    "borrower_country_key",
    "supplier_key",
    "supplier_country_key",
    F.col("method_abbrev").alias("method_key"),
    F.col("category_code").alias("category_key"),
    F.col("wb_fiscal_year").alias("fiscal_year"),
    F.date_format("contract_signing_date", "yyyyMMdd").cast("int").alias("signing_date_key"),
    "contract_signing_date",
    "fiscal_quarter",
    "contract_description",
    "review_type",
    "supplier_origin",
    "amount_usd",
    "contract_supplier_count",
    "is_joint_award",
    "is_individual_consultant",
    "is_amount_outlier",
)
fact_tbl = write_table(fact, "fact_contract_awards",
                       "Contract award lines (contract x supplier), USD; probable duplicates excluded")

# COMMAND ----------

# MAGIC %md ### Flattened view for SQL / chatbot

# COMMAND ----------

VW_AWARDS_SQL = f"""
CREATE OR REPLACE VIEW {T('vw_awards')} AS
SELECT f.award_line_id, f.wb_contract_number, f.fiscal_year, y.is_complete_fy, f.contract_signing_date,
       f.fiscal_quarter, f.contract_description, f.amount_usd, f.contract_supplier_count, f.is_joint_award, f.is_amount_outlier,
       f.review_type, f.supplier_origin,
       p.project_id, p.project_name, p.practices, p.practice_first_listed,
       c.borrower_country, c.borrower_country_code, c.borrower_type, c.region_code, c.region_name,
       m.method_key, m.method_name, m.method_group, m.competition_tier, m.is_open_competitive, m.is_direct,
       k.category_name AS procurement_category,
       s.supplier_key, s.supplier_name, s.is_individual_consultant,
       sc.supplier_country, sc.supplier_country_code
FROM {T('fact_contract_awards')} f
JOIN {T('dim_project')} p              ON f.project_id = p.project_id
JOIN {T('dim_borrower_country')} c     ON f.borrower_country_key = c.borrower_country_key
JOIN {T('dim_procurement_method')} m   ON f.method_key = m.method_key
JOIN {T('dim_procurement_category')} k ON f.category_key = k.category_key
JOIN {T('dim_supplier')} s             ON f.supplier_key = s.supplier_key
JOIN {T('dim_supplier_country')} sc    ON f.supplier_country_key = sc.supplier_country_key
JOIN {T('dim_fiscal_year')} y          ON f.fiscal_year = y.fiscal_year
"""
spark.sql(VW_AWARDS_SQL)

for t in ["fact_contract_awards", "dim_project", "bridge_project_practice", "dim_borrower_country",
          "dim_supplier_country", "dim_supplier", "dim_procurement_method", "dim_procurement_category",
          "dim_fiscal_year", "dim_date", "vw_awards"]:
    print(f"{t:28} {spark.table(T(t)).count():>9,}")
