"""Real MNIST run through the actual simulator on both accuracy engines.

Trains (or reuses) one checkpoint with torch_reference, then re-runs the very
same checkpoint, seed and profile under aihwkit_ideal. The engines must agree,
because aihwkit_ideal is only supposed to replace the linear MAC - the tiling,
ADC quantization, D2D and retention stay owned by ctfm.simulation.torch_runner.

The device profile is SYNTHETIC. Accuracy numbers here validate the engine
wiring, not CTFM device performance.
"""
import argparse
import json
import sys
import time
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "packages" / "ctfm-core" / "tests"))

from ctfm.adapters import engine_capabilities
from ctfm.simulation import run_experiment
from test_simulation_experiment import configuration, synthetic_profile


def summarize(result):
    """Accuracy per run, keyed so the two engines can be diffed directly."""
    out = {}
    for run in result["runs"]:
        key = "|".join(
            str(run.get(k)) for k in ("kind", "pool", "mapping", "array_index", "years")
        )
        accuracy = run.get("accuracy")
        out[key] = None if accuracy is None else round(float(accuracy), 10)
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default="/opt/ctfm-engines/smoke/aihwkit-mnist")
    ap.add_argument("--cache", default="/opt/ctfm-engines/mnist-cache")
    ap.add_argument("--effects", action="store_true", help="also exercise D2D/retention/ADC")
    args = ap.parse_args()

    caps = engine_capabilities()
    if not caps["aihwkit_ideal"]["available"]:
        print("aihwkit_ideal unavailable:", caps["aihwkit_ideal"]["reason"])
        return 2

    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    profile = synthetic_profile()

    report = {"capabilities": caps, "effects": args.effects, "engines": {}}

    reference_config = configuration(profile, args.effects)
    t0 = time.time()
    reference = run_experiment(
        reference_config, [profile], out / "torch_reference", cache_dir=args.cache
    )
    report["engines"]["torch_reference"] = {
        "status": reference["status"],
        "summary": reference["summary"],
        "accuracy": summarize(reference),
        "seconds": round(time.time() - t0, 1),
    }
    checkpoint = out / "torch_reference" / "checkpoint.pt"

    analog_config = configuration(profile, args.effects)
    analog_config["engines"]["accuracy"] = "aihwkit_ideal"
    analog_config["checkpoint_id"] = reference["checkpoint_id"]
    t0 = time.time()
    analog = run_experiment(
        analog_config,
        [profile],
        out / "aihwkit_ideal",
        cache_dir=args.cache,
        checkpoint_path=checkpoint,
    )
    report["engines"]["aihwkit_ideal"] = {
        "status": analog["status"],
        "summary": analog["summary"],
        "accuracy": summarize(analog),
        "seconds": round(time.time() - t0, 1),
    }

    report["shared_checkpoint"] = reference["checkpoint_id"] == analog["checkpoint_id"]
    ref_acc = report["engines"]["torch_reference"]["accuracy"]
    ana_acc = report["engines"]["aihwkit_ideal"]["accuracy"]
    diffs = {
        k: {"torch_reference": ref_acc[k], "aihwkit_ideal": ana_acc.get(k)}
        for k in ref_acc
        if ref_acc[k] != ana_acc.get(k)
    }
    report["accuracy_mismatches"] = diffs
    # Engine provenance must record aihwkit, otherwise the run silently fell back.
    report["recorded_engines"] = sorted({r.get("engine") for r in analog["runs"]})

    (out / "report.json").write_text(json.dumps(report, indent=2, sort_keys=True, default=str))
    print(json.dumps(report, indent=2, sort_keys=True, default=str)[:4000])
    ok = report["shared_checkpoint"] and not diffs and "aihwkit_ideal" in report["recorded_engines"]
    print("\nRESULT:", "MATCH" if ok else "MISMATCH")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
