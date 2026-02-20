# NEXUS — Game Analytics Intelligence Platform

> A production-grade game analytics agent that answers natural-language questions about Steam game data, powered by Groq LLMs and FastAPI.

---

## Quick Start

```bash
# 1. Clone the branch
git clone -b Game_Analytics_Agent <repo_url>
cd Game_Analytics_Agent

# 2. Install dependencies
pip install -r requirements.txt

# 3. Add your keys
cp .env.example .env
# Edit .env and set GROQ_API_KEY

# 4. Place the CSV files
mkdir -p data/csv
# Copy game_ids.csv, game_data.csv, additional_data.csv into data/csv/

# 5. Run
uvicorn main:app --reload --port 8000
```

Open `http://localhost:8000` for the UI, or `http://localhost:8000/docs` for Swagger.

---

## API

### `POST /game/analytics`

**Request:**
```json
{ "query": "Do free games have higher ratings on average than paid games?" }
```

**Response:**
```json
{
  "response": "Free games average a rating of 7.2 vs 6.8 for paid games...",
  "metadata": {
    "query_type": "statistics",
    "confidence_score": 0.91,
    "games": [ ... ],
    "statistics": { ... },
    "currency_rates": { ... },
    "total_results": 42,
    "sql_used": "SELECT ...",
    "session_id": "uuid",
    "execution_time_ms": 312,
    "data_sources": ["game_ids.csv", "game_data.csv", "additional_data.csv"]
  }
}
```

### Other endpoints

| Method | Path | Description |
|--------|------|-------------|
| GET | `/health` | System health + dataset stats |
| GET | `/game/stats` | Dataset row counts |
| GET | `/game/analytics/history?session_id=X` | Session query history |
| GET | `/docs` | Swagger UI |
| GET | `/` | Glassmorphic dashboard |

---

## Example Queries

| Query | Intent |
|-------|--------|
| Do free games have higher ratings? | statistics |
| How many Action games support Korean? | filter |
| Best multiplayer shooters after 2015 | filter |
| Price of Counter-Strike in INR and USD | currency |
| Compare Dota 2 vs CS:GO | comparison |
| Average game price per genre | statistics |
| Games trending upward since 2015 | trend |

For off-topic questions (weather, stocks, etc.), the agent returns a polite fallback explaining it only handles game analytics.

---

## Architecture

```
User Query
    │
    ▼
Intent Classifier (irrelevant / currency / comparison / statistics / filter / lookup)
    │
    ▼
SQL Builder (Groq LLM → SQLite query against games table)
    │
    ▼
SQL Executor → rows
    │
    ├── Currency Engine (live rates → price conversions)
    │
    ▼
Answer Generator (Groq LLM → human-readable response)
    │
    ▼
{ response, metadata }
```

---

## Technology Stack

| Layer | Technology |
|-------|-----------|
| API | FastAPI + Uvicorn |
| LLM | Groq (llama-3.1-8b-instant) |
| Data | Pandas + SQLite (in-memory) |
| Currency | ExchangeRate-API (free tier) |
| Session | In-process deque store |
| UI | HTML5 + CSS3 glassmorphism + Chart.js |

---

## Directory Structure

```
Game_Analytics_Agent/
├── main.py                  # FastAPI entry point
├── requirements.txt
├── .env.example
├── README.md
├── core/
│   └── orchestrator.py      # 5-stage reasoning pipeline
├── tools/
│   ├── sql_executor.py      # SQLite query runner
│   └── currency_engine.py   # Live exchange rates
├── data/
│   ├── loader.py            # CSV loading + cleaning + SQLite
│   └── csv/                 # ← place your CSV files here
│       ├── game_ids.csv
│       ├── game_data.csv
│       └── additional_data.csv
├── api/
│   ├── routes.py
│   └── models.py
├── session/
│   └── manager.py           # Conversation history
└── ui/
    └── index.html           # Glassmorphic dashboard
```
