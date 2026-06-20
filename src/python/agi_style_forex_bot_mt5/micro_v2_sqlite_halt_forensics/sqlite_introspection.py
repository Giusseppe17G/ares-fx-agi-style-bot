"""SQLite schema and row introspection helpers."""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path
from typing import Any


QUERIES_USED = [
    "SELECT name, type, sql FROM sqlite_master WHERE type IN ('table','view') ORDER BY name",
    "PRAGMA table_info(<table>)",
    "SELECT COUNT(*) AS row_count FROM <table>",
    "SELECT rowid AS _rowid_, * FROM <table> ORDER BY rowid DESC LIMIT <limit>",
]


def inspect_sqlite(sqlite_path: str | Path, *, row_limit_per_table: int = 10000) -> dict[str, Any]:
    path = Path(sqlite_path)
    if not path.exists():
        return {
            "sqlite_exists": False,
            "sqlite_path": str(path),
            "tables": [],
            "rows_by_table": {},
            "queries_used": QUERIES_USED,
            "sqlite_read_error": "SQLITE_MISSING",
        }
    uri = f"file:{path.resolve().as_posix()}?mode=ro"
    conn = sqlite3.connect(uri, uri=True)
    conn.row_factory = sqlite3.Row
    try:
        objects = [dict(row) for row in conn.execute(QUERIES_USED[0])]
        tables = []
        rows_by_table: dict[str, list[dict[str, Any]]] = {}
        for obj in objects:
            table = str(obj["name"])
            columns = [dict(row) for row in conn.execute(f"PRAGMA table_info({_quote_ident(table)})")]
            try:
                row_count = int(conn.execute(f"SELECT COUNT(*) AS row_count FROM {_quote_ident(table)}").fetchone()["row_count"])
            except sqlite3.Error:
                row_count = 0
            tables.append(
                {
                    "name": table,
                    "type": obj.get("type", ""),
                    "sql": obj.get("sql", ""),
                    "columns": columns,
                    "column_names": [str(col.get("name", "")) for col in columns],
                    "row_count": row_count,
                }
            )
            if row_count:
                rows_by_table[table] = _rows(conn, table, row_limit_per_table)
        return {
            "sqlite_exists": True,
            "sqlite_path": str(path),
            "tables": tables,
            "rows_by_table": rows_by_table,
            "queries_used": QUERIES_USED,
            "sqlite_read_error": "",
            "execution_attempted": False,
            "order_send_called": False,
            "order_check_called": False,
        }
    finally:
        conn.close()


def _rows(conn: sqlite3.Connection, table: str, limit: int) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for row in conn.execute(f"SELECT rowid AS _rowid_, * FROM {_quote_ident(table)} ORDER BY rowid DESC LIMIT ?", (int(limit),)):
        item = dict(row)
        if "payload_json" in item:
            item["_payload"] = _loads(item.get("payload_json"))
        rows.append(item)
    return list(reversed(rows))


def _quote_ident(value: str) -> str:
    return '"' + value.replace('"', '""') + '"'


def _loads(value: Any) -> dict[str, Any]:
    if isinstance(value, dict):
        return value
    try:
        loaded = json.loads(str(value or ""))
        return loaded if isinstance(loaded, dict) else {}
    except Exception:
        return {}
