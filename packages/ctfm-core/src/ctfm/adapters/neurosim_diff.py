"""Two-plane (G+/G-) NeuroSim cost path for the ``assumed_proxy`` preset (docs/spec/08 sections 3-5).

The accuracy model drives unsigned 8 bit codes LSB-first through two measured conductance planes. This module makes the
cost engine see the same thing instead of a re-quantised, sign-encoded stand-in:

* G+ and G- reach the engine as conductance files in siemens (``ctfmConductanceInput``), not as one normalised weight file;
* the activation trace holds the 8 unsigned bit planes of the same codes, LSB first;
* the engine (isolated patch 0002) computes both planes inside every subarray-cycle, owns per-plane blocks per plane,
  counts shift-add/accumulate and everything downstream once, and takes the slower plane for timing;
* what the engine actually used (column conductance, active rows, weight cells, subarray slots) is printed in a ledger
  and checked here against numbers computed independently from the files, so "the engine exited 0" is never taken as
  "the engine modelled this circuit".

Blocks without a grounded model (signed sensing front end, ADC range scaling, bias add, ...) stay unknown, never zero.
"""
from __future__ import annotations

import concurrent.futures
import math
import os
import re
import subprocess
from pathlib import Path

UNSIGNED_BITS = 8


# ---------------------------------------------------------------------------
# trace writers
# ---------------------------------------------------------------------------

def write_conductance_csv(g_out_in, path):
    """One plane's conductances in siemens as the engine reads them: [in_features, out_features], exact values."""
    import numpy as np
    g = np.asarray(g_out_in, dtype=np.float64)
    if g.ndim != 2 or not np.isfinite(g).all() or not (g > 0).all():
        raise ValueError("Conductance planes must be finite and strictly positive")
    np.savetxt(str(path), g.T, delimiter=",", fmt="%.17g")
    return g.T.shape


def unsigned_planes(codes, bits=UNSIGNED_BITS):
    """[in_features, bits] bit planes of unsigned codes; column k is bit k, i.e. the k-th cycle of the LSB-first schedule."""
    import numpy as np
    values = np.asarray(codes)
    if values.ndim != 1:
        raise ValueError("One activation vector per trace")
    if not np.issubdtype(values.dtype, np.integer):
        if not np.array_equal(values, np.floor(values)):
            raise ValueError("Activation codes must be integers")
        values = values.astype(np.int64)
    if values.min() < 0 or values.max() >= 2**bits:
        raise ValueError("Unsigned %d bit codes must lie in [0, %d]" % (bits, 2**bits-1))
    return ((values.reshape(-1, 1) >> np.arange(bits)) & 1).astype(np.int64)


def write_unsigned_planes_csv(codes, path, bits=UNSIGNED_BITS):
    import numpy as np
    planes = unsigned_planes(codes, bits)
    np.savetxt(str(path), planes, delimiter=",", fmt="%d")
    return planes.shape


def decode_unsigned_planes(planes):
    """Inverse of :func:`unsigned_planes` (weights 1, 2, 4, ... for columns 0, 1, 2, ...)."""
    import numpy as np
    array = np.asarray(planes, dtype=np.int64)
    return (array << np.arange(array.shape[1])).sum(axis=1)


# ---------------------------------------------------------------------------
# ledger and report parsing
# ---------------------------------------------------------------------------

_NUMBER = r"([0-9.eE+-]+)"
_SUMMARY = {
    "chip_area_m2": (r"^ChipArea\s*:\s*" + _NUMBER + r"um\^2", 1e-12),
    "array_area_m2": (r"^Chip total CIM array\s*:\s*" + _NUMBER + r"um\^2", 1e-12),
    "ic_area_m2": (r"^Total IC Area on chip[^:]*:\s*" + _NUMBER + r"um\^2", 1e-12),
    "adc_area_m2": (r"^Total ADC[^:]*Area on chip\s*:\s*" + _NUMBER + r"um\^2", 1e-12),
    "accum_area_m2": (r"^Total Accumulation Circuits[^:]*on chip\s*:\s*" + _NUMBER + r"um\^2", 1e-12),
    "other_area_m2": (r"^Other Peripheries[^:]*:\s*" + _NUMBER + r"um\^2", 1e-12),
    "clock_period_s": (r"^Chip clock period is:\s*" + _NUMBER + r"ns", 1e-9),
    "latency_s": (r"^Chip layer-by-layer readLatency \(per image\) is:\s*" + _NUMBER + r"ns", 1e-9),
    "energy_j": (r"^Chip total readDynamicEnergy is:\s*" + _NUMBER + r"pJ", 1e-12),
    "leakage_energy_j": (r"^Chip total leakage Energy is:\s*" + _NUMBER + r"pJ", 1e-12),
    "leakage_power_w": (r"^Chip total leakage Power is:\s*" + _NUMBER + r"uW", 1e-6),
    "buffer_latency_s": (r"^Chip buffer readLatency is:\s*" + _NUMBER + r"ns", 1e-9),
    "buffer_energy_j": (r"^Chip buffer readDynamicEnergy is:\s*" + _NUMBER + r"pJ", 1e-12),
    "ic_latency_s": (r"^Chip ic readLatency is:\s*" + _NUMBER + r"ns", 1e-9),
    "ic_energy_j": (r"^Chip ic readDynamicEnergy is:\s*" + _NUMBER + r"pJ", 1e-12),
    "adc_class_latency_s": (r"^----------- ADC[^:]*readLatency is :\s*" + _NUMBER + r"ns", 1e-9),
    "accum_class_latency_s": (r"^----------- Accumulation Circuits.*readLatency is :\s*" + _NUMBER + r"ns", 1e-9),
    "other_class_latency_s": (r"^----------- Other Peripheries[^:]*readLatency is :\s*" + _NUMBER + r"ns", 1e-9),
    "adc_class_energy_j": (r"^----------- ADC[^:]*readDynamicEnergy is :\s*" + _NUMBER + r"pJ", 1e-12),
    "accum_class_energy_j": (r"^----------- Accumulation Circuits.*readDynamicEnergy is :\s*" + _NUMBER + r"pJ", 1e-12),
    "other_class_energy_j": (r"^----------- Other Peripheries[^:]*readDynamicEnergy is :\s*" + _NUMBER + r"pJ", 1e-12),
}
_KEYVALUE = re.compile(r"([A-Za-z_0-9]+)=([^\s]+)")


def _number(text):
    try:
        return float(text)
    except ValueError:
        return text


def parse_report(text):
    """Chip summary in SI plus the CTFM ledger. Values the report lacks stay None."""
    summary = {}
    for name, (pattern, scale) in _SUMMARY.items():
        matches = re.findall(pattern, text, re.MULTILINE)
        # the per-layer breakdown blocks print the same labels before the chip-level block, which is the last one
        summary[name] = None if not matches else float(matches[-1])*scale
    ledger = {"flags": None, "clk": None, "params": None, "slot": None, "layers": []}
    for line in text.splitlines():
        if line.startswith("CTFM_FLAGS "):
            ledger["flags"] = {k: int(v) for k, v in _KEYVALUE.findall(line)}
        elif line.startswith("CTFM_CLK "):
            ledger["clk"] = {k: _number(v) for k, v in _KEYVALUE.findall(line)}
        elif line.startswith("CTFM_PARAMS "):
            ledger["params"] = {k: _number(v) for k, v in _KEYVALUE.findall(line)}
        elif line.startswith("CTFM_SLOT "):
            ledger["slot"] = {k: _number(v) for k, v in _KEYVALUE.findall(line)}
        elif line.startswith("CTFM_LAYER "):
            ledger["layers"].append({k: _number(v) for k, v in _KEYVALUE.findall(line)})
    removed = re.search(r"CTFM used-only: removed ([0-9.]+) unused subarray slot", text)
    ledger["removed_unused_slots"] = None if removed is None else float(removed.group(1))
    return {"summary": summary, "ledger": ledger}


# ---------------------------------------------------------------------------
# independent expectations computed from the files
# ---------------------------------------------------------------------------

def expected_column_conductance(g_out_in, planes, params, tile):
    """Sum over subarray-cycles and columns of the column conductance NeuroSim derives (GetColumnResistance).

    ``g_out_in`` is [out, in] in siemens, ``planes`` the [in, 8] bit planes, ``params`` the engine's ledger PARAMS. For every
    input bit, every active row of a subarray adds 1 / (1/g + (j+1) R_row + (rows - i) R_col + R_access), with i the row
    and j the column inside the subarray and rows the subarray's actual row count.
    """
    import numpy as np
    g = np.asarray(g_out_in, dtype=np.float64).T          # [in, out]
    n_in, n_out = g.shape
    r_row, r_col, r_acc = params["wire_res_row_ohm"], params["wire_res_col_ohm"], params["resistance_access_ohm"]
    bits = np.asarray(planes, dtype=np.float64)           # [in, 8]
    total = 0.0
    for r0 in range(0, n_in, tile):
        rows = min(tile, n_in-r0)
        for c0 in range(0, n_out, tile):
            cols = min(tile, n_out-c0)
            block = g[r0:r0+rows, c0:c0+cols]
            i = np.arange(rows).reshape(-1, 1)
            j = np.arange(cols).reshape(1, -1)
            resistance = 1.0/block + (j+1)*r_row + (rows-i)*r_col + r_acc
            contribution = 1.0/resistance                  # [rows, cols]
            active = bits[r0:r0+rows, :]                   # [rows, 8]
            total += float((active.T @ contribution).sum())
    return total


def expected_activity(planes, tile, n_out):
    """Rows read summed over subarray-cycles: every set bit is read once per column-subarray it feeds."""
    import numpy as np
    column_tiles = -(-n_out//tile)
    return float(np.asarray(planes).sum())*column_tiles


def spec_slots(layer_dims, tile):
    """Subarray slots the spec 08 tiling needs per plane: ceil(fan_in/tile) x ceil(fan_out/tile) per layer."""
    return [(-(-int(a)//tile))*(-(-int(b)//tile)) for a, b in layer_dims]


# ---------------------------------------------------------------------------
# engine runs
# ---------------------------------------------------------------------------

def build_config_diff(preset, hardware, bounds, adc_order):
    """Compile-time configuration of the two-plane cost build: pool resistance window, spec 08 accounting flags."""
    from ctfm.adapters import neurosim
    if adc_order not in neurosim.ADC_ORDERS:
        raise ValueError("Cost depends on the ADC order: " + ", ".join(neurosim.ADC_ORDERS))
    if bounds.get("resistance_on_ohm") is None:
        raise ValueError("The pool has no positive conductance: " + str(bounds.get("reason")))
    base = neurosim.build_config(preset, hardware)
    from ctfm.adapters import neurosim_build
    extra = {"resistance_on_ohm": bounds["resistance_on_ohm"], "resistance_off_ohm": bounds["resistance_off_ohm"],
             # writeVoltage only decides whether write level shifters exist; 1.0 V is below the engine's 1.5 V threshold
             "write_voltage_v": 1.0,
             "ctfm_conductance_input": 1, "ctfm_differential": 1,
             "ctfm_adc_order": 1 if adc_order == "adc_then_subtract" else 2,
             "ctfm_no_duplication": 1, "ctfm_read_only": 1, "ctfm_used_only": 1}
    config = dict(base)
    config.update(extra)
    return config, extra


def pool_bounds(states):
    """Ron = 1/Gmax and Roff = 1/Gmin over the pool's measured conductances (spec 08 section 3)."""
    values = [float(s["conductance_s"]) for s in states
              if s.get("conductance_s") is not None and math.isfinite(float(s["conductance_s"])) and float(s["conductance_s"]) > 0]
    if not values:
        return {"resistance_on_ohm": None, "resistance_off_ohm": None, "max_conductance_s": None,
                "min_conductance_s": None, "reason": "no positive measured conductance in the pool"}
    return {"resistance_on_ohm": 1.0/max(values), "resistance_off_ohm": 1.0/min(values),
            "max_conductance_s": max(values), "min_conductance_s": min(values), "reason": None}


def stage_weights(layers, out_dir):
    """Write G+/G- per layer; return the network rows and per-layer file pairs."""
    from ctfm.adapters import neurosim
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    dims = [(int(l["g_plus"].shape[1]), int(l["g_plus"].shape[0])) for l in layers]
    network_csv = out_dir/"NetWork_ctfm.csv"
    neurosim.write_network_csv(dims, network_csv)
    files = []
    for layer in layers:
        plus, minus = out_dir/("gplus_%s.csv" % layer["name"]), out_dir/("gminus_%s.csv" % layer["name"])
        write_conductance_csv(layer["g_plus"], plus)
        write_conductance_csv(layer["g_minus"], minus)
        files.append((plus, minus))
    return dims, network_csv, files


def stage_sample(codes_per_layer, layers, sample_dir):
    sample_dir = Path(sample_dir)
    sample_dir.mkdir(parents=True, exist_ok=True)
    paths = []
    for layer, codes in zip(layers, codes_per_layer):
        path = sample_dir/("codes_%s.csv" % layer["name"])
        write_unsigned_planes_csv(codes, path)
        paths.append(path)
    return paths


def _run_once(binary, cwd, network_csv, tile, weight_files, input_files, timeout):
    argv = [str(binary), str(network_csv), "8", "8", str(tile), str(tile)]
    for (plus, minus), inputs in zip(weight_files, input_files):
        argv += [str(plus), str(minus), str(inputs)]
    completed = subprocess.run(argv, cwd=str(cwd), capture_output=True, text=True, timeout=timeout)
    return completed.returncode, completed.stdout, completed.stderr, argv


def run_samples(binary, cwd, network_csv, tile, weight_files, sample_inputs, *, workers=None, timeout=600.0, cancelled=None):
    """Run the engine once per test sample (each with its own input bit trace); returns the parsed reports.

    A single engine run costs one input vector, so per-image energy varies with the image's activity. The samples are the
    fixed first test images, and the caller reports how many were used.
    """
    workers = workers or max(1, min(8, (os.cpu_count() or 2)))
    results = [None]*len(sample_inputs)

    def job(index):
        if cancelled is not None and cancelled():
            return index, None
        code, out, err, argv = _run_once(binary, cwd, network_csv, tile, weight_files, sample_inputs[index], timeout)
        return index, (code, out, err, argv)

    with concurrent.futures.ThreadPoolExecutor(max_workers=workers) as pool:
        for index, payload in pool.map(job, range(len(sample_inputs))):
            results[index] = payload
    return results


def aggregate(samples):
    """Mean/std/min/max of the per-image quantities; area-like values must be identical across images."""
    import numpy as np
    reports = [parse_report(text) for (_, text, _, _) in samples]
    names = ("energy_j", "latency_s", "leakage_energy_j", "buffer_energy_j", "ic_energy_j", "adc_class_energy_j",
             "accum_class_energy_j", "other_class_energy_j", "clock_period_s", "adc_class_latency_s", "accum_class_latency_s",
             "other_class_latency_s", "buffer_latency_s", "ic_latency_s")
    stats = {}
    for name in names:
        values = [r["summary"][name] for r in reports]
        if any(v is None for v in values):
            stats[name] = None
            continue
        arr = np.asarray(values, dtype=float)
        stats[name] = {"mean": float(arr.mean()), "std": float(arr.std(ddof=1)) if len(arr) > 1 else 0.0,
                       "min": float(arr.min()), "max": float(arr.max()), "n": int(len(arr))}
    areas = {}
    for name in ("chip_area_m2", "array_area_m2", "ic_area_m2", "adc_area_m2", "accum_area_m2", "other_area_m2", "leakage_power_w"):
        values = [r["summary"][name] for r in reports]
        areas[name] = values[0]
        areas[name+"_identical_across_images"] = all(v == values[0] for v in values)
    layers = []
    n_layers = len(reports[0]["ledger"]["layers"])
    for l in range(n_layers):
        keys = [k for k in reports[0]["ledger"]["layers"][l] if k != "l"]
        layers.append({k: float(np.mean([r["ledger"]["layers"][l][k] for r in reports])) for k in keys})
    return {"images": len(reports), "stats": stats, "static": areas, "ledger_layers_mean": layers,
            "ledger_flags": reports[0]["ledger"]["flags"], "ledger_params": reports[0]["ledger"]["params"],
            "ledger_slot": reports[0]["ledger"]["slot"], "removed_unused_slots": reports[0]["ledger"]["removed_unused_slots"],
            "first": reports[0]}
