# Databricks notebook source
# MAGIC %md
# MAGIC # 00 · Configuration
# MAGIC Shared settings for the World Bank contract-awards pipeline. Every other notebook starts with `%run ./00_config`.
# MAGIC
# MAGIC **Databricks Free Edition setup (one time)**
# MAGIC 1. Run this notebook once. It creates the schema `workspace.wb_procurement` and the volume `raw`.
# MAGIC 2. In *Catalog → workspace → wb_procurement → Volumes → raw*, click **Upload to this volume** and upload the CSV
# MAGIC    downloaded from Finances One (dataset DS00005). Any file name ending in `.csv` works; the newest is used.
# MAGIC 3. Run `01_bronze_ingest` → `02_silver_transform` → `03_gold_model` → `04_data_quality` → `05_indicators` →
# MAGIC    `06_export` (or run `99_run_all`).
# MAGIC
# MAGIC The same notebooks run locally with PySpark (`python scripts/run_pipeline_local.py`); the branch below
# MAGIC switches catalog/paths and uses Parquet instead of Delta.

# COMMAND ----------

import os

IS_DATABRICKS = "DATABRICKS_RUNTIME_VERSION" in os.environ

CATALOG = "workspace"          # default catalog in Databricks Free Edition
SCHEMA = "wb_procurement"
RAW_VOLUME = "raw"
EXPORT_VOLUME = "exports"

# Fiscal-year window covered by the dataset ("since FY2020" => first possible signing date 1 Jul 2019)
FIRST_VALID_DATE = "2019-07-01"

# Gold fact excludes rows flagged as probable duplicate entries (see 02_silver). Set False to keep them.
EXCLUDE_PROBABLE_DUPLICATES = True

if IS_DATABRICKS:
    spark.sql(f"CREATE SCHEMA IF NOT EXISTS {CATALOG}.{SCHEMA}")
    spark.sql(f"CREATE VOLUME IF NOT EXISTS {CATALOG}.{SCHEMA}.{RAW_VOLUME}")
    spark.sql(f"CREATE VOLUME IF NOT EXISTS {CATALOG}.{SCHEMA}.{EXPORT_VOLUME}")
    RAW_DIR = f"/Volumes/{CATALOG}/{SCHEMA}/{RAW_VOLUME}"
    EXPORT_DIR = f"/Volumes/{CATALOG}/{SCHEMA}/{EXPORT_VOLUME}"
    _csvs = sorted(f.path for f in dbutils.fs.ls(RAW_DIR) if f.path.lower().endswith(".csv"))
    RAW_PATH = _csvs[-1] if _csvs else None
    TABLE_FORMAT = "delta"

    def T(name: str) -> str:
        return f"{CATALOG}.{SCHEMA}.{name}"
else:
    RAW_PATH = os.environ.get("WB_RAW_PATH", "data/contract_awards_raw.csv")
    EXPORT_DIR = os.environ.get("WB_EXPORT_DIR", "data/gold")
    TABLE_FORMAT = "parquet"
    spark.sql(f"CREATE DATABASE IF NOT EXISTS {SCHEMA}")

    def T(name: str) -> str:
        return f"{SCHEMA}.{name}"


def write_table(df, name: str, comment: str = None):
    """Overwrite a managed table and (on Databricks) attach a table comment."""
    (df.write.mode("overwrite").format(TABLE_FORMAT)
       .option("overwriteSchema", "true").saveAsTable(T(name)))
    if comment and IS_DATABRICKS:
        spark.sql(f"COMMENT ON TABLE {T(name)} IS '{comment.replace(chr(39), '')}'")
    return spark.table(T(name))


print(f"IS_DATABRICKS={IS_DATABRICKS}  RAW_PATH={RAW_PATH}  target={T('<table>')}  format={TABLE_FORMAT}")
