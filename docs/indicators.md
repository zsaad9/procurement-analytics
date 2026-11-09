# Procurement indicators

Ten indicators computed in `notebooks/05_indicators.py` (Spark SQL) and re-implemented as DAX in
`powerbi/measures.dax`. Computed values per fiscal year are in [`indicator_values.md`](indicator_values.md),
generated from the gold tables.

**Conventions for every indicator**

* Unit of value: `amount_usd` = the supplier's contract amount in USD as recorded in STEP. Joint-venture contracts
  are split equally across members by the publisher, so summing all rows of a contract gives the contract value.
* Unit of count: a **contract** = a distinct `wb_contract_number`. Never count rows: 1 contract can have several
  supplier rows.
* Time: World Bank fiscal year of the contract signing date (FY2025 = 1 Jul 2024 – 30 Jun 2025). The latest fiscal
  year is partial (`dim_fiscal_year.is_complete_fy = false`), so multi-year comparisons use complete years only.
* Scope: gold fact (probable duplicate entries excluded). Data excludes subcontracts and cofinancing.

---

### I1. Total award value
* **Definition**: Total USD value of contracts signed in the period.
* **Formula**: `Σ amount_usd`
* **Limitations**: Contract value at signing, not disbursement; amendments and cancellations after signing are not
  reflected. Excludes cofinancing and subcontracts. Recent periods can be understated because of STEP data-entry lag.
  A handful of very large contracts move the total (the largest 1% of contracts carry about 54% of value).

### I2. Number of contracts awarded
* **Definition**: Count of distinct contracts signed in the period.
* **Formula**: `COUNT(DISTINCT wb_contract_number)`
* **Limitations**: Sensitive to how borrowers split packages into lots (each lot is a contract). Data-entry lag hits
  counts more than value because small contracts are entered later. Counts are not additive across supplier
  attributes (one contract can involve suppliers from two countries).

### I3. Average and median contract value
* **Definition**: Typical size of a contract.
* **Formula**: contract value `v_c = Σ amount_usd over the contract's rows`; average = `Σ v_c / N`;
  median = 50th percentile of `v_c`.
* **Limitations**: The average is dominated by a few mega-contracts; the median is the better trend measure. Mix
  effects matter: a shift from Goods/RFQ to Works raises both without any change within a category, so also read
  `ind_contract_size_by_category`.

### I4. Procurement method mix
* **Definition**: Distribution of award value and contract count across procurement methods, grouped into
  competition tiers.
* **Formula**: `value_share(tier) = Σ amount_usd[tier] / Σ amount_usd`; `count_share(tier) = contracts[tier] / contracts`
* **Tiers** (see `dim_procurement_method`):

  | Tier | Methods |
  |---|---|
  | Open competitive | Request for Bids, Request for Proposals, E-Auctions, QCBS, QBS, FBS, LCS, CQS |
  | Limited competitive | Request for Quotations |
  | Individual consultant (not classifiable) | Individual Consultant Selection |
  | Direct (non-competitive) | Direct Selection, UN Agencies (Direct) |
  | Other arrangement | Community Driven Development, Force Account, Commercial Practices, Non-Profit Organizations, PPP, Procurement Agents |
* **Limitations**: The dataset has **no market-approach field**, so open *international* and open *national*
  competition cannot be separated. ICS can be competitive or direct and is shown separately. CQS is classed as open
  competitive because it requires advertised expressions of interest, but it is a lighter process than QCBS.

### I5. Open competitive share of award value
* **Definition**: Share of award value contracted through open competitive methods.
* **Formula**: `Σ amount_usd[is_open_competitive] / Σ amount_usd`
* **Limitations**: As I4. Measures method, not competition intensity: number of bids is not in the data, so a
  single-bid RFB counts as open competitive.

### I6. Direct selection share
* **Definition**: Share of award value (and of contracts) awarded without competition.
* **Formula**: value: `Σ amount_usd[is_direct] / Σ amount_usd`; count: `contracts[is_direct] / contracts`
* **Limitations**: Direct selection is often justified (emergencies, UN agencies, proprietary goods, COVID-19
  vaccines). A high share is a flag for review, not evidence of non-compliance. Excludes direct ICS appointments,
  which cannot be identified.

### I7. Domestic supplier share
* **Definition**: Share of award value won by suppliers registered in the borrower country.
* **Formula**: `Σ amount_usd[Domestic] / Σ amount_usd[Domestic + Foreign + International organization]`
* **Supporting views**: value by `supplier_origin`; top foreign supplier countries (`ind_foreign_supplier_countries`).
* **Limitations**: Based on country of registration, not where value is added (a local subsidiary of a foreign group
  counts as domestic). Regional/multi-country borrowers are excluded (no single "home" country). Unknown supplier
  country (653 source rows) is excluded from the denominator. International organisations (supplier country `World`)
  are counted as non-domestic. Joint ventures between a local and a foreign firm are split 50/50 by the publisher's
  rule, not by actual work share.

### I8. Supplier concentration
* **Definition**: How much award value goes to the largest firms.
* **Formula**: per fiscal year, rank firms by `Σ amount_usd`; top-10 share = `Σ top-10 / Σ all firms`; also top-100
  share and HHI = `Σ (share_i × 100)²`.
* **Limitations**: Suppliers are identified by STEP Supplier ID. One group can have several IDs (country affiliates,
  spelling variants: 7,725 normalised names map to more than one ID), so concentration is understated. Anonymised
  individual consultants (one ID per award) and unknown suppliers are excluded. A global HHI says little about
  competition in any one market; for market analysis compute it within country × category.

### I9. Prior-review share
* **Definition**: Share of award value whose procurement was subject to World Bank prior review.
* **Formula**: `Σ amount_usd[review_type = 'Prior'] / Σ amount_usd`
* **Limitations**: Review thresholds differ by country risk and category and changed over time, so the share
  reflects both risk profiles and portfolio mix. 179 source rows have no review type.

### I10. Regional and sector distribution
* **Definition**: Share of award value by World Bank region, and by global practice.
* **Formula**: region: `Σ amount_usd[region] / Σ amount_usd`. Sector: `Σ amount_usd × allocation_weight` via
  `bridge_project_practice`, where each project's value is split equally across its listed practices.
* **Limitations**: Regions use the current regional structure for all years (Afghanistan and Pakistan are in MNA
  throughout). 10.4% of rows have no global practice (shown as "Not specified"). The equal split is an assumption:
  the data does not say which practice leads or how a project's value divides between practices.
