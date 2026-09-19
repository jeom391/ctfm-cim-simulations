"""NeuroSim 2DInferenceV1.4 PPA adapter: engine detection, inputs, preset gate, run.

This adapter never produces accuracy. Accuracy stays with torch_reference or
aihwkit_ideal; NeuroSim only estimates area/energy/latency.

Three states are kept strictly apart and must never collapse into one flag:

  engine_status()    is the binary built and runnable on this host
  preset_decision()  is there a validated CTFM equivalent-circuit preset
  run_engine()       did this particular execution succeed

An engine that builds and runs does not make a CTFM PPA number legitimate. With
no validated preset the gate returns ``unsupported`` and no number is produced.
Missing or failed values are ``None``, never zero.
"""
import hashlib
import json
import math
import os
import re
import signal
import subprocess
import time
from pathlib import Path

ENGINE_ROOT = Path(os.environ.get("CTFM_NEUROSIM_ROOT", "/opt/ctfm-engines/neurosim"))
BINARY_RELPATH = Path("Inference_pytorch/NeuroSIM/main")

# Values NeuroSim needs that no CTFM measurement provides. A preset must state
# every one explicitly with its source, per docs/spec/03-simulation.md.
REQUIRED_PRESET_FIELDS = {
    "technode_nm": "technology node; also selects NeuroSim readVoltage internally",
    "read_voltage_v": "engine read voltage; NOT the measured VDS",
    "read_pulse_width_s": "read pulse width; must not be copied from the write pulse",
    "cell_bit": "bits stored per analog cell",
    "synapse_bit": "weight precision presented to the engine",
    "sub_array": "square subarray size",
    "parallel_rows": "rows read in parallel",
    "adc_architecture": "SAR or MLSA, and current or voltage mode",
    "columns_per_adc": "how many columns share one ADC",
    "interconnect": "H-tree or XY bus",
    "memcell_type": "engine memory cell model used as the CTFM equivalent",
    "input_precision_bits": "activation precision presented to the engine",
}

# Structural differences between this project's accuracy model and NeuroSim's
# circuit model. Recorded on every decision so a PPA number is never read as if
# the two models agreed.
MODEL_MISMATCHES = (
    {"id": "nonuniform_states",
     "detail": "CTFM adopts finite measured, non-uniformly spaced conductances; NeuroSim maps "
               "weights onto uniform levels between minConductance and maxConductance"},
    {"id": "cells_per_weight",
     "detail": "The accuracy model uses one analog cell per differential plane per weight; "
               "NeuroSim uses ceil(synapseBit/cellBit) columns per weight"},
    {"id": "differential_planes",
     "detail": "NeuroSim has no native two-plane differential representation; the cost of the "
               "second plane has to be modelled explicitly"},
    {"id": "read_voltage",
     "detail": "Measurements use VDS=0.1 V; NeuroSim derives readVoltage from technode "
               "(22 nm -> 0.55 V) and does not accept the measured value directly"},
    {"id": "adc_position",
     "detail": "The accuracy model quantizes the differential partial sum after digital "
               "subtraction; NeuroSim quantizes per physical column group"},
)

# Shapes measured to segfault inside CopyPEArray on this build (commit ac828e6),
# via scripts/linux/smoke_neurosim_binary.py. No general rule is claimed: some
# multi-layer fully-connected networks run fine (1024x128 twice and three times
# both complete), while these mixed-width ones crash although each of their
# layers runs on its own.
CRASHING_TOPOLOGIES = frozenset({
    ((784, 128), (128, 10)),    # mnist_mlp_v1
    ((784, 128), (128, 128)),
})
# Every layer tested with fewer than this many output features crashed: out=10 at
# in=128/256/384/512/640/784 and at subArray 64 and 128, plus out=16/24/32/48/64
# at in=784. out=96 and above completed.
MIN_SAFE_OUT_FEATURES = 96

UNSUPPORTED_TOPOLOGY = (
    "NeuroSim V1.4 segfaults on this shape (verified on this build: 784x128x10, 784x128x128, "
    "1024x10, 128x10, and every tested layer with fewer than 96 output features)")

# The accuracy model stores one analog cell per differential plane per weight and
# reads G+ minus G-. NeuroSim has no two-plane differential array, so the second
# plane's area, energy and latency would have to be modelled by an explicit
# approximation. Whether such an approximation may stand in for the CTFM circuit
# is a physical judgement nobody has made yet, so no cost model is assumed here.
DIFFERENTIAL_PLANE_UNRESOLVED = (
    "Differential two-plane cost is not modelled: NeuroSim has no native G+/G- plane pair and "
    "no approved approximation exists for the second plane's area/energy/latency")


def _sha256(path):
    digest = hashlib.sha256()
    with open(path, "rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def engine_status(root=None):
    """Report whether the engine binary exists, and pin what produced it."""
    root = Path(root or ENGINE_ROOT)
    binary = root / BINARY_RELPATH
    result = {"available": False, "binary": str(binary), "commit": None,
              "compiler": None, "binary_sha256": None, "reason": None}
    if not binary.is_file():
        result["reason"] = "NeuroSim binary not built at " + str(binary)
        return result
    if not os.access(binary, os.X_OK):
        result["reason"] = "NeuroSim binary is not executable"
        return result
    result["binary_sha256"] = _sha256(binary)
    try:
        completed = subprocess.run(["git", "-C", str(root), "rev-parse", "HEAD"],
                                   capture_output=True, text=True, timeout=30)
        result["commit"] = completed.stdout.strip() or None
    except (OSError, subprocess.SubprocessError):
        result["commit"] = None
    marker = root / "Inference_pytorch/NeuroSIM/compiler.txt"
    result["compiler"] = marker.read_text().strip() if marker.is_file() else None
    result["available"] = True
    return result


def preset_decision(preset=None, preset_path=None):
    """Decide whether a CTFM PPA run may proceed at all.

    A preset is admissible only if it exists, carries every required field, and
    is explicitly marked validated against the CTFM equivalent circuit. Nothing
    here invents a default: NeuroSim's stock SRAM/22 nm values are a starting
    point for review, never a CTFM result.
    """
    decision = {"status": "unsupported", "preset_id": None, "preset_hash": None,
                "missing_fields": [], "problems": [], "assumed_equivalent_circuit": False,
                "model_mismatches": [dict(m) for m in MODEL_MISMATCHES]}
    if preset is None and preset_path is None:
        decision["problems"].append("No preset supplied; PPA is off for the first release")
        return decision
    if preset_path is not None:
        path = Path(preset_path)
        if not path.is_file():
            decision["problems"].append("Preset file not found: " + str(path))
            return decision
        decision["preset_hash"] = _sha256(path)
        try:
            preset = json.loads(path.read_bytes())
        except ValueError as exc:
            decision["problems"].append("Preset is not valid JSON (" + type(exc).__name__ + ")")
            return decision
    if not isinstance(preset, dict):
        decision["problems"].append("Preset must be a JSON object")
        return decision
    decision["preset_id"] = preset.get("preset_id")
    decision["assumed_equivalent_circuit"] = bool(preset.get("assumed_equivalent_circuit"))
    decision["missing_fields"] = sorted(f for f in REQUIRED_PRESET_FIELDS if preset.get(f) is None)
    if decision["missing_fields"]:
        decision["problems"].append("Preset is missing required physical values")
    for field in ("read_voltage_v", "read_pulse_width_s"):
        value = preset.get(field)
        if value is None:
            continue
        if isinstance(value, bool) or not isinstance(value, (int, float)) \
                or not math.isfinite(value) or value <= 0:
            decision["problems"].append(field + " must be a positive finite SI value")
    if preset.get("read_pulse_width_s") == 1e-3:
        decision["problems"].append("read_pulse_width_s equals the 1 ms write pulse; write width "
                                    "must not be reused as read latency")
    if not preset.get("validated_for_ctfm"):
        decision["problems"].append("Preset is not marked validated_for_ctfm; an unvalidated "
                                    "preset may not produce CTFM PPA numbers")
    if not decision["problems"]:
        decision["status"] = "supported"
    return decision


def conductance_bounds(profile_states):
    """Ron=1/Gmax and Roff=1/Gmin in SI ohms from the adopted measured states.

    Returns None bounds rather than substituting a value when the pool has no
    usable positive conductance.
    """
    values = [float(s["conductance_s"]) for s in profile_states
              if s.get("selected") and s.get("conductance_s") is not None
              and float(s["conductance_s"]) > 0 and math.isfinite(float(s["conductance_s"]))]
    if not values:
        return {"resistance_on_ohm": None, "resistance_off_ohm": None,
                "max_conductance_s": None, "min_conductance_s": None,
                "reason": "no positive measured conductance in the adopted pool"}
    return {"resistance_on_ohm": 1.0 / max(values), "resistance_off_ohm": 1.0 / min(values),
            "max_conductance_s": max(values), "min_conductance_s": min(values), "reason": None}


def encode_weight_csv(weight, path):
    """Write NeuroSim's weight trace: [in_features, out_features], '%10.5f'.

    Mirrors utee.hook.write_matrix_weight from the engine checkout. Kept here so
    ctfm-core need not import that checkout; the Linux parity script compares
    both writers byte for byte.
    """
    import numpy as np
    array = np.asarray(weight, dtype=float)
    matrix = array.reshape(array.shape[0], -1).transpose()
    np.savetxt(str(path), matrix, delimiter=",", fmt="%10.5f")
    return matrix.shape


def encode_activation_csv(activation, bits, path):
    """Write NeuroSim's FC activation trace: [in_features, bits] of bit planes.

    Mirrors utee.hook.dec2bin plus write_matrix_activation_fc: a two's-complement
    encoding whose first plane is the sign bit weighted -2**(bits-1)*delta, with
    delta = 1/2**(bits-1). Values must lie in [-1, 1).
    """
    import numpy as np
    values = np.asarray(activation, dtype=float).reshape(-1)
    if values.size == 0:
        raise ValueError("Activation trace requires at least one value")
    if not np.isfinite(values).all():
        raise ValueError("Nonfinite activation trace")
    if values.min() < -1 or values.max() >= 1:
        raise ValueError("NeuroSim activation encoding requires values in [-1, 1)")
    delta = 1.0 / (2 ** (bits - 1))
    scaled = values / delta
    planes = np.zeros((values.size, bits), dtype=int)
    sign = (scaled < 0).astype(int)
    planes[:, 0] = sign
    rest = scaled + (2 ** (bits - 1)) * sign
    base = 2 ** (bits - 1)
    for index in range(1, bits):
        base = base / 2
        bit = (rest >= base).astype(int)
        planes[:, index] = bit
        rest = rest - base * bit
    np.savetxt(str(path), planes, delimiter=",", fmt="%d")
    return planes.shape


def write_network_csv(layer_dims, path):
    """Encode fully-connected layers the way NeuroSim's NetWork_*.csv does.

    Columns: IFM_row, IFM_col, in_channels, kernel_row, kernel_col, out_channels,
    followed_by_pooling, trailing flag. An FC layer is a 1x1 'conv'.
    """
    rows = ["1,1,{},1,1,{},0,1".format(fan_in, fan_out) for fan_in, fan_out in layer_dims]
    Path(path).write_text("\n".join(rows) + "\n")
    return rows


def topology_support(layer_dims):
    """Refuse shapes verified to crash this build; let anything else attempt a run.

    A shape that is not listed still runs: run_engine() spawns the binary in its
    own subprocess, so a segfault surfaces as status 'failed' with a negative
    return code instead of taking the worker down. This guard only avoids
    spending a run on a shape already known to die.
    """
    shape = tuple((int(a), int(b)) for a, b in layer_dims)
    if shape in CRASHING_TOPOLOGIES:
        return False, UNSUPPORTED_TOPOLOGY
    if any(fan_out < MIN_SAFE_OUT_FEATURES for _, fan_out in shape):
        return False, UNSUPPORTED_TOPOLOGY
    return True, None


_AREA_PATTERNS = (
    ("chip_area_m2", r"^ChipArea\s*:\s*([0-9.eE+-]+)um\^2", 1e-12),
    ("chip_array_area_m2", r"^Chip total CIM array\s*:\s*([0-9.eE+-]+)um\^2", 1e-12),
    ("chip_adc_area_m2", r"^Total ADC[^:]*Area on chip\s*:\s*([0-9.eE+-]+)um\^2", 1e-12),
)

# NeuroSim reports two independent cost models and the strings differ only by a
# few words, so every pattern is anchored to the whole line. An unanchored
# "readLatency \(per image\)" also matches "Chip pipeline-system buffer
# readLatency", which would silently report buffer latency as system latency.
_MODE_PATTERNS = {
    "layer_by_layer": (
        ("latency_s", r"^Chip layer-by-layer readLatency \(per image\) is:\s*([0-9.eE+-]+)ns", 1e-9),
        ("read_dynamic_energy_j", r"^Chip total readDynamicEnergy is:\s*([0-9.eE+-]+)pJ", 1e-12),
        ("leakage_power_w", r"^Chip total leakage Power is:\s*([0-9.eE+-]+)uW", 1e-6),
        ("leakage_energy_j", r"^Chip total leakage Energy is:\s*([0-9.eE+-]+)pJ", 1e-12),
        ("tops", r"^Throughput TOPS \(Layer-by-Layer Process\):\s*([0-9.eE+-]+)", 1.0),
        ("tops_per_w", r"^Energy Efficiency TOPS/W \(Layer-by-Layer Process\):\s*([0-9.eE+-]+)", 1.0),
    ),
    "pipelined": (
        ("latency_s", r"^Chip pipeline-system-clock-cycle \(per image\) is:\s*([0-9.eE+-]+)ns", 1e-9),
        ("read_dynamic_energy_j", r"^Chip pipeline-system readDynamicEnergy \(per image\) is:\s*([0-9.eE+-]+)pJ", 1e-12),
        ("leakage_power_w", r"^Chip pipeline-system leakage Power \(per image\) is:\s*([0-9.eE+-]+)uW", 1e-6),
        ("leakage_energy_j", r"^Chip pipeline-system leakage Energy \(per image\) is:\s*([0-9.eE+-]+)pJ", 1e-12),
        ("tops", r"^Throughput TOPS \(Pipelined Process\):\s*([0-9.eE+-]+)", 1.0),
        ("tops_per_w", r"^Energy Efficiency TOPS/W \(Pipelined Process\):\s*([0-9.eE+-]+)", 1.0),
    ),
}


def parse_stdout(text):
    """Convert NeuroSim's um^2/ns/pJ/uW report into SI. Absent values stay None.

    Area is chip-wide; latency and energy are reported per process mode, so both
    are returned under ``modes`` and the caller chooses rather than inheriting
    whichever line happened to match first.
    """
    def grab(pattern, scale):
        match = re.search(pattern, text, re.MULTILINE)
        return None if match is None else float(match.group(1)) * scale

    parsed = {name: grab(pattern, scale) for name, pattern, scale in _AREA_PATTERNS}
    parsed["modes"] = {mode: {name: grab(pattern, scale) for name, pattern, scale in patterns}
                       for mode, patterns in _MODE_PATTERNS.items()}
    parsed["modes_reported"] = sorted(mode for mode, values in parsed["modes"].items()
                                      if values["latency_s"] is not None)
    return parsed


def _terminate(process):
    try:
        os.killpg(os.getpgid(process.pid), signal.SIGTERM)
        process.wait(timeout=30)
    except (OSError, subprocess.TimeoutExpired):
        try:
            os.killpg(os.getpgid(process.pid), signal.SIGKILL)
        except OSError:
            pass


def run_engine(network_csv, trace_args, *, synapse_bit, input_bit, sub_array, parallel_rows,
               root=None, timeout=1800.0, cancelled=None):
    """Invoke the engine binary in its own process group.

    The group is what gets signalled, so a cancelled job cannot leave the engine
    or its children running. A crash is reported as a negative return code and a
    failed status rather than being turned into a number.
    """
    status = engine_status(root)
    blank = {"engine": status, "returncode": None, "stdout": "", "stderr": "", "parsed": None}
    if not status["available"]:
        return dict(blank, status="unsupported", reason=status["reason"])
    argv = [status["binary"], str(network_csv), str(synapse_bit), str(input_bit),
            str(sub_array), str(parallel_rows)] + [str(a) for a in trace_args]
    started = time.monotonic()
    process = subprocess.Popen(argv, cwd=str(Path(status["binary"]).parent.parent),
                               stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
                               start_new_session=True)
    try:
        while True:
            try:
                out, err = process.communicate(timeout=1.0)
                break
            except subprocess.TimeoutExpired:
                if cancelled is not None and cancelled():
                    _terminate(process)
                    return dict(blank, status="cancelled", reason="cancelled")
                if time.monotonic() - started > timeout:
                    _terminate(process)
                    return dict(blank, status="failed",
                                reason="engine exceeded {} s".format(timeout))
    finally:
        if process.poll() is None:
            _terminate(process)
    result = {"engine": status, "argv": argv, "returncode": process.returncode,
              "stdout": out, "stderr": err, "seconds": round(time.monotonic() - started, 3)}
    if process.returncode != 0:
        return dict(result, status="failed", parsed=None,
                    reason="engine exited with {}".format(process.returncode))
    return dict(result, status="succeeded", parsed=parse_stdout(out), reason=None)


# NeuroSim normalizes the weight file onto [algoWeightMin, algoWeightMax] = [-1, 1]
# (Param.cpp), so the nominal restored weights have to be scaled into that range
# and the scale recorded. The engine then spreads that range linearly over
# [minConductance, maxConductance], which is one of the model mismatches.
ALGO_WEIGHT_MAX = 1.0


def _normalize(array, bits):
    """Scale into NeuroSim's [-1, 1) input domain and report the divisor used."""
    import numpy as np
    values = np.asarray(array, dtype=float)
    if not np.isfinite(values).all():
        raise ValueError("Nonfinite values cannot be encoded for the engine")
    peak = float(np.abs(values).max())
    if peak == 0.0:
        return values, 1.0
    # Keep the top code strictly below 1.0; dec2bin's grid excludes +1.
    ceiling = ALGO_WEIGHT_MAX - 2.0 ** -(bits - 1)
    scale = peak / ceiling
    return values / scale, scale


def build_engine_inputs(layers, layer_inputs, out_dir, *, input_bits, synapse_bit,
                        profile_states=None, network_name="ctfm"):
    """Assemble one engine invocation from a nominal mapping and its trace.

    ``layers`` are the nominal restored layers (name plus [out, in] weights) and
    ``layer_inputs`` the matching per-layer activations captured from the trace
    forward pass, in the same order. Upstream records only the first sample of
    each layer's input, so that is what is written here too.

    Returns the argv fragment, the normalization actually applied and the
    conductance bounds, so the caller can store all three next to the result
    instead of the numbers appearing without their scaling.
    """
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    if len(layers) != len(layer_inputs):
        raise ValueError("Each layer needs exactly one captured activation trace")

    dims = [(int(layer["weights"].shape[1]), int(layer["weights"].shape[0])) for layer in layers]
    network_csv = out_dir / ("NetWork_%s.csv" % network_name)
    rows = write_network_csv(dims, network_csv)

    trace_args, normalization = [], []
    for layer, activation in zip(layers, layer_inputs):
        name = layer["name"]
        weight, weight_scale = _normalize(layer["weights"], synapse_bit)
        sample, input_scale = _normalize(activation[0], input_bits)
        weight_csv = out_dir / ("weight_%s.csv" % name)
        input_csv = out_dir / ("input_%s.csv" % name)
        encode_weight_csv(weight, weight_csv)
        encode_activation_csv(sample, input_bits, input_csv)
        trace_args += [weight_csv, input_csv]
        normalization.append({
            "layer": name,
            "shape": [int(layer["weights"].shape[0]), int(layer["weights"].shape[1])],
            "weight_divisor": weight_scale,
            "activation_divisor": input_scale,
            "note": "engine weights are the nominal restored w_hat divided by this "
                    "divisor to fit NeuroSim's [-1, 1] algorithmic range",
        })

    return {
        "network_csv": network_csv,
        "network_rows": rows,
        "layer_dims": dims,
        "trace_args": trace_args,
        "normalization": normalization,
        "trace_sample": "test[:256] first example per layer",
        "conductance": conductance_bounds(profile_states or []),
        "input_bits": input_bits,
        "synapse_bit": synapse_bit,
    }


def export_preset(preset, out_dir, filename="neurosim-preset.json"):
    """Write the effective preset next to the run and return its hash.

    A PPA number is only reproducible with the exact preset that produced it, so
    the file is written even when the gate refuses the run.
    """
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    path = out_dir / filename
    payload = dict(preset or {})
    payload.setdefault("engine", "neurosim_2d_inference_v1_4")
    payload["required_fields"] = sorted(REQUIRED_PRESET_FIELDS)
    payload["model_mismatches"] = [dict(m) for m in MODEL_MISMATCHES]
    path.write_bytes(json.dumps(payload, indent=2, sort_keys=True, ensure_ascii=False).encode())
    # Relative filename only: the result is served to browsers, and server paths
    # are an implementation detail the API contract keeps out of responses.
    return {"filename": filename, "sha256": _sha256(path)}


def ppa_result(layer_dims, *, preset=None, preset_path=None, root=None, inputs=None,
               out_dir=None, timeout=1800.0, cancelled=None):
    """The gate the simulator calls, and the executor once the gate opens.

    Refuses with explicit reasons until a validated CTFM preset exists, the
    engine is built, and the topology is one this build survives. Numeric fields
    stay None so absence is never read as zero. When every reason clears and
    ``inputs`` is supplied, the engine actually runs and the SI numbers come from
    its stdout.
    """
    engine = engine_status(root)
    decision = preset_decision(preset, preset_path)
    supported, reason = topology_support(layer_dims)
    reasons = list(decision["problems"])
    if not engine["available"]:
        reasons.append(engine["reason"])
    if not supported:
        reasons.append(reason)
    # The differential pair is two physical planes per weight; the cost of the
    # second plane is not modelled yet because whether NeuroSim may be used as an
    # approximation for it is decision A5, not something to assume here.
    reasons.append(DIFFERENTIAL_PLANE_UNRESOLVED)

    result = {"status": "unsupported", "engine": engine, "preset": decision,
              "area_m2": None, "energy_j_per_inference": None,
              "latency_s_per_inference": None, "raw_output": None,
              "model_mismatches": decision["model_mismatches"],
              "trace_sample": "test[:256]", "time_basis": "nominal t_ref",
              "reasons": reasons}
    if out_dir is not None:
        result["preset_artifact"] = export_preset(preset, out_dir)
    if inputs is not None:
        result["normalization"] = inputs["normalization"]
        result["conductance"] = inputs["conductance"]
        result["trace_sample"] = inputs["trace_sample"]
    if reasons or inputs is None:
        return result

    run = run_engine(inputs["network_csv"], inputs["trace_args"],
                     synapse_bit=inputs["synapse_bit"], input_bit=inputs["input_bits"],
                     sub_array=preset["sub_array"], parallel_rows=preset["parallel_rows"],
                     root=root, timeout=timeout, cancelled=cancelled)
    # argv carries absolute server paths, so only the basenames are published.
    argv = [Path(a).name for a in (run.get("argv") or [])]
    result["raw_output"] = {"stdout": run.get("stdout"), "stderr": run.get("stderr"),
                            "returncode": run.get("returncode"), "argv": argv}
    if run["status"] != "succeeded":
        result.update(status=run["status"], reasons=[run.get("reason")])
        return result
    parsed = run["parsed"]
    mode = (parsed["modes_reported"] or [None])[0]
    values = parsed["modes"].get(mode, {}) if mode else {}
    result.update(status="succeeded", reasons=[], process_mode=mode, parsed=parsed,
                  area_m2=parsed["chip_area_m2"],
                  energy_j_per_inference=values.get("read_dynamic_energy_j"),
                  latency_s_per_inference=values.get("latency_s"))
    return result
