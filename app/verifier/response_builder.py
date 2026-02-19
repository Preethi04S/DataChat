from __future__ import annotations
import json
from app.planner.models import QueryPlan, Intent
from app.data.schema import DatasetSchema
from app.core.config import GROQ_API_KEY, GROQ_MODEL, LLM_MODE
from app.core.logging import get_logger
from app.verifier.verifier import verify_all

logger = get_logger(__name__)

RESPONSE_SYSTEM_PROMPT = """You are a helpful assistant that describes CSV query results in natural language.

RULES:
- Only mention books/items that appear in the provided results.
- Do not mention any book title, author, or value not present in the data.
- Be concise and informative.
- If results are empty, say you couldn't find matching results.
- Format numbers clearly.
- Do not invent or hallucinate any data.
- Keep the response under 200 words."""


def build_response(
    question: str,
    plan: QueryPlan,
    metadata: list[dict],
    schema: DatasetSchema,
) -> str:
    if not metadata:
        return "I couldn't find any books matching your query in the dataset."

    display_col = schema.display_column
    is_aggregation = plan.aggregation and (plan.aggregation.groupby or plan.aggregation.metrics)

    if is_aggregation:
        response = _build_aggregation_response(metadata, plan, schema)
    elif plan.intent in (Intent.rank, Intent.lookup, Intent.filter):
        response = _build_list_response(metadata, display_col, plan, schema)
    else:
        response = _build_list_response(metadata, display_col, plan, schema)

    if LLM_MODE != "stub" and GROQ_API_KEY:
        humanized = _humanize_with_llm(question, response, metadata, display_col)
        if humanized:
            verification = verify_all(humanized, metadata, display_col)
            if verification.passed:
                return humanized
            else:
                logger.warning(f"LLM response failed verification: {verification.reason}. Using template.")

    verification = verify_all(response, metadata, display_col)
    if not verification.passed:
        logger.warning(f"Template response failed verification: {verification.reason}")
        if metadata:
            return "I found matching results in the dataset. Please see the metadata for details."
        return "I couldn't produce a verified response. See the metadata table for results."

    return response


def _build_list_response(metadata: list[dict], display_col: str, plan: QueryPlan, schema: DatasetSchema) -> str:
    count = len(metadata)

    if plan.intent == Intent.rank and plan.sort:
        sort_col = plan.sort.column
        direction = "highest" if plan.sort.direction == "desc" else "lowest"
        items = []
        for i, row in enumerate(metadata, 1):
            name = row.get(display_col, "Unknown")
            val = row.get(sort_col, "N/A")
            items.append(f"{i}. \"{name}\" ({sort_col}: {val})")
        header = f"Here are the top {count} books by {direction} {sort_col}:"
        return header + "\n" + "\n".join(items)

    if count == 1:
        row = metadata[0]
        name = row.get(display_col, "Unknown")
        parts = [f"\"{name}\""]
        for col in schema.column_names:
            if col != display_col and col in row and row[col] is not None:
                parts.append(f"{col}: {row[col]}")
        return f"Found: {', '.join(parts)}"

    items = []
    for i, row in enumerate(metadata, 1):
        name = row.get(display_col, "Unknown")
        items.append(f"{i}. \"{name}\"")
    header = f"Found {count} matching books:"
    return header + "\n" + "\n".join(items)


def _build_aggregation_response(metadata: list[dict], plan: QueryPlan, schema: DatasetSchema) -> str:
    if not plan.aggregation:
        return "Aggregation results are available in the metadata."

    agg_cols = [c for c in metadata[0].keys() if c.startswith("__agg__")] if metadata else []
    groupby = plan.aggregation.groupby

    if not groupby:
        parts = []
        if metadata:
            for key, val in metadata[0].items():
                if key.startswith("__agg__"):
                    label = key.replace("__agg__", "").replace("_", " ")
                    parts.append(f"{label}: {val}")
        return "Aggregation results: " + ", ".join(parts) if parts else "No aggregation results."

    lines = [f"Results grouped by {', '.join(groupby)}:"]
    for row in metadata:
        group_vals = [f"{g}={row.get(g, 'N/A')}" for g in groupby]
        agg_vals = []
        for col in agg_cols:
            label = col.replace("__agg__", "").replace("_", " ")
            agg_vals.append(f"{label}: {row.get(col, 'N/A')}")
        lines.append(f"  {', '.join(group_vals)} -> {', '.join(agg_vals)}")

    return "\n".join(lines)


def _humanize_with_llm(question: str, template_response: str, metadata: list[dict], display_col: str) -> str | None:
    try:
        import httpx

        facts = json.dumps(metadata[:10], default=str)
        user_msg = (
            f"User question: {question}\n\n"
            f"Computed answer (template): {template_response}\n\n"
            f"Raw data (first 10 rows): {facts}\n\n"
            f"Rewrite the template answer in a more natural, friendly way. "
            f"You MUST only mention items that appear in the raw data. "
            f"Do NOT add any books or values not present in the data."
        )

        body = {
            "model": GROQ_MODEL,
            "messages": [
                {"role": "system", "content": RESPONSE_SYSTEM_PROMPT},
                {"role": "user", "content": user_msg},
            ],
            "temperature": 0,
            "max_tokens": 512,
        }

        headers = {
            "Authorization": f"Bearer {GROQ_API_KEY}",
            "Content-Type": "application/json",
        }

        resp = httpx.post(
            "https://api.groq.com/openai/v1/chat/completions",
            json=body,
            headers=headers,
            timeout=15.0,
        )
        resp.raise_for_status()
        return resp.json()["choices"][0]["message"]["content"].strip()

    except Exception as e:
        logger.warning(f"LLM humanization failed: {e}")
        return None
