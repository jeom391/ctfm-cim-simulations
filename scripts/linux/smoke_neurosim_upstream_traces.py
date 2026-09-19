"""Capture NeuroSim's own traces for its shipped VGG8 example, then run them.

Upstream's inference wrapper does not actually run on a CPU-only host, in three
separate places, so this driver redirects each from the outside rather than
editing the checkout:
  * inference.py calls torch.load(pretrained) with no map_location and the
    shipped VGG8.pth was saved from a CUDA device.
  * modules/quantization_cpu_np_infer.py hardcodes device="cuda" five times,
    despite its filename.
  * utee/wage_quantizer.py builds a torch.cuda.FloatTensor.

The full CIFAR-10 WAGE test loop also takes hours on CPU, but the forward hooks
write every layer trace during the first batch. So we let the first batch write
layer_record_VGG8/, stop, and execute upstream's own generated trace_command.sh.

The result is a real NeuroSim run on a real upstream network with real upstream
traces. It validates the binary and this repo's stdout parser. It is still
NeuroSim's stock SRAM/22 nm configuration, so it is not a CTFM PPA number.
"""
import json
import os
import signal
import subprocess
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]
                                          / "packages" / "ctfm-core" / "src"))

from ctfm.adapters.neurosim import parse_stdout  # noqa: E402

ENGINE = Path(os.environ.get("CTFM_ENGINE_ROOT", "/opt/ctfm-engines"))
INFERENCE = ENGINE / "neurosim" / "Inference_pytorch"
OUT = ENGINE / "smoke" / "neurosim-upstream-traces"
RECORD = INFERENCE / "layer_record_VGG8"

DRIVER = '''
import torch
_real_load = torch.load
def load(*a, **kw):
    kw.setdefault("map_location", "cpu")
    kw.setdefault("weights_only", False)
    return _real_load(*a, **kw)
torch.load = load

# modules/quantization_cpu_np_infer.py hardcodes device="cuda" in five places and
# utee/wage_quantizer.py uses torch.cuda.FloatTensor, so upstream's "cpu"
# inference path cannot actually run CPU-only. Redirect from outside rather than
# editing the checkout. The quantization sites build
# torch.normal(0., torch.full(size, self.vari)); this run uses vari=0.0, so the
# draw is identically zero and moving it to CPU changes no number.
if not torch.cuda.is_available():
    _real_full = torch.full
    def full(*a, **kw):
        if str(kw.get("device", "")).startswith("cuda"):
            kw["device"] = "cpu"
        return _real_full(*a, **kw)
    torch.full = full
    torch.cuda.FloatTensor = torch.FloatTensor
import runpy, sys, os
sys.path.insert(0, os.getcwd())  # upstream imports utee/models relative to Inference_pytorch
# batch_size 1 because upstream's writers record only input_matrix[0, :] - the
# first sample of the batch - so a larger batch changes nothing in the traces
# while making the first CPU forward pass hundreds of times more expensive.
sys.argv = ["inference.py", "--dataset", "cifar10", "--model", "VGG8", "--mode", "WAGE",
            "--inference", "1", "--cellBit", "1", "--subArray", "128", "--parallelRead", "64",
            "--batch_size", "1"]
runpy.run_path("inference.py", run_name="__main__")
'''


def capture_traces(deadline):
    """Let upstream's forward hooks emit the layer traces, then stop it."""
    (OUT / "driver.py").write_text(DRIVER)
    process = subprocess.Popen(
        [str(ENGINE / "aihwkit-venv" / "bin" / "python"), str(OUT / "driver.py")],
        cwd=str(INFERENCE), stdout=open(OUT / "wrapper-stdout.log", "w"),
        stderr=open(OUT / "wrapper-stderr.log", "w"),
        env={**os.environ, "TORCH_HOME": str(ENGINE / "neurosim-data"), "PYTHONUNBUFFERED": "1"},
        start_new_session=True,
    )
    command = RECORD / "trace_command.sh"
    try:
        while time.time() < deadline:
            if process.poll() is not None:
                return process.returncode, "wrapper exited"
            # 8 conv/fc layers -> 16 trace files plus the command script.
            if command.is_file() and len(list(RECORD.glob("*.csv"))) >= 16:
                time.sleep(5)  # let the last file finish flushing
                return None, "traces captured"
            time.sleep(5)
        return None, "timeout waiting for traces"
    finally:
        if process.poll() is None:
            os.killpg(os.getpgid(process.pid), signal.SIGTERM)
            try:
                process.wait(timeout=30)
            except subprocess.TimeoutExpired:
                os.killpg(os.getpgid(process.pid), signal.SIGKILL)


def main():
    # VGG8's first CPU forward pass writes roughly one layer pair every few
    # minutes, so the budget is an argument rather than a constant.
    budget = float(os.environ.get("CTFM_TRACE_BUDGET_S", 1800))
    OUT.mkdir(parents=True, exist_ok=True)
    report = {"engine_defaults_note": "NeuroSim stock Param.cpp (SRAM, 22 nm); not a CTFM preset"}

    rc, why = capture_traces(time.time() + budget)
    report["trace_capture"] = {"wrapper_returncode": rc, "reason": why, "budget_s": budget}
    command = RECORD / "trace_command.sh"
    if not command.is_file():
        report["error"] = "upstream never wrote trace_command.sh"
        print(json.dumps(report, indent=2))
        return 1

    argv = command.read_text().split()
    report["argv"] = argv
    report["trace_files"] = sorted(p.name for p in RECORD.glob("*.csv"))
    # trace_command.sh is written when the hooks are registered, before any
    # forward pass, so its presence alone does not mean the traces exist. Running
    # the engine on the header-only argv just aborts.
    layers = len([line for line in (INFERENCE / "NeuroSIM" / "NetWork_VGG8.csv")
                  .read_text().splitlines() if line.strip()])
    report["layers_expected"] = layers
    report["layers_traced"] = (len(argv) - 6) // 2
    if report["layers_traced"] != layers:
        report["error"] = ("upstream traced %d of %d layers; running the engine on a partial "
                           "argv only aborts" % (report["layers_traced"], layers))
        print(json.dumps(report, indent=2))
        return 1

    completed = subprocess.run(argv, cwd=str(INFERENCE), capture_output=True,
                               text=True, timeout=3600)
    (OUT / "engine-stdout.log").write_text(completed.stdout)
    (OUT / "engine-stderr.log").write_text(completed.stderr)
    report["engine_returncode"] = completed.returncode
    report["parsed_si"] = parse_stdout(completed.stdout)

    (OUT / "report.json").write_text(json.dumps(report, indent=2))
    print(json.dumps(report, indent=2))
    return 0 if completed.returncode == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
