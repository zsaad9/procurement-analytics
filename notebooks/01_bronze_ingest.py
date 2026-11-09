# Databricks notebook source
# MAGIC %md
# MAGIC # 01 · Bronze: ingest the raw CSV as-is
# MAGIC
# MAGIC * Every column is read as **string**: no type inference, no trimming, no value changes.
# MAGIC * The file has line breaks inside quoted `Contract Description` values and doubled quotes (`""`) as the
# MAGIC   escape character, so it is read with `multiLine=true` and `escape='"'`.
# MAGIC * Column names are converted to snake_case because Delta does not allow spaces, `/` or `(` in column names.
# MAGIC   The original header is kept in the column comment / `bronze_column_map` table.
# MAGIC * Only reader convention applied: empty fields become `NULL`. Literal strings such as `null` or the Namibia
# MAGIC   code `NA` are preserved untouched (Spark's default `nullValue` is the empty string).
# MAGIC * Lineage columns: `_source_file`, `_ingested_at`.

# COMMAND ----------

# MAGIC %run ./00_config

# COMMAND ----------

import re
from pyspark.sql import functions as F

assert RAW_PATH, "No CSV found. Upload the Finances One CSV to the raw volume first (see 00_config)."


def snake(col: str) -> str:
    col = col.replace("﻿", "").strip().lower()
    col = col.replace("(usd)", "usd").replace("/", " ").replace("-", " ")
    col = re.sub(r"[^a-z0-9]+", "_", col)
    return col.strip("_")


raw = (spark.read
       .option("header", True)
       .option("multiLine", True)
       .option("escape", '"')
       .option("quote", '"')
       .option("encoding", "UTF-8")
       .option("inferSchema", False)
       .option("mode", "PERMISSIVE")
       .option("columnNameOfCorruptRecord", "_corrupt_record")
       .csv(RAW_PATH))

column_map = [(c, snake(c)) for c in raw.columns]
bronze = raw.select(
    *[F.col(f"`{orig}`").alias(new) for orig, new in column_map],
    F.col("_metadata.file_path").alias("_source_file"),
    F.current_timestamp().alias("_ingested_at"),
)
display_cols = [new for _, new in column_map]
print(column_map)

# COMMAND ----------

bronze_tbl = write_table(bronze, "bronze_contract_awards",
                         "Raw World Bank IPF contract awards (Finances One DS00005), all columns as string")
write_table(spark.createDataFrame(column_map, "source_column string, bronze_column string"), "bronze_column_map")

n = bronze_tbl.count()
print(f"Bronze rows written: {n:,}  columns: {len(display_cols)}")
if "_corrupt_record" in bronze_tbl.columns:
    print("Corrupt records:", bronze_tbl.filter("_corrupt_record IS NOT NULL").count())
