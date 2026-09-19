"""Check every advertised ADC/tile combination on the real AIHWKit backend.

Mirrors test_every_advertised_torch_adc_combination_matches_independent_numpy,
but drives Network with engine='aihwkit_ideal'. Capabilities may only advertise
a combination for AIHWKit once it appears here as a pass, because AIHWKit builds
one analog tile per weight block and the block shapes differ per tile size.
"""
import json
import sys

import numpy as np
import torch

from ctfm.adapters import engine_capabilities
from ctfm.simulation.math import tiled_linear
from ctfm.simulation.torch_runner import Network

ATOL = RTOL = 2e-5


def main():
    caps = engine_capabilities()
    if not caps["aihwkit_ideal"]["available"]:
        print("aihwkit_ideal unavailable:", caps["aihwkit_ideal"]["reason"])
        return 2

    rng = np.random.default_rng(193)
    x = rng.normal(size=(3, 270)).astype(np.float32)
    weights = rng.normal(scale=0.12, size=(130, 270)).astype(np.float32)
    bias = rng.normal(scale=0.01, size=130).astype(np.float32)
    layers = [dict(name="supported", weights=weights, bias=bias)]

    results = []
    for tile in (64, 128, 256):
        for bits in range(3, 9):
            expected, stats = tiled_linear(x, weights, bias, tile_size=tile, bits=bits, bound=1.75)
            network = Network(layers, "aihwkit_ideal", tile_size=tile, bits=bits,
                              bounds={"supported": 1.75})
            actual = network(torch.from_numpy(x)).numpy()
            error = float(np.abs(actual - expected).max())
            results.append({
                "tile_size": tile,
                "adc_bits": bits,
                "max_abs_error": error,
                "clipped_match": network.stats["supported"]["clipped_count"] == stats["clipped_count"],
                "pass": bool(np.allclose(actual, expected, atol=ATOL, rtol=RTOL))
                and network.stats["supported"]["clipped_count"] == stats["clipped_count"],
            })

    passed = [r for r in results if r["pass"]]
    report = {
        "engine": "aihwkit_ideal",
        "aihwkit_version": caps["aihwkit_ideal"]["version"],
        "torch": str(torch.__version__),
        "tolerance": {"atol": ATOL, "rtol": RTOL},
        "reference": "ctfm.simulation.math.tiled_linear (independent NumPy)",
        "combinations": results,
        "passed": len(passed),
        "total": len(results),
    }
    print(json.dumps(report, indent=2))
    return 0 if len(passed) == len(results) else 1


if __name__ == "__main__":
    sys.exit(main())
