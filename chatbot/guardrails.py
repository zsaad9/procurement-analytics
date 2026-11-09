"""
SQL guardrails: every query produced by the language model passes through `validate_sql` before it runs.

Layered defence (any layer alone would block a write; together they also block data exfiltration):
1. Parse with sqlglot. Exactly one statement, and it must be a read query (SELECT / WITH ... SELECT / UNION).
2. Reject any write, DDL, session or file node anywhere in the tree (INSERT, UPDATE, DELETE, MERGE, CREATE, DROP,
   ALTER, COPY, ATTACH, PRAGMA, SET, INSTALL/LOAD, CALL ...).
3. Only whitelisted tables may be referenced; table functions such as read_csv / read_parquet / glob are rejected.
4. A row LIMIT is enforced (added or tightened).
5. At execution time the DuckDB connection is opened read_only=True with external file access disabled, and the
   query is interrupted after a timeout (see engine.py).
"""
from dataclasses import dataclass, field

import sqlglot
from sqlglot import exp

ALLOWED_TABLES = {
    "vw_awards", "fact_contract_awards", "dim_project", "bridge_project_practice", "dim_borrower_country",
    "dim_supplier_country", "dim_supplier", "dim_procurement_method", "dim_procurement_category",
    "dim_fiscal_year", "ind_summary_by_fy",
}

_FORBIDDEN_NODE_NAMES = [
    "Insert", "Update", "Delete", "Merge", "Create", "Drop", "Alter", "AlterTable", "Command", "Copy", "Attach",
    "Detach", "Pragma", "Set", "Use", "Transaction", "Commit", "Rollback", "Grant", "Revoke", "TruncateTable",
    "Install", "Load", "LoadData", "Export", "Into", "Describe", "Show", "Kill", "Analyze", "Refresh", "Cache",
    "Uncache",
]
FORBIDDEN_NODES = tuple(getattr(exp, n) for n in _FORBIDDEN_NODE_NAMES if hasattr(exp, n))

FORBIDDEN_FUNCTIONS = {
    "read_csv", "read_csv_auto", "read_parquet", "read_json", "read_json_auto", "read_text", "read_blob",
    "parquet_scan", "csv_scan", "glob", "sniff_csv", "query", "query_table", "current_setting", "getenv",
    "duckdb_settings", "duckdb_extensions", "duckdb_secrets", "system", "shell", "load_extension", "pg_read_file",
    "read_ndjson", "read_xlsx", "iceberg_scan", "delta_scan", "sqlite_scan", "postgres_scan", "mysql_scan",
    "http_get", "httpfs",
}


class UnsafeQueryError(ValueError):
    pass


@dataclass
class ValidatedQuery:
    sql: str
    tables: set = field(default_factory=set)
    limit_applied: int | None = None


def validate_sql(sql: str, dialect: str = "duckdb", max_rows: int = 1000) -> ValidatedQuery:
    if not sql or not sql.strip():
        raise UnsafeQueryError("Empty query.")
    try:
        statements = [s for s in sqlglot.parse(sql, read=dialect) if s is not None]
    except sqlglot.errors.ParseError as e:
        raise UnsafeQueryError(f"SQL could not be parsed: {e.errors[0]['description'] if e.errors else e}")
    if len(statements) != 1:
        raise UnsafeQueryError(f"Exactly one statement is allowed (got {len(statements)}).")
    tree = statements[0]

    if not isinstance(tree, (exp.Select, exp.Union, exp.Intersect, exp.Except, exp.Subquery)):
        raise UnsafeQueryError(f"Only read-only SELECT queries are allowed (got {type(tree).__name__.upper()}).")

    for node in tree.walk():
        if FORBIDDEN_NODES and isinstance(node, FORBIDDEN_NODES):
            raise UnsafeQueryError(f"Forbidden operation in query: {type(node).__name__.upper()}.")
        if isinstance(node, (exp.Anonymous, exp.Func)):
            fname = (node.name if isinstance(node, exp.Anonymous) else node.sql_name()).lower()
            if fname in FORBIDDEN_FUNCTIONS:
                raise UnsafeQueryError(f"Function '{fname}' is not allowed.")
        if isinstance(node, exp.Table) and not isinstance(node.this, exp.Identifier):
            raise UnsafeQueryError("Table functions are not allowed; query the gold tables directly.")

    cte_names = {c.alias_or_name.lower() for c in tree.find_all(exp.CTE)}
    tables = set()
    for t in tree.find_all(exp.Table):
        name = t.name.lower()
        if name in cte_names:
            continue
        if t.args.get("db") or t.args.get("catalog"):
            # allow fully qualified Databricks names that end in an allowed table, e.g. workspace.wb_procurement.vw_awards
            if name not in ALLOWED_TABLES:
                raise UnsafeQueryError(f"Table '{t.sql()}' is not in the allowed list.")
        elif name not in ALLOWED_TABLES:
            raise UnsafeQueryError(f"Table '{name}' is not in the allowed list: {sorted(ALLOWED_TABLES)}.")
        tables.add(name)
    if not tables:
        raise UnsafeQueryError("Query must read from at least one gold table.")

    limit_node = tree.args.get("limit")
    current = None
    if limit_node is not None:
        try:
            current = int(limit_node.expression.this)
        except (AttributeError, ValueError, TypeError):
            current = None
    if current is None or current > max_rows:
        tree = tree.limit(max_rows, copy=True) if isinstance(tree, exp.Select) else \
            exp.select("*").from_(tree.subquery("q")).limit(max_rows)
        applied = max_rows
    else:
        applied = current
    return ValidatedQuery(sql=tree.sql(dialect=dialect, pretty=True), tables=tables, limit_applied=applied)
