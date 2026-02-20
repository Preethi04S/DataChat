# DataChat AI — Akaike Technologies Assessment

This repository contains submissions for the Akaike Technologies Data Science Assessment.

---

## Round 0 — DataChat AI (CSV Analytics Chatbot)

**Branch:** `main`

A proof-carrying CSV chatbot with verifiable, audit-ready answers. Ask natural language questions about a books dataset and get grounded, verified responses powered by Groq LLM.

### How to Run

```bash
git clone https://github.com/Preethi04S/DataChat.git
cd DataChat

python -m venv .venv
# Windows:
.venv\Scripts\activate
# macOS/Linux:
source .venv/bin/activate

pip install -r requirements.txt
uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload
```

Open `http://localhost:8000`

### Architecture

```
Question → Groq LLM (QueryPlan) → Validator → Executor → Verifier → Response
```

### Tech Stack

- **Backend**: Python 3.10+, FastAPI, Pandas, Pydantic
- **LLM**: Groq API (Llama 3.3 70B)
- **Frontend**: Vanilla HTML/CSS/JS with Chart.js

---

## Round 1 — NEXUS Game Analytics Agent

**Branch:** `Game_Analytics_Agent`

An agentic game analytics system that answers natural-language questions about 29,235 Steam games using a 5-stage reasoning pipeline.

### Branch Structure

```
Game_Analytics_Agent branch
├── EDA_notebook.ipynb          ← Exploratory Data Analysis
└── Game_Analytics_Agent/
    ├── main.py
    ├── core/orchestrator.py    ← 5-stage pipeline
    ├── data/loader.py          ← CSV parsing + SQLite
    ├── tools/
    ├── api/
    ├── session/
    └── ui/index.html
```

### How to Run

```bash
git clone -b Game_Analytics_Agent https://github.com/Preethi04S/DataChat.git
cd DataChat/Game_Analytics_Agent

python -m venv .venv
.venv\Scripts\activate

pip install -r requirements.txt

# Set GROQ_API_KEY in .env
cp .env.example .env

# Place CSV files in data/csv/
uvicorn main:app --reload --port 8000
```

### API Endpoint

```
POST /game/analytics
Body:  { "query": "Do free games have higher ratings than paid games?" }
```

### Verified Query Answers

| Query | Answer |
|-------|--------|
| Do free games have higher ratings on average than paid games? | Free: 7.20/10, Paid: 7.11/10 |
| How many Action games support Korean? | 1,093 games |
| Best multiplayer shooters released after 2015 | Top 20 ranked by rating |
| Price of Counter Strike in INR and USD | $9.99 USD / ₹831 INR |

See the full README inside `Game_Analytics_Agent/` for complete documentation.
