"""Targeted probe of the NeuroSim V1.4 CopyPEArray segfault boundary.

Companion to repro_neurosim_crash.py: that one reduces the reported shape to a
minimal case, this one maps which (shape, subArray) pairs actually crash. It
exists because the reduction turned up a shape the recorded rule said should
crash but does not, and the results here are what MEASURED_TOPOLOGIES in
ctfm.adapters.neurosim records.

Run on the engine host:

    python scripts/linux/probe_neurosim_crash_boundary.py

Findings as of 2026-09-20 (commit ac828e6, gcc 13.3) are in
docs/implementation-status.md: mnist_mlp_v1 crashes at subArray 64 and 128 and
completes at 256, and narrow output layers do NOT crash on their own.
"""
import os, subprocess, sys, json
from pathlib import Path
ENGINE = Path("/opt/ctfm-engines")
INFERENCE = ENGINE/"neurosim"/"Inference_pytorch"
sys.path.insert(0, str(INFERENCE))
import numpy as np
from utee.hook import write_matrix_activation_fc, write_matrix_weight

OUT = Path("/opt/ctfm-engines/probe-boundary")

def run(shape, sub_array=64, parallel=64, tag=None):
    tag = tag or ("x".join(str(v) for p in shape for v in p)+f"_sa{sub_array}")
    work = OUT/tag; (work/"t").mkdir(parents=True, exist_ok=True)
    rng = np.random.default_rng(7)
    net = work/"NetWork.csv"
    net.write_text("\n".join("1,1,{},1,1,{},0,1".format(a,b) for a,b in shape)+"\n")
    argv = [str(INFERENCE/"NeuroSIM"/"main"), str(net), "8","8", str(sub_array), str(parallel)]
    for i,(fi,fo) in enumerate(shape, 1):
        w = rng.normal(scale=.12, size=(fo,fi)).clip(-1, 1-2**-7)
        a = rng.random((1,fi)).astype(np.float32)*(1-2**-7)
        wf, af = work/"t"/f"w{i}.csv", work/"t"/f"a{i}.csv"
        write_matrix_weight(w, str(wf)); write_matrix_activation_fc(a, None, 8, str(af))
        argv += [str(wf), str(af)]
    r = subprocess.run(argv, cwd=str(INFERENCE), capture_output=True, text=True, timeout=600)
    return r.returncode

cases = []
# 1. input-dimension boundary on the mnist two-layer shape
for fan_in in (128, 196, 255, 256, 257, 260, 320, 512, 784):
    cases.append(([(fan_in,128),(128,10)], 64, 64, None))
# 2. does the boundary move with subArray?
for sub in (32, 128):
    for fan_in in (256, 257, 784):
        cases.append(([(fan_in,128),(128,10)], sub, sub, None))
# 3. shapes the recorded rule calls crashing: narrow outputs on their own
for shape in ([(128,10)], [(256,10)], [(1024,10)], [(784,64)], [(256,64)]):
    cases.append((shape, 64, 64, None))
# 4. single wide layer that was recorded as fine
cases.append(([(784,128)], 64, 64, None))

results = []
for shape, sub, par, tag in cases:
    rc = run(shape, sub, par, tag)
    results.append({"shape": shape, "sub_array": sub, "returncode": rc, "crashed": rc < 0})
    print(json.dumps(results[-1]), flush=True)
Path(OUT/"results.json").write_text(json.dumps(results, indent=2))
