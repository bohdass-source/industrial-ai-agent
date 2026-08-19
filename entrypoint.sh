#!/bin/sh
set -e

echo "== waiting for PostgreSQL =="
python - <<'PY'
import sys, time
from sqlalchemy import create_engine, text
from app.config import settings

for i in range(60):
  try:
    with create_engine(settings.database_url).connect() as c:
      c.execute(text("SELECT 1"))
    print("DB is up")
    sys.exit(0)
  except Exception:
    time.sleep(2)
print("DB not reachable after 120s", file=sys.stderr)
sys.exit(1)
PY

echo "== waiting for Ollama =="
python - <<'PY'
import sys, time, urllib.request
from app.config import settings
url = (settings.llm_base_url or "http://localhost:11434/v1").rstrip("/") + "/models"
for i in range(90):
  try:
    urllib.request.urlopen(url, timeout=3)
    print("Ollama is up")
    sys.exit(0)
  except Exception:
    time.sleep(2)
print("Ollama not reachable after 180s", file=sys.stderr)
sys.exit(1)
PY

echo "== seeding synthetic data =="
python -m app.seed_data --if-empty

echo "== indexing manuals into pgvector =="
python -m app.rag.manual_index --if-missing

echo "== starting API =="
exec uvicorn app.main:app --host 0.0.0.0 --port 8000
