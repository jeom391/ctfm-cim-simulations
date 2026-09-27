"""assumed_proxy PPA for the mapped G+/G- network: engine runs over real traces, checks, composition (docs/spec/08)."""
from __future__ import annotations

import re
import subprocess
import tempfile
from pathlib import Path

from ctfm.adapters import neurosim_build, neurosim_compose as compose_mod, neurosim_diff as nd

DEFAULT_IMAGES = 256


def engine_root_supports_two_planes(root):
    """The checkout must contain patch 0002; a claim is not enough, the source is read."""
    from ctfm.adapters.neurosim import engine_fixes
    return engine_fixes(root)["two_plane_cost_model"]


def fidelity_checks(layers, codes_first, agg, tile, layer_dims):
    """What the engine used for the first image, compared with numbers computed here from the same files."""
    import numpy as np
    params = agg["ledger_params"]
    per_layer = []
    ledger_layers = agg["first"]["ledger"]["layers"]
    for layer, codes, ledger, dims in zip(layers, codes_first, ledger_layers, layer_dims):
        planes = nd.unsigned_planes(codes)
        exp_plus = nd.expected_column_conductance(layer["g_plus"], planes, params, tile)
        exp_minus = nd.expected_column_conductance(layer["g_minus"], planes, params, tile)
        per_layer.append({
            "layer": layer["name"], "shape": list(dims),
            "column_conductance_rel_error": {"plus": abs(ledger["plus_colg_s"]-exp_plus)/exp_plus,
                                             "minus": abs(ledger["minus_colg_s"]-exp_minus)/exp_minus},
            "rows_read": ledger["active_rows"], "rows_read_expected": nd.expected_activity(planes, tile, dims[1]),
            "input_bits_set": int(planes.sum()), "cycles_per_subarray": ledger["cycles"],
            "weight_cells": ledger["weight_cells"], "weight_cells_expected": dims[0]*dims[1],
            "used_slots": ledger["used_subarrays"], "used_slots_expected": nd.spec_slots([dims], tile)[0]})
    passed = bool(per_layer) and len(per_layer) == len(layers) == len(codes_first) == len(ledger_layers) == len(layer_dims) and all(max(x["column_conductance_rel_error"].values()) < 1e-9 and x["rows_read"] == x["rows_read_expected"]
                 and x["weight_cells"] == x["weight_cells_expected"] and x["used_slots"] == x["used_slots_expected"]
                 for x in per_layer)
    return {"status": "passed" if passed else "failed", "image_index": 0, "layers": per_layer,
            "meaning": ("The engine derived its column conductances from exactly the G+/G- files, read exactly the set input "
                        "bits, and holds one cell per weight per plane in the spec 08 tiling")}


_FOOTPRINT = re.compile(r"Transistor width of 1T1R=([0-9.]+)F is larger than the assigned cell width=([0-9.]+)F")


def explain_failure(stdout, returncode, bounds=None):
    """A concrete reason for an engine exit, using the engine's own message. Returns (code, reason, details)."""
    text = stdout or ""
    match = _FOOTPRINT.search(text)
    if match:
        needed, footprint = float(match.group(1)), float(match.group(2))
        ron = (bounds or {}).get("resistance_on_ohm")
        details = {"access_transistor_width_f": needed, "cell_footprint_width_f": footprint, "resistance_on_ohm": ron}
        reason = ("The pool's conductance range does not fit the fixed cell: its on-resistance (Ron = 1/Gmax%s) needs an access "
                  "transistor %.2f F wide, the fixed 1T1R footprint (4F x 12F, spec 08 section 3) allows %.2f F. The width scales "
                  "as 1/Ron" % ((" = %.0f ohm" % ron) if ron else "", needed, footprint))
        if ron:
            k = needed*ron
            details["largest_admissible_gmax_s"] = footprint/k
            details["pool_gmax_s"] = 1.0/ron
            reason += ("; with the engine's 22 nm model the largest Gmax that fits is %.1f uS, this pool's Gmax is %.1f uS"
                       % (footprint/k*1e6, 1e6/ron))
        reason += ". Spec 08 reports such a configuration as not evaluable: the footprint and the conductances are not changed."
        return "cell_footprint_exceeded", reason, details
    errors = [line.strip() for line in text.splitlines() if "ERROR" in line]
    tail = [line.strip() for line in text.splitlines() if line.strip()][-1:] if not errors else []
    message = (errors or tail or [""])[0]
    return "engine_failed", "engine exited with %s%s" % (returncode, (": " + message) if message else ""), {"message": message}


def run_ppa(layers, codes, preset, hardware, states, *, root, out_dir, cache_root=None, cancelled=None, adc_bounds=None,
            images=DEFAULT_IMAGES, workers=None, timeout=900.0):
    """Run the two-plane cost engine for one ADC order.

    ``layers``: nominal mapped layers (name, g_plus, g_minus in S, shape [out, in]); ``codes``: per layer, [images, in]
    unsigned 8 bit codes from the accuracy path's own encoder; ``states``: the pool's measured states.
    """
    order = hardware["adc_order"]
    tile = hardware["tile_size"]
    out_dir = Path(out_dir)
    bounds = nd.pool_bounds(states)
    config, extra = nd.build_config_diff(preset, hardware, bounds, order)
    built = neurosim_build.build(Path(root), config, cache_root=cache_root)
    # Engine inputs are large and only needed for the runs, so they live in a temporary directory, not in the experiment's
    # artifact folder (every file there is registered as an artifact).
    with tempfile.TemporaryDirectory(prefix="ctfm-neurosim-") as stage:
        dims, network_csv, weight_files = nd.stage_weights(layers, Path(stage)/"engine")
        n = min(images, len(codes[0]))
        sample_inputs = [nd.stage_sample([c[i] for c in codes], layers, Path(stage)/"engine"/("image_%03d" % i)) for i in range(n)]
        cwd = Path(root)/"Inference_pytorch/NeuroSIM"
        # The first image runs alone: a configuration the engine refuses (for example a cell that does not fit) should fail once,
        # with the engine's own message, not 256 times.
        first = nd.run_samples(built["binary"], cwd, network_csv, tile, weight_files, sample_inputs[:1], workers=1,
                               timeout=timeout, cancelled=cancelled)
        if first[0] is not None and first[0][0] != 0:
            runs = first
        else:
            rest = nd.run_samples(built["binary"], cwd, network_csv, tile, weight_files, sample_inputs[1:], workers=workers,
                                  timeout=timeout, cancelled=cancelled) if len(sample_inputs) > 1 else []
            runs = first + rest
    if cancelled is not None and cancelled():
        return {"status": "cancelled", "reason": "cancelled", "build": built}
    bad = [(i, r) for i, r in enumerate(runs) if r is None or r[0] != 0]
    if bad:
        index, run = bad[0]
        code, stdout, stderr, argv = run if run else (None, "", "", [])
        failure, reason, details = explain_failure(stdout, code, bounds)
        return {"status": "failed", "build": built, "bounds": bounds, "reason": reason, "failure_code": failure,
                "failure_details": details, "order": order,
                "raw_output": {"stdout": (stdout or "")[-4000:], "stderr": (stderr or "")[-1000:], "returncode": code, "image": index}}
    agg = nd.aggregate(runs)
    layer_dims = dims
    fidelity = fidelity_checks(layers, [c[0] for c in codes], agg, tile, layer_dims)
    composed = compose_mod.compose(agg, order=order, tile=tile, layer_dims=layer_dims, adc_bounds=adc_bounds, bounds=bounds)
    required = ["array_area_equals_slots"]
    if order == "adc_then_subtract":
        required += ["adc_area_equals_slots", "adc_class_energy_equals_ledger"]
    if fidelity["status"] != "passed" or any(composed["consistency"].get(k) is not True for k in required):
        return {"status": "failed", "order": order, "build": built, "bounds": bounds,
                "reason": "Engine fidelity/consistency verification failed; cost values are withheld.",
                "failure_code": "model_verification_failed", "fidelity": fidelity,
                "consistency": composed["consistency"],
                "raw_output": {"stdout_first_image_tail": runs[0][1][-3000:]}}
    return {"status": "partial", "order": order, "build": built, "bounds": bounds, "images": agg["images"],
            "stats": agg["stats"], "static": agg["static"], "ledger": {"flags": agg["ledger_flags"], "params": agg["ledger_params"],
                                                                    "slot": agg["ledger_slot"], "layers": agg["ledger_layers_mean"]},
            "fidelity": fidelity, "composed": composed, "raw_output": {"argv_basenames": [Path(a).name for a in runs[0][3]],
                                                                      "stdout_first_image_tail": runs[0][1][-3000:]}}


ENCODING = {"input": "unsigned 8 bit codes (0..255), q = clip(floor(255 x / r + 0.5)), the accuracy path's own encoder",
            "schedule": "8 fixed cycles, least-significant bit first; all-zero cycles are not skipped",
            "engine_trace": "the same bit planes, column k = bit k; the engine reads a bit as 'row on'"}


def assumed_proxy_result(layer_dims, *, preset, hardware, layers, codes, states, out_dir, root=None, cache_root=None,
                         cancelled=None, adc_bounds=None, images=DEFAULT_IMAGES):
    """The ppa summary for one requested ADC order: gate, engine runs, checks, known/unknown composition."""
    from ctfm.adapters import neurosim
    root = Path(root or neurosim.ENGINE_ROOT)
    base = neurosim.ppa_result(layer_dims, preset=preset, inputs=None, out_dir=out_dir, hardware=hardware, root=root)
    blocking = list(base["blocking_reasons"])
    if not engine_root_supports_two_planes(root):
        blocking.append("The NeuroSim checkout at %s lacks patch 0002 (two-plane conductance cost model); "
                        "assumed_proxy needs it" % root)
    if blocking:
        return dict(base, status="unsupported", blocking_reasons=blocking, reasons=blocking)
    try:
        run = run_ppa(layers, codes, preset, hardware, states, root=root, out_dir=out_dir, cache_root=cache_root,
                      cancelled=cancelled, adc_bounds=adc_bounds, images=images)
    except (OSError, subprocess.SubprocessError, neurosim_build.EngineBuildError) as exc:
        # Accuracy has already completed. External engine failures must not discard it.
        # Cancellation and programming errors are deliberately not caught here.
        run = {"status": "failed", "reason": "NeuroSim execution failed: " + str(exc),
               "failure_code": "engine_execution_error", "order": hardware.get("adc_order"),
               "failure_details": {"exception": type(exc).__name__}}
    if run["status"] != "partial":
        reason = run.get("reason")
        return dict(base, status=run["status"], blocking_reasons=[reason], reasons=[reason], build=_public_build(run.get("build")),
                    raw_output=run.get("raw_output"), failure_code=run.get("failure_code"), failure_details=run.get("failure_details"),
                    conductance=dict(run.get("bounds") or {}), order=run.get("order"),
                    diagnostics={"ledger": {}, "images": 0}, fidelity=run.get("fidelity"),
                    consistency=run.get("consistency"))
    composed = run["composed"]
    unknown = composed["unknown_components"]
    incomplete = ["%s: %s" % (u["id"], u["detail"]) for u in unknown]
    stats = run["stats"]
    static = run["static"]
    inventory = base["coverage"]["inventory"] if base.get("coverage") else None
    coverage = {"status": "partial", "inventory": inventory,
                "counted_components": [c["id"] for c in composed["components"]],
                "known_components": composed["components"],
                "missing_components": unknown,
                "excluded_by_scope": composed["excluded_by_scope"],
                "totals_reason": composed["known_total"]["note"]}
    result = dict(base)
    result.update(
        status="partial", reasons=incomplete, incomplete_reasons=incomplete, blocking_reasons=[],
        area_m2=None, energy_j_per_inference=None, latency_s_per_inference=None,
        known_total=composed["known_total"], known_components=composed["components"], unknown_components=unknown,
        coverage=coverage, schedule_check=composed["schedule_check"], placement=composed["placement"],
        fidelity=run["fidelity"], consistency=composed["consistency"], adc_range_note=composed["adc_range_note"],
        model_mismatches=composed["mismatches"], input_encoding=ENCODING, order=run["order"],
        build=_public_build(run["build"]),
        conductance=dict(run["bounds"], transfer="G+ and G- files in siemens, used as-is; Ron = 1/Gmax and Roff = 1/Gmin of the pool"),
        trace_sample="fixed first %d test images, mean per image (min/max/std in diagnostics)" % run["images"],
        time_basis="nominal reference time; D2D, Retention and C2C are accuracy-only",
        engine_totals={"area_m2": static["chip_area_m2"],
                       "energy_j_per_inference": stats["energy_j"]["mean"],
                       "latency_s_per_inference": stats["latency_s"]["mean"]},
        diagnostics={"images": run["images"], "per_image_stats": stats, "static": static, "ledger": run["ledger"],
                     "latency": composed["latency"]},
        raw_output=run["raw_output"], process_mode="layer_by_layer")
    # One curated file per run for the export; the engine's own inputs are not kept.
    import json
    report = Path(out_dir)/("ppa-%s.json" % run["order"])
    report.parent.mkdir(parents=True, exist_ok=True)
    report.write_text(json.dumps({k: v for k, v in result.items() if k not in ("engine", "preset")}, indent=1, default=str,
                                 allow_nan=False), encoding="utf-8")
    result["report_artifact"] = {"filename": report.name}
    return result


def _public_build(built):
    if not built:
        return None
    return {k: v for k, v in built.items() if k != "compiler"}


def effective_ppa(hardware, ppa):
    """Requested (accuracy side) versus effective (cost side) settings, side by side, with the field-by-field agreement.

    The accuracy path and the cost engine are configured from the same request through different code; this records what each
    one actually ran with so a mismatch is visible instead of assumed away.
    """
    build = ppa.get("build") or {}
    applied = build.get("applied") or {}
    ledger = ((ppa.get("diagnostics") or {}).get("ledger") or {})
    params = ledger.get("params") or {}
    flags = ledger.get("flags") or {}
    order = hardware.get("adc_order")
    bits = hardware.get("adc_bits")
    tile = hardware.get("tile_size")
    bounds = ppa.get("conductance") or {}
    ats = order == "adc_then_subtract"
    accuracy = {"tile_size": tile, "adc_bits": bits, "adc_order": order, "input_bits": 8, "input_encoding": "unsigned, LSB-first, 8 cycles",
                "conductance_source": "mapped G+/G- of the requested profile/pool/mapping (siemens)", "range_policy": hardware.get("range_policy")}
    cost = {"sub_array_rows": applied.get("numRowSubArray"), "sub_array_cols": applied.get("numColSubArray"),
            "level_output": applied.get("levelOutput"), "ctfm_adc_order": applied.get("ctfmAdcOrder"),
            "num_bit_input": params.get("num_bit_input"), "cell_bit": applied.get("cellBit"),
            "resistance_on_ohm": applied.get("resistanceOn"), "resistance_off_ohm": applied.get("resistanceOff"),
            "write_voltage_v": applied.get("writeVoltage"), "flags": flags, "read_pulse_width_s": applied.get("readPulseWidth"),
            "engine_commit": (ppa.get("engine") or {}).get("commit"), "engine_fixes": (ppa.get("engine") or {}).get("fixes")}
    ran = bool(params and flags)      # the engine printed its ledger; when the build was refused only the build side is known
    agree = {
        "tile_size": tile is not None and cost["sub_array_rows"] == tile == cost["sub_array_cols"],
        "adc_levels": bits is not None and cost["level_output"] == 2**bits,
        "adc_order": (cost["ctfm_adc_order"] == (1 if ats else 2)) and (flags.get("adc_order") == (1 if ats else 2) if ran else True),
        "input_bits": (cost["num_bit_input"] == 8) if ran else None,
        "one_cell_per_weight": cost["cell_bit"] == 8 and ((flags.get("conductance_input") == 1) if ran else True),
        "resistance_window_from_pool": (bounds.get("resistance_on_ohm") is not None
                                        and cost["resistance_on_ohm"] == bounds.get("resistance_on_ohm")
                                        and cost["resistance_off_ohm"] == bounds.get("resistance_off_ohm")),
        "no_duplication_read_only_used_only": (all(flags.get(k) == 1 for k in ("no_duplication", "read_only", "used_only")) if ran
                                                else all(applied.get(k) == 1 for k in ("ctfmNoDuplication", "ctfmReadOnly", "ctfmUsedOnly"))),
        "write_level_shifters_not_built": cost["write_voltage_v"] is not None and cost["write_voltage_v"] <= 1.5}
    return {"accuracy_side": accuracy, "cost_side": cost, "agreement": agree, "engine_ran": ran,
            "all_agree": all(v is True for v in agree.values() if v is not None)}


def ppa_for_run(ppa, run):
    """Only the evaluated candidate's nominal hardware cost belongs on its ALL runs."""
    from copy import deepcopy
    candidate = ppa.get("candidate") or {}
    if run.get("kind") == "ALL" and candidate.get("candidate_id") == run.get("candidate_id") and candidate:
        return deepcopy(ppa)
    return None
