#!/usr/bin/env bash
# Full HTTP flow on Linux with both accuracy engines sharing one checkpoint.
#
# API and worker run from the SAME venv and the SAME CTFM_STORAGE_ROOT, because
# a capability reported by the API process means nothing unless the worker that
# actually computes has it too.
set -uo pipefail

ROOT=${CTFM_ENGINE_ROOT:-/opt/ctfm-engines}
REPO=${CTFM_REPO:?set CTFM_REPO to the repository path}
VENV="$ROOT/aihwkit-venv"
RUN="$ROOT/http-e2e"
PORT=${PORT:-8123}
BASE="http://127.0.0.1:$PORT"

rm -rf "$RUN"; mkdir -p "$RUN/storage"
export CTFM_STORAGE_ROOT="$RUN/storage"
export PYTHONUNBUFFERED=1

cleanup() {
  for pid in ${API_PID:-} ${WORKER_PID:-}; do
    [ -n "$pid" ] && kill -TERM "-$pid" 2>/dev/null
  done
  sleep 2
  for pid in ${API_PID:-} ${WORKER_PID:-}; do
    [ -n "$pid" ] && kill -KILL "-$pid" 2>/dev/null
  done
}
trap cleanup EXIT

cd "$REPO"
setsid "$VENV/bin/python" -m uvicorn ctfm_api.app:app --host 127.0.0.1 --port "$PORT" \
  > "$RUN/api.log" 2>&1 &
API_PID=$!
setsid "$VENV/bin/python" -m ctfm_worker > "$RUN/worker.log" 2>&1 &
WORKER_PID=$!

echo "== waiting for API on $BASE =="
for _ in $(seq 1 60); do
  if curl -fsS "$BASE/api/v1/capabilities" > "$RUN/capabilities.json" 2>/dev/null; then break; fi
  sleep 1
done
if [ ! -s "$RUN/capabilities.json" ]; then
  echo "API did not come up"; tail -30 "$RUN/api.log"; exit 1
fi

"$VENV/bin/python" - "$RUN/capabilities.json" <<'PY'
import json, sys
caps = json.load(open(sys.argv[1]))
for name, value in caps["engines"].items():
    print("  %-16s available=%-6s version=%s" % (name, value["available"], value.get("version")))
rows = caps["hardware"]["validated_combinations"]
print("  validated_combinations: %d rows, engines=%s"
      % (len(rows), sorted({r["engine"] for r in rows})))
PY

echo "== torch_reference =="
"$VENV/bin/python" scripts/smoke_workflow.py --base-url "$BASE" --engine torch_reference \
  | tee "$RUN/torch_reference.json"
TORCH_RC=${PIPESTATUS[0]}

# The smoke script streams one-line progress objects before the final report, so
# take the last top-level object rather than the first "{" in the file.
read -r -d '' FINAL_OBJECT <<'PY'
import json


def final_object(path):
    lines = open(path, encoding="utf-8").read().splitlines()
    starts = [i for i, line in enumerate(lines) if line.rstrip() == "{"]
    if not starts:
        raise ValueError("no pretty-printed report object in " + path)
    return json.loads("\n".join(lines[starts[-1]:]))
PY

CHECKPOINT=$("$VENV/bin/python" - "$RUN/torch_reference.json" <<PY
$FINAL_OBJECT
import sys
print(final_object(sys.argv[1]).get("checkpoint_id") or "")
PY
)
if [ -z "$CHECKPOINT" ]; then echo "could not read checkpoint id"; exit 1; fi
echo "== aihwkit_ideal (reusing checkpoint $CHECKPOINT) =="
"$VENV/bin/python" scripts/smoke_workflow.py --base-url "$BASE" --engine aihwkit_ideal \
  --checkpoint-id "$CHECKPOINT" | tee "$RUN/aihwkit_ideal.json"
AIHWKIT_RC=${PIPESTATUS[0]}

echo "== comparing the two runs =="
"$VENV/bin/python" - "$RUN/torch_reference.json" "$RUN/aihwkit_ideal.json" <<PY
$FINAL_OBJECT
import sys

a, b = final_object(sys.argv[1]), final_object(sys.argv[2])
print("checkpoint shared:", a["checkpoint_id"] == b["checkpoint_id"])
print("engines used     :", a["engines_used"], "->", b["engines_used"])
mismatches = {k: (v, b["accuracies"].get(k)) for k, v in a["accuracies"].items()
              if v != b["accuracies"].get(k)}
print("accuracy mismatches:", mismatches or "none")
ok = (a["checkpoint_id"] == b["checkpoint_id"] and not mismatches
      and "aihwkit_ideal" in b["engines_used"])
print("RESULT:", "MATCH" if ok else "MISMATCH")
sys.exit(0 if ok else 1)
PY
COMPARE_RC=$?

echo "torch_rc=$TORCH_RC aihwkit_rc=$AIHWKIT_RC compare_rc=$COMPARE_RC"
[ "$TORCH_RC" -eq 0 ] && [ "$AIHWKIT_RC" -eq 0 ] && [ "$COMPARE_RC" -eq 0 ]
