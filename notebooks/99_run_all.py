# Databricks notebook source
# MAGIC %md
# MAGIC # 99 · Run the full pipeline
# MAGIC Runs every stage in order. Stops at the first failure (including a failed critical data-quality check).
# MAGIC To schedule it, create a Databricks **Job** with this notebook as the single task.

# COMMAND ----------

STAGES = ["01_bronze_ingest", "02_silver_transform", "03_gold_model", "04_data_quality", "05_indicators", "06_export"]
for nb in STAGES:
    print(f"▶ {nb}")
    dbutils.notebook.run(f"./{nb}", 3600)
print("Pipeline finished")
