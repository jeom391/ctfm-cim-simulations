#!/usr/bin/env bash
# Determine which torch builds the prebuilt aihwkit extension is ABI-compatible
# with, by round-tripping a tile weight matrix through the C++ binding.
#
# Import success is not the test: torch 2.13+ imports cleanly and then misreads
# tensor dimensions, so the round-trip is what separates "works" from "silently
# wrong". Re-run this whenever the aihwkit or torch pin moves.
set -uo pipefail

ROOT=${CTFM_ENGINE_ROOT:-/opt/ctfm-engines}
VERSIONS=${*:-"2.9.1 2.10.0 2.11.0 2.12.0 2.13.0 2.14.0"}
UV="$ROOT/bin/uv"
VENV="$ROOT/probe-sweep"
CPU_INDEX=https://download.pytorch.org/whl/cpu

export UV_PYTHON_INSTALL_DIR="$ROOT/python"
export UV_CACHE_DIR="$ROOT/uv-cache"

[ -d "$VENV" ] || "$UV" venv --python 3.11 "$VENV" >/dev/null
# --no-deps so swapping torch underneath aihwkit never re-resolves aihwkit itself.
"$UV" pip install -q --python "$VENV/bin/python" --no-deps "aihwkit==1.1.0" >/dev/null
"$UV" pip install -q --python "$VENV/bin/python" numpy scipy scikit-learn >/dev/null

for TV in $VERSIONS; do
  echo "##### torch $TV #####"
  if ! "$UV" pip install -q --python "$VENV/bin/python" \
        --index-url "$CPU_INDEX" "torch==${TV}+cpu" >/dev/null 2>&1; then
    echo "  install FAILED"
    continue
  fi
  "$VENV/bin/python" - <<'PY' 2>&1 | grep -v 'UserWarning\|_conversion_method' | sed 's/^/  /'
import torch
print("torch", torch.__version__)
try:
    from aihwkit.simulator.configs import FloatingPointRPUConfig
except Exception as exc:
    print("IMPORT FAIL:", type(exc).__name__, str(exc)[:200])
    raise SystemExit
cfg = FloatingPointRPUConfig()
tile = cfg.get_default_tile_module_class(3, 4)(3, 4, cfg, False).tile
weights = tile.get_weights()
try:
    tile.set_weights(weights.clone())
    print("set_weights OK", tuple(weights.shape))
except Exception as exc:
    print("set_weights FAIL:", type(exc).__name__, exc)
PY
done
