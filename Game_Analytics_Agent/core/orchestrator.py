"""
NEXUS Orchestrator – the core reasoning pipeline.

Flow:
  1. Classify intent
  2. Build SQL / detect currency need
  3. Execute SQL
  4. Format results + call Groq LLM for natural-language answer
  5. Return structured response dict
"""
import os
import re
import json
import time
import sqlite3
import pandas as pd

from groq import Groq
from tools.sql_executor import run_query, get_table_stats
from tools.currency_engine import convert_price, convert_multiple, get_rates
from session.manager import history_as_text, add_turn, new_session
from data.loader import get_schema_info

# ── Groq client (lazy) ────────────────────────────────────────────────────────
_groq_client: Groq | None = None

def _groq() -> Groq:
    global _groq_client
    if _groq_client is None:
        _groq_client = Groq(api_key=os.environ["GROQ_API_KEY"])
    return _groq_client


MODEL = "llama-3.1-8b-instant"

# ── Intent keywords ───────────────────────────────────────────────────────────
CURRENCY_PATTERNS = re.compile(
    r"\b(price|cost|how much|inr|usd|eur|gbp|jpy|brl|rupee|dollar|euro|yen|currency|convert)\b",
    re.I,
)
COMPARISON_PATTERNS = re.compile(r"\b(compare|vs|versus|difference|between)\b", re.I)
TREND_PATTERNS      = re.compile(r"\b(trend|over time|year|growth|change|history)\b", re.I)
FILTER_PATTERNS     = re.compile(
    r"\b(list|show|find|give|top|best|worst|filter|search|games? (that|with|support|having))\b",
    re.I,
)
STAT_PATTERNS       = re.compile(r"\b(average|mean|count|total|how many|percent|ratio|more|higher|lower)\b", re.I)
IRRELEVANT_TOPICS   = re.compile(
    r"\b(weather|stock|crypto|bitcoin|recipe|cook|news|sport(?:s)?|football|cricket|movie(?:s)?|"
    r"politic(?:s)?|president|actor|singer|song|music|book(?:s)?|health|medical|legal|law)\b",
    re.I,
)


def classify_intent(query: str) -> str:
    q = query.lower()
    if IRRELEVANT_TOPICS.search(q) and not any(
        kw in q for kw in ["game", "steam", "play", "genre", "rating"]
    ):
        return "irrelevant"
    if CURRENCY_PATTERNS.search(q):
        return "currency"
    if COMPARISON_PATTERNS.search(q):
        return "comparison"
    if TREND_PATTERNS.search(q):
        return "trend"
    if STAT_PATTERNS.search(q):
        return "statistics"
    if FILTER_PATTERNS.search(q):
        return "filter"
    return "lookup"


# ── Currency detection ─────────────────────────────────────────────────────────
CURRENCY_CODES = ["USD", "INR", "EUR", "GBP", "JPY", "BRL", "AUD", "CAD", "SGD", "MXN"]
CURRENCY_WORDS = {
    "dollar": "USD", "rupee": "INR", "euro": "EUR", "pound": "GBP",
    "yen": "JPY", "real": "BRL",
}

def _extract_currencies(query: str) -> list[str]:
    found = []
    q_upper = query.upper()
    for code in CURRENCY_CODES:
        if code in q_upper:
            found.append(code)
    for word, code in CURRENCY_WORDS.items():
        if word in query.lower() and code not in found:
            found.append(code)
    return found if found else ["USD"]


# ── SQL builder (LLM-assisted) ────────────────────────────────────────────────

def _build_sql(query: str, schema: dict, intent: str) -> str:
    """Ask the LLM to write SQLite SQL for this query."""
    cols = schema["columns"]
    col_info = ", ".join(cols[:40])  # cap to avoid huge prompt

    system = (
        "You are a SQLite expert. Given the schema and user question, write a single valid "
        "SQLite SELECT query. The table is named `games`. Only output the raw SQL — no markdown, "
        "no explanation. Use LOWER() for case-insensitive string comparisons. "
        "If the user wants a count, use COUNT(*). "
        "If the user wants top-N results, use LIMIT N. "
        "Do not use columns that don't exist in the schema."
    )
    user_msg = (
        f"Table schema columns: {col_info}\n\n"
        f"Sample row: {json.dumps(schema['sample'][0]) if schema['sample'] else 'N/A'}\n\n"
        f"User question: {query}\n\n"
        f"Write the SQL query:"
    )

    resp = _groq().chat.completions.create(
        model=MODEL,
        messages=[{"role": "system", "content": system},
                  {"role": "user",   "content": user_msg}],
        max_tokens=400,
        temperature=0.0,
    )
    sql = resp.choices[0].message.content.strip()
    # Strip markdown fences if present
    sql = re.sub(r"```[a-z]*\n?", "", sql).strip().rstrip("`").strip()
    return sql


# ── Natural language answer generator ─────────────────────────────────────────

def _generate_answer(
    query: str,
    intent: str,
    rows: list[dict],
    extra_context: str = "",
    history_text: str = "",
) -> str:
    data_summary = json.dumps(rows[:20], default=str) if rows else "No results found."

    system = (
        "You are NEXUS, a game analytics assistant. "
        "Answer the user's question using ONLY the provided data. "
        "Be concise, friendly, and factual. "
        "If the data is empty, say so politely. "
        "Never make up game names or statistics."
    )
    context_block = ""
    if history_text:
        context_block = f"\n\nPrevious conversation:\n{history_text}\n"
    if extra_context:
        context_block += f"\n\nExtra context:\n{extra_context}\n"

    user_msg = (
        f"User question: {query}\n"
        f"Query intent: {intent}\n"
        f"Data retrieved:\n{data_summary}"
        f"{context_block}"
        f"\n\nProvide a clear, human-readable answer:"
    )

    resp = _groq().chat.completions.create(
        model=MODEL,
        messages=[{"role": "system", "content": system},
                  {"role": "user",   "content": user_msg}],
        max_tokens=600,
        temperature=0.3,
    )
    return resp.choices[0].message.content.strip()


# ── Main orchestrator ─────────────────────────────────────────────────────────

def process_query(
    query: str,
    conn: sqlite3.Connection,
    df: pd.DataFrame,
    schema: dict,
    session_id: str | None = None,
) -> dict:
    t0 = time.time()

    # Session
    if not session_id:
        session_id = new_session()
    history_text = history_as_text(session_id)

    # 1. Intent
    intent = classify_intent(query)

    # 2. Irrelevant fallback
    if intent == "irrelevant":
        response_text = (
            "I'm NEXUS, a game analytics assistant specialised in Steam game data. "
            "I can help you with questions about game prices, ratings, genres, languages, "
            "multiplayer features, release trends, and more. "
            "Could you ask me something about games?"
        )
        result = {
            "response": response_text,
            "metadata": {
                "query_type": "irrelevant",
                "confidence_score": 1.0,
                "games": [],
                "statistics": {},
                "session_id": session_id,
                "execution_time_ms": int((time.time() - t0) * 1000),
            },
        }
        add_turn(session_id, query, response_text)
        return result

    rows = []
    extra_context = ""
    currency_info = {}
    sql_used = ""
    error_msg = None

    try:
        # 3. Build & run SQL
        sql_used = _build_sql(query, schema, intent)
        rows = run_query(conn, sql_used)

        # Check for SQL error
        if rows and "error" in rows[0]:
            error_msg = rows[0]["error"]
            rows = []

        # 4. Currency handling
        if intent == "currency" or CURRENCY_PATTERNS.search(query):
            currencies = _extract_currencies(query)
            # Try to find price in rows
            for row in rows[:5]:
                price_val = row.get("price") or row.get("price_usd") or 0
                try:
                    price_float = float(price_val)
                except (TypeError, ValueError):
                    price_float = 0.0
                if price_float > 0:
                    currency_info = convert_multiple(price_float, currencies)
                    parts = [f"{v['display']}" for v in currency_info.values() if "display" in v]
                    extra_context += f"Price conversions: {', '.join(parts)}. "
                    break

        # 5. Compute basic statistics for stat queries
        statistics = {}
        if rows and intent in ("statistics", "comparison"):
            numeric_keys = [k for k in rows[0].keys()
                            if isinstance(rows[0][k], (int, float)) and k != "rowid"]
            for k in numeric_keys[:5]:
                vals = [r[k] for r in rows if isinstance(r.get(k), (int, float))]
                if vals:
                    statistics[k] = {
                        "count": len(vals),
                        "mean": round(sum(vals) / len(vals), 3),
                        "min": min(vals),
                        "max": max(vals),
                    }

        # 6. Generate natural language answer
        answer = _generate_answer(query, intent, rows, extra_context, history_text)

    except Exception as exc:
        answer = (
            f"I encountered an issue processing your query: {exc}. "
            "Please try rephrasing or ask a different question about games."
        )
        error_msg = str(exc)

    # Confidence heuristic
    confidence = 0.5
    if rows and not error_msg:
        coverage = min(len(rows) / 10, 1.0)
        confidence = round(0.6 + 0.4 * coverage, 2)
    elif error_msg:
        confidence = 0.2

    result = {
        "response": answer,
        "metadata": {
            "query_type": intent,
            "confidence_score": confidence,
            "games": rows[:10],          # cap to 10 for readability
            "total_results": len(rows),
            "statistics": statistics,
            "currency_rates": currency_info,
            "sql_used": sql_used,
            "session_id": session_id,
            "execution_time_ms": int((time.time() - t0) * 1000),
            "data_sources": ["game_ids.csv", "game_data.csv", "additional_data.csv"],
        },
    }
    if error_msg:
        result["metadata"]["error"] = error_msg

    add_turn(session_id, query, answer)
    return result
