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
    "read_pulse_width_source": "where the read pulse width comes from, e.g. "
                               "'engine_baseline_22nm' or a named measurement",
    "access_type": "access device model, e.g. CMOS_access",
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
    {"id": "input_encoding",
     "detail": "The accuracy model drives unsigned 8 bit activations LSB-first over a fixed "
               "8 cycle schedule; NeuroSim's FC activation trace is a signed two's-complement "
               "encoding whose first plane carries the sign weight, so a nonnegative "
               "activation reaches only 2**(bits-1) levels -- one bit less than the accuracy "
               "path drives. Measured per layer in the result's activation_fidelity"},
    {"id": "adc_position",
     "detail": "The accuracy model quantizes the differential partial sum after digital "
               "subtraction; NeuroSim quantizes per physical column group"},
)

# Measured (shape, subArray) outcomes on this build (commit ac828e6, gcc 13.3),
# from scripts/linux/repro_neurosim_crash.py and the boundary probe recorded in
# docs/implementation-status.md. The crash is a SIGSEGV inside CopyPEArray.
#
# The subArray size is part of the observation, not a detail: mnist_mlp_v1
# segfaults at 64 and 128 and RUNS at 256. An earlier note in this file claimed
# a general "fewer than 96 output features crashes" rule and listed 1024x10 and
# 128x10 as crashing; direct measurement refutes all three -- they complete at
# subArray 64. No general rule is claimed here, only what was observed.
MEASURED_TOPOLOGIES = {
    (((784, 128), (128, 10)), 64): False,
    (((784, 128), (128, 10)), 128): False,
    (((784, 128), (128, 10)), 256): True,
    (((257, 128), (128, 10)), 32): False,
    (((257, 128), (128, 10)), 64): False,
    (((257, 128), (128, 10)), 128): True,
    (((260, 128), (128, 10)), 64): False,
    (((320, 128), (128, 10)), 64): False,
    (((512, 128), (128, 10)), 64): True,
    (((256, 128), (128, 10)), 32): True,
    (((256, 128), (128, 10)), 64): True,
    (((256, 128), (128, 10)), 128): True,
    (((255, 128), (128, 10)), 64): True,
    (((196, 128), (128, 10)), 64): True,
    (((128, 128), (128, 10)), 64): True,
    (((128, 10),), 64): True,
    (((256, 10),), 64): True,
    (((1024, 10),), 64): True,
    (((256, 64),), 64): True,
    (((784, 64),), 64): False,
    (((784, 128),), 64): True,
}

UNSUPPORTED_TOPOLOGY = (
    "NeuroSim V1.4 segfaults on this shape at this subArray size (measured on this build). "
    "The same shape may run at another array size: mnist_mlp_v1 784x128x10 crashes at "
    "subArray 64 and 128 and completes at 256.")

# The accuracy model stores one analog cell per differential plane per weight and
# reads G+ minus G-. NeuroSim has no two-plane differential array, so the second
# plane's area, energy and latency would have to be modelled by an explicit
# approximation. Whether such an approximation may stand in for the CTFM circuit
# is a physical judgement nobody has made yet, so no cost model is assumed here.
DIFFERENTIAL_PLANE_UNRESOLVED = (
    "Differential two-plane cost is not modelled: NeuroSim has no native G+/G- plane pair and "
    "no approved approximation exists for the second plane's area/energy/latency")


ADC_ORDERS = ('subtract_then_adc', 'adc_then_subtract')
# ---------------------------------------------------------------------------
# Physical inventory and cost coverage (docs/spec/08-hardware-baseline.md s5)
# ---------------------------------------------------------------------------

# Blocks whose cost this project cannot yet produce. Each one is reported by
# name so a partial total is never mistaken for a complete one.
MISSING_COST_BLOCKS = {
    "analog_subtraction_frontend": {
        "applies_to": ["subtract_then_adc"],
        "detail": "Subtracting two column currents in the analog domain needs a bipolar "
                  "sensing front end. An unsigned current-mode MLSA block is not the same "
                  "circuit, so no area/energy/latency is claimed for it"},
    "bipolar_range_conversion": {
        "applies_to": ["subtract_then_adc"],
        "detail": "Mapping a signed column current onto the converter's input range is a "
                  "circuit, not a free change of units; assuming an ideal range-scaling "
                  "front end means its cost is missing"},
    "digital_subtraction": {
        "applies_to": ["adc_then_subtract"],
        "detail": "The digital subtract and the bit-significance shift-add after it are "
                  "counted structurally but have no cost model wired up yet"},
    "differential_plane_pair": {
        "applies_to": ["subtract_then_adc", "adc_then_subtract"],
        "detail": DIFFERENTIAL_PLANE_UNRESOLVED},
    "per_block_engine_costs": {
        "applies_to": ["subtract_then_adc", "adc_then_subtract"],
        "detail": "compose_differential_cost() implements the two-plane rule, but the "
                  "per-block area/energy/latency it composes must come from an engine run; "
                  "until then the composition has nothing to add up"},
}

EXCLUDED_BY_SCOPE = (
    {"id": "write_datapath",
     "detail": "Programming and erase energy, time and the level shifters and drivers that "
               "serve them are outside the inference read datapath this model costs"},
    {"id": "retention_and_d2d_sweeps",
     "detail": "Cost is evaluated once at the nominal t_ref; per-timepoint and per-array "
               "numbers are not produced and must not be shown as if they were"},
)


def circuit_inventory(layer_dims, *, tile_size, columns_per_adc, adc_bits, adc_order,
                      input_bits=8):
    """Count the physical parts of the two-plane differential array.

    ``layer_dims`` is [(fan_in, fan_out), ...]. A logical R x C tile means two
    R x C arrays, one per plane, one analog cell per weight per plane -- not
    ceil(synapse_bit/cell_bit) columns. Shared blocks are counted once for the
    whole layer; per-plane blocks are counted per plane.
    """
    if adc_order not in ADC_ORDERS:
        raise ValueError("Cost depends on the ADC order: "+", ".join(ADC_ORDERS))
    for name, value in (("tile_size", tile_size), ("columns_per_adc", columns_per_adc),
                        ("input_bits", input_bits)):
        if not isinstance(value, int) or isinstance(value, bool) or value < 1:
            raise ValueError(name+" must be a positive integer")
    layers = []
    for fan_in, fan_out in layer_dims:
        fan_in, fan_out = int(fan_in), int(fan_out)
        row_tiles = -(-fan_in//tile_size)
        column_tiles = -(-fan_out//tile_size)
        tiles = row_tiles*column_tiles
        # Physical cells: one per weight per plane, both planes present.
        cells_per_plane = fan_in*fan_out
        columns = min(tile_size, fan_out)
        adcs_per_tile_per_plane = -(-columns//columns_per_adc)
        # Converting first needs a converter on each plane and the two planes are
        # read at the same time, so neither shares the other's converter.
        planes_converted = 2 if adc_order == "adc_then_subtract" else 1
        adcs = tiles*adcs_per_tile_per_plane*planes_converted
        # Every bit plane is converted; the fixed 8 cycle schedule does not skip
        # an all-zero cycle in v1.
        conversions = adcs*input_bits*columns_per_adc if columns_per_adc else 0
        layers.append({
            "shape": [fan_in, fan_out],
            "logical_tiles": tiles, "row_tiles": row_tiles, "column_tiles": column_tiles,
            "physical_arrays": 2*tiles, "cells_per_plane": cells_per_plane,
            "physical_cells": 2*cells_per_plane,
            "adc_count": adcs, "adcs_per_tile_per_plane": adcs_per_tile_per_plane,
            "planes_converted": planes_converted,
            "conversion_cycles_per_inference": adcs*input_bits,
            "column_conversions_per_inference": conversions,
            # Counted once per layer however many planes there are.
            "shared_once": ["input_buffer", "final_accumulator", "interconnect",
                            "bit_significance_shift_add"],
            "per_plane": ["row_driver", "column_multiplexer", "array"],
        })
    return {"adc_order": adc_order, "tile_size": tile_size, "columns_per_adc": columns_per_adc,
            "adc_bits": adc_bits, "input_bits": input_bits, "layers": layers,
            "physical_cells": sum(l["physical_cells"] for l in layers),
            "adc_count": sum(l["adc_count"] for l in layers),
            "conversion_cycles_per_inference": sum(l["conversion_cycles_per_inference"]
                                                   for l in layers),
            "cells_per_weight_per_plane": 1,
            "latency_composition": ("planes read in parallel, so the array read latency is the "
                                    "maximum of the two, plus the common accumulate and "
                                    "subtract time"),
            "area_energy_composition": ("per-plane blocks add across both planes; shared blocks "
                                        "are counted once -- the chip total is never the "
                                        "single-plane total times two")}


# Blocks the composition needs a cost for. Split exactly the way decision A5
# fixed it: a per-plane block exists once per plane and adds across both, a
# shared block exists once for the pair however many planes there are.
PER_PLANE_BLOCKS = ("array", "row_driver", "column_multiplexer")
SHARED_BLOCKS = ("input_buffer", "final_accumulator", "interconnect",
                 "bit_significance_shift_add")
# Where the converter lives depends on the order: converting first puts one on
# each plane, subtracting first puts one after the (unmodelled) analog subtract.
CONVERTER_BLOCK = "adc"


def compose_differential_cost(per_plane, shared, *, adc_order, converter=None,
                              common_latency_s=0.0):
    """Combine per-block costs into the two-plane chip cost.

    docs/spec/08-hardware-baseline.md section 5 fixes the rule:

      area, energy  per-plane blocks add across BOTH planes; shared blocks are
                    counted once. The result is never the single-plane total
                    times two.
      latency       the planes are read at the same time, so the array read
                    latency is the MAXIMUM of the two, plus the common
                    accumulation and subtraction time.

    ``per_plane`` is {block: {"plane_a": {...}, "plane_b": {...}}} or
    {block: {...}} when both planes are identical. Each cost is
    {"area_m2", "energy_j", "latency_s"}. Missing blocks are returned by name and
    the totals stay None -- this function never fills a gap with zero.

    The rule is implemented; the per-block SI values still have to come from an
    engine run, which is why a caller with no block costs gets nulls back.
    """
    if adc_order not in ADC_ORDERS:
        raise ValueError("Composition depends on the ADC order: "+", ".join(ADC_ORDERS))
    per_plane = dict(per_plane or {})
    shared = dict(shared or {})
    if converter is not None:
        # Converting first means a converter per plane; subtracting first means a
        # single converter shared by the pair, after the analog subtract.
        (per_plane if adc_order == "adc_then_subtract" else shared)[CONVERTER_BLOCK] = converter

    missing = [name for name in PER_PLANE_BLOCKS if name not in per_plane]
    missing += [name for name in SHARED_BLOCKS if name not in shared]
    if CONVERTER_BLOCK not in per_plane and CONVERTER_BLOCK not in shared:
        missing.append(CONVERTER_BLOCK)

    def planes(cost):
        """A block given once applies identically to both planes."""
        if isinstance(cost, dict) and {"plane_a", "plane_b"} <= set(cost):
            return [cost["plane_a"], cost["plane_b"]]
        return [cost, cost]

    def value(cost, key):
        found = cost.get(key) if isinstance(cost, dict) else None
        return None if found is None or not math.isfinite(found) else float(found)

    incomplete = list(missing)
    area = energy = 0.0
    plane_latencies = [0.0, 0.0]
    for name, cost in per_plane.items():
        for index, side in enumerate(planes(cost)):
            for key, target in (("area_m2", "area"), ("energy_j", "energy")):
                found = value(side, key)
                if found is None:
                    incomplete.append(name+"."+key)
                elif target == "area":
                    area += found
                else:
                    energy += found
            latency = value(side, "latency_s")
            if latency is None:
                incomplete.append(name+".latency_s")
            else:
                plane_latencies[index] += latency
    for name, cost in shared.items():
        for key in ("area_m2", "energy_j"):
            found = value(cost, key)
            if found is None:
                incomplete.append(name+"."+key)
            elif key == "area_m2":
                area += found
            else:
                energy += found

    # Shared-block latency is common time, not per-plane time, so it is added
    # once after the parallel read rather than into either plane.
    common = float(common_latency_s or 0.0)
    for name, cost in shared.items():
        found = value(cost, "latency_s")
        if found is None:
            incomplete.append(name+".latency_s")
        else:
            common += found

    complete = not incomplete
    return {
        "adc_order": adc_order,
        "rule": ("per-plane blocks summed over both planes; shared blocks counted once; "
                 "latency = max(plane read) + common accumulate/subtract"),
        "per_plane_blocks": sorted(per_plane), "shared_blocks": sorted(shared),
        "missing": sorted(set(incomplete)),
        "plane_latencies_s": plane_latencies if complete else None,
        "common_latency_s": common if complete else None,
        "area_m2": area if complete else None,
        "energy_j_per_inference": energy if complete else None,
        "latency_s_per_inference": (max(plane_latencies)+common) if complete else None,
        "note": ("the chip total is the composition above, never a single-plane total "
                 "multiplied by two"),
    }


def cost_coverage(inventory):
    """What is counted, what has no cost model, and why the total stays null.

    docs/spec/08 section 5: a partial cost may be published, but the missing
    blocks have to be named and the totals have to be null rather than a number
    that looks complete.
    """
    order = inventory["adc_order"]
    missing = [dict(id=name, **body) for name, body in sorted(MISSING_COST_BLOCKS.items())
               if order in body["applies_to"]]
    return {"status": "partial", "inventory": inventory,
            "counted_components": ["array_cells", "adc_count", "conversion_schedule",
                                   "shared_block_multiplicity"],
            "missing_components": missing,
            "excluded_by_scope": [dict(item) for item in EXCLUDED_BY_SCOPE],
            "area_m2": None, "energy_j_per_inference": None, "latency_s_per_inference": None,
            "totals_reason": ("Totals stay null while " + ", ".join(m["id"] for m in missing)
                              + " have no cost model; a partial sum must not be presented as a "
                                "complete PPA")}


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
    decision["problems"].extend(read_window_problems(preset))
    if not preset.get("validated_for_ctfm"):
        decision["problems"].append("Preset is not marked validated_for_ctfm; an unvalidated "
                                    "preset may not produce CTFM PPA numbers")
    if not decision["problems"]:
        decision["status"] = "supported"
    return decision


# Provenance values that mean "this number is the write/program pulse". The
# quantity 1 ms is not banned per se -- docs/spec/08-hardware-baseline.md section 3
# says to check where a value comes from and what it means, not to reject a
# number on sight. A read window that happens to be 1 ms is admissible if it is
# sourced as a read; a read window copied from the write pulse is not, whatever
# its magnitude.
WRITE_PULSE_SOURCES = frozenset({
    "write_pulse", "write_pulse_width", "program_pulse", "erase_pulse",
    "measurement_write_pulse", "programming_pulse",
})


def read_window_problems(preset):
    """Check the read pulse width by provenance and meaning, not by magnitude."""
    problems = []
    width = preset.get("read_pulse_width_s")
    source = preset.get("read_pulse_width_source")
    if width is None:
        return problems
    if not isinstance(source, str) or not source.strip():
        problems.append("read_pulse_width_source must state where the read pulse width "
                        "comes from; an unsourced read window cannot be checked against "
                        "the write pulse")
        return problems
    if source.strip().lower().replace(" ", "_") in WRITE_PULSE_SOURCES:
        problems.append("read_pulse_width_s is sourced from the write/program pulse "
                        "(" + source + "); write width must not be reused as read latency")
    write = preset.get("write_pulse_width_s")
    if isinstance(write, (int, float)) and not isinstance(write, bool)             and math.isfinite(write) and width == write:
        problems.append("read_pulse_width_s equals the declared write_pulse_width_s "
                        "({!r} s); write width must not be reused as read latency".format(write))
    return problems


def schedule_feasibility(preset, parsed):
    """Is the assumed read window long enough for the circuit that was costed?

    docs/spec/08 section 3: 10 ns is an assumed read excitation condition. If
    settling or ADC conversion takes longer, that must show up in the effective
    schedule and be reported as a configuration that does not hold. When the
    engine does not report a comparable latency the check is recorded as NOT
    PERFORMED -- never as a pass.
    """
    window = preset.get("read_pulse_width_s") if isinstance(preset, dict) else None
    result = {"assumed_read_window_s": window, "engine_column_read_latency_s": None,
              "status": "not_performed", "detail": None}
    if window is None:
        result["detail"] = "preset states no read_pulse_width_s"
        return result
    latency = (parsed or {}).get("subarray_read_latency_s")
    if latency is None:
        result["detail"] = ("engine output reports no subarray read latency, so the "
                            "assumed read window was not checked against settling/ADC time")
        return result
    result["engine_column_read_latency_s"] = latency
    if latency > window:
        result["status"] = "infeasible"
        result["detail"] = ("engine subarray read latency {:g} s exceeds the assumed {:g} s "
                            "read window; the configuration does not hold".format(latency, window))
    else:
        result["status"] = "feasible"
    return result


# NeuroSim's own numbering for the cell and access models the preset names.
MEMCELL_TYPES = {"sram": 1, "rram": 2, "fefet": 3}
ACCESS_TYPES = {"cmos_access": 1, "cmos": 1, "bjt_access": 2, "bjt": 2, "none": 3}


def build_config(preset, hardware):
    """Turn an admitted preset plus the request's ADC choice into the compile-time
    configuration the build cache keys on.

    Only values the preset states explicitly are used. Nothing is defaulted here:
    a preset that omits a field never reaches this function, because the gate
    refuses it first.
    """
    from ctfm.adapters import neurosim_build
    cell = str(preset.get("memcell_type", "")).strip().lower().replace(" ", "_")
    access = str(preset.get("access_type", "cmos_access")).strip().lower().replace(" ", "_")
    if cell not in MEMCELL_TYPES:
        raise ValueError("Preset memcell_type is not one NeuroSim models: "
                         + repr(preset.get("memcell_type")))
    if access not in ACCESS_TYPES:
        raise ValueError("Preset access_type is not one NeuroSim models: "
                         + repr(preset.get("access_type")))
    architecture = str(preset.get("adc_architecture", "")).lower()
    return neurosim_build.resolve_config(
        adc_bits=hardware["adc_bits"], columns_per_adc=int(preset["columns_per_adc"]),
        technode_nm=int(preset["technode_nm"]), cell_bit=int(preset["cell_bit"]),
        # The requested physical array wins; the preset may not quietly cost another.
        sub_array=int(hardware.get("tile_size") or preset["sub_array"]),
        read_pulse_width_s=float(preset["read_pulse_width_s"]),
        memcell_type=MEMCELL_TYPES[cell], access_type=ACCESS_TYPES[access],
        # The baseline reads a whole tile in parallel, which NeuroSim expresses as
        # operationmode 2; parallelRead is then derived, never written.
        operation_mode=2,
        global_bus_type="h-tree" in str(preset.get("interconnect", "")).lower(),
        sar_adc="sar" in architecture, current_mode="current" in architecture,
        pipeline=False, speed_up_degree=1, temperature_k=int(preset.get("temperature_k", 300)))


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


def decode_activation_planes(planes, bits):
    """Invert :func:`encode_activation_csv`, so the trace can be read back.

    Mirrors the engine's own decoding: the first plane carries the sign weight
    -2**(bits-1)*delta and the rest are descending magnitude weights.
    """
    import numpy as np
    array = np.asarray(planes, dtype=float)
    if array.ndim != 2 or array.shape[1] != bits:
        raise ValueError("Expected one row per value with %d bit planes" % bits)
    delta = 1.0/(2**(bits-1))
    weights = np.array([-(2**(bits-1))]+[2**(bits-1-index) for index in range(1, bits)],
                       dtype=float)
    return array @ weights*delta


def activation_trace_fidelity(activation, bits):
    """What the engine actually receives compared with what the accuracy path drives.

    The accuracy model drives unsigned 8 bit codes (256 levels over [0, r]).
    NeuroSim's FC activation trace is signed two's complement, so a nonnegative
    signal only reaches the positive half of the grid: 2**(bits-1) levels, i.e.
    one bit less resolution. This function measures that instead of leaving it as
    a remark, and the numbers travel with the result.
    """
    import numpy as np
    values = np.asarray(activation, dtype=float).reshape(-1)
    normalized, divisor = _normalize(values, bits)
    delta = 1.0/(2**(bits-1))
    nonnegative = bool(values.min() >= 0) if values.size else True
    representable = 2**(bits-1) if nonnegative else 2**bits
    # The unsigned code the accuracy path would have used for the same sample.
    peak = float(np.abs(values).max()) if values.size else 0.0
    unsigned = np.zeros_like(values) if peak == 0 else np.floor(255*values/peak+.5)/255*peak
    reconstructed = np.round(normalized/delta)*delta*divisor
    error = np.abs(reconstructed-unsigned)
    return {
        "encoding": "twos_complement_sign_first",
        "engine_bits": bits,
        "signal_is_nonnegative": nonnegative,
        "levels_available_to_this_signal": representable,
        "effective_bits_for_this_signal": bits-1 if nonnegative else bits,
        "accuracy_path_levels": 256,
        "max_abs_difference_from_unsigned_codes": float(error.max()) if error.size else 0.0,
        "relative_to_peak": float(error.max()/peak) if peak else 0.0,
        "detail": ("a nonnegative activation uses only the positive half of the signed grid, "
                   "so the engine sees one bit less resolution than the accuracy path drives"),
    }


def write_network_csv(layer_dims, path):
    """Encode fully-connected layers the way NeuroSim's NetWork_*.csv does.

    Columns: IFM_row, IFM_col, in_channels, kernel_row, kernel_col, out_channels,
    followed_by_pooling, trailing flag. An FC layer is a 1x1 'conv'.
    """
    rows = ["1,1,{},1,1,{},0,1".format(fan_in, fan_out) for fan_in, fan_out in layer_dims]
    Path(path).write_text("\n".join(rows) + "\n")
    return rows


def topology_support(layer_dims, sub_array=None):
    """Refuse (shape, subArray) pairs measured to crash; let anything else try.

    An unmeasured pair still runs: run_engine() spawns the binary in its own
    process group, so a segfault surfaces as a 'failed' status with a negative
    return code instead of taking the worker down. This guard only avoids
    spending a run on a pair already known to die, and it never refuses a pair
    that was measured to complete.

    Without a subArray size nothing can be decided from measurements that are
    subArray-specific, so the shape is refused only when every size measured for
    it crashed.
    """
    shape = tuple((int(a), int(b)) for a, b in layer_dims)
    if sub_array is not None:
        known = MEASURED_TOPOLOGIES.get((shape, int(sub_array)))
        if known is False:
            return False, UNSUPPORTED_TOPOLOGY
        return True, None
    outcomes = [ok for (measured, _), ok in MEASURED_TOPOLOGIES.items() if measured == shape]
    if outcomes and not any(outcomes):
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
               root=None, timeout=1800.0, cancelled=None, binary=None):
    """Invoke the engine binary in its own process group.

    The group is what gets signalled, so a cancelled job cannot leave the engine
    or its children running. A crash is reported as a negative return code and a
    failed status rather than being turned into a number.
    """
    status = engine_status(root)
    blank = {"engine": status, "returncode": None, "stdout": "", "stderr": "", "parsed": None}
    # A configuration-specific binary from the build cache takes precedence: the
    # reference checkout's binary carries upstream's compile-time constants, not
    # this run's. Its working directory is the checkout, which is where the
    # engine looks for its own data files.
    executable = str(binary) if binary else status["binary"]
    if binary is None and not status["available"]:
        return dict(blank, status="unsupported", reason=status["reason"])
    if binary is not None and not Path(binary).is_file():
        return dict(blank, status="unsupported", reason="Built binary missing at "+str(binary))
    argv = [executable, str(network_csv), str(synapse_bit), str(input_bit),
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
            # Measured, not asserted: what the engine's signed encoding does to
            # the unsigned activations the accuracy path drives.
            "activation_fidelity": activation_trace_fidelity(activation[0], input_bits),
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
               out_dir=None, timeout=1800.0, cancelled=None, hardware=None,
               cache_root=None, build=True):
    """The gate the simulator calls, and the executor once the gate opens.

    Refuses with explicit reasons until a validated CTFM preset exists, the
    engine is built, and the topology is one this build survives. Numeric fields
    stay None so absence is never read as zero. When every reason clears and
    ``inputs`` is supplied, the engine actually runs and the SI numbers come from
    its stdout.
    """
    engine = engine_status(root)
    decision = preset_decision(preset, preset_path)
    sub_array = (hardware or {}).get("tile_size")
    supported, reason = topology_support(layer_dims, sub_array)
    # Two different kinds of "no": a blocking reason means the engine must not be
    # run at all, while an incomplete reason means the run is legitimate but its
    # numbers do not add up to a chip total. Collapsing them would either publish
    # a partial number as complete, or refuse to compute the parts we can.
    blocking = list(decision["problems"])
    if not engine["available"]:
        blocking.append(engine["reason"])
    if not supported:
        blocking.append(reason)
    incomplete = [DIFFERENTIAL_PLANE_UNRESOLVED]
    # The engine must be costed for the array the accuracy path actually used.
    # A preset that names a different subArray would price a different circuit.
    if preset and sub_array is not None and preset.get("sub_array") not in (None, sub_array):
        blocking.append("Preset sub_array %r is not the requested array size %r; the cost "
                        "would be for a different circuit than the accuracy run"
                        % (preset.get("sub_array"), sub_array))

    result = {"status": "unsupported", "engine": engine, "preset": decision,
              "area_m2": None, "energy_j_per_inference": None,
              "latency_s_per_inference": None, "raw_output": None,
              "model_mismatches": decision["model_mismatches"],
              "trace_sample": "test[:256]", "time_basis": "nominal t_ref",
              "schedule_check": schedule_feasibility(preset or {}, None),
              "coverage": None, "build": None,
              "blocking_reasons": blocking, "incomplete_reasons": incomplete,
              "reasons": blocking+incomplete}
    # The structural count does not need the engine: how many physical cells,
    # converters and conversion cycles the requested configuration implies is
    # arithmetic on the shapes, and publishing it with the missing blocks named
    # is what docs/spec/08 section 5 allows while the total stays null.
    if hardware and hardware.get("adc_order") in ADC_ORDERS:
        result["coverage"] = cost_coverage(circuit_inventory(
            layer_dims, tile_size=hardware["tile_size"],
            columns_per_adc=hardware.get("columns_per_adc", 8),
            adc_bits=hardware.get("adc_bits"), adc_order=hardware["adc_order"],
            input_bits=hardware.get("input_bits", 8)))
        incomplete.extend(m["id"]+": "+m["detail"]
                          for m in result["coverage"]["missing_components"]
                          if m["id"] != "differential_plane_pair")
        result["reasons"] = blocking+incomplete
    if out_dir is not None:
        result["preset_artifact"] = export_preset(preset, out_dir)
    if inputs is not None:
        result["normalization"] = inputs["normalization"]
        result["conductance"] = inputs["conductance"]
        result["trace_sample"] = inputs["trace_sample"]
    # Only a blocking reason stops the run. An incomplete cost model does not:
    # the blocks that are modelled are still worth computing, and the total stays
    # null either way (docs/spec/08 section 5).
    if blocking or inputs is None:
        return result

    # levelOutput and the rest are compile-time constants, so the requested ADC
    # configuration is a different binary, not a different argument. The cache
    # keeps one build per resolved configuration and refuses to hand back a
    # binary whose effective Param.cpp is not the requested one.
    binary = None
    if build:
        from ctfm.adapters import neurosim_build
        try:
            built = neurosim_build.build(Path(root or ENGINE_ROOT),
                                         build_config(preset, hardware or {}),
                                         cache_root=cache_root)
        except (ValueError, RuntimeError, TimeoutError, OSError, KeyError) as exc:
            failure = "Configuration-specific build failed: %s: %s" % (type(exc).__name__, exc)
            result.update(status="failed", blocking_reasons=blocking+[failure],
                          reasons=blocking+[failure]+incomplete)
            return result
        result["build"] = {k: v for k, v in built.items() if k != "compiler"}
        binary = built["binary"]

    run = run_engine(inputs["network_csv"], inputs["trace_args"],
                     synapse_bit=inputs["synapse_bit"], input_bit=inputs["input_bits"],
                     sub_array=sub_array or preset["sub_array"],
                     parallel_rows=preset["parallel_rows"],
                     root=root, timeout=timeout, cancelled=cancelled, binary=binary)
    # argv carries absolute server paths, so only the basenames are published.
    argv = [Path(a).name for a in (run.get("argv") or [])]
    result["raw_output"] = {"stdout": run.get("stdout"), "stderr": run.get("stderr"),
                            "returncode": run.get("returncode"), "argv": argv}
    if run["status"] != "succeeded":
        result.update(status=run["status"], blocking_reasons=blocking+[run.get("reason")],
                      reasons=blocking+[run.get("reason")]+incomplete)
        return result
    parsed = run["parsed"]
    result["schedule_check"] = schedule_feasibility(preset or {}, parsed)
    if result["schedule_check"]["status"] == "infeasible":
        detail = result["schedule_check"]["detail"]
        result.update(status="unsupported", blocking_reasons=blocking+[detail],
                      reasons=blocking+[detail]+incomplete)
        return result
    mode = (parsed["modes_reported"] or [None])[0]
    values = parsed["modes"].get(mode, {}) if mode else {}
    # Even a successful engine run is partial while the blocks above have no
    # model, so the engine's chip totals are reported as engine_totals and the
    # published area/energy/latency stay null.
    missing = (result["coverage"] or {}).get("missing_components") or []
    result.update(status="partial" if incomplete else "succeeded",
                  reasons=list(incomplete), process_mode=mode, parsed=parsed,
                  engine_totals={"area_m2": parsed["chip_area_m2"],
                                 "energy_j_per_inference": values.get("read_dynamic_energy_j"),
                                 "latency_s_per_inference": values.get("latency_s")})
    if not missing:
        result.update(area_m2=parsed["chip_area_m2"],
                      energy_j_per_inference=values.get("read_dynamic_energy_j"),
                      latency_s_per_inference=values.get("latency_s"))
    return result
