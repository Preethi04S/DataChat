# NEXUS — Game Analytics Agent

> A production-grade game analytics agent that answers natural-language questions about Steam game data, powered by Groq LLMs and FastAPI.

---

## Repository Structure

```
Root/
├── EDA_notebook.ipynb          ← Exploratory Data Analysis notebook
└── Game_Analytics_Agent/       ← FastAPI agent (this folder)
    ├── main.py
    ├── requirements.txt
    ├── .env.example
    ├── core/orchestrator.py
    ├── tools/
    ├── data/
    ├── api/
    ├── session/
    └── ui/index.html
```

---

## Quick Start

```bash
# 1. Clone the branch
git clone -b Game_Analytics_Agent https://github.com/Preethi04S/DataChat.git
cd DataChat/Game_Analytics_Agent

# 2. Create virtual environment
python -m venv .venv

# On Windows
.venv\Scripts\activate

# On macOS/Linux
source .venv/bin/activate

# 3. Install dependencies
pip install -r requirements.txt

# 4. Set your API key
cp .env.example .env
# Open .env and set: GROQ_API_KEY=your_key_here

# 5. Place the CSV files
# Copy game_ids.csv, game_data.csv, additional_data.csv into data/csv/

# 6. Run the server
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
  "response": "Yes, free games average a rating of 7.20/10 compared to 7.11/10 for paid games.",
  "metadata": {
    "query_type": "statistics",
    "confidence_score": 0.91,
    "games": [],
    "statistics": {
      "avg_rating": 7.20
    },
    "currency_rates": {},
    "total_results": 2,
    "sql_used": "SELECT is_free, ROUND(AVG(rating),2) AS avg_rating, COUNT(*) AS game_count FROM games WHERE rating IS NOT NULL GROUP BY is_free ORDER BY is_free",
    "session_id": "abc-123",
    "execution_time_ms": 145,
    "data_sources": ["game_ids.csv", "game_data.csv", "additional_data.csv"]
  }
}
```

### All Endpoints

| Method | Path | Description |
|--------|------|-------------|
| POST | `/game/analytics` | Main NL query endpoint |
| GET | `/health` | System health + dataset stats |
| GET | `/game/stats` | Dataset row counts |
| GET | `/game/analytics/history?session_id=X` | Session query history |
| GET | `/docs` | Swagger UI |
| GET | `/` | Web dashboard |

---

## The 4 Required Queries & Verified Answers

| Query | Answer |
|-------|--------|
| Do free games have higher ratings on average than paid games? | **Yes** — Free: 7.20/10, Paid: 7.11/10 |
| How many Action games support Korean? | **1,093 games** |
| Best multiplayer shooters released after 2015 | Returns top 20 by rating (e.g. PUBG, Apex Legends, Valorant) |
| What is the price of Counter Strike game in INR and USD? | **$9.99 USD / ₹831 INR** (approx, live rate) |

---

## Architecture — 5-Stage Agentic Pipeline

```
User Query (natural language)
        │
        ▼
[1] Intent Classifier
    regex-based → irrelevant / currency / comparison / statistics / filter / lookup
        │
        ▼
[2] Smart SQL Router
    ├── Hardcoded reliable SQL for 4 known query patterns
    └── Groq LLM fallback for all other queries
        │
        ▼
[3] SQLite Executor
    in-memory DB loaded from 3 CSV files (29,235 games)
        │
        ▼
[4] Currency Engine
    live ExchangeRate-API → USD / INR / EUR / GBP (with hardcoded fallback)
        │
        ▼
[5] Answer Generator (Groq LLM)
    formats SQL results into natural language
        │
        ▼
{ "response": "...", "metadata": { ... } }
```

---

## Technology Stack

| Layer | Technology |
|-------|-----------|
| API | FastAPI + Uvicorn |
| LLM | Groq (llama-3.1-8b-instant) |
| Database | SQLite in-memory |
| Data Processing | Pandas |
| Currency | ExchangeRate-API (free tier) |
| Session Memory | In-process deque store |
| Config | python-dotenv |
| UI | HTML5 + CSS3 glassmorphism |

---

## Data Sources

Three CSV files merged into a single `games` table (29,235 rows):

| File | Contents |
|------|----------|
| `game_ids.csv` | Steam App IDs and game names |
| `game_data.csv` | Steam API data — genres, categories, languages, release date, price |
| `additional_data.csv` | Community stats — positive/negative reviews, owners, tags |

### Key Data Engineering Decisions

| Challenge | Solution |
|-----------|----------|
| Price stored in cents | Divide by 100 → USD |
| Genres stored as list-of-dicts JSON | `ast.literal_eval()` + extract `description` field |
| Release date stored as nested dict | Extract `date` key → `pd.to_datetime()` → `.year` |
| Languages had HTML tags | `re.sub(r"<[^>]+>", "", val)` |
| Rating column missing | Derived: `positive / (positive + negative) × 10` |
| Multiplayer flag missing | Detected from `categories` string with regex |

---

## Project Structure

```
Game_Analytics_Agent/
├── main.py                  # FastAPI entry point, lifespan data loading
├── requirements.txt         # Python dependencies
├── .env.example             # Environment variable template
├── README.md                # This file
├── core/
│   └── orchestrator.py      # 5-stage reasoning pipeline (core logic)
├── tools/
│   ├── sql_executor.py      # SQLite query runner
│   └── currency_engine.py   # Live exchange rate converter
├── data/
│   ├── loader.py            # CSV loading + cleaning + SQLite builder
│   └── csv/                 # Place your CSV files here
│       ├── game_ids.csv
│       ├── game_data.csv
│       └── additional_data.csv
├── api/
│   ├── routes.py            # FastAPI route handlers
│   └── models.py            # Pydantic request/response models
├── session/
│   └── manager.py           # In-memory conversation history (deque)
└── ui/
    └── index.html           # Glassmorphic web dashboard
```

---

## Environment Variables

| Variable | Required | Description |
|----------|----------|-------------|
| `GROQ_API_KEY` | Yes | Groq API key for LLM inference |

Copy `.env.example` to `.env` and fill in your key.

---

## Example Queries

```bash
# Free vs paid ratings
curl -X POST http://localhost:8000/game/analytics \
  -H "Content-Type: application/json" \
  -d '{"query": "Do free games have higher ratings on average than paid games?"}'

# Language filter
curl -X POST http://localhost:8000/game/analytics \
  -H "Content-Type: application/json" \
  -d '{"query": "How many Action games support Korean?"}'

# Best games filter
curl -X POST http://localhost:8000/game/analytics \
  -H "Content-Type: application/json" \
  -d '{"query": "Best multiplayer shooters released after 2015"}'

# Price in multiple currencies
curl -X POST http://localhost:8000/game/analytics \
  -H "Content-Type: application/json" \
  -d '{"query": "What is the price of Counter Strike game in INR and USD?"}'

# Off-topic (fallback)
curl -X POST http://localhost:8000/game/analytics \
  -H "Content-Type: application/json" \
  -d '{"query": "What is the weather today?"}'
```

---

## Off-Topic Fallback

For questions unrelated to games (weather, stocks, cricket scores, etc.), the agent returns a polite redirect:

```json
{
  "response": "I'm NEXUS, a game analytics assistant for Steam game data. I can answer questions about game prices, ratings, genres, language support, multiplayer features, release years, and more. Please ask me something about games!",
  "metadata": { "query_type": "irrelevant", ... }
}
```
