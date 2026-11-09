# Data profile: Contract Awards in Investment Project Financing (since FY2020)

Source file: `contract_awards_raw.csv`  
As-of date in file: 11/09/2026

## 1. Shape

- Records (CSV rows): **296,826**
- Physical lines in file: 329,154 (difference = header + line breaks embedded inside quoted `Contract Description` values, so the file must be read with a multi-line-aware CSV parser)
- Columns: **21**
- Distinct WB contract numbers: **284,572**
- Distinct projects: 3,162; borrower countries/economies (incl. regional groupings): 159; supplier IDs: 189,874
- Total supplier contract amount: **USD 137,562,056,570**

## 2. Columns

| # | Column | Blank | Literal placeholder values | Distinct | Example |
|---|---|---:|---|---:|---|
| 1 | As of Date | 0 |  | 1 | 11/09/2026 |
| 2 | Fiscal Year | 0 |  | 8 | 2027 |
| 3 | Region | 0 |  | 8 | Latin America and Caribbean |
| 4 | Borrower Country / Economy | 0 |  | 159 | Ecuador |
| 5 | Borrower Country / Economy Code | 10,088 | `NA`: 11 | 147 | EC |
| 6 | Project ID | 0 |  | 3,162 | P181079 |
| 7 | Project Name | 0 |  | 3,155 | Ecuador: Emergency Resilient Reconstruction P |
| 8 | Project Global Practice | 30,942 |  | 242 | Transportation |
| 9 | Procurement Category | 0 |  | 4 | Consultant Services |
| 10 | Procurement Method | 0 |  | 19 | Consultant Qualification Selection |
| 11 | WB Contract Number | 0 |  | 284,572 | 1905624 |
| 12 | Contract Description | 350 |  | 258,506 | Auditoría en Seguridad Vial |
| 13 | Borrower Contract Reference Number | 0 | `N/A`: 1, `-`: 1, `0`: 1 | 242,990 | PRRE-BM-CS-CQS-004-2026 |
| 14 | Contract Signing Date | 0 |  | 2,678 | 10/31/2026 |
| 15 | Supplier ID | 0 | `0`: 7 | 189,874 | 1007704 |
| 16 | Supplier | 0 | `null`: 7 | 125,654 | FRED ENGINEERING S.R.L., |
| 17 | Supplier Country / Economy | 31 | `null`: 622 | 231 | Italy |
| 18 | Supplier Country / Economy Code | 31 | `null`: 622, `NA`: 28 | 231 | IT |
| 19 | Supplier Contract Amount (USD) | 0 |  | 241,077 | 68260.00 |
| 20 | Review type | 179 |  | 3 | Post |
| 21 | Contract signed - Calendar year | 0 |  | 8 | 2026 |

Note: `NA` in the country-code columns is **Namibia**, not a missing value. It must be preserved; readers with default NA handling (pandas, R) turn it into null.

## 3. Dates and fiscal years

- Contract Signing Date: format MM/DD/YYYY, unparseable = 0, min = 2019-07-01, max = 2026-10-31
- World Bank fiscal year runs 1 July to 30 June (FY2025 = 1 Jul 2024 to 30 Jun 2025). Rows where the source `Fiscal Year` differs from the FY derived from the signing date: **0**
- Rows where `Contract signed - Calendar year` differs from the signing-date year: 0

| Fiscal year | Rows | Contracts | USD (bn) |
|---|---:|---:|---:|
| FY2020 | 35,074.0 | 33,556.0 | 15.10 |
| FY2021 | 44,947.0 | 43,113.0 | 19.13 |
| FY2022 | 40,903.0 | 38,724.0 | 19.33 |
| FY2023 | 43,791.0 | 42,249.0 | 17.45 |
| FY2024 | 46,021.0 | 44,449.0 | 20.80 |
| FY2025 | 45,993.0 | 44,304.0 | 21.27 |
| FY2026 | 34,768.0 | 33,229.0 | 19.04 |
| FY2027 | 5,329.0 | 4,948.0 | 5.43 |

FY2027 is partial: it contains contracts signed up to 2026-10-31 only. Recent fiscal years may also be incomplete because awards are entered into STEP after signing (reporting lag), so the latest complete-looking year should be compared with care.

## 4. Duplicates and record grain

- Fully identical rows: 0
- Duplicate (WB Contract Number, Supplier ID) pairs: 0 -> the record grain is **one row per contract x supplier**
- Contracts with more than one supplier row (joint ventures / multiple awardees): 8,933 contracts, 21,187 rows; max suppliers on one contract: 42
  - of these, 7,135 have identical amounts on every member row (equal JV split); 1,798 differ slightly (max relative spread 16.7%, median of non-zero spreads 2.94%), consistent with rounding of the equal split
  - contract-level attributes that vary across a contract's rows: {'Project ID': 0, 'Procurement Method': 0, 'Procurement Category': 0, 'Contract Signing Date': 0, 'Review type': 0}
- **Probable duplicate entries** (different WB contract number but same project, supplier, amount, signing date and whitespace/case-normalised description): **837 rows, USD 110,702,522**
- Wider rule (same project, borrower reference number, supplier, amount and date; description may differ): 1,416 rows, USD 295,232,775. Flagged for review only (some are legitimate separate lots).

## 5. Inconsistent category values

**Procurement Method** (19 raw values):

| Raw value | Rows |
|---|---:|
| `Request for Quotations` | 107,079 |
| `Individual Consultant Selection` | 65,473 |
| `Request for Bids` | 57,152 |
| `Direct Selection` | 35,529 |
| `Consultant Qualification  Selection` | 16,422 |
| `Quality And Cost-Based Selection` | 11,095 |
| `Least Cost Selection` | 1,590 |
| `Quality Based Selection` | 565 |
| `Request for Proposals` | 496 |
| `Community Driven Development` | 484 |
| `UN Agencies (Direct)` | 314 |
| `Fixed Budget Selection` | 230 |
| `Consultant Qualification Selection` | 108 |
| `Force Account` | 95 |
| `E-Auctions` | 76 |
| `Commercial Practices` | 74 |
| `Non-Profit Organizations` | 33 |
| `Public Private Partnership` | 10 |
| `Procurement Agents` | 1 |

- `Consultant Qualification  Selection` (double space, 16,422 rows) and `Consultant Qualification Selection` (108 rows) are the same method.
- The dataset has **no market-approach field** (open international vs. open national vs. limited). `Request for Bids` can be either international or national competition; this cannot be split from this file.

**Procurement Category**: Consultant Services (113,373), Goods (93,090), Works (66,663), Non-consulting Services (23,700)

**Region**: Eastern and Southern Africa (68,848), Western and Central Africa (63,362), South Asia (50,847), Latin America and Caribbean (39,841), East Asia and Pacific (29,097), Europe and Central Asia (28,877), Middle East, North Africa, Afghanistan, and Pakistan (15,655), Other (299)

- Afghanistan and Pakistan are reported under the current region name 'Middle East, North Africa, Afghanistan, and Pakistan' for all years (no historical South Asia mapping).

**Project Global Practice**: 242 distinct raw strings because it is a semicolon-separated multi-value list; blank for 30,942 rows (10.4%). Distinct tokens:

| Token | Rows containing it |
|---|---:|
| `Agriculture` | 111,928 |
| `Industry & Trade/Ser` | 63,371 |
| `Public Admin` | 60,743 |
| `Social Protection` | 54,092 |
| `Education` | 47,519 |
| `Water/Sanit/Waste` | 39,322 |
| `Health` | 38,366 |
| `Info & Communication` | 37,409 |
| `Transportation` | 33,463 |
| `Energy & Extractives` | 16,232 |
| `Financial Sector` | 6,797 |
| `Social Sustain` | 43 |
| `Water, Sanitation` | 16 |
| `Energy and Mineral` | 15 |
| `Industry, Trade` | 13 |
| `Digital Development` | 3 |

Legacy labels (`Water, Sanitation`, `Energy and Mineral`, `Industry, Trade`, `Digital Development`, `Social Sustain`) coexist with the current labels and are mapped in Silver.

**Country fields**

- Borrower country code blank for 10,088 rows: Cote d'Ivoire (5,019), Somalia, Federal Republic of (2,874), Southern Africa (733), Southwest Indian Ocean (319), Latin America and Caribbean (278), DRC - Angola (243), Western Balkans (229), East Asia and Pacific (104), Pacific 1 (95), Horn of Africa (66), Pacific 2 (57), Multi-Regional (41), Europe and Central Asia (30)
  - Cote d'Ivoire and Somalia are real countries with missing codes (their supplier-side codes are CI and SO); the rest are regional / multi-country groupings.
- 25,808 rows have numeric-prefixed codes (e.g. 3W, 3E, 6O) that denote regional programmes, not countries.
- Supplier country is blank for 31 rows and the literal string `null` for 622 rows (USD 1,737,514,734).
- Country names are consistent between borrower and supplier columns (e.g. 'Turkiye', 'Viet Nam'), so the domestic/foreign test is done on names. Some codes are World Bank legacy codes, not ISO (DR Congo = `ZR`, Yemen = `RY`).

**Supplier fields**

- 65,473 rows have a 16-character hashed Supplier ID with supplier name 'INDIVIDUAL CONSULTANT' (all under Individual Consultant Selection): individuals are anonymised and each row gets its own ID (55,531 distinct IDs), so individuals cannot be tracked across contracts.
- Supplier name literal `null`: 7 rows (Supplier ID `0`).
- 7,725 normalised firm names map to more than one Supplier ID (e.g. ERNST YOUNG: 22, KPMG: 22, AJAY KUMAR: 24, RAKESH KUMAR: 27, CFAO MOTORS: 32). Country affiliates legitimately have separate IDs, but this also means supplier concentration measured on Supplier ID understates group-level concentration.

**Text hygiene**

- Procurement Method: untrimmed values 0, values with repeated spaces 16,422, embedded line breaks 0
- Project Name: untrimmed values 0, values with repeated spaces 4,539, embedded line breaks 0
- Supplier: untrimmed values 0, values with repeated spaces 149, embedded line breaks 0
- Contract Description: untrimmed values 34,392, values with repeated spaces 13,966, embedded line breaks 21,251
- Borrower Contract Reference Number: untrimmed values 1,201, values with repeated spaces 677, embedded line breaks 1
- Review type blank: 179 rows

## 6. Amounts and outliers

- `Supplier Contract Amount (USD)` parses as numeric for all rows (unparseable: 0); negative: 0; zero: 9; below USD 10: 509; below USD 1: 212
- Distribution (USD): p1 = 173, p5 = 995, p25 = 7,398, p50 = 33,659, p75 = 132,000, p95 = 1,334,649, p99 = 7,491,716, p99.9 = 46,266,365, max = 553,067,460, mean = 463,443
- Outlier rule (log10 amount outside Q1 - 3*IQR .. Q3 + 3*IQR within each procurement category): **330 rows flagged** (high: 7, low: 323)
- Skew: the largest 1% of rows account for 52.0% of total value. Averages are therefore dominated by a few very large contracts; medians are reported alongside them.
- Ten largest rows. Their descriptions (COVID-19 vaccines, hydropower equipment, HVDC converter station, road packages) are consistent with genuinely large awards, so high outliers are flagged, not removed:

| FY | Borrower | Method | Supplier | USD m |
|---|---|---|---|---:|
| 2024 | Pakistan | Request for Bids | M/S PERVEZ ASSOCIATES & CO | 553.1 |
| 2025 | Tajikistan | Direct Selection | VOITH HYDRO GMBH & CO. KG | 526.3 |
| 2025 | Burkina Faso | Request for Bids | GROUPEMENT VENUS LIVRAISON/COGEA INTERNATIONA | 474.6 |
| 2022 | Argentina | Direct Selection | PFIZER | 472.2 |
| 2026 | Tunisia | Request for Proposals | ORASCOM CONSTRUCTION INDUSTRIES | 437.3 |
| 2026 | Tunisia | Request for Proposals | HITACHI ENERGY SWEDEN AB | 437.3 |
| 2022 | Argentina | Direct Selection | MODERNA SWITZERLAND GMBH | 430.0 |
| 2022 | Lebanon | Direct Selection | WORLD FOOD PROGRAMME (WFP) | 416.9 |
| 2022 | Bangladesh | Direct Selection | China National Biotec Group Company Limited | 390.0 |
| 2021 | Turkiye | Direct Selection | BIONTECH MANUFACTURING GMBH | 389.4 |

## 7. Caveats

Stated for this dataset (apply to every figure):

- Excludes awards to **subcontractors**.
- Excludes **cofinancing**.
- For **joint ventures**, the contract value is split equally across the JV members, so the per-supplier amount is not the member's real share of work. Summing all rows of a contract gives the contract value.

Analyst notes from this profile:

- Source system is STEP (Systematic Tracking of Exchanges in Procurement); recent fiscal years can be incomplete because of data-entry lag.
- Supplier country is the country recorded for the supplier in STEP; it says nothing about where the work is performed or where value is added.
- There is no market-approach (international vs national) field, no number of bids, and no estimated cost, so competition intensity and price efficiency cannot be measured from this file.

