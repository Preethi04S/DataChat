from __future__ import annotations
import time
import uuid
import math
from fastapi import APIRouter, HTTPException, UploadFile, File
from pydantic import BaseModel, Field
import pandas as pd

from app.core.config import (
    MAX_QUESTION_LENGTH, GROQ_API_KEY, GROQ_MODEL, LLM_MODE,
    ALLOWED_UPLOAD_EXTENSIONS, MAX_UPLOAD_SIZE_MB,
)
from app.core.logging import get_logger
from app.core.rate_limit import rate_limiter
from app.core.cache import plan_cache, DeterministicCache
from app.core.audit import append_audit_entry
from app.core.metrics import pipeline_metrics
from app.core.security import sanitize_input, detect_injection_attempt, validate_filename
from app.core.conversation import conversation_manager, ConversationTurn
from app.data.loader import get_df, get_schema, load_from_bytes, get_dataset_name, get_cleaning_report
from app.data.fingerprint import get_dataset_hash
from app.data.profiler import profile_dataset
from app.planner.groq_planner import create_plan
from app.planner.validator import validate_plan, ValidationError
from app.executor.executor import execute_plan, ExecutionError
from app.verifier.response_builder import build_response
from app.verifier.verifier import verify_all

logger = get_logger(__name__)

router = APIRouter()


class AskRequest(BaseModel):
    question: str = Field(..., min_length=1, max_length=MAX_QUESTION_LENGTH)
    session_id: str = Field(default="", max_length=64)


class AskResponse(BaseModel):
    response: str
    metadata: list[dict]
    request_id: str = ""
    intent: str = ""
    cached: bool = False
    elapsed_ms: int = 0


@router.post("/ask", response_model=AskResponse)
def ask(req: AskRequest):
    if not rate_limiter.consume():
        pipeline_metrics.increment("rate_limited")
        raise HTTPException(status_code=429, detail="Rate limit exceeded. Try again shortly.")

    pipeline_metrics.increment("total_queries")
    request_id = str(uuid.uuid4())
    start = time.monotonic()
    question = sanitize_input(req.question)

    # ── Security: Injection Detection ──
    is_suspicious, reason = detect_injection_attempt(req.question)
    if is_suspicious:
        pipeline_metrics.increment("injection_attempts")
        logger.warning(f"Injection attempt detected: {reason} | question={req.question[:100]}")

    if not question:
        raise HTTPException(status_code=400, detail="Question cannot be empty.")

    schema = get_schema()
    df = get_df()
    dataset_hash = get_dataset_hash()

    try:
        plan = create_plan(question, schema)
        plan = validate_plan(plan, schema)
    except ValidationError as e:
        logger.warning(f"Plan validation failed: {e}")
        _audit(request_id, dataset_hash, None, 0, 0, False, "validation_error", start)
        return AskResponse(
            response=f"I couldn't build a valid query for your question. {str(e)}",
            metadata=[],
        )
    except Exception as e:
        logger.error(f"Planning failed: {e}")
        _audit(request_id, dataset_hash, None, 0, 0, False, "plan_error", start)
        return AskResponse(
            response="I encountered an error while processing your question. Please try rephrasing.",
            metadata=[],
        )

    plan_dict = plan.model_dump()
    cache_key = DeterministicCache.make_key(dataset_hash, plan_dict)
    cached = plan_cache.get(cache_key)

    if cached is not None:
        logger.info(f"Cache hit for request {request_id}")
        pipeline_metrics.increment("cache_hits")
        elapsed_ms = round((time.monotonic() - start) * 1000)
        _audit(request_id, dataset_hash, plan_dict, cached.get("rows_scanned", 0),
               len(cached["result"]["metadata"]), True, cached.get("verify_status", "ok"), start)
        return AskResponse(
            **cached["result"],
            request_id=request_id,
            intent=plan.intent.value if hasattr(plan.intent, "value") else str(plan.intent),
            cached=True,
            elapsed_ms=elapsed_ms,
        )

    try:
        metadata = execute_plan(plan, df, schema)
    except ExecutionError as e:
        logger.error(f"Execution failed: {e}")
        _audit(request_id, dataset_hash, plan_dict, len(df), 0, False, "execution_error", start)
        return AskResponse(
            response=f"I couldn't execute the query: {str(e)}",
            metadata=[],
        )

    response_text = build_response(question, plan, metadata, schema)

    verification = verify_all(response_text, metadata, schema.display_column)
    verify_status = "ok" if verification.passed else "failed"

    if not verification.passed:
        logger.warning(f"Final verification failed: {verification.reason}")
        response_text = "I found matching results but cannot safely verbalize details. See the metadata table."
        verify_status = "fail_closed"

    elapsed_ms = round((time.monotonic() - start) * 1000)
    result = {"response": response_text, "metadata": metadata}

    plan_cache.put(cache_key, {
        "result": result,
        "rows_scanned": len(df),
        "verify_status": verify_status,
        "elapsed_ms": elapsed_ms,
    })

    # ── Metrics & Conversation Tracking ──
    pipeline_metrics.record_latency("ask_endpoint", elapsed_ms)
    pipeline_metrics.increment(f"intent_{plan.intent.value}" if hasattr(plan.intent, "value") else f"intent_{plan.intent}")
    if verify_status != "ok":
        pipeline_metrics.increment("verification_failures")

    if req.session_id:
        session = conversation_manager.get_or_create(req.session_id)
        session.add_turn(ConversationTurn(
            question=question,
            plan_intent=plan.intent.value if hasattr(plan.intent, "value") else str(plan.intent),
            columns_used=[f.column for f in plan.filters] + ([plan.sort.column] if plan.sort else []),
            filters_used=[f"{f.column} {f.op}" for f in plan.filters],
            result_count=len(metadata),
        ))

    _audit(request_id, dataset_hash, plan_dict, len(df), len(metadata), False, verify_status, start)
    return AskResponse(
        **result,
        request_id=request_id,
        intent=plan.intent.value if hasattr(plan.intent, "value") else str(plan.intent),
        cached=False,
        elapsed_ms=elapsed_ms,
    )


@router.get("/health")
def health():
    try:
        schema = get_schema()
        return {
            "status": "ok",
            "dataset_loaded": True,
            "rows": schema.row_count,
            "columns": len(schema.columns),
        }
    except Exception:
        return {"status": "ok", "dataset_loaded": False}


@router.get("/schema")
def schema_endpoint():
    try:
        schema = get_schema()
        return schema.to_dict()
    except RuntimeError:
        raise HTTPException(status_code=503, detail="Dataset not loaded")


@router.get("/examples")
def examples():
    try:
        schema = get_schema()
    except RuntimeError:
        raise HTTPException(status_code=503, detail="Dataset not loaded")

    questions = _generate_examples(schema)
    return {"examples": questions}


@router.post("/upload")
async def upload_file(file: UploadFile = File(...)):
    MAX_FILE_SIZE = MAX_UPLOAD_SIZE_MB * 1024 * 1024

    filename = file.filename or "upload"

    # ── Security: Validate filename ──
    valid, reason = validate_filename(filename)
    if not valid:
        pipeline_metrics.increment("upload_rejected")
        raise HTTPException(status_code=400, detail=f"Invalid filename: {reason}")

    ext = filename.rsplit(".", 1)[-1].lower() if "." in filename else ""

    if ext not in ALLOWED_UPLOAD_EXTENSIONS:
        pipeline_metrics.increment("upload_rejected")
        raise HTTPException(
            status_code=400,
            detail=f"Unsupported file type: .{ext}. Allowed: {', '.join(sorted(ALLOWED_UPLOAD_EXTENSIONS))}",
        )

    content = await file.read()
    if len(content) > MAX_FILE_SIZE:
        raise HTTPException(status_code=400, detail="File too large. Maximum size is 50 MB.")

    if len(content) == 0:
        raise HTTPException(status_code=400, detail="File is empty.")

    try:
        df, schema = load_from_bytes(content, filename)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        logger.error(f"Upload failed: {e}")
        raise HTTPException(status_code=400, detail=f"Failed to parse file: {str(e)}")

    plan_cache.clear()

    return {
        "status": "ok",
        "filename": filename,
        "rows": schema.row_count,
        "columns": len(schema.columns),
        "display_column": schema.display_column,
    }


@router.get("/dataset-info")
def dataset_info():
    try:
        schema = get_schema()
        return {
            "name": get_dataset_name(),
            "rows": schema.row_count,
            "columns": len(schema.columns),
            "display_column": schema.display_column,
        }
    except RuntimeError:
        return {"name": "none", "rows": 0, "columns": 0, "display_column": ""}


class RecommendRequest(BaseModel):
    title: str = Field(..., min_length=1, max_length=300)
    count: int = Field(default=5, ge=1, le=20)


@router.post("/recommend")
def recommend(req: RecommendRequest):
    """Find similar books based on a book title — matches by author, category, and rating."""
    try:
        schema = get_schema()
        df = get_df()
    except RuntimeError:
        raise HTTPException(status_code=503, detail="Dataset not loaded")

    display_col = schema.display_column
    if not display_col:
        return {"recommendations": [], "based_on": None}

    # Find the source book
    mask = df[display_col].astype(str).str.lower().str.contains(req.title.lower(), na=False)
    matches = df[mask]
    if matches.empty:
        return {"recommendations": [], "based_on": None}

    source = matches.iloc[0]
    source_dict = {k: (v if not (isinstance(v, float) and str(v) == "nan") else None) for k, v in source.to_dict().items()}

    # Find similar books
    author_col = next((c for c in schema.string_columns if "author" in c.lower()), None)
    category_col = next((c for c in schema.string_columns if any(x in c.lower() for x in ["categor", "genre"])), None)
    rating_col = next((c for c in schema.numeric_columns if "rating" in c.lower() and "count" not in c.lower()), None)

    scores = df.copy()
    scores["__score__"] = 0.0

    if author_col and source.get(author_col):
        scores.loc[scores[author_col] == source[author_col], "__score__"] += 3.0
    if category_col and source.get(category_col):
        scores.loc[scores[category_col] == source[category_col], "__score__"] += 2.0
    if rating_col:
        src_rating = source.get(rating_col, 0)
        if src_rating and src_rating > 0:
            scores["__score__"] += (1.0 - (scores[rating_col] - src_rating).abs() / 5.0).clip(0, 1)

    # Exclude the source book itself
    scores = scores[scores[display_col] != source[display_col]]
    scores = scores[scores["__score__"] > 0].sort_values("__score__", ascending=False).head(req.count)

    recs = []
    for _, row in scores.iterrows():
        rec = {k: (v if not (isinstance(v, float) and str(v) == "nan") else None) for k, v in row.to_dict().items()}
        rec.pop("__score__", None)
        recs.append(rec)

    return {"recommendations": recs, "based_on": source_dict}


def _generate_examples(schema) -> list[dict]:
    examples = []

    rating_col = None
    for col in schema.numeric_columns:
        if "rating" in col.lower() and "count" not in col.lower():
            rating_col = col
            break

    count_col = None
    for col in schema.numeric_columns:
        if "count" in col.lower() or "reviews" in col.lower():
            count_col = col
            break

    pages_col = None
    for col in schema.numeric_columns:
        if "page" in col.lower():
            pages_col = col
            break

    year_col = None
    for col in schema.numeric_columns:
        if "year" in col.lower():
            year_col = col
            break

    author_col = None
    for col in schema.string_columns:
        if "author" in col.lower():
            author_col = col
            break

    category_col = None
    for col in schema.string_columns:
        if any(x in col.lower() for x in ["categor", "genre"]):
            category_col = col
            break

    display_col = schema.display_column

    if rating_col:
        examples.append({
            "question": f"Give me top 5 books with best {rating_col.replace('_', ' ')}",
            "rationale": "Rank query: sorts by rating descending, limits to 5",
        })

    if rating_col:
        examples.append({
            "question": f"Which books have {rating_col.replace('_', ' ')} above 4.5?",
            "rationale": "Filter query: filters rows where rating > 4.5",
        })

    if author_col:
        examples.append({
            "question": f"Show me books by Agatha Christie",
            "rationale": "Lookup query: filters by author name",
        })

    if category_col and rating_col:
        examples.append({
            "question": f"What is the average {rating_col.replace('_', ' ')} by {category_col.replace('_', ' ')}?",
            "rationale": "Aggregation query: groups by category, computes mean rating",
        })

    if year_col:
        examples.append({
            "question": f"Show me books published between 2000 and 2010",
            "rationale": "Range filter query: uses between operator on year",
        })

    if pages_col:
        examples.append({
            "question": f"What are the longest books by {pages_col.replace('_', ' ')}?",
            "rationale": "Rank query: sorts by page count descending",
        })

    if count_col:
        examples.append({
            "question": f"Which books have the most {count_col.replace('_', ' ')}?",
            "rationale": "Rank query: sorts by popularity metric descending",
        })

    examples.append({
        "question": "How many books are in the dataset?",
        "rationale": "Aggregation query: counts total rows",
    })

    if author_col and rating_col:
        examples.append({
            "question": f"Who are the top 10 authors by average {rating_col.replace('_', ' ')}?",
            "rationale": "Grouped aggregation: groups by author, averages rating",
        })

    return examples


@router.get("/analytics")
def analytics():
    """Return dataset-level analytics for the dashboard."""
    try:
        schema = get_schema()
        df = get_df()
    except RuntimeError:
        raise HTTPException(status_code=503, detail="Dataset not loaded")

    result = {
        "total_books": int(len(df)),
        "total_authors": 0,
        "total_categories": 0,
        "avg_rating": None,
        "avg_pages": None,
        "year_range": None,
        "top_authors": [],
        "rating_distribution": [],
    }

    # Authors
    author_col = next((c for c in schema.string_columns if "author" in c.lower()), None)
    if author_col:
        unique_authors = df[author_col].dropna().nunique()
        result["total_authors"] = int(unique_authors)
        top_authors = df[author_col].dropna().value_counts().head(10)
        result["top_authors"] = [{"name": str(name), "count": int(count)} for name, count in top_authors.items()]

    # Categories
    category_col = next((c for c in schema.string_columns if any(x in c.lower() for x in ["categor", "genre"])), None)
    if category_col:
        result["total_categories"] = int(df[category_col].dropna().nunique())

    # Rating
    rating_col = next((c for c in schema.numeric_columns if "rating" in c.lower() and "count" not in c.lower()), None)
    if rating_col:
        numeric_ratings = pd.to_numeric(df[rating_col], errors="coerce")
        avg = numeric_ratings.mean()
        if not math.isnan(avg):
            result["avg_rating"] = round(float(avg), 2)
        # Rating distribution
        bins = [0, 1, 2, 3, 4, 5]
        labels = ["0-1", "1-2", "2-3", "3-4", "4-5"]
        cuts = pd.cut(numeric_ratings.dropna(), bins=bins, labels=labels, right=True)
        dist = cuts.value_counts().sort_index()
        result["rating_distribution"] = [{"range": str(r), "count": int(c)} for r, c in dist.items() if c > 0]

    # Pages
    pages_col = next((c for c in schema.numeric_columns if "page" in c.lower()), None)
    if pages_col:
        numeric_pages = pd.to_numeric(df[pages_col], errors="coerce")
        avg_pages = numeric_pages.mean()
        if not math.isnan(avg_pages):
            result["avg_pages"] = round(float(avg_pages), 1)

    # Year range
    year_col = next((c for c in schema.numeric_columns if "year" in c.lower()), None)
    if year_col:
        numeric_years = pd.to_numeric(df[year_col], errors="coerce").dropna()
        if len(numeric_years) > 0:
            min_year = int(numeric_years.min())
            max_year = int(numeric_years.max())
            result["year_range"] = f"{min_year}-{max_year}"

    return result


class FollowUpRequest(BaseModel):
    question: str = Field(..., min_length=1, max_length=500)
    response: str = Field(default="")
    metadata_count: int = Field(default=0)


@router.post("/suggest-followups")
def suggest_followups(req: FollowUpRequest):
    """Generate smart follow-up question suggestions based on the previous query."""
    try:
        schema = get_schema()
    except RuntimeError:
        raise HTTPException(status_code=503, detail="Dataset not loaded")

    followups = _generate_followups(req.question, req.response, req.metadata_count, schema)
    return {"followups": followups}


def _generate_followups(question: str, response: str, metadata_count: int, schema) -> list[str]:
    """Generate follow-up suggestions. Uses LLM if available, otherwise rule-based."""
    # Try LLM-based suggestions first
    if LLM_MODE != "stub" and GROQ_API_KEY:
        try:
            return _llm_followups(question, response, metadata_count, schema)
        except Exception as e:
            logger.warning(f"LLM follow-up generation failed: {e}")

    # Rule-based fallback
    return _rule_based_followups(question, schema)


def _llm_followups(question: str, response: str, metadata_count: int, schema) -> list[str]:
    import httpx
    import json

    col_info = ", ".join([f"{c.name} ({c.dtype})" for c in schema.columns])

    body = {
        "model": GROQ_MODEL,
        "messages": [
            {
                "role": "system",
                "content": (
                    "You suggest 3 follow-up questions for a dataset Q&A chatbot. "
                    "Return ONLY a JSON array of 3 short question strings. No explanation. "
                    f"Dataset columns: {col_info}. "
                    "Questions should be different from the original and explore related aspects."
                ),
            },
            {
                "role": "user",
                "content": f"Original question: {question}\nResults found: {metadata_count}\nSuggest 3 follow-ups:",
            },
        ],
        "temperature": 0.7,
        "max_tokens": 200,
    }

    headers = {
        "Authorization": f"Bearer {GROQ_API_KEY}",
        "Content-Type": "application/json",
    }

    resp = httpx.post(
        "https://api.groq.com/openai/v1/chat/completions",
        json=body,
        headers=headers,
        timeout=8.0,
    )
    resp.raise_for_status()
    content = resp.json()["choices"][0]["message"]["content"].strip()

    # Parse JSON array from response
    if content.startswith("["):
        suggestions = json.loads(content)
    else:
        # Try to extract JSON array from text
        start = content.find("[")
        end = content.rfind("]") + 1
        if start >= 0 and end > start:
            suggestions = json.loads(content[start:end])
        else:
            return _rule_based_followups(question, schema)

    return [str(s).strip() for s in suggestions[:3] if isinstance(s, str) and len(s.strip()) > 5]


def _rule_based_followups(question: str, schema) -> list[str]:
    """Generate rule-based follow-up suggestions from schema."""
    followups = []
    q_lower = question.lower()

    display_col = schema.display_column
    rating_col = next((c for c in schema.numeric_columns if "rating" in c.lower() and "count" not in c.lower()), None)
    author_col = next((c for c in schema.string_columns if "author" in c.lower()), None)
    category_col = next((c for c in schema.string_columns if any(x in c.lower() for x in ["categor", "genre"])), None)
    year_col = next((c for c in schema.numeric_columns if "year" in c.lower()), None)
    pages_col = next((c for c in schema.numeric_columns if "page" in c.lower()), None)

    if "top" in q_lower or "best" in q_lower:
        if rating_col:
            followups.append(f"What about the lowest rated books?")
        if author_col:
            followups.append(f"Which author has the most books?")
    elif "author" in q_lower:
        if rating_col:
            followups.append(f"What is the average rating for this author?")
        if category_col:
            followups.append(f"What categories do they write in?")
    elif "categor" in q_lower or "genre" in q_lower:
        if rating_col:
            followups.append(f"Which category has the highest average rating?")
        followups.append(f"How many books are in each category?")
    elif "year" in q_lower or "published" in q_lower:
        if rating_col:
            followups.append(f"Which year had the best average rating?")
        followups.append(f"How many books were published per year?")

    # Generic fallbacks
    if len(followups) < 3:
        generic = [
            f"Show me the top 10 highest rated books" if rating_col else None,
            f"How many books does each author have?" if author_col else None,
            f"What are the longest books in the dataset?" if pages_col else None,
            f"Show books published after 2015" if year_col else None,
            f"What is the average rating by category?" if rating_col and category_col else None,
            f"How many books are in the dataset?",
        ]
        for g in generic:
            if g and g not in followups and len(followups) < 3:
                # Skip if too similar to original question
                if g.lower()[:20] != question.lower()[:20]:
                    followups.append(g)

    return followups[:3]


@router.get("/metrics")
def metrics_endpoint():
    """Expose pipeline metrics for observability dashboards."""
    return pipeline_metrics.get_summary()


@router.get("/data-quality")
def data_quality():
    """Return comprehensive data quality profile for the loaded dataset."""
    try:
        df = get_df()
        schema = get_schema()
    except RuntimeError:
        raise HTTPException(status_code=503, detail="Dataset not loaded")

    report = profile_dataset(df, schema)
    return {
        "dataset": get_dataset_name(),
        "rows": schema.row_count,
        "columns": len(schema.columns),
        "profile": report.to_dict(),
    }


@router.get("/cleaning-report")
def cleaning_report_endpoint():
    """Return the data cleaning report from the last dataset load.

    Shows all anomalies detected and fixes applied:
    - Shifted/misaligned columns
    - Type mismatches
    - Logical inconsistencies (e.g. rating without reviews)
    - Outliers (IQR-based detection and winsorization)
    - Placeholder descriptions
    - Duplicate rows
    - Text standardization
    """
    report = get_cleaning_report()
    if report is None:
        raise HTTPException(status_code=503, detail="No cleaning report available. Dataset not loaded.")
    return report


@router.get("/session/{session_id}/history")
def session_history(session_id: str):
    """Retrieve conversation history for a session."""
    if len(session_id) > 64:
        raise HTTPException(status_code=400, detail="Invalid session ID")
    session = conversation_manager.get_or_create(session_id)
    return {
        "session_id": session_id,
        "turns": [
            {
                "question": t.question,
                "intent": t.plan_intent,
                "columns_used": t.columns_used,
                "result_count": t.result_count,
                "timestamp": t.timestamp if hasattr(t, "timestamp") else None,
            }
            for t in session.turns
        ],
        "turn_count": len(session.turns),
    }


def _audit(request_id, dataset_hash, plan, rows_scanned, rows_returned, cache_hit, verify_status, start):
    elapsed_ms = (time.monotonic() - start) * 1000
    try:
        append_audit_entry(
            request_id=request_id,
            dataset_hash=dataset_hash,
            normalized_plan=plan,
            rows_scanned=rows_scanned,
            rows_returned=rows_returned,
            cache_hit=cache_hit,
            verify_status=verify_status,
            elapsed_ms=elapsed_ms,
        )
    except Exception as e:
        logger.error(f"Audit logging failed: {e}")
