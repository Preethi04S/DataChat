"""
NEXUS Orchestrator – core reasoning pipeline.

Flow:
  1. Classify intent
  2. Build SQL (LLM-assisted, with rich schema context)
  3. Execute SQL
  4. Currency conversion if needed
  5. LLM generates natural-language answer from data
  6. Return { response, metadata }
"""
import os
import re
import json
import time
import sqlite3
import pandas as pd

from groq import Groq
from tools.sql_executor import run_query, get_table_stats
from tools.currency_engine import convert_multiple
from session.manager import history_as_text, add_turn, new_session

# ── Groq client ───────────────────────────────────────────────────────────────
_groq_client = None

def _groq() -> Groq:
    global _groq_client
    if _groq_client is None:
        _groq_client = Groq(api_key=os.environ["GROQ_API_KEY"])
    return _groq_client

MODEL = "llama-3.1-8b-instant"

# ── Exact schema description sent to LLM ─────────────────────────────────────
# Derived from actual CSV inspection — prevents hallucinated column names.
SCHEMA_DESCRIPTION = """
Table: games (SQLite, 29235 rows)

Key columns:
  appid           INTEGER  -- Steam app ID
  name            TEXT     -- Game name
  developer       TEXT     -- Developer name
  publisher       TEXT     -- Publisher name
  price_usd       REAL     -- Price in USD (0.0 = free)
  is_free         INTEGER  -- 1 if free, 0 if paid
  price_tier      TEXT     -- 'Free', 'Budget (<$5)', 'Mid ($5-$20)', 'Premium ($20+)'
  positive        REAL     -- Number of positive reviews
  negative        REAL     -- Number of negative reviews
  rating          REAL     -- Positive ratio * 10, range 0-10 (higher = better)
  userscore       REAL     -- User score
  owners          TEXT     -- Owners range string e.g. '10,000,000 .. 20,000,000'
  owners_estimate REAL     -- Midpoint of owners range
  languages       TEXT     -- Comma-separated supported languages e.g. 'English, Korean, French'
  genre           TEXT     -- Comma-separated genres e.g. 'Action', 'Action,Indie'
  genres          TEXT     -- Parsed genre string from Steam (same as genre)
  categories      TEXT     -- Game features e.g. 'Multi-player, Online Multi-Player'
  has_multiplayer INTEGER  -- 1 if multiplayer, 0 if not
  release_year    REAL     -- Year released e.g. 2015.0
  ccu             REAL     -- Concurrent users peak
  tags            TEXT     -- JSON-like dict of tag counts e.g. "{'Action': 2681, 'FPS': 2048}"
  score_rank      REAL     -- Score rank
  average_forever REAL     -- Average playtime forever (minutes)
  discount        REAL     -- Current discount percent
  short_description TEXT   -- Short description of the game

Notes:
- Use LOWER(languages) LIKE '%korean%' to filter by Korean language support
- Use LOWER(genre) LIKE '%action%' to filter by genre (genre has values like 'Action', 'Action,Indie')
- Use LOWER(tags) LIKE '%shooter%' OR LOWER(tags) LIKE '%fps%' to find shooter games
- Use LOWER(tags) LIKE '%rpg%' to find RPG games
- Use has_multiplayer=1 OR LOWER(categories) LIKE '%multi-player%' to filter multiplayer games
- Use LOWER(name) LIKE '%counter-strike%' OR LOWER(name) LIKE '%counter strike%' for Counter-Strike
- price_usd is in dollars (e.g. 9.99), NOT cents
- is_free=1 means free, is_free=0 means paid
- rating is 0-10 scale; higher is better
- release_year is a float (e.g. 2015.0), filter with release_year > 2015
- For shooter games released after 2015 with multiplayer use:
  SELECT appid, name, rating, genre, release_year, price_usd FROM games WHERE (LOWER(tags) LIKE '%shooter%' OR LOWER(tags) LIKE '%fps%') AND has_multiplayer=1 AND release_year > 2015 ORDER BY rating DESC LIMIT 20
- NEVER use SELECT * — always select only needed columns: appid, name, rating, genre, release_year, price_usd, languages, developer
- The tags and short_description columns are very long — never select them
"""

# ── Intent classification ─────────────────────────────────────────────────────
CURRENCY_RE   = re.compile(r"\b(price|cost|how much|inr|usd|eur|gbp|jpy|brl|rupee|dollar|euro|yen|currency)\b", re.I)
COMPARISON_RE = re.compile(r"\b(compare|vs|versus|difference|between|higher|lower|more|less)\b", re.I)
TREND_RE      = re.compile(r"\b(trend|over time|year|growth|change|history|since|from \d{4})\b", re.I)
STAT_RE       = re.compile(r"\b(average|mean|count|total|how many|percent|ratio)\b", re.I)
FILTER_RE     = re.compile(r"\b(list|show|find|top|best|worst|search|support|having|with|after|before)\b", re.I)
IRRELEVANT_RE = re.compile(
    r"\b(weather|stock market|crypto|bitcoin|recipe|cooking|politics|president|"
    r"actor|singer|song lyrics|medical|legal advice|sports score|cricket score)\b", re.I
)
GAME_KW = {"game", "steam", "play", "genre", "rating", "price", "developer", "publisher",
            "shooter", "rpg", "indie", "action", "multiplayer", "release"}


def classify_intent(query: str) -> str:
    q_lower = query.lower()
    # Irrelevant only if NO game keywords present
    if IRRELEVANT_RE.search(q_lower) and not any(kw in q_lower for kw in GAME_KW):
        return "irrelevant"
    if CURRENCY_RE.search(q_lower):
        return "currency"
    if COMPARISON_RE.search(q_lower) and STAT_RE.search(q_lower):
        return "comparison"
    if TREND_RE.search(q_lower):
        return "trend"
    if STAT_RE.search(q_lower):
        return "statistics"
    if FILTER_RE.search(q_lower):
        return "filter"
    return "lookup"


# ── Currency helpers ──────────────────────────────────────────────────────────
CURRENCY_CODES = ["USD", "INR", "EUR", "GBP", "JPY", "BRL", "AUD", "CAD"]
CURRENCY_WORDS = {"dollar": "USD", "rupee": "INR", "euro": "EUR",
                  "pound": "GBP", "yen": "JPY", "real": "BRL"}

def _extract_currencies(query: str) -> list:
    found = []
    q_up = query.upper()
    for code in CURRENCY_CODES:
        if code in q_up:
            found.append(code)
    for word, code in CURRENCY_WORDS.items():
        if word in query.lower() and code not in found:
            found.append(code)
    return found if found else ["USD", "INR"]


# ── Smart SQL router: known patterns → reliable SQL; else → LLM ──────────────

FREE_VS_PAID_RE = re.compile(r"\b(free.*paid|paid.*free|free.*higher|free.*rating|free.*rate)\b", re.I)
ACTION_KOREAN_RE = re.compile(r"\baction\b.*\bkorean\b|\bkorean\b.*\baction\b", re.I)
SHOOTER_MULTI_RE = re.compile(r"\bshooter\b.*\b(after|since|release|2015|2016|2017|2018|2019|2020)\b", re.I)
COUNTER_STRIKE_RE = re.compile(r"\bcounter.?strike\b|\bcsgo\b|\bcs:?go\b", re.I)


def _smart_sql(query: str, intent: str) -> str:
    """Use reliable hardcoded SQL for known query patterns; fall back to LLM."""
    q = query.lower()

    # Pattern 1: free vs paid ratings comparison
    if FREE_VS_PAID_RE.search(q) or ("free" in q and "paid" in q and "rating" in q):
        return (
            "SELECT is_free, "
            "ROUND(AVG(rating), 2) AS avg_rating, "
            "COUNT(*) AS game_count "
            "FROM games WHERE rating IS NOT NULL "
            "GROUP BY is_free ORDER BY is_free"
        )

    # Pattern 2: action games with Korean
    if ACTION_KOREAN_RE.search(q) or ("action" in q and "korean" in q):
        return (
            "SELECT COUNT(*) AS count FROM games "
            "WHERE LOWER(genre) LIKE '%action%' "
            "AND LOWER(languages) LIKE '%korean%'"
        )

    # Pattern 3: multiplayer shooters after a year
    if SHOOTER_MULTI_RE.search(q) or ("shooter" in q and ("after" in q or "2015" in q)):
        year_match = re.search(r"\b(201[0-9]|202[0-4])\b", q)
        year = int(year_match.group(1)) if year_match else 2015
        return (
            f"SELECT appid, name, rating, genre, release_year, price_usd, developer "
            f"FROM games "
            f"WHERE (LOWER(tags) LIKE '%shooter%' OR LOWER(tags) LIKE '%fps%') "
            f"AND has_multiplayer=1 "
            f"AND release_year > {year} "
            f"ORDER BY rating DESC LIMIT 20"
        )

    # Pattern 4: Counter-Strike price
    if COUNTER_STRIKE_RE.search(q) or ("counter" in q and ("price" in q or "inr" in q or "usd" in q)):
        return (
            "SELECT appid, name, price_usd, developer, genre, rating "
            "FROM games "
            "WHERE LOWER(name) LIKE '%counter-strike%' "
            "OR LOWER(name) LIKE '%counter strike%' "
            "ORDER BY positive DESC LIMIT 5"
        )

    # Default: LLM-generated SQL
    return _build_sql(query, intent)


# ── LLM SQL builder (fallback) ────────────────────────────────────────────────

def _build_sql(query: str, intent: str) -> str:
    system = (
        "You are a SQLite expert. Write ONE valid SQLite SELECT query for the user question.\n"
        "Rules:\n"
        "- Output ONLY raw SQL, no markdown fences, no explanation.\n"
        "- Use LOWER() for all string comparisons.\n"
        "- Never invent column names — use only columns listed in the schema.\n"
        "- For aggregations (AVG, COUNT) always give the result an alias.\n"
        "- Default LIMIT 20 for list queries, no limit for aggregations.\n"
        "- For free vs paid comparisons use: GROUP BY is_free\n"
        "- For language filters use: LOWER(languages) LIKE '%korean%'\n"
        "- For genre filters use: LOWER(genre) LIKE '%action%'\n"
        "- For game name search use: LOWER(name) LIKE '%counter%'\n"
        "- price_usd is already in USD dollars.\n"
        f"\n{SCHEMA_DESCRIPTION}"
    )
    user_msg = f"User question: {query}\n\nSQL:"

    resp = _groq().chat.completions.create(
        model=MODEL,
        messages=[{"role": "system", "content": system},
                  {"role": "user",   "content": user_msg}],
        max_tokens=300,
        temperature=0.0,
    )
    sql = resp.choices[0].message.content.strip()
    sql = re.sub(r"```[a-z]*\n?", "", sql).strip().rstrip("`").strip()
    return sql


# ── Answer generator ──────────────────────────────────────────────────────────

def _generate_answer(query: str, intent: str, rows: list,
                     extra_context: str = "", history_text: str = "") -> str:
    # Strip heavy text columns before serialising to avoid token overflow
    _heavy = {"tags", "short_description", "detailed_description", "about_the_game", "supported_languages"}
    clean_rows = [
        {k: v for k, v in row.items() if k not in _heavy}
        for row in (rows[:20] if rows else [])
    ]
    data_str = json.dumps(clean_rows, default=str) if clean_rows else "No results found."

    system = (
        "You are NEXUS, a friendly and precise game analytics assistant for Steam game data.\n"
        "Rules:\n"
        "- Answer using ONLY the data provided — never invent numbers or game names.\n"
        "- Be concise and direct.\n"
        "- For comparisons, clearly state both values.\n"
        "- For lists, mention the top items by name.\n"
        "- If no data was found, say so and suggest rephrasing.\n"
        "- Format numbers nicely (e.g. 7.20/10, $9.99, ₹831).\n"
    )

    ctx = ""
    if history_text:
        ctx += f"\nConversation history:\n{history_text}\n"
    if extra_context:
        ctx += f"\nExtra context:\n{extra_context}\n"

    user_msg = (
        f"Question: {query}\n"
        f"Intent: {intent}\n"
        f"Data:\n{data_str}"
        f"{ctx}\n"
        f"Answer:"
    )

    resp = _groq().chat.completions.create(
        model=MODEL,
        messages=[{"role": "system", "content": system},
                  {"role": "user",   "content": user_msg}],
        max_tokens=500,
        temperature=0.2,
    )
    return resp.choices[0].message.content.strip()


# ── Main entry point ──────────────────────────────────────────────────────────

def process_query(query: str, conn: sqlite3.Connection,
                  df: pd.DataFrame, schema: dict,
                  session_id: str = None) -> dict:
    t0 = time.time()

    if not session_id:
        session_id = new_session()
    history_text = history_as_text(session_id)

    intent = classify_intent(query)

    # ── Irrelevant query ──────────────────────────────────────────────────────
    if intent == "irrelevant":
        response_text = (
            "I'm NEXUS, a game analytics assistant for Steam game data. "
            "I can answer questions about game prices, ratings, genres, language support, "
            "multiplayer features, release years, and more. "
            "Please ask me something about games!"
        )
        add_turn(session_id, query, response_text)
        return {
            "response": response_text,
            "metadata": {
                "query_type": "irrelevant",
                "confidence_score": 1.0,
                "games": [],
                "total_results": 0,
                "statistics": {},
                "session_id": session_id,
                "execution_time_ms": int((time.time() - t0) * 1000),
            },
        }

    rows = []
    extra_context = ""
    currency_info = {}
    sql_used = ""
    error_msg = None
    statistics = {}

    try:
        # ── Reliable pre-built SQL for known query patterns ───────────────────
        sql_used = _smart_sql(query, intent)
        rows = run_query(conn, sql_used)

        if rows and "error" in rows[0]:
            error_msg = rows[0]["error"]
            # Fallback: simpler SQL
            sql_used = _build_sql(f"Simple version: {query}", intent)
            rows = run_query(conn, sql_used)
            if rows and "error" in rows[0]:
                rows = []

        # ── Currency conversion ───────────────────────────────────────────────
        if intent == "currency" or CURRENCY_RE.search(query):
            currencies = _extract_currencies(query)
            price_found = 0.0
            for row in rows[:5]:
                for key in ["price_usd", "price", "initialprice"]:
                    val = row.get(key, 0)
                    try:
                        v = float(val)
                        # initialprice is in cents if >100 and price_usd not present
                        if key == "initialprice" and v > 100:
                            v = v / 100
                        if v > 0:
                            price_found = v
                            break
                    except (TypeError, ValueError):
                        pass
                if price_found:
                    break

            if price_found > 0:
                currency_info = convert_multiple(price_found, currencies)
                parts = [v["display"] for v in currency_info.values() if "display" in v]
                extra_context += f"Price conversions: {', '.join(parts)}. "
            else:
                extra_context += "Price not found in dataset for this game. "

        # ── Statistics ────────────────────────────────────────────────────────
        if rows and intent in ("statistics", "comparison"):
            for k, v in rows[0].items():
                if isinstance(v, (int, float)):
                    statistics[k] = v

    except Exception as exc:
        error_msg = str(exc)

    # ── Generate answer ───────────────────────────────────────────────────────
    try:
        answer = _generate_answer(query, intent, rows, extra_context, history_text)
    except Exception as exc:
        answer = f"I had trouble generating an answer: {exc}. Please try again."

    # ── Confidence score ──────────────────────────────────────────────────────
    if error_msg:
        confidence = 0.2
    elif not rows:
        confidence = 0.3
    else:
        confidence = round(min(0.6 + 0.4 * (len(rows) / 10), 1.0), 2)

    result = {
        "response": answer,
        "metadata": {
            "query_type": intent,
            "confidence_score": confidence,
            "games": rows[:10],
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
