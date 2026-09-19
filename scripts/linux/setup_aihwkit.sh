#!/usr/bin/env bash
# Provision the dedicated Linux engine environment for the AIHWKit accuracy engine.
# Persistent on purpose: /tmp environments from earlier sessions did not survive.
set -euo pipefail

ROOT=${CTFM_ENGINE_ROOT:-/opt/ctfm-engines}
VENV="$ROOT/aihwkit-venv"
LOGS="$ROOT/logs"
UV="$ROOT/bin/uv"
CPU_INDEX=https://download.pytorch.org/whl/cpu

mkdir -p "$ROOT/bin" "$LOGS"

if [ ! -x "$UV" ]; then
  echo "== installing uv into $ROOT/bin =="
  curl -LsSf https://astral.sh/uv/install.sh | env UV_INSTALL_DIR="$ROOT/bin" UV_NO_MODIFY_PATH=1 sh
fi
"$UV" --version

export UV_PYTHON_INSTALL_DIR="$ROOT/python"
export UV_CACHE_DIR="$ROOT/uv-cache"

echo "== python 3.11 =="
"$UV" python install 3.11

if [ ! -d "$VENV" ]; then
  echo "== venv $VENV =="
  "$UV" venv --python 3.11 "$VENV"
fi

# torch first, so the aihwkit resolve cannot silently drag in a CUDA torch from
# PyPI. The pin is 2.12.0 and NOT the workspace's 2.14.0: the prebuilt aihwkit
# 1.1.0 extension is only ABI-compatible with torch 2.10-2.12. Measured on this
# host with scripts/linux/sweep_torch_abi.sh:
#   2.9.1            ImportError, undefined symbol c10::TensorImpl::decref_pyobject
#   2.10.0 - 2.12.0  tile.set_weights round-trips correctly
#   2.13.0, 2.14.0   imports fine but the C++ shape check misreads the tensor
#                    ("Invalid weights dimensions: expected [3,4] tensor")
# 2.13+ is the dangerous case because import succeeds, so the engine must stay
# gated behind the parity probe rather than behind an import check.
TORCH_PIN=${CTFM_AIHWKIT_TORCH:-2.12.0}
echo "== torch $TORCH_PIN (cpu index) =="
"$UV" pip install --python "$VENV/bin/python" \
  --index-url "$CPU_INDEX" \
  "torch==${TORCH_PIN}+cpu" "torchvision" 2>&1 | tee "$LOGS/torch-install.log"

echo "== aihwkit =="
"$UV" pip install --python "$VENV/bin/python" "aihwkit==1.1.0" 2>&1 | tee "$LOGS/aihwkit-install.log"

echo "== installed versions =="
"$VENV/bin/python" - <<'PY'
import platform
import torch
from importlib.metadata import version
print("python     ", platform.python_version())
print("torch      ", torch.__version__)
print("aihwkit    ", version("aihwkit"))
import aihwkit
print("aihwkit at ", aihwkit.__file__)
PY
