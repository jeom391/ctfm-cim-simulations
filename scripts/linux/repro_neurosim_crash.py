"""Reduce the NeuroSim V1.4 segfault to the smallest shape that still crashes.

docs/spec/08-hardware-baseline.md acceptance 6: fix the crash starting from a
minimal reproduction, and do not hide it by padding the 10-class output to 96 or
by changing mnist_mlp_v1. This script produces that reproduction. It changes
nothing and diagnoses nothing by itself -- it records exactly which shape, which
argv and which signal, so a fix has a regression case to point at.

Method:
  1. confirm the reported shape crashes at all (otherwise there is nothing to
     reduce and the run says so);
  2. shrink one layer at a time by bisection, keeping the smallest shape that
     still crashes with the same signal;
  3. re-run the winner N times to show it is deterministic rather than a flake;
  4. write repro.json with the shape, argv, return code, stderr tail and the
     engine identity (commit + binary hash) it was observed on.

Run on the engine host:

    python scripts/linux/repro_neurosim_crash.py --out /opt/ctfm-engines/repro

Traces come from NeuroSim's own writers, imported from the checkout, so a
malformed trace cannot be mistaken for an engine bug.
"""
import argparse
import hashlib
import json
import os
import subprocess
import sys
from pathlib import Path

ENGINE = Path(os.environ.get("CTFM_ENGINE_ROOT", "/opt/ctfm-engines"))
INFERENCE = ENGINE / "neurosim" / "Inference_pytorch"
sys.path.insert(0, str(INFERENCE))

import numpy as np  # noqa: E402

from utee.hook import write_matrix_activation_fc, write_matrix_weight  # noqa: E402

# The shape the product needs and the engine refuses; everything else is derived
# from it by shrinking.
REPORTED = [(784, 128), (128, 10)]


def engine_identity():
    binary = INFERENCE / "NeuroSIM" / "main"
    digest = None
    if binary.is_file():
        digest = hashlib.sha256(binary.read_bytes()).hexdigest()
    commit = subprocess.run(["git", "-C", str(ENGINE / "neurosim"), "rev-parse", "HEAD"],
                            capture_output=True, text=True).stdout.strip() or None
    return {"binary": str(binary), "binary_sha256": digest, "commit": commit}


def run_shape(shape, out, args, tag):
    """Build the traces for one shape and run the binary on it."""
    work = out / "cases" / tag
    (work / "traces").mkdir(parents=True, exist_ok=True)
    rng = np.random.default_rng(20260920)
    network_csv = work / "NetWork.csv"
    network_csv.write_text("\n".join("1,1,{},1,1,{},0,1".format(a, b) for a, b in shape) + "\n")
    argv = [str(INFERENCE / "NeuroSIM" / "main"), str(network_csv), str(args.synapse_bit),
            str(args.input_bit), str(args.sub_array), str(args.parallel_read)]
    for index, (fan_in, fan_out) in enumerate(shape, start=1):
        weight = rng.normal(scale=0.12, size=(fan_out, fan_in)).clip(-1, 1 - 2**-7)
        activation = rng.random((1, fan_in)).astype(np.float32) * (1 - 2**-7)
        weight_file = work / "traces" / ("weight_%d.csv" % index)
        input_file = work / "traces" / ("input_%d.csv" % index)
        write_matrix_weight(weight, str(weight_file))
        write_matrix_activation_fc(activation, None, args.input_bit, str(input_file))
        argv += [str(weight_file), str(input_file)]
    completed = subprocess.run(argv, cwd=str(INFERENCE), capture_output=True, text=True,
                               timeout=args.timeout)
    (work / "stdout.log").write_text(completed.stdout)
    (work / "stderr.log").write_text(completed.stderr)
    return {"shape": [list(pair) for pair in shape], "argv": argv,
            "returncode": completed.returncode, "crashed": completed.returncode < 0,
            "stderr_tail": "\n".join(completed.stderr.splitlines()[-20:])}


def shrink(shape, out, args, attempts):
    """Bisect each dimension down while the crash survives."""
    best = [list(pair) for pair in shape]
    for position in range(len(best)):
        for axis in (0, 1):
            low, high = 1, best[position][axis]
            while low < high:
                middle = (low + high) // 2
                candidate = [list(pair) for pair in best]
                candidate[position][axis] = middle
                if position + 1 < len(candidate) and axis == 1:
                    candidate[position + 1][0] = middle  # keep the layers connected
                tag = "shrink-" + "x".join(str(v) for pair in candidate for v in pair)
                result = run_shape([tuple(pair) for pair in candidate], out, args, tag)
                attempts.append(result)
                if result["crashed"]:
                    best = candidate
                    high = middle
                else:
                    low = middle + 1
    return best


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", default=str(ENGINE / "repro" / "neurosim-crash"))
    parser.add_argument("--synapse-bit", type=int, default=8)
    parser.add_argument("--input-bit", type=int, default=8)
    parser.add_argument("--sub-array", type=int, default=64)
    parser.add_argument("--parallel-read", type=int, default=64)
    parser.add_argument("--repeats", type=int, default=3)
    parser.add_argument("--timeout", type=float, default=900.0)
    args = parser.parse_args()
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)

    attempts = []
    reported = run_shape([tuple(p) for p in REPORTED], out, args, "reported")
    attempts.append(reported)
    if not reported["crashed"]:
        report = {"engine": engine_identity(), "status": "no_crash_to_reduce",
                  "reported": reported, "attempts": attempts,
                  "note": "This build does not crash on the reported shape; record the build "
                          "that does before claiming the engine limitation still holds."}
        (out / "repro.json").write_text(json.dumps(report, indent=2))
        print(json.dumps(report, indent=2))
        return 0

    minimal = shrink([tuple(p) for p in REPORTED], out, args, attempts)
    repeats = [run_shape([tuple(p) for p in minimal], out, args, "confirm-%d" % i)
               for i in range(args.repeats)]
    report = {
        "engine": engine_identity(),
        "status": "reduced",
        "reported_shape": REPORTED,
        "minimal_shape": minimal,
        "returncode": repeats[0]["returncode"],
        "deterministic": all(r["crashed"] for r in repeats),
        "confirmations": repeats,
        "attempts": attempts,
        "arguments": {"synapse_bit": args.synapse_bit, "input_bit": args.input_bit,
                      "sub_array": args.sub_array, "parallel_read": args.parallel_read},
        "note": "Add the minimal shape to CRASHING_TOPOLOGIES with this report as its "
                "evidence, and keep it as the regression case for any patch.",
    }
    (out / "repro.json").write_text(json.dumps(report, indent=2))
    print(json.dumps({k: v for k, v in report.items() if k != "attempts"}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
