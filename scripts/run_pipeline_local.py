"""
Run the Databricks notebooks locally with PySpark (no Databricks needed) to test the pipeline.

    pip install pyspark==4.0.1
    python scripts/run_pipeline_local.py                 # all stages
    python scripts/run_pipeline_local.py 02 03           # selected stages (needs earlier stages in the same run)

Each notebook is split on '# COMMAND ----------'; markdown cells are skipped; '%run ./00_config' executes the config
notebook in the same namespace, mimicking Databricks. Tables are stored as Parquet under ./spark-warehouse and the
exports land in ./data/gold. Note: the local catalog is in-memory, so run all stages in one invocation.
"""
import os
import re
import sys
import time
from pathlib import Path

from pyspark.sql import SparkSession

ROOT = Path(__file__).resolve().parents[1]
NB = ROOT / "notebooks"
os.chdir(ROOT)
STAGES = ["01_bronze_ingest", "02_silver_transform", "03_gold_model", "04_data_quality", "05_indicators", "06_export"]

spark = (SparkSession.builder.appName("wb-procurement-local").master("local[*]")
         .config("spark.sql.session.timeZone", "UTC")
         .config("spark.driver.memory", os.environ.get("SPARK_DRIVER_MEMORY", "6g"))
         .config("spark.sql.shuffle.partitions", "16")
         .config("spark.ui.enabled", "false")
         .config("spark.ui.showConsoleProgress", "false")
         .getOrCreate())
spark.sparkContext.setLogLevel("ERROR")


def cells(path: Path):
    for cell in path.read_text().split("# COMMAND ----------"):
        lines = [l for l in cell.splitlines() if l.strip() != "# Databricks notebook source"]
        magic = [l for l in lines if l.startswith("# MAGIC")]
        if magic:
            first = magic[0].replace("# MAGIC", "").strip()
            if first.startswith("%run"):
                yield ("run", first.split()[1])
            continue  # %md and other magics are skipped
        yield ("py", "\n".join(lines))


def run_notebook(name: str, ns: dict):
    for kind, body in cells(NB / f"{name}.py"):
        if kind == "run":
            run_notebook(Path(body).name, ns)
        elif body.strip():
            exec(compile(body, f"{name}.py", "exec"), ns)


selected = [s for s in STAGES if not sys.argv[1:] or any(s.startswith(a) for a in sys.argv[1:])]
ns = {"spark": spark, "display": lambda df: df.show(20, truncate=False)}
for stage in selected:
    t = time.time()
    print(f"\n========== {stage} ==========")
    run_notebook(stage, ns)
    print(f"---------- {stage} done in {time.time() - t:.0f}s")
