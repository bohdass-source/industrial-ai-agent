# Industrial AI Agent

A production-oriented **agentic AI** system for industrial equipment maintenance.  
The agent autonomously diagnoses machine failures, retrieves maintenance history, searches maintenance manuals via RAG, checks spare-parts inventory, generates repair recommendations, and creates maintenance tickets — all through a multi-step LangGraph ReAct workflow.

---

## Table of Contents

1. [Project Overview](#project-overview)
2. [Architecture & Agent Workflow](#architecture--agent-workflow)
3. [Technology Stack](#technology-stack)
4. [Repository Structure](#repository-structure)
5. [Local Setup](#local-setup)
6. [Docker Setup](#docker-setup)
7. [Environment Variables](#environment-variables)
8. [API Usage](#api-usage)
9. [Known Limitations](#known-limitations)

---

## Project Overview

Industrial equipment failures are expensive and time-sensitive.  
This agent provides a conversational, LLM-powered interface to a maintenance knowledge base:

- **Agentic loop**: the LLM reasons over tool results across multiple steps before producing a final answer.
- **RAG (Retrieval-Augmented Generation)**: maintenance manual chunks are retrieved from PostgreSQL and injected into the LLM context.
- **Tool use**: the agent can call four structured tools — history lookup, manual search, spare-parts check, and ticket creation.
- **Duplicate-ticket protection**: the ticket tool prevents duplicate open tickets for the same machine/error combination.
- **Streaming support**: `/agent/stream` returns Server-Sent Events so clients see incremental reasoning steps.

---

## Architecture & Agent Workflow

```
User request (machine_id + error_code)
         │
         ▼
┌─────────────────────────────────┐
│         FastAPI (app/main.py)    │
│  /health  /agent/run  /agent/stream │
└────────────────┬────────────────┘
                 │
                 ▼
┌─────────────────────────────────┐
│   LangGraph ReAct Agent         │
│  (app/agent/workflow.py)        │
│                                 │
│  ┌──────────┐   ┌────────────┐  │
│  │  Agent   │──▶│ Tool Node  │  │
│  │  Node    │◀──│            │  │
│  │ (Ollama) │   │ 4 tools    │  │
│  └──────────┘   └────────────┘  │
└─────────────────────────────────┘
         │ tool calls
         ▼
┌─────────────────────────────────┐
│  Tools (app/agent/tools.py)     │
│  • get_maintenance_history      │
│  • search_manual (RAG)          │
│  • check_spare_parts            │
│  • create_maintenance_ticket    │
└────────────────┬────────────────┘
                 │
                 ▼
┌─────────────────────────────────┐
│  PostgreSQL + pgvector           │
│  • maintenance_history          │
│  • manual_chunks                │
│  • spare_parts                  │
│  • maintenance_tickets          │
└─────────────────────────────────┘
```

### ReAct Loop

1. **Reason** – The LLM decides which tool to call next.
2. **Act** – The tool node executes the call and returns results.
3. Steps 1–2 repeat until the LLM produces a final text answer with no further tool calls.

---

## Technology Stack

| Layer | Technology |
|-------|------------|
| API server | FastAPI + Uvicorn |
| Agent framework | LangGraph (ReAct loop) |
| LLM | Ollama (llama3 or any compatible model) |
| LLM client | langchain-ollama |
| Vector store | PostgreSQL + pgvector |
| ORM | SQLAlchemy 2 |
| Containerisation | Docker + Docker Compose |
| Python | 3.11 |

---

## Repository Structure

```
industrial-ai-agent/
├── app/
│   ├── main.py            # FastAPI app, lifespan, global exception handler
│   ├── config.py          # Pydantic settings (reads .env)
│   ├── api/
│   │   └── routes.py      # /health, /agent/run, /agent/stream
│   ├── agent/
│   │   ├── tools.py       # Four LangChain tools (DB-backed)
│   │   └── workflow.py    # LangGraph ReAct graph
│   └── db/
│       └── database.py    # SQLAlchemy models, init_db, seed data
├── Dockerfile
├── docker-compose.yml
├── entrypoint.sh          # Waits for Postgres, then starts Uvicorn
├── requirements.txt
├── .env.example           # Safe template – copy to .env and edit
└── README.md
```

---

## Local Setup

### Prerequisites

- Python 3.11+
- PostgreSQL with pgvector extension  
  (or use Docker Compose — see below)
- [Ollama](https://ollama.com/) running locally

### Steps

```bash
# 1. Clone the repository
git clone https://github.com/bohdass-source/industrial-ai-agent.git
cd industrial-ai-agent

# 2. Create and activate a virtual environment
python -m venv .venv
source .venv/bin/activate        # Windows: .venv\Scripts\activate

# 3. Install dependencies
pip install -r requirements.txt

# 4. Configure environment
cp .env.example .env
# Edit .env with your PostgreSQL credentials and Ollama URL

# 5. Start the application
uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload
```

---

## Docker Setup

```bash
# 1. Copy and configure environment file
cp .env.example .env
# Edit .env – at minimum change POSTGRES_PASSWORD

# 2. Build and start all services (Postgres + pgvector, Ollama, App)
docker compose up --build

# 3. Pull the LLM model (first run only)
docker compose exec ollama ollama pull llama3

# 4. The API is now available at http://localhost:8000
```

To stop all services:

```bash
docker compose down
```

---

## Environment Variables

See `.env.example` for all variables.  
**Never commit `.env` to version control.**

| Variable | Default | Description |
|----------|---------|-------------|
| `OLLAMA_BASE_URL` | `http://ollama:11434` | Ollama service URL |
| `OLLAMA_MODEL` | `llama3` | Model to use |
| `POSTGRES_HOST` | `postgres` | PostgreSQL hostname |
| `POSTGRES_PORT` | `5432` | PostgreSQL port |
| `POSTGRES_DB` | `industrial_ai` | Database name |
| `POSTGRES_USER` | `postgres` | Database user |
| `POSTGRES_PASSWORD` | — | **Required** – set in `.env` |
| `APP_HOST` | `0.0.0.0` | Bind address |
| `APP_PORT` | `8000` | Listen port |
| `LOG_LEVEL` | `INFO` | Logging verbosity |

---

## API Usage

### Health check

```bash
curl http://localhost:8000/health
```

```json
{"status": "ok"}
```

---

### Run agent (full response)

`POST /agent/run` – runs the full agentic loop and returns the final recommendation.

```bash
curl -X POST http://localhost:8000/agent/run \
  -H "Content-Type: application/json" \
  -d '{"machine_id": "CNC-001", "error_code": "E404"}'
```

```json
{
  "machine_id": "CNC-001",
  "error_code": "E404",
  "response": "Based on the maintenance history and manual, the spindle motor is overheating due to a blocked cooling vent. Recommended actions: 1) Clean the cooling vent with compressed air. 2) Replace the thermal paste on the heat sink (Cooling Fan Assembly SP-COOL-01, qty: 3 available). 3) Verify the coolant pump. A maintenance ticket has been created (id=1)."
}
```

---

### Stream agent (Server-Sent Events)

`POST /agent/stream` – streams incremental reasoning steps as SSE.

```bash
curl -X POST http://localhost:8000/agent/stream \
  -H "Content-Type: application/json" \
  -d '{"machine_id": "CNC-001", "error_code": "E404"}'
```

```
data: [agent] Calling get_maintenance_history for CNC-001...
data: [tools] [2024-01-15] Error E404: Spindle motor overheated → Resolution: Cleaned cooling vent...
data: [agent] Calling search_manual for CNC-001...
data: [tools] CNC-001 Spindle Motor Overheating (E404): Inspect cooling vent...
data: [agent] Based on the maintenance history and manual...
data: [DONE]
```

---

### Unknown machine or error code

The agent gracefully handles cases where no data is found:

```bash
curl -X POST http://localhost:8000/agent/run \
  -H "Content-Type: application/json" \
  -d '{"machine_id": "UNKNOWN-999", "error_code": "E999"}'
```

The agent will report that no history or manual content was found and still provide a best-effort recommendation based on the LLM's general knowledge.

---

## Known Limitations

- **No real vector similarity search**: manual chunk retrieval uses keyword scoring rather than actual pgvector embedding similarity. Embedding generation requires an additional model (e.g., `nomic-embed-text`) and is not included in the current implementation.
- **Ollama dependency**: the agent requires a running Ollama instance. If Ollama is unavailable, the LLM node returns a graceful error message rather than crashing.
- **Demo seed data**: the database is pre-seeded with three example machines (`CNC-001`, `ROBOT-002`). Production use requires loading real maintenance history and manual data.
- **No authentication**: the API has no authentication layer. Add an API-key middleware or OAuth2 before exposing publicly.
- **Synchronous DB in async app**: SQLAlchemy calls run in a thread pool (`asyncio.to_thread`). For higher concurrency, consider an async driver such as `asyncpg`.
