"""Check every advertised ADC/tile/order combination on the real AIHWKit backend.

Mirrors test_every_advertised_adc_combination_matches_the_independent_numpy_reference,
but drives Network with engine='aihwkit_ideal'. Capabilities may only advertise a
combination for AIHWKit once it appears here as a pass: AIHWKit builds one analog
tile per weight block, and under the v1.2 model each differential plane is its own
set of blocks, so the block shapes differ per tile size AND per plane.

The v1.2 accuracy path is unsigned 8 bit bit-serial over a G+/G- cell pair, so
this drives the same `differential_linear` reference the unit tests use rather
than the legacy single-plane `tiled_linear`.

    python scripts/linux/verify_aihwkit_adc_combinations.py
"""
import json
import sys

import numpy as np
import torch

from ctfm.adapters import engine_capabilities
from ctfm.simulation.math import differential_linear, ADC_ORDERS
from ctfm.simulation.torch_runner import Network

# float32 and float64 can round a sample sitting on a code boundary to
# neighbouring codes, so the bound is one ADC step carried through the 8 cycle
# shift-add rather than a free-form epsilon.
SCALE = 0.37
INPUT_RANGE = 2.0
SHAPE = (130, 270)


def tolerance(bound, bits, order, tile):
    step = bound*(2 if order == "subtract_then_adc" else 1)/(2**bits-1)
    return step*255*(INPUT_RANGE/255)*SCALE*(SHAPE[1]//tile+1)


def main():
    caps = engine_capabilities()
    if not caps["aihwkit_ideal"]["available"]:
        print("aihwkit_ideal unavailable:", caps["aihwkit_ideal"]["reason"])
        return 2

    rng = np.random.default_rng(193)
    x = np.abs(rng.normal(size=(3, SHAPE[1]))).astype(np.float32)
    g_plus = np.abs(rng.normal(scale=1e-5, size=SHAPE))+1e-7
    g_minus = np.abs(rng.normal(scale=1e-5, size=SHAPE))+1e-7
    bias = rng.normal(scale=1e-3, size=SHAPE[0])
    layer = dict(name="swept", g_plus=g_plus, g_minus=g_minus, scale=SCALE, bias=bias,
                 input_range=INPUT_RANGE)

    results = []
    for tile in (64, 128, 256):
        # Ranges come from the ADC-off pass on the same backend, exactly as a run
        # would collect them.
        bounds = {}
        Network([layer], "aihwkit_ideal", tile_size=tile, input_bits=8)(
            torch.from_numpy(x), calibration=bounds)

        # With the ADC off the bit serial schedule must equal the direct MAC
        # (acceptance 2) on this backend too, not only on torch_reference.
        direct = Network([layer], "aihwkit_ideal", tile_size=tile, input_bits=8)(
            torch.from_numpy(x)).numpy()
        reference, _ = differential_linear(x, g_plus, g_minus, bias, SCALE, INPUT_RANGE,
                                           tile_size=tile)
        adc_off_error = float(np.abs(direct-reference).max())
        results.append({"tile_size": tile, "adc_bits": None, "adc_order": None,
                        "max_abs_error": adc_off_error,
                        "pass": bool(np.allclose(direct, reference, atol=1e-9, rtol=1e-4))})

        for bits in range(3, 9):
            for order in ADC_ORDERS:
                bound = bounds["swept"][order]
                expected, stats = differential_linear(
                    x, g_plus, g_minus, bias, SCALE, INPUT_RANGE, tile_size=tile,
                    adc_bits=bits, bound=bound, order=order)
                network = Network([layer], "aihwkit_ideal", tile_size=tile, bits=bits,
                                  bounds=bounds, adc_order=order)
                actual = network(torch.from_numpy(x)).numpy()
                error = float(np.abs(actual-expected).max())
                limit = tolerance(bound, bits, order, tile)
                blocks = -(-SHAPE[0]//tile)*-(-SHAPE[1]//tile)
                clip_delta = abs(network.stats["swept"]["clipped_count"]-stats["clipped_count"])
                results.append({
                    "tile_size": tile, "adc_bits": bits, "adc_order": order,
                    "max_abs_error": error, "tolerance": limit,
                    "clip_count_delta": clip_delta, "clip_block_allowance": blocks,
                    "pass": bool(error <= limit and clip_delta <= blocks),
                })

    passed = [r for r in results if r["pass"]]
    report = {
        "engine": "aihwkit_ideal",
        "aihwkit_version": caps["aihwkit_ideal"]["version"],
        "torch": str(torch.__version__),
        "model": "v1.2 unsigned 8 bit bit-serial over a G+/G- pair",
        "reference": "ctfm.simulation.math.differential_linear (independent NumPy)",
        "tolerance_rule": "one ADC step carried through the 8 cycle shift-add",
        "combinations": results,
        "passed": len(passed),
        "total": len(results),
        "note": ("a pass here is what lets capabilities advertise the tile/bits/order triple "
                 "for aihwkit_ideal; it says nothing about CTFM physical validity"),
    }
    print(json.dumps(report, indent=2))
    return 0 if len(passed) == len(results) else 1


if __name__ == "__main__":
    sys.exit(main())
