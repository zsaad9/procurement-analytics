"""Schema description and business glossary given to the language model (and shown in the UI)."""

SCHEMA_DOC = """
You query a World Bank procurement warehouse built from "Contract Awards in Investment Project Financing (since FY2020)".

PRIMARY TABLE (use it unless you need something else): vw_awards — one row per contract x supplier ("award line").
  award_line_id, wb_contract_number (contract id; COUNT(DISTINCT wb_contract_number) = number of contracts),
  fiscal_year INT (World Bank FY: FY2025 = 1 Jul 2024 - 30 Jun 2025), is_complete_fy BOOLEAN,
  contract_signing_date DATE, fiscal_quarter ('Q1'..'Q4', Q1 = Jul-Sep), contract_description,
  amount_usd DECIMAL (supplier's amount; joint-venture contracts are split equally across members, so
  SUM(amount_usd) over a contract's rows = contract value),
  contract_supplier_count, is_joint_award, is_amount_outlier, review_type ('Prior','Post','Not recorded'),
  supplier_origin ('Domestic','Foreign','International organization','Unknown supplier country',
                   'Not applicable (regional borrower)'),
  project_id, project_name, practices (semicolon list of global practices), practice_first_listed,
  borrower_country, borrower_country_code, borrower_type ('Country','Regional / multi-country'),
  region_code ('AFE','AFW','EAP','ECA','LCR','MNA','SAR','OTH'), region_name,
  method_key (RFB, RFP, EA, QCBS, QBS, FBS, LCS, CQS, RFQ, ICS, DS, UN, CDD, FA, CP, NPO, PPP, PA),
  method_name, method_group, competition_tier ('Open competitive','Limited competitive',
  'Individual consultant (not classifiable)','Direct (non-competitive)','Other arrangement'),
  is_open_competitive BOOLEAN, is_direct BOOLEAN,
  procurement_category ('Goods','Works','Consultant Services','Non-consulting Services'),
  supplier_key, supplier_name, is_individual_consultant BOOLEAN (individuals are anonymised),
  supplier_country, supplier_country_code

OTHER TABLES: fact_contract_awards, dim_project, bridge_project_practice(project_id, global_practice,
allocation_weight), dim_borrower_country, dim_supplier_country, dim_supplier, dim_procurement_method,
dim_procurement_category, dim_fiscal_year(fiscal_year, fy_label, is_complete_fy, months_covered),
ind_summary_by_fy (pre-computed indicators per fiscal year).
"""

GLOSSARY = """
BUSINESS RULES
- "Awards" / "award value" = SUM(amount_usd). "Number of awards/contracts" = COUNT(DISTINCT wb_contract_number).
- "Share of awards" is ambiguous: return BOTH value share and contract-count share.
- Africa = region_code IN ('AFE','AFW'). MENA / Middle East = 'MNA' (includes Afghanistan and Pakistan).
- Open competition = is_open_competitive (RFB, RFP, e-auction, QCBS, QBS, FBS, LCS, CQS).
  The data has NO market-approach field, so "open INTERNATIONAL competition" vs "national competition" cannot be
  separated. If asked, answer with is_open_competitive and state this limitation as an assumption.
- Direct selection = is_direct (Direct Selection and UN Agencies (Direct)).
- Domestic supplier share = Domestic / (Domestic + Foreign + International organization), by value.
- Supplier concentration: exclude is_individual_consultant and supplier_key = 'UNKNOWN'.
- The latest fiscal year can be partial: check is_complete_fy and mention it.
- Global practice / sector: use bridge_project_practice with SUM(amount_usd * allocation_weight) to avoid
  double counting multi-practice projects.
- Never invent columns. Use ROUND for shares (as fractions 0-1) and amounts.
"""

FEW_SHOT = [
    {
        "q": "Total award value and number of contracts in FY2024",
        "sql": "SELECT SUM(amount_usd) AS total_award_value_usd, COUNT(DISTINCT wb_contract_number) AS contracts\n"
               "FROM vw_awards WHERE fiscal_year = 2024",
    },
    {
        "q": "Top 5 foreign supplier countries by award value",
        "sql": "SELECT supplier_country, SUM(amount_usd) AS value_usd\nFROM vw_awards WHERE supplier_origin = 'Foreign'\n"
               "GROUP BY supplier_country ORDER BY value_usd DESC LIMIT 5",
    },
]
