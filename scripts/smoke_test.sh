#!/usr/bin/env bash
# End-to-end проверка: health -> БД -> склад -> агент -> тикет
set -euo pipefail
BASE="${BASE:-http://localhost:8000}"

echo "== 1. health =="
curl -sf "$BASE/health"; echo

echo "== 2. машины (остановленные) =="
curl -sf "$BASE/machines" | python3 -c "
import json, sys
d = json.load(sys.stdin)
print('machines:', len(d))
print('stopped:', [m['machine_name'] for m in d if m['status'] == 'stopped'])
"

echo "== 3. склад: BLT-142 =="
curl -sf "$BASE/spare_parts" | python3 -c "
import json, sys
d = json.load(sys.stdin)
print([p for p in d if p['part_number'] == 'BLT-142'])
"

echo "== 4. запуск агента (E142) =="
curl -sf -X POST "$BASE/agent/run" -H 'Content-Type: application/json' \
  -d '{"message":"Conveyor Line 4 suddenly stopped. Error E142.","thread_id":"smoke-1"}' \
  | python3 -m json.tool

echo "== 5. созданные тикеты =="
curl -sf "$BASE/tickets?limit=3" | python3 -m json.tool

echo "== SMOKE TEST DONE =="
