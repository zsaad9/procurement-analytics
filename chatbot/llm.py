"""
Question -> SQL planners.

* ClaudePlanner: uses the Anthropic API (set ANTHROPIC_API_KEY; model via ANTHROPIC_MODEL). Handles open-ended
  questions, then writes the plain-English answer from the returned rows only.
* RuleBasedPlanner: deterministic, no API key needed. Understands a fixed vocabulary (fiscal years, regions,
  countries, categories, methods, domestic/foreign, prior review) and the intents total / count / share / average /
  median / top-N. Used for offline demos, CI tests, and as a fallback.

Both return a Plan: the SQL, a drill-down SQL listing the underlying contract lines, and the assumptions made.
"""
import json
import os
import re
from dataclasses import dataclass, field

from schema_context import FEW_SHOT, GLOSSARY, SCHEMA_DOC


@dataclass
class Plan:
    sql: str | None
    detail_sql: str | None = None
    assumptions: list = field(default_factory=list)
    cannot_answer: bool = False
    reason: str = ""
    intent: str = ""


# --------------------------------------------------------------------------------------------- LLM planner
class ClaudePlanner:
    name = "claude"

    def __init__(self, model: str | None = None, dialect: str = "duckdb"):
        import anthropic  # imported lazily so the offline mode needs no SDK
        self.client = anthropic.Anthropic()
        self.model = model or os.environ.get("ANTHROPIC_MODEL", "claude-sonnet-5-5")
        self.dialect = dialect

    def _system(self):
        shots = "\n\n".join(f"Q: {s['q']}\nSQL:\n{s['sql']}" for s in FEW_SHOT)
        return (f"You translate procurement questions into ONE read-only {self.dialect} SQL query.\n"
                f"{SCHEMA_DOC}\n{GLOSSARY}\nEXAMPLES\n{shots}\n\n"
                "Reply with JSON only, no prose: {\"sql\": str|null, \"detail_sql\": str|null, "
                "\"assumptions\": [str], \"cannot_answer\": bool, \"reason\": str}.\n"
                "detail_sql lists the underlying award lines behind the answer (wb_contract_number, fiscal_year, "
                "borrower_country, method_name, procurement_category, supplier_name, supplier_country, amount_usd, "
                "contract_description) ORDER BY amount_usd DESC LIMIT 100.\n"
                "If the data cannot answer the question (e.g. bid prices, number of bidders, cofinancing, "
                "subcontractors), set cannot_answer=true and explain why in reason.")

    def _call(self, system, user, max_tokens=1500):
        msg = self.client.messages.create(model=self.model, max_tokens=max_tokens, system=system,
                                          messages=[{"role": "user", "content": user}])
        return "".join(b.text for b in msg.content if getattr(b, "type", "") == "text")

    def plan(self, question: str, previous_error: str | None = None) -> Plan:
        user = question if not previous_error else (
            f"{question}\n\nYour previous SQL failed with this error; return corrected JSON:\n{previous_error}")
        raw = self._call(self._system(), user)
        m = re.search(r"\{.*\}", raw, re.S)
        if not m:
            return Plan(sql=None, cannot_answer=True, reason="Model did not return JSON.")
        d = json.loads(m.group(0))
        return Plan(sql=d.get("sql"), detail_sql=d.get("detail_sql"), assumptions=d.get("assumptions") or [],
                    cannot_answer=bool(d.get("cannot_answer")), reason=d.get("reason", ""), intent="llm")

    def summarize(self, question: str, sql: str, result_markdown: str, assumptions: list) -> str:
        system = ("You are a World Bank procurement analyst. Answer the question in 2-4 sentences using ONLY the "
                  "numbers in the query result. Format shares as percentages with one decimal and USD amounts in "
                  "millions or billions. Mention assumptions that change the meaning. Never add numbers that are "
                  "not in the result.")
        user = f"Question: {question}\nAssumptions: {assumptions}\nSQL:\n{sql}\nResult:\n{result_markdown}"
        return self._call(system, user, max_tokens=400).strip()


# --------------------------------------------------------------------------------------------- rule-based planner
REGIONS = [  # longest phrases first
    ("eastern and southern africa", ["AFE"], "Eastern and Southern Africa"),
    ("western and central africa", ["AFW"], "Western and Central Africa"),
    ("west africa", ["AFW"], "Western and Central Africa"), ("east africa", ["AFE"], "Eastern and Southern Africa"),
    ("sub-saharan africa", ["AFE", "AFW"], "Africa (AFE + AFW)"), ("africa", ["AFE", "AFW"], "Africa (AFE + AFW)"),
    ("east asia", ["EAP"], "East Asia and Pacific"), ("pacific", ["EAP"], "East Asia and Pacific"),
    ("europe", ["ECA"], "Europe and Central Asia"), ("central asia", ["ECA"], "Europe and Central Asia"),
    ("latin america", ["LCR"], "Latin America and Caribbean"), ("caribbean", ["LCR"], "Latin America and Caribbean"),
    ("middle east", ["MNA"], "Middle East, North Africa, Afghanistan and Pakistan"),
    ("mena", ["MNA"], "Middle East, North Africa, Afghanistan and Pakistan"),
    ("south asia", ["SAR"], "South Asia"),
]
CATEGORIES = [("non-consulting", "Non-consulting Services"), ("consultant", "Consultant Services"),
              ("consulting", "Consultant Services"), ("goods", "Goods"), ("works", "Works")]
SUBJECTS = [  # regex, SQL predicate, label, extra assumption
    (r"open international competi|international competitive|open international",
     "is_open_competitive", "open competitive methods",
     "The dataset has no market-approach field, so open INTERNATIONAL competition cannot be separated from open "
     "national competition. Answered with all open competitive methods (RFB, RFP, e-auction, QCBS, QBS, FBS, LCS, "
     "CQS)."),
    (r"national competi", "is_open_competitive", "open competitive methods",
     "The dataset has no market-approach field, so national competition cannot be isolated. Answered with all open "
     "competitive methods."),
    (r"open competi|competitive (method|procurement|selection)|competitively", "is_open_competitive",
     "open competitive methods", None),
    (r"direct selection|direct contract|sole.source|single.source|non.competitive", "is_direct",
     "direct selection", None),
    (r"\brfq\b|request for quotation", "method_key = 'RFQ'", "Request for Quotations", None),
    (r"\brfb\b|request for bids", "method_key = 'RFB'", "Request for Bids", None),
    (r"\bqcbs\b|quality and cost", "method_key = 'QCBS'", "QCBS", None),
    (r"domestic|local (firm|supplier|compan)", "supplier_origin = 'Domestic'", "domestic suppliers", "domestic"),
    (r"foreign|international (firm|supplier|compan)", "supplier_origin = 'Foreign'", "foreign suppliers", "domestic"),
    (r"prior review", "review_type = 'Prior'", "prior review", None),
    (r"joint venture|\bjv\b", "is_joint_award", "joint awards", None),
]
GROUPS = [(r"by region|per region|each region|across regions", "region_name"),
          (r"by (fiscal )?year|per (fiscal )?year|each year|trend|over time|annual", "fiscal_year"),
          (r"by (procurement )?method|per method", "method_name"),
          (r"by (procurement )?category|per category", "procurement_category"),
          (r"by supplier country|supplier countr(y|ies)", "supplier_country"),
          (r"by (borrower )?country|per country|each country", "borrower_country")]
DETAIL_COLS = ("wb_contract_number, fiscal_year, borrower_country, region_code, method_name, procurement_category, "
               "supplier_name, supplier_country, supplier_origin, review_type, amount_usd, contract_description")


class RuleBasedPlanner:
    name = "rule-based"

    def __init__(self, borrower_countries: list[str] | None = None, supplier_countries: list[str] | None = None):
        self.countries = sorted(borrower_countries or [], key=len, reverse=True)
        self.supplier_countries = sorted(supplier_countries or [], key=len, reverse=True)

    @staticmethod
    def _q(s):
        return "'" + s.replace("'", "''") + "'"

    def plan(self, question: str, previous_error: str | None = None) -> Plan:
        q = question.lower()
        where, assumptions, labels = [], [], []

        years = sorted({int(y) for y in re.findall(r"\bfy\s?'?(\d{4})\b", q)} |
                       {2000 + int(y) for y in re.findall(r"\bfy\s?'?(\d{2})\b", q)})
        rng = re.search(r"fy\s?(\d{4})\s*(?:-|to|through|–)\s*(?:fy\s?)?(\d{4})", q)
        if rng:
            years = list(range(int(rng.group(1)), int(rng.group(2)) + 1))
        since = re.search(r"since fy\s?(\d{4})", q)
        if since:
            years = []
            where.append(f"fiscal_year >= {since.group(1)}")
        if years:
            where.append(f"fiscal_year IN ({', '.join(map(str, years))})" if len(years) > 1 else f"fiscal_year = {years[0]}")
            labels.append("FY" + "-".join(str(y) for y in ([years[0], years[-1]] if len(years) > 1 else years)))

        text_wo = q
        for phrase, codes, label in REGIONS:
            if re.search(r"\b" + re.escape(phrase) + r"\b", text_wo):
                where.append(f"region_code IN ({', '.join(map(self._q, codes))})")
                labels.append(label)
                if phrase in ("africa", "sub-saharan africa"):
                    assumptions.append("Africa = World Bank regions AFE (Eastern and Southern) + AFW (Western and Central).")
                if phrase == "middle east" or phrase == "mena":
                    assumptions.append("The MNA region in this data also includes Afghanistan and Pakistan.")
                text_wo = text_wo.replace(phrase, " ")
                break

        # supplier-country phrases ("from China", "Chinese firms") vs borrower-country phrases ("in Kenya")
        supplier_ctry = None
        for c in self.supplier_countries:
            cl = c.lower()
            if re.search(r"\b(from|suppliers? (from|in|registered in)|firms? from|contractors? from)\s+" + re.escape(cl) + r"\b", q):
                supplier_ctry = c
                break
        if supplier_ctry is None and re.search(r"\bchinese\b", q):
            supplier_ctry = "China"
        share_q = bool(re.search(r"share|percent|%|proportion|fraction", q))
        supplier_subject = None
        if supplier_ctry and share_q:
            # "what share ... went to firms from China" -> supplier country is the subject, not a filter
            supplier_subject = (f"supplier_country = {self._q(supplier_ctry)}", f"suppliers from {supplier_ctry}")
        elif supplier_ctry:
            where.append(f"supplier_country = {self._q(supplier_ctry)}")
            labels.append(f"suppliers from {supplier_ctry}")
        for c in self.countries:
            if c == supplier_ctry:
                continue
            if re.search(r"\b" + re.escape(c.lower()) + r"\b", text_wo):
                where.append(f"borrower_country = {self._q(c)}")
                labels.append(c)
                break

        for kw, cat in CATEGORIES:
            if re.search(r"\b" + kw, q):
                where.append(f"procurement_category = {self._q(cat)}")
                labels.append(cat)
                break

        subject = None
        for rx, pred, label, extra in SUBJECTS:
            if re.search(rx, q):
                subject = (pred, label)
                if extra == "domestic":
                    where.append("supplier_origin IN ('Domestic', 'Foreign', 'International organization')")
                    assumptions.append("Domestic share = Domestic / (Domestic + Foreign + International organization) "
                                       "by value; regional borrowers and unknown supplier countries are excluded.")
                elif extra:
                    assumptions.append(extra)
                break

        if subject is None and supplier_subject:
            subject = supplier_subject
        group = next((col for rx, col in GROUPS if re.search(rx, q)), None)
        top = re.search(r"\btop\s*(\d+)?\b|\blargest\b|\bbiggest\b", q)
        wants_share = bool(re.search(r"share|percent|%|proportion|fraction|what part", q))
        wants_count = bool(re.search(r"how many|number of|count", q))
        wants_avg = bool(re.search(r"average|mean", q))
        wants_median = "median" in q
        if re.search(r"bid(s|der)|price|cost estimate|cofinanc|subcontract", q):
            return Plan(sql=None, cannot_answer=True, intent="unsupported",
                        reason="This dataset records awarded contracts only. It has no bids, bidder counts, estimated "
                               "costs, cofinancing or subcontractor awards, so it cannot answer that question.")

        where_sql = ("\nWHERE " + "\n  AND ".join(where)) if where else ""
        gsel = f"{group}, " if group else ""
        gby = f"\nGROUP BY {group}\nORDER BY {group if group == 'fiscal_year' else '1'}" if group else ""

        if top and re.search(r"supplier|firm|contractor|compan", q) and not re.search(r"supplier countr", q):
            n = int(top.group(1) or 10)
            entity = "supplier_country" if re.search(r"countr", q) else "supplier_name"
            if entity == "supplier_name":
                where.append("NOT is_individual_consultant AND supplier_key <> 'UNKNOWN'")
                assumptions.append("Anonymised individual consultants and unknown suppliers are excluded from rankings; "
                                   "suppliers are identified by STEP Supplier ID (affiliates of one group may have separate IDs).")
            if subject:
                where.append(subject[0])
            where_sql = ("\nWHERE " + "\n  AND ".join(where)) if where else ""
            sql = (f"SELECT {entity}, SUM(amount_usd) AS value_usd, COUNT(DISTINCT wb_contract_number) AS contracts,\n"
                   f"       COUNT(DISTINCT borrower_country) AS borrower_countries\nFROM vw_awards{where_sql}\n"
                   f"GROUP BY {entity}\nORDER BY value_usd DESC\nLIMIT {n}")
            intent = "top"
        elif top and re.search(r"countr", q):
            n = int(top.group(1) or 10)
            entity = "supplier_country" if re.search(r"supplier|foreign|firm", q) else "borrower_country"
            if subject:
                where.append(subject[0])
            where_sql = ("\nWHERE " + "\n  AND ".join(where)) if where else ""
            sql = (f"SELECT {entity}, SUM(amount_usd) AS value_usd, COUNT(DISTINCT wb_contract_number) AS contracts\n"
                   f"FROM vw_awards{where_sql}\nGROUP BY {entity}\nORDER BY value_usd DESC\nLIMIT {n}")
            intent = "top"
        elif top and re.search(r"contract", q):
            n = int(top.group(1) or 10)
            if subject:
                where.append(subject[0])
            where_sql = ("\nWHERE " + "\n  AND ".join(where)) if where else ""
            sql = (f"SELECT wb_contract_number, fiscal_year, borrower_country, method_name, procurement_category,\n"
                   f"       STRING_AGG(supplier_name, ' / ') AS suppliers, SUM(amount_usd) AS contract_value_usd,\n"
                   f"       ANY_VALUE(contract_description) AS description\nFROM vw_awards{where_sql}\n"
                   f"GROUP BY wb_contract_number, fiscal_year, borrower_country, method_name, procurement_category\n"
                   f"ORDER BY contract_value_usd DESC\nLIMIT {n}")
            intent = "top"
        elif wants_share and subject:
            p = subject[0]
            sql = (f"SELECT {gsel}ROUND(SUM(CASE WHEN {p} THEN amount_usd ELSE 0 END) / SUM(amount_usd), 4) AS value_share,\n"
                   f"       ROUND(COUNT(DISTINCT CASE WHEN {p} THEN wb_contract_number END) * 1.0\n"
                   f"             / COUNT(DISTINCT wb_contract_number), 4) AS contract_count_share,\n"
                   f"       SUM(CASE WHEN {p} THEN amount_usd ELSE 0 END) AS subject_value_usd,\n"
                   f"       SUM(amount_usd) AS total_value_usd,\n"
                   f"       COUNT(DISTINCT CASE WHEN {p} THEN wb_contract_number END) AS subject_contracts,\n"
                   f"       COUNT(DISTINCT wb_contract_number) AS total_contracts\nFROM vw_awards{where_sql}{gby}")
            assumptions.append("'Share of awards' is reported both by value (USD) and by number of contracts.")
            intent = "share"
        elif wants_avg or wants_median:
            if subject:
                where.append(subject[0])
                where_sql = "\nWHERE " + "\n  AND ".join(where)
            gcol = f"{group}, " if group else ""
            sql = (f"WITH contracts AS (\n  SELECT {gcol}wb_contract_number, SUM(amount_usd) AS contract_value\n"
                   f"  FROM vw_awards{where_sql.replace(chr(10), chr(10) + '  ')}\n  GROUP BY {gcol}wb_contract_number\n)\n"
                   f"SELECT {gcol}COUNT(*) AS contracts, ROUND(AVG(contract_value), 2) AS avg_contract_value_usd,\n"
                   f"       ROUND(MEDIAN(contract_value), 2) AS median_contract_value_usd\nFROM contracts"
                   + (f"\nGROUP BY {group}\nORDER BY {group if group == 'fiscal_year' else '1'}" if group else ""))
            assumptions.append("Contract value = sum of all supplier rows of a contract (re-adds joint-venture splits).")
            intent = "average"
        elif wants_count or re.search(r"total|how much|value|amount|awarded|spend", q) or group:
            if subject:
                where.append(subject[0])
                where_sql = "\nWHERE " + "\n  AND ".join(where)
            sql = (f"SELECT {gsel}SUM(amount_usd) AS total_award_value_usd,\n"
                   f"       COUNT(DISTINCT wb_contract_number) AS contracts\nFROM vw_awards{where_sql}{gby}")
            intent = "total"
        else:
            return Plan(sql=None, cannot_answer=True, intent="unknown",
                        reason="The offline rule-based mode did not recognise this question. Try wording like "
                               "'total award value by fiscal year', 'share of FY2025 awards in Africa using direct "
                               "selection', 'top 10 suppliers in Works', or set ANTHROPIC_API_KEY for free-form questions.")

        dwhere = list(where)
        if intent == "share" and subject:
            dwhere.append(subject[0])
        detail = (f"SELECT {DETAIL_COLS}\nFROM vw_awards" + (("\nWHERE " + "\n  AND ".join(dwhere)) if dwhere else "")
                  + "\nORDER BY amount_usd DESC\nLIMIT 100")
        if not years and not since and group != "fiscal_year":
            assumptions.append("No fiscal year given: all years FY2020 to date are included (the latest FY is partial).")
        return Plan(sql=sql, detail_sql=detail, assumptions=assumptions, intent=intent,
                    reason=", ".join(labels + ([subject[1]] if subject else [])))

    # ------------------------------------------------------------------ deterministic answer text
    @staticmethod
    def summarize(question, sql, df, plan: Plan) -> str:
        if df is None or df.empty:
            return "The query returned no rows for these filters."
        fmt_usd = lambda v: (f"USD {float(v)/1e9:,.2f} billion" if abs(float(v)) >= 1e9 else f"USD {float(v)/1e6:,.1f} million"
                             if abs(float(v)) >= 1e6 else f"USD {float(v):,.0f}")
        scope = plan.reason or "all awards"
        if plan.intent == "share" and len(df) == 1:
            r = df.iloc[0]
            return (f"For {scope}: {float(r.value_share):.1%} of award value ({fmt_usd(r.subject_value_usd)} of "
                    f"{fmt_usd(r.total_value_usd)}) and {float(r.contract_count_share):.1%} of contracts "
                    f"({int(r.subject_contracts):,} of {int(r.total_contracts):,}).")
        if plan.intent == "total" and len(df) == 1:
            r = df.iloc[0]
            return f"For {scope}: total award value {fmt_usd(r.total_award_value_usd)} across {int(r.contracts):,} contracts."
        if plan.intent == "average" and len(df) == 1:
            r = df.iloc[0]
            return (f"For {scope}: {int(r.contracts):,} contracts, average value {fmt_usd(r.avg_contract_value_usd)}, "
                    f"median {fmt_usd(r.median_contract_value_usd)}.")
        def fv(col, v):
            if v is None or (isinstance(v, float) and v != v):
                return "n/a"
            if "share" in col:
                return f"{float(v):.1%}"
            if "usd" in col or col.endswith("value"):
                return fmt_usd(v)
            if col == "fiscal_year":
                return f"FY{int(v)}"
            if isinstance(v, (int,)) or (hasattr(v, "is_integer") and float(v).is_integer()):
                return f"{int(v):,}"
            return str(v)

        def row_txt(r):
            return ", ".join(f"{c} {fv(c, r[c])}" for c in df.columns[:4])

        if len(df) == 1:
            return f"For {scope}: {row_txt(df.iloc[0])}."
        txt = f"{len(df)} rows for {scope}. First: {row_txt(df.iloc[0])}."
        if len(df) > 1:
            txt += f" Last: {row_txt(df.iloc[-1])}."
        return txt + " Full table below."
