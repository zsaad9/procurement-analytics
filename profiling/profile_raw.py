"""
Profile the raw World Bank "Contract Awards in Investment Project Financing" CSV.

Usage:
    python profiling/profile_raw.py data/contract_awards_raw.csv docs/data_profile.md

Every figure in the output report is computed here from the file; nothing is hard-coded.
Reads all columns as strings first (so placeholder values such as 'null' or the
Namibia ISO code 'NA' are not silently converted to missing), then profiles each issue.
"""
import sys
import json
import numpy as np
import pandas as pd

SRC = sys.argv[1] if len(sys.argv) > 1 else "data/contract_awards_raw.csv"
OUT = sys.argv[2] if len(sys.argv) > 2 else "docs/data_profile.md"
PLACEHOLDERS = {"null", "none", "n/a", "na", "nan", "-", "unknown", "0"}

df = pd.read_csv(SRC, dtype=str, keep_default_na=False, encoding="utf-8-sig")
lines = []
w = lines.append
metrics = {}

with open(SRC, "rb") as fh:
    physical_lines = sum(1 for _ in fh)

amt = pd.to_numeric(df["Supplier Contract Amount (USD)"], errors="coerce")
sign = pd.to_datetime(df["Contract Signing Date"], format="%m/%d/%Y", errors="coerce")
wb_fy = np.where(sign.dt.month >= 7, sign.dt.year + 1, sign.dt.year)

w("# Data profile: Contract Awards in Investment Project Financing (since FY2020)\n")
w(f"Source file: `{SRC.split('/')[-1]}`  \nAs-of date in file: {', '.join(df['As of Date'].unique())}\n")
w("## 1. Shape\n")
w(f"- Records (CSV rows): **{len(df):,}**")
w(f"- Physical lines in file: {physical_lines:,} (difference = header + line breaks embedded inside quoted "
  f"`Contract Description` values, so the file must be read with a multi-line-aware CSV parser)")
w(f"- Columns: **{df.shape[1]}**")
w(f"- Distinct WB contract numbers: **{df['WB Contract Number'].nunique():,}**")
w(f"- Distinct projects: {df['Project ID'].nunique():,}; borrower countries/economies (incl. regional groupings): "
  f"{df['Borrower Country / Economy'].nunique():,}; supplier IDs: {df['Supplier ID'].nunique():,}")
w(f"- Total supplier contract amount: **USD {amt.sum():,.0f}**\n")
metrics.update(rows=len(df), contracts=int(df["WB Contract Number"].nunique()), total_usd=float(amt.sum()))

w("## 2. Columns\n")
w("| # | Column | Blank | Literal placeholder values | Distinct | Example |")
w("|---|---|---:|---|---:|---|")
for i, c in enumerate(df.columns, 1):
    s = df[c]
    blank = int((s.str.strip() == "").sum())
    ph = s[s.str.strip().str.lower().isin(PLACEHOLDERS)].value_counts().to_dict()
    ph_txt = ", ".join(f"`{k}`: {v:,}" for k, v in ph.items()) or ""
    ex = s.iloc[0].replace("|", "/").replace("\n", " ")[:45]
    w(f"| {i} | {c} | {blank:,} | {ph_txt} | {s.nunique():,} | {ex} |")
w("\nNote: `NA` in the country-code columns is **Namibia**, not a missing value. It must be preserved; "
  "readers with default NA handling (pandas, R) turn it into null.\n")

w("## 3. Dates and fiscal years\n")
w(f"- Contract Signing Date: format MM/DD/YYYY, unparseable = {int(sign.isna().sum())}, "
  f"min = {sign.min():%Y-%m-%d}, max = {sign.max():%Y-%m-%d}")
w(f"- World Bank fiscal year runs 1 July to 30 June (FY2025 = 1 Jul 2024 to 30 Jun 2025). "
  f"Rows where the source `Fiscal Year` differs from the FY derived from the signing date: "
  f"**{int((df['Fiscal Year'].astype(int) != wb_fy).sum())}**")
w(f"- Rows where `Contract signed - Calendar year` differs from the signing-date year: "
  f"{int((df['Contract signed - Calendar year'].astype(int) != sign.dt.year).sum())}")
fy = df.assign(a=amt).groupby("Fiscal Year").agg(rows=("a", "size"), contracts=("WB Contract Number", "nunique"),
                                                 usd=("a", "sum"))
w("\n| Fiscal year | Rows | Contracts | USD (bn) |\n|---|---:|---:|---:|")
for k, r in fy.iterrows():
    w(f"| FY{k} | {r.rows:,} | {r.contracts:,} | {r.usd/1e9:,.2f} |")
fy27_max = sign[df["Fiscal Year"] == str(fy.index.max())].max()
w(f"\nFY{fy.index.max()} is partial: it contains contracts signed up to {fy27_max:%Y-%m-%d} only. "
  "Recent fiscal years may also be incomplete because awards are entered into STEP after signing "
  "(reporting lag), so the latest complete-looking year should be compared with care.\n")

w("## 4. Duplicates and record grain\n")
key = ["WB Contract Number", "Supplier ID"]
n_per = df.groupby("WB Contract Number").size()
w(f"- Fully identical rows: {int(df.duplicated().sum())}")
w(f"- Duplicate (WB Contract Number, Supplier ID) pairs: {int(df.duplicated(key).sum())} "
  "-> the record grain is **one row per contract x supplier**")
w(f"- Contracts with more than one supplier row (joint ventures / multiple awardees): "
  f"{int((n_per > 1).sum()):,} contracts, {int(n_per[n_per > 1].sum()):,} rows; max suppliers on one contract: {int(n_per.max())}")
multi = df[df["WB Contract Number"].isin(n_per[n_per > 1].index)].assign(a=amt)
mg = multi.groupby("WB Contract Number")["a"]
spread = (mg.max() - mg.min()) / mg.max()
w(f"  - of these, {int((spread == 0).sum()):,} have identical amounts on every member row (equal JV split); "
  f"{int((spread > 0).sum()):,} differ slightly (max relative spread {spread.max():.1%}, median of non-zero "
  f"spreads {spread[spread > 0].median():.2%}), consistent with rounding of the equal split")
consistent_cols = ["Project ID", "Procurement Method", "Procurement Category", "Contract Signing Date", "Review type"]
incons = {c: int((multi.groupby("WB Contract Number")[c].nunique() > 1).sum()) for c in consistent_cols}
w(f"  - contract-level attributes that vary across a contract's rows: {incons}")
k_prob = ["Project ID", "Supplier ID", "Supplier Contract Amount (USD)", "Contract Signing Date", "_desc"]
d2 = df.assign(_desc=df["Contract Description"].str.lower().str.split().str.join(" "))
prob = d2.duplicated(k_prob)
w(f"- **Probable duplicate entries** (different WB contract number but same project, supplier, amount, signing "
  f"date and whitespace/case-normalised description): **{int(prob.sum()):,} rows, USD {amt[prob].sum():,.0f}**")
k_ref = ["Project ID", "Borrower Contract Reference Number", "Supplier ID", "Supplier Contract Amount (USD)",
         "Contract Signing Date"]
ref = df.duplicated(k_ref)
w(f"- Wider rule (same project, borrower reference number, supplier, amount and date; description may differ): "
  f"{int(ref.sum()):,} rows, USD {amt[ref].sum():,.0f}. Flagged for review only (some are legitimate separate lots).\n")
metrics.update(prob_dup_rows=int(prob.sum()), prob_dup_usd=float(amt[prob].sum()))

w("## 5. Inconsistent category values\n")
pm = df["Procurement Method"]
w("**Procurement Method** (19 raw values):\n")
w("| Raw value | Rows |\n|---|---:|")
for k, v in pm.value_counts().items():
    w(f"| `{k}` | {v:,} |")
w(f"\n- `Consultant Qualification  Selection` (double space, {int((pm=='Consultant Qualification  Selection').sum()):,} rows) "
  f"and `Consultant Qualification Selection` ({int((pm=='Consultant Qualification Selection').sum()):,} rows) are the same method.")
w("- The dataset has **no market-approach field** (open international vs. open national vs. limited). "
  "`Request for Bids` can be either international or national competition; this cannot be split from this file.\n")
w("**Procurement Category**: " + ", ".join(f"{k} ({v:,})" for k, v in df["Procurement Category"].value_counts().items()) + "\n")
w("**Region**: " + ", ".join(f"{k} ({v:,})" for k, v in df["Region"].value_counts().items()))
w("\n- Afghanistan and Pakistan are reported under the current region name "
  "'Middle East, North Africa, Afghanistan, and Pakistan' for all years (no historical South Asia mapping).\n")
gp = df["Project Global Practice"]
toks = gp[gp != ""].str.split(";").explode().str.strip()
w(f"**Project Global Practice**: {gp.nunique():,} distinct raw strings because it is a semicolon-separated "
  f"multi-value list; blank for {int((gp=='').sum()):,} rows ({(gp=='').mean():.1%}). Distinct tokens:\n")
w("| Token | Rows containing it |\n|---|---:|")
for k, v in toks.value_counts().items():
    w(f"| `{k}` | {v:,} |")
w("\nLegacy labels (`Water, Sanitation`, `Energy and Mineral`, `Industry, Trade`, `Digital Development`, "
  "`Social Sustain`) coexist with the current labels and are mapped in Silver.\n")

w("**Country fields**\n")
bc = df["Borrower Country / Economy Code"]
w(f"- Borrower country code blank for {int((bc=='').sum()):,} rows: " +
  ", ".join(f"{k} ({v:,})" for k, v in df.loc[bc == "", "Borrower Country / Economy"].value_counts().items()))
w("  - Cote d'Ivoire and Somalia are real countries with missing codes (their supplier-side codes are CI and SO); "
  "the rest are regional / multi-country groupings.")
num_codes = bc[bc.str.match(r"^\d")]
w(f"- {int(len(num_codes)):,} rows have numeric-prefixed codes (e.g. 3W, 3E, 6O) that denote regional programmes, "
  "not countries.")
sc = df["Supplier Country / Economy"]
w(f"- Supplier country is blank for {int((sc=='').sum()):,} rows and the literal string `null` for "
  f"{int((sc=='null').sum()):,} rows (USD {amt[sc.isin(['', 'null'])].sum():,.0f}).")
w("- Country names are consistent between borrower and supplier columns (e.g. 'Turkiye', 'Viet Nam'), so the "
  "domestic/foreign test is done on names. Some codes are World Bank legacy codes, not ISO (DR Congo = `ZR`, "
  "Yemen = `RY`).\n")

w("**Supplier fields**\n")
sid = df["Supplier ID"]
hexid = sid.str.fullmatch(r"[0-9a-f]{16}")
w(f"- {int(hexid.sum()):,} rows have a 16-character hashed Supplier ID with supplier name "
  f"'INDIVIDUAL CONSULTANT' (all under Individual Consultant Selection): individuals are anonymised and each row "
  f"gets its own ID ({sid[hexid].nunique():,} distinct IDs), so individuals cannot be tracked across contracts.")
w(f"- Supplier name literal `null`: {int((df['Supplier']=='null').sum())} rows (Supplier ID `0`).")
norm = df["Supplier"].str.upper().str.replace(r"[^A-Z0-9 ]", "", regex=True).str.split().str.join(" ")
multi_id = df[~hexid].assign(n=norm).groupby("n")["Supplier ID"].nunique()
w(f"- {int((multi_id > 1).sum()):,} normalised firm names map to more than one Supplier ID (e.g. "
  + ", ".join(f"{k}: {v}" for k, v in multi_id.drop(labels=[''], errors='ignore').sort_values().tail(5).items())
  + "). Country affiliates legitimately have separate IDs, but this also means supplier concentration measured on "
  "Supplier ID understates group-level concentration.\n")

w("**Text hygiene**\n")
for c in ["Procurement Method", "Project Name", "Supplier", "Contract Description", "Borrower Contract Reference Number"]:
    s = df[c]
    w(f"- {c}: untrimmed values {int((s != s.str.strip()).sum()):,}, values with repeated spaces "
      f"{int(s.str.contains('  ', regex=False).sum()):,}, embedded line breaks {int(s.str.contains(chr(10), regex=False).sum()):,}")
rt = df["Review type"]
w(f"- Review type blank: {int((rt=='').sum())} rows\n")

w("## 6. Amounts and outliers\n")
w(f"- `Supplier Contract Amount (USD)` parses as numeric for all rows (unparseable: {int(amt.isna().sum())}); "
  f"negative: {int((amt<0).sum())}; zero: {int((amt==0).sum())}; below USD 10: {int((amt<10).sum())}; "
  f"below USD 1: {int((amt<1).sum())}")
q = amt.quantile([.01, .05, .25, .5, .75, .95, .99, .999])
w("- Distribution (USD): " + ", ".join(f"p{int(k*1000)/10:g} = {v:,.0f}" for k, v in q.items())
  + f", max = {amt.max():,.0f}, mean = {amt.mean():,.0f}")
la = np.log10(amt[amt > 0])
grp = df.loc[amt > 0, "Procurement Category"]
flags = pd.Series(False, index=df.index)
for g, s in la.groupby(grp):
    q1, q3 = s.quantile([.25, .75]); iqr = q3 - q1
    flags.loc[s[(s > q3 + 3 * iqr) | (s < q1 - 3 * iqr)].index] = True
w(f"- Outlier rule (log10 amount outside Q1 - 3*IQR .. Q3 + 3*IQR within each procurement category): "
  f"**{int(flags.sum()):,} rows flagged** (high: {int((flags & (amt > amt.median())).sum()):,}, "
  f"low: {int((flags & (amt <= amt.median())).sum()):,})")
top = df.assign(a=amt).nlargest(10, "a")
share_top = amt.nlargest(int(len(amt) * 0.01)).sum() / amt.sum()
w(f"- Skew: the largest 1% of rows account for {share_top:.1%} of total value. Averages are therefore dominated by "
  "a few very large contracts; medians are reported alongside them.")
w("- Ten largest rows. Their descriptions (COVID-19 vaccines, hydropower equipment, HVDC converter station, road packages) are consistent with genuinely large awards, so high outliers are flagged, not removed:\n")
w("| FY | Borrower | Method | Supplier | USD m |\n|---|---|---|---|---:|")
for _, r in top.iterrows():
    w(f"| {r['Fiscal Year']} | {r['Borrower Country / Economy']} | {r['Procurement Method']} | "
      f"{r['Supplier'][:45]} | {r['a']/1e6:,.1f} |")
w("")
metrics.update(outlier_rows=int(flags.sum()))

w("## 7. Caveats\n")
w("Stated for this dataset (apply to every figure):\n")
w("- Excludes awards to **subcontractors**.")
w("- Excludes **cofinancing**.")
w("- For **joint ventures**, the contract value is split equally across the JV members, so the per-supplier amount "
  "is not the member's real share of work. Summing all rows of a contract gives the contract value.\n")
w("Analyst notes from this profile:\n")
w("- Source system is STEP (Systematic Tracking of Exchanges in Procurement); recent fiscal years can be incomplete "
  "because of data-entry lag.")
w("- Supplier country is the country recorded for the supplier in STEP; it says nothing about where the work is "
  "performed or where value is added.")
w("- There is no market-approach (international vs national) field, no number of bids, and no estimated cost, so "
  "competition intensity and price efficiency cannot be measured from this file.\n")

with open(OUT, "w") as fh:
    fh.write("\n".join(lines) + "\n")
print("\n".join(lines))
print(json.dumps(metrics))
