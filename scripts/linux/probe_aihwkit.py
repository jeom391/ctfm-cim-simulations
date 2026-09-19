"""Run the repository's own AIHWKit capability probe against a real install.

Reports engine_capabilities() verbatim plus a full mnist_mlp_v1-shaped logits
parity check, so "the probe passes" is backed by the actual layer sizes the
simulator uses rather than only the 2x4x3 fixture.
"""
import json
import sys
import time

import torch

from ctfm.adapters import engine_capabilities, make_linear

TOL = {"atol": 1e-5, "rtol": 1e-4}


def parity(name, in_features, out_features, batch, seed):
    gen = torch.Generator().manual_seed(seed)
    x = torch.randn(batch, in_features, generator=gen, dtype=torch.float32)
    w = torch.randn(out_features, in_features, generator=gen, dtype=torch.float32) * 0.1
    ref = torch.nn.functional.linear(x, w)
    layer = make_linear(w, "aihwkit_ideal")
    with torch.no_grad():
        got = layer(x)
    err = (got - ref).abs().max().item()
    return {
        "layer": name,
        "shape": [out_features, in_features],
        "batch": batch,
        "max_abs_error": err,
        "allclose": bool(torch.allclose(got, ref, **TOL)),
    }


def main():
    caps = engine_capabilities()
    out = {
        "python": sys.version.split()[0],
        "torch": str(torch.__version__),
        "capabilities": caps,
        "tolerance": TOL,
    }
    if caps["aihwkit_ideal"]["available"]:
        t0 = time.time()
        out["model_parity"] = [
            parity("fc1", 784, 128, 256, 20260919),
            parity("fc2", 128, 10, 256, 20260920),
        ]
        out["model_parity_seconds"] = round(time.time() - t0, 3)
    print(json.dumps(out, indent=2, sort_keys=True))
    ok = caps["aihwkit_ideal"]["available"] and all(
        r["allclose"] for r in out.get("model_parity", [])
    )
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
