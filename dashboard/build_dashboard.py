"""
Build the self-contained HTML dashboard (docs/index.html) from the gold Parquet exports.

    python dashboard/build_dashboard.py

Every number shown in the dashboard is pre-computed here with DuckDB for every combination of the three filters
(fiscal year x region x procurement category, each including "All"), embedded as JSON, and only rendered by the
browser. No figure is typed by hand. "All years" means complete fiscal years only (the latest FY is partial).
"""
import json
from pathlib import Path

import duckdb

ROOT = Path(__file__).resolve().parents[1]
G = ROOT / "data/gold/parquet"
OUT = ROOT / "docs/index.html"
TEMPLATE = ROOT / "dashboard/template.html"

con = duckdb.connect()
for t in ["fact_contract_awards", "dim_project", "dim_borrower_country", "dim_supplier_country", "dim_supplier",
          "dim_procurement_method", "dim_procurement_category", "dim_fiscal_year", "bridge_project_practice",
          "dq_results"]:
    con.execute(f"CREATE VIEW {t} AS SELECT * FROM read_parquet('{(G / (t + '.parquet')).as_posix()}')")

con.execute("""
CREATE TABLE base AS
SELECT f.wb_contract_number AS cn, f.fiscal_year AS fy, y.is_complete_fy AS complete,
       c.region_code AS reg, k.category_name AS cat, f.amount_usd::DOUBLE AS v,
       m.method_name AS method, m.competition_tier AS tier, m.is_open_competitive AS open, m.is_direct AS direct,
       f.supplier_origin AS origin, f.review_type AS review, f.supplier_key AS sk, s.supplier_name AS sname,
       s.is_individual_consultant AS indiv, sc.supplier_country AS scountry, c.borrower_country AS bcountry,
       f.project_id AS pid, f.contract_description AS descr, (month(f.contract_signing_date) + 5) % 12 + 1 AS fmonth
FROM fact_contract_awards f
JOIN dim_borrower_country c USING (borrower_country_key)
JOIN dim_procurement_category k USING (category_key)
JOIN dim_procurement_method m USING (method_key)
JOIN dim_supplier s USING (supplier_key)
JOIN dim_supplier_country sc ON sc.supplier_country_key = f.supplier_country_key
JOIN dim_fiscal_year y ON y.fiscal_year = f.fiscal_year
""")

# explode every row into the 8 filter combinations it belongs to (FY or ALL-complete) x (region or ALL) x (cat or ALL)
parts = []
for fyx, fyw in [("CAST(fy AS VARCHAR)", "TRUE"), ("'ALL'", "complete")]:
    for rx in ["reg", "'ALL'"]:
        for cx in ["cat", "'ALL'"]:
            parts.append(f"SELECT {fyx} AS fk, {rx} AS rk, {cx} AS ck, * FROM base WHERE {fyw}")
con.execute("CREATE TABLE e AS " + " UNION ALL ".join(parts))
KEY = "fk, rk, ck"


def grouped(sql):
    """run a query returning (fk, rk, ck, ...) rows -> {combo_key: [rest, ...]}"""
    out = {}
    for row in con.execute(sql).fetchall():
        out.setdefault(f"{row[0]}|{row[1]}|{row[2]}", []).append(list(row[3:]))
    return out


r4 = lambda x: None if x is None else round(float(x), 4)
r0 = lambda x: None if x is None else round(float(x))

# --- KPIs
kpi = grouped(f"""
WITH c AS (SELECT {KEY}, cn, SUM(v) cv FROM e GROUP BY ALL),
     med AS (SELECT {KEY}, median(cv) med, COUNT(*) n FROM c GROUP BY ALL),
     a AS (SELECT {KEY}, SUM(v) val,
             SUM(CASE WHEN open THEN v ELSE 0 END) / SUM(v) open_sh,
             SUM(CASE WHEN direct THEN v ELSE 0 END) / SUM(v) direct_sh,
             SUM(CASE WHEN origin = 'Domestic' THEN v END)
               / SUM(CASE WHEN origin IN ('Domestic','Foreign','International organization') THEN v END) dom_sh,
             SUM(CASE WHEN review = 'Prior' THEN v ELSE 0 END) / SUM(v) prior_sh,
             COUNT(DISTINCT CASE WHEN review = 'Prior' THEN cn END) prior_n
           FROM e GROUP BY ALL),
     s AS (SELECT {KEY}, sk, SUM(v) sv FROM e WHERE NOT indiv AND sk <> 'UNKNOWN' GROUP BY ALL),
     t AS (SELECT {KEY}, SUM(CASE WHEN rk2 <= 10 THEN sv END) / SUM(sv) top10
           FROM (SELECT *, row_number() OVER (PARTITION BY {KEY} ORDER BY sv DESC) rk2 FROM s) GROUP BY ALL)
SELECT a.fk, a.rk, a.ck, val, n, med, open_sh, direct_sh, dom_sh, prior_sh, prior_n, top10
FROM a JOIN med USING (fk, rk, ck) LEFT JOIN t USING (fk, rk, ck)
""")

TIERS = ["Open competitive", "Limited competitive", "Individual consultant (not classifiable)",
         "Direct (non-competitive)", "Other arrangement"]
ORIGINS = ["Domestic", "Foreign", "International organization", "Unknown supplier country",
           "Not applicable (regional borrower)"]
tiers = grouped(f"SELECT {KEY}, tier, SUM(v), COUNT(DISTINCT cn) FROM e GROUP BY ALL")
origins = grouped(f"SELECT {KEY}, origin, SUM(v) FROM e GROUP BY ALL")
methods = grouped(f"""
WITH c AS (SELECT {KEY}, method, tier, cn, SUM(v) cv FROM e GROUP BY ALL)
SELECT {KEY}, method, tier, SUM(cv), COUNT(*), median(cv) FROM c GROUP BY ALL ORDER BY 6 DESC""")
regions = grouped(f"""
SELECT {KEY}, reg, SUM(v), COUNT(DISTINCT cn),
       SUM(CASE WHEN open THEN v ELSE 0 END) / SUM(v),
       SUM(CASE WHEN origin = 'Domestic' THEN v END)
         / SUM(CASE WHEN origin IN ('Domestic','Foreign','International organization') THEN v END),
       SUM(CASE WHEN review = 'Prior' THEN v ELSE 0 END) / SUM(v),
       SUM(CASE WHEN direct THEN v ELSE 0 END) / SUM(v)
FROM e GROUP BY ALL ORDER BY 5 DESC""")
practices = grouped(f"""
SELECT {KEY}, b.global_practice, SUM(e.v * b.allocation_weight) av
FROM e JOIN bridge_project_practice b ON e.pid = b.project_id GROUP BY ALL ORDER BY av DESC""")


def topn(sql, n=10):
    return grouped(f"SELECT * FROM ({sql}) WHERE rn <= {n} ORDER BY fk, rk, ck, rn")


top_foreign = topn(f"""SELECT {KEY}, scountry, SUM(v) val, COUNT(DISTINCT cn),
    row_number() OVER (PARTITION BY {KEY} ORDER BY SUM(v) DESC) rn FROM e WHERE origin = 'Foreign' GROUP BY fk, rk, ck, scountry""")
top_borrowers = topn(f"""SELECT {KEY}, bcountry, SUM(v) val, COUNT(DISTINCT cn),
    row_number() OVER (PARTITION BY {KEY} ORDER BY SUM(v) DESC) rn FROM e GROUP BY fk, rk, ck, bcountry""")
top_suppliers = topn(f"""SELECT {KEY}, sk, any_value(sname), mode(scountry), SUM(v) val, COUNT(DISTINCT cn),
    row_number() OVER (PARTITION BY {KEY} ORDER BY SUM(v) DESC) rn
    FROM e WHERE NOT indiv AND sk <> 'UNKNOWN' GROUP BY fk, rk, ck, sk""")
top_direct = topn(f"""SELECT {KEY}, cn, any_value(fy), any_value(bcountry), string_agg(DISTINCT sname, ' / '),
    SUM(v) val, left(any_value(coalesce(descr, '')), 110),
    row_number() OVER (PARTITION BY {KEY} ORDER BY SUM(v) DESC) rn
    FROM e WHERE direct GROUP BY fk, rk, ck, cn""")
monthly = grouped(f"""SELECT {KEY}, fmonth, COUNT(DISTINCT cn) FROM e WHERE fk <> 'ALL' GROUP BY ALL ORDER BY fmonth""")

combos = {}
for key, rows in kpi.items():
    val, n, med, op, di, do, pr, prn, t10 = rows[0]
    tmap = {r[0]: r for r in tiers.get(key, [])}
    omap = {r[0]: r for r in origins.get(key, [])}
    mon = [0] * 12
    for m, c in monthly.get(key, []):
        mon[int(m) - 1] = int(c)
    combos[key] = {
        "k": [r0(val), int(n), r0(med), r4(op), r4(di), r4(do), r4(pr), r4(t10), int(prn)],
        "tier": [[r0(tmap[t][1]), int(tmap[t][2])] if t in tmap else [0, 0] for t in TIERS],
        "origin": [r0(omap[o][1]) if o in omap else 0 for o in ORIGINS],
        "methods": [[m, TIERS.index(t), r0(v), int(c), r0(md)] for m, t, v, c, md in methods.get(key, [])],
        "regions": [[g, r0(v), int(c), r4(o), r4(d), r4(p), r4(di)] for g, v, c, o, d, p, di in regions.get(key, [])],
        "practices": [[p, r0(v)] for p, v in practices.get(key, [])],
        "foreign": [[c, r0(v), int(nc)] for c, v, nc, _ in top_foreign.get(key, [])],
        "borrowers": [[c, r0(v), int(nc)] for c, v, nc, _ in top_borrowers.get(key, [])],
        "suppliers": [[nm, sc or "Unknown", r0(v), int(nc)] for _, nm, sc, v, nc, _ in top_suppliers.get(key, [])],
        "direct": [[cn, int(fy), bc, sn, r0(v), d] for cn, fy, bc, sn, v, d, _ in top_direct.get(key, [])],
    }
    if not key.startswith("ALL"):
        combos[key]["mon"] = mon

fys = [r[0] for r in con.execute("SELECT fiscal_year FROM dim_fiscal_year ORDER BY 1").fetchall()]
fyinfo = con.execute("""SELECT fiscal_year, is_complete_fy, CAST(last_signing_date AS VARCHAR), months_covered
                        FROM dim_fiscal_year ORDER BY 1""").fetchall()
partial = [r for r in fyinfo if not r[1]]
regions_meta = con.execute("""SELECT region_code, any_value(region_name) FROM dim_borrower_country
                              GROUP BY 1 ORDER BY CASE WHEN region_code = 'OTH' THEN 1 ELSE 0 END, 1""").fetchall()
cats = [r[0] for r in con.execute("SELECT category_name FROM dim_procurement_category ORDER BY 1").fetchall()]
dq = con.execute("""SELECT status, severity, layer, check_name, records_checked, records_flagged, pct_flagged, description
                    FROM dq_results ORDER BY CASE status WHEN 'FAIL' THEN 0 WHEN 'WARN' THEN 1 WHEN 'INFO' THEN 2 ELSE 3 END,
                    layer, check_name""").fetchall()
DATA = {
    "meta": {
        "fys": fys, "complete": [r[0] for r in fyinfo if r[1]],
        "partial": {"fy": partial[0][0], "through": partial[0][2], "months": partial[0][3]} if partial else None,
        "regions": [[c, n] for c, n in regions_meta], "cats": cats, "tiers": TIERS, "origins": ORIGINS,
        "rows": int(con.execute("SELECT COUNT(*) FROM fact_contract_awards").fetchone()[0]),
    },
    "c": combos,
    "dq": [[s, sv, l, cn, int(rc), int(rf), float(p), d] for s, sv, l, cn, rc, rf, p, d in dq],
}

html = TEMPLATE.read_text(encoding="utf-8").replace("/*__DATA__*/null", json.dumps(DATA, separators=(",", ":")))
OUT.write_text(html, encoding="utf-8")
print(f"wrote {OUT} ({OUT.stat().st_size/1e6:.2f} MB), {len(combos)} filter combinations")
