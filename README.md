# DataChat AI - Enterprise CSV Analytics Chatbot

A proof-carrying CSV chatbot with verifiable, audit-ready answers. Ask natural language questions about a books dataset and get grounded, verified responses powered by Groq LLM.

## How to Run (Quick Start)

> **Prerequisites**: Python 3.10+ installed on your machine.

### Step 1: Clone the repository

```bash
git clone https://github.com/Preethi04S/datachat-ai.git
cd datachat-ai
```

### Step 2: Create a virtual environment (recommended)

```bash
# On Windows
python -m venv .venv
.venv\Scripts\activate

# On macOS/Linux
python3 -m venv .venv
source .venv/bin/activate
```

### Step 3: Install dependencies

```bash
pip install -r requirements.txt
```

### Step 4: Run the server

```bash
uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload
```

### Step 5: Open the UI

Open your browser and go to: **http://localhost:8000**

The `.env` file and `data/books.csv` dataset are already included in the repository, so no additional setup is needed.

### Step 6: Try it out

Type a natural language question in the chat, for example:
- "Give me top 5 books with best average rating"
- "Which books have average rating above 4.5?"
- "Show me books by Agatha Christie"
- "What is the average rating by categories?"
- "How many books are in the dataset?"

## Architecture

```
Question -> Groq LLM (QueryPlan) -> Validator -> Executor -> Verifier -> Response
```

- **LLM produces constrained JSON plans only** (no code generation)
- **Plans are validated** against the actual CSV schema
- **Execution is deterministic** (pandas)
- **Responses are verified**: every book mentioned must exist in the returned data
- **Fail-closed**: unverifiable responses are replaced with safe fallbacks

See [DESIGN.md](DESIGN.md) for full architecture, feature set (25+), and threat model.

## UI Features

The UI has four tabs:
- **Chat**: Ask questions and see results with metadata tables, charts, and follow-up suggestions
- **Schema**: View inferred column types, missingness, and sample values
- **Examples**: Click pre-generated questions to run them
- **Analytics**: Interactive dashboard with dataset statistics and visualizations

Additional features:
- Dark/Light Theme toggle
- Voice Input (speech-to-text)
- Text-to-Speech for responses
- Bookmarks for favorite queries
- Book Detail Modal (click any table row)
- AI-powered follow-up suggestions
- Export Chat as Markdown
- Export Results as CSV or JSON
- Smart Book Recommendations
- Auto-generated charts for numeric results

## API Endpoints

| Method | Path | Description |
|--------|------|-------------|
| POST | /ask | Ask a question. Body: `{"question": "..."}` |
| GET | /health | Health check and dataset status |
| GET | /schema | Inferred schema with types and missingness |
| GET | /examples | Example questions derived from schema |
| POST | /upload | Upload new dataset (CSV, JSON, Excel, TSV, Parquet) |
| POST | /recommend | Find similar books by title |
| GET | /dataset-info | Current dataset metadata |
| GET | /analytics | Dataset-level statistics and distributions |
| POST | /suggest-followups | AI-powered follow-up suggestions |
| GET | /metrics | Pipeline observability metrics |
| GET | /data-quality | Data quality profiling report |
| GET | /cleaning-report | Data cleaning actions report |
| GET | /session/{id}/history | Conversation history for a session |

### API Documentation

FastAPI auto-generated docs at: **http://localhost:8000/docs**

### Example curl requests

```bash
# Top rated books
curl -X POST http://localhost:8000/ask \
  -H "Content-Type: application/json" \
  -d '{"question": "Give me top 5 books with best average rating"}'

# Filter by rating
curl -X POST http://localhost:8000/ask \
  -H "Content-Type: application/json" \
  -d '{"question": "Which books have average rating above 4.5?"}'

# Aggregation
curl -X POST http://localhost:8000/ask \
  -H "Content-Type: application/json" \
  -d '{"question": "What is the average rating by categories?"}'

# Health check
curl http://localhost:8000/health

# Schema
curl http://localhost:8000/schema
```

## Running Tests

```bash
# All tests (uses stub mode, no Groq API key needed)
# On Windows:
set LLM_MODE=stub && pytest tests/ -v

# On macOS/Linux:
LLM_MODE=stub pytest tests/ -v
```

## Environment Variables

| Variable | Default | Description |
|----------|---------|-------------|
| GROQ_API_KEY | (included in .env) | Groq API key for LLM |
| GROQ_MODEL | llama-3.3-70b-versatile | Groq model ID |
| BOOKS_CSV_PATH | data/books.csv | Path to CSV dataset |
| LLM_MODE | groq | Set to `stub` for testing without LLM |
| MAX_SCAN_ROWS | 100000 | Max rows to load |
| MAX_RETURN_ROWS | 50 | Max rows returned per query |
| RATE_LIMIT_TOKENS | 20 | Rate limit bucket capacity |
| LOG_LEVEL | INFO | Logging level |

## Project Structure

```
app/
  main.py                    # FastAPI app entry point
  api/routes.py              # API endpoint handlers
  core/
    config.py                # Configuration and env vars
    logging.py               # Logging setup
    rate_limit.py            # Token bucket rate limiter
    cache.py                 # Deterministic query cache (LRU)
    audit.py                 # Append-only audit log with hash chain
    security.py              # OWASP security middleware & input sanitization
    metrics.py               # Pipeline observability metrics
    conversation.py          # Multi-turn conversation manager
  data/
    loader.py                # CSV loading and schema inference
    schema.py                # Schema model and type inference
    fingerprint.py           # SHA-256 dataset fingerprinting
    profiler.py              # Data quality profiling & anomaly detection
    cleaner.py               # Data cleaning & outlier handling
  planner/
    models.py                # QueryPlan Pydantic models
    groq_planner.py          # Groq LLM planning with constrained JSON
    validator.py             # Plan validation against schema
  executor/
    executor.py              # Deterministic pandas execution
  verifier/
    verifier.py              # Mention + numeric claim verification
    response_builder.py      # Response generation & LLM humanization
ui/
  index.html                 # Dashboard UI
  styles.css                 # Dark neon theme
  app.js                     # Frontend logic
scripts/
  download_dataset.py        # Dataset downloader
  evaluate.py                # Evaluation harness
  verify_cleaning.py         # Data cleaning verification
tests/
  unit/test_validator.py     # Plan validation tests
  unit/test_executor.py      # Executor correctness tests
  integration/test_api.py    # API contract + injection resistance tests
data/
  books.csv                  # Books dataset (included)
```

## Tech Stack

- **Backend**: Python 3.10+, FastAPI, Pandas, Pydantic
- **LLM**: Groq API (Llama 3.3 70B)
- **Frontend**: Vanilla HTML/CSS/JS with Chart.js
- **Security**: OWASP-aligned headers, input sanitization, CSP
- **Testing**: pytest (unit + integration)
