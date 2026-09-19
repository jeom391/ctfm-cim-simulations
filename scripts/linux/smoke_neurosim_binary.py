"""Drive the built NeuroSim binary directly on the mnist_mlp_v1 topology.

Trace files are written by NeuroSim's *own* writers (utee.hook), imported rather
than reimplemented, so the format cannot drift from what the engine expects.

Scope: this proves the binary runs, what its stdout looks like, and that the
numbers can be parsed. It uses NeuroSim's stock Param.cpp defaults, which are an
SRAM cell at 22 nm. Those are NOT CTFM values and this run is NOT a CTFM PPA
result.
"""
import argparse
import json
import os
import re
import subprocess
import sys
from pathlib import Path

ENGINE = Path(os.environ.get("CTFM_ENGINE_ROOT", "/opt/ctfm-engines"))
INFERENCE = ENGINE / "neurosim" / "Inference_pytorch"
sys.path.insert(0, str(INFERENCE))

import numpy as np  # noqa: E402

from utee.hook import write_matrix_activation_fc, write_matrix_weight  # noqa: E402

# mnist_mlp_v1: 784 -> 128 -> 10, expressed as 1x1 "conv" layers.
# Columns: IFM_row, IFM_col, in_channels, kernel_row, kernel_col, out_channels,
# followed_by_pooling, <trailing flag as shipped in NetWork_*.csv>
LAYERS = [(784, 128), (128, 10)]


def write_network_csv(path):
    rows = ["1,1,{},1,1,{},0,1".format(fan_in, fan_out) for fan_in, fan_out in LAYERS]
    path.write_text("\n".join(rows) + "\n")
    return rows


def parse_report(text):
    """Pull the chip-level totals out of NeuroSim stdout, in SI units."""
    def grab(pattern, scale):
        match = re.search(pattern, text)
        return None if match is None else float(match.group(1)) * scale

    return {
        "chip_area_m2": grab(r"ChipArea\s*:\s*([0-9.eE+-]+)um\^2", 1e-12),
        "chip_array_area_m2": grab(r"Chip total CIM array\s*:\s*([0-9.eE+-]+)um\^2", 1e-12),
        "chip_adc_area_m2": grab(r"Total ADC .*Area on chip\s*:\s*([0-9.eE+-]+)um\^2", 1e-12),
        "readLatency_s": grab(r"Chip layer-by-layer readLatency \(per image\) is:\s*([0-9.eE+-]+)ns", 1e-9),
        "readDynamicEnergy_j": grab(r"Chip layer-by-layer readDynamicEnergy \(per image\) is:\s*([0-9.eE+-]+)pJ", 1e-12),
        "leakage_w": grab(r"Chip leakage Energy is:\s*([0-9.eE+-]+)pJ", 1e-12),
        "tops": grab(r"Throughput TOPS .*:\s*([0-9.eE+-]+)", 1.0),
    }


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default=str(ENGINE / "smoke" / "neurosim-binary"))
    ap.add_argument("--synapse-bit", type=int, default=8)
    ap.add_argument("--input-bit", type=int, default=8)
    ap.add_argument("--sub-array", type=int, default=128)
    ap.add_argument("--parallel-read", type=int, default=64)
    ap.add_argument("--timeout", type=float, default=900.0)
    args = ap.parse_args()

    out = Path(args.out)
    (out / "traces").mkdir(parents=True, exist_ok=True)
    rng = np.random.default_rng(20260919)

    network_csv = out / "NetWork_ctfm_mlp.csv"
    rows = write_network_csv(network_csv)

    argv = [str(INFERENCE / "NeuroSIM" / "main"), str(network_csv),
            str(args.synapse_bit), str(args.input_bit),
            str(args.sub_array), str(args.parallel_read)]

    for index, (fan_in, fan_out) in enumerate(LAYERS, start=1):
        # write_matrix_weight transposes to [in, out]; keep torch's [out, in] here.
        weight = (rng.normal(scale=0.12, size=(fan_out, fan_in))).clip(-1, 1 - 2**-7)
        activation = rng.random((1, fan_in)).astype(np.float32) * (1 - 2**-7)
        weight_file = out / "traces" / f"weight_layer{index}.csv"
        input_file = out / "traces" / f"input_layer{index}.csv"
        write_matrix_weight(weight, str(weight_file))
        write_matrix_activation_fc(activation, None, args.input_bit, str(input_file))
        argv += [str(weight_file), str(input_file)]

    completed = subprocess.run(
        argv, cwd=str(INFERENCE), capture_output=True, text=True, timeout=args.timeout
    )
    (out / "stdout.log").write_text(completed.stdout)
    (out / "stderr.log").write_text(completed.stderr)

    report = {
        "argv": argv,
        "network_csv_rows": rows,
        "returncode": completed.returncode,
        "parsed_si": parse_report(completed.stdout),
        "engine_defaults_note": "NeuroSim stock Param.cpp: SRAM cell, 22 nm; not a CTFM preset",
    }
    (out / "report.json").write_text(json.dumps(report, indent=2))
    print(json.dumps(report, indent=2))
    if completed.returncode != 0:
        print("--- stderr tail ---")
        print("\n".join(completed.stderr.splitlines()[-20:]))
    return 0 if completed.returncode == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
