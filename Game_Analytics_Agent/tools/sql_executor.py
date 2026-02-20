"""
SQL executor – runs SQLite queries against the in-memory games table
and returns results as a list of dicts plus row-level metadata.
"""
import sqlite3
import pandas as pd
from typing import Any


def run_query(conn: sqlite3.Connection, sql: str, params: tuple = ()) -> list[dict]:
    """Execute SQL and return rows as dicts. Returns [] on error."""
    try:
        df = pd.read_sql_query(sql, conn, params=params)
        return df.to_dict(orient="records")
    except Exception as e:
        return [{"error": str(e), "sql": sql}]


def get_table_stats(conn: sqlite3.Connection) -> dict:
    """Quick stats about the games table."""
    try:
        total = pd.read_sql("SELECT COUNT(*) as n FROM games", conn).iloc[0]["n"]
        free  = pd.read_sql("SELECT COUNT(*) as n FROM games WHERE is_free=1", conn).iloc[0]["n"]
        paid  = total - free
        return {"total_games": int(total), "free_games": int(free), "paid_games": int(paid)}
    except Exception as e:
        return {"error": str(e)}
