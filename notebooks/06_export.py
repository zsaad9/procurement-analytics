# Databricks notebook source
# MAGIC %md
# MAGIC # 06 · Export gold and indicator tables
# MAGIC
# MAGIC Writes every gold, indicator and DQ table as **Parquet** (zstd-compressed, so every file stays under
# MAGIC GitHub's 25 MB browser-upload limit; for the chatbot / DuckDB) and **CSV** (for Power BI
# MAGIC Desktop's *Get data → Folder/Text*), one folder per table, to the `exports` volume.
# MAGIC Download them from *Catalog → workspace → wb_procurement → Volumes → exports*, or connect Power BI directly
# MAGIC to the Databricks SQL warehouse instead (see `powerbi/README.md`).

# COMMAND ----------

# MAGIC %run ./00_config

# COMMAND ----------

import os, glob, shutil

TABLES = ["fact_contract_awards", "dim_project", "bridge_project_practice", "dim_borrower_country",
          "dim_supplier_country", "dim_supplier", "dim_procurement_method", "dim_procurement_category",
          "dim_fiscal_year", "dim_date", "dq_results",
          "ind_summary_by_fy", "ind_contract_size_by_category", "ind_method_mix", "ind_method_mix_by_category",
          "ind_supplier_origin", "ind_foreign_supplier_countries", "ind_supplier_concentration",
          "ind_top_suppliers", "ind_region", "ind_sector"]


def export(name):
    df = spark.table(T(name)).coalesce(1)
    for fmt in ["parquet", "csv"]:
        tmp = f"{EXPORT_DIR}/_tmp_{name}_{fmt}"
        target = f"{EXPORT_DIR}/{fmt}/{name}.{fmt}"
        w = df.write.mode("overwrite")
        (w.option("header", True).csv(tmp) if fmt == "csv" else w.option("compression", "zstd").parquet(tmp))
        # Spark writes a folder of part files; keep the single part file under a clean name
        if IS_DATABRICKS:
            part = [f.path for f in dbutils.fs.ls(tmp) if f.name.startswith("part-")][0]
            dbutils.fs.mkdirs(f"{EXPORT_DIR}/{fmt}")
            dbutils.fs.cp(part, target)
            dbutils.fs.rm(tmp, True)
        else:
            os.makedirs(f"{EXPORT_DIR}/{fmt}", exist_ok=True)
            part = glob.glob(f"{tmp}/part-*")[0]
            shutil.move(part, target)
            shutil.rmtree(tmp)


for t in TABLES:
    export(t)
    print("exported", t)
