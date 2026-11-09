# data/

* `contract_awards_raw.csv`: **not committed** (about 115 MB, above GitHub's 100 MB limit). Download
  *Contract Awards in Investment Project Financing (since FY 2020)* from World Bank Finances One (DS00005) and save it
  here under this name to run the pipeline locally. In Databricks, upload it to the `raw` volume instead.
* `gold/parquet/`: gold, indicator and data-quality tables exported by `notebooks/06_export.py` from the
  9 Nov 2026 snapshot. Committed so the chatbot, Power BI and docs can be reproduced without running Spark.
* `gold/csv/`: same tables as CSV (git-ignored; regenerate with the pipeline).
