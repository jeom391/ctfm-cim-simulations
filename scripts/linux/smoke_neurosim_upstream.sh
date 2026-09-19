#!/usr/bin/env bash
# Run NeuroSim's own shipped inference example end to end and keep the raw
# evidence (stdout, stderr, return code, generated traces, engine report).
#
# This is the upstream smoke only. It proves the built binary runs and what its
# output looks like; it says nothing about whether any CTFM equivalent-circuit
# preset is physically valid.
set -uo pipefail

ROOT=${CTFM_ENGINE_ROOT:-/opt/ctfm-engines}
SRC="$ROOT/neurosim/Inference_pytorch"
VENV="$ROOT/aihwkit-venv"
OUT="$ROOT/smoke/neurosim-upstream"

mkdir -p "$OUT"
cd "$SRC"

export TORCH_HOME="$ROOT/neurosim-data"
export PYTHONUNBUFFERED=1

git -C "$ROOT/neurosim" log -1 --format='commit=%H%ndate=%cI' > "$OUT/engine-commit.txt"
g++ --version | head -1 > "$OUT/compiler.txt"
sha256sum "$SRC/NeuroSIM/main" > "$OUT/binary-sha256.txt"

set -x
"$VENV/bin/python" inference.py \
  --dataset cifar10 --model VGG8 --mode WAGE \
  --inference 1 --cellBit 1 --subArray 128 --parallelRead 64 \
  > "$OUT/stdout.log" 2> "$OUT/stderr.log"
rc=$?
set +x
echo "$rc" > "$OUT/returncode.txt"

echo "== return code: $rc =="
echo "== tail stdout =="; tail -30 "$OUT/stdout.log"
echo "== tail stderr =="; tail -20 "$OUT/stderr.log"
if [ -f "$SRC/layer_record_VGG8/trace_command.sh" ]; then
  cp "$SRC/layer_record_VGG8/trace_command.sh" "$OUT/trace_command.sh"
  echo "== trace command captured =="
fi
