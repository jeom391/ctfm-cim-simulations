"""Composition of the two-plane engine output into known and unknown cost components (docs/spec/08 section 5).

Only blocks the engine models under the same physical assumptions as the accuracy path are summed. A block without a
grounded model is listed as unknown and never counted as zero; totals are complete only when nothing is unknown, which
is never the case today, so ``known_total`` is labelled as a sum of known components and not as a PPA.
"""
from __future__ import annotations

from ctfm.adapters.neurosim_diff import spec_slots

READ_WINDOW_S = 1e-8

# Blocks with no grounded model in this engine or in the approved spec, and the ADC orders they apply to.
UNKNOWN_BLOCKS = {
    "adc_range_scaling": {
        "applies_to": ["adc_then_subtract", "subtract_then_adc"],
        "detail": "The accuracy model converts over a per-layer range [0, R] (or [-R, R]) taken from the nominal validation "
                  "maximum; the engine's current-mode MLSA references span the full-scale column current (all rows at Gmax). "
                  "Mapping one onto the other needs programmable references or gain, a circuit with no cost model here"},
    "digital_bias_add": {
        "applies_to": ["adc_then_subtract", "subtract_then_adc"],
        "detail": "The accuracy model adds a digital bias once per layer after accumulation; the engine models no bias adder"},
    "analog_subtraction_frontend": {
        "applies_to": ["subtract_then_adc"],
        "detail": "Subtracting the two plane currents before conversion needs an analog subtractor; NeuroSim has none and no "
                  "approved approximation exists"},
    "signed_column_sensing": {
        "applies_to": ["subtract_then_adc"],
        "detail": "The converter after the analog subtraction senses a signed current. The engine's MLSA is unsigned and its "
                  "power model is a fit against one column resistance (column read current and sensing are one block), so "
                  "converter area, column read energy and sensing latency are not claimed for this order"},
}

EXCLUDED_SCOPE = (
    {"id": "write_datapath",
     "detail": "Program/erase energy and time and the circuits that only serve them (source-line switch matrix, write level "
               "shifters) are outside the read datapath; the build uses writeVoltage 1 V and the read-only flag so they are "
               "not built"},
    {"id": "time_dependent_effects",
     "detail": "Cost is evaluated once at the nominal reference time; D2D, Retention and C2C change the accuracy path only"},
)


def diff_mismatches():
    return [
        {"id": "read_voltage",
         "detail": "Measurements use VDS = 0.1 V; the engine reads at 0.55 V (22 nm table) and treats the measured conductance "
                   "as a linear resistance at that voltage (no voltage transfer check)"},
        {"id": "adc_quantizer",
         "detail": "The accuracy model quantizes each bit-plane partial sum on a uniform grid over [0, R]; the engine's MLSA has "
                   "levelOutput-1 references spanning the full-scale current. Only the converter's cost is taken from the engine"},
        {"id": "final_layer_activation",
         "detail": "The engine adds activation cost after every layer including the output layer; the accuracy model applies "
                   "ReLU to hidden layers only"},
        {"id": "mlsa_power_fit",
         "detail": "Column read power and MLSA sensing come from a SPICE-fitted expression in the engine (22 nm LSTP), a proxy "
                   "for the assumed current-mode converter, not for CTFM"},
        {"id": "pe_granularity",
         "detail": "PE-level and higher shared blocks (adder trees, buffers, buses) are sized by the engine's floorplan (PE = "
                   "2 x 2 subarrays); subarray slots that hold no weights are not built, so their subarray-level area and "
                   "leakage are removed"},
    ]


def _mean(stats, name):
    entry = stats.get(name)
    return None if entry is None else entry["mean"]


def compose(agg, *, order, tile, layer_dims, read_window_s=READ_WINDOW_S, adc_bounds=None, bounds=None, columns_per_adc=8):
    """Known/unknown components for one ADC order from the aggregated engine runs."""
    stats, static, slot = agg["stats"], agg["static"], agg["ledger_slot"]
    layers = agg["ledger_layers_mean"]
    ats = order == "adc_then_subtract"
    used = sum(l["used_subarrays"] for l in layers)
    inst = sum(l["instantiated_subarrays"] for l in layers)

    def area(key):
        return used*slot[key]

    def total(key):
        return sum(l[key] for l in layers)

    known, unknown = [], []

    def add_known(id_, owner, area_m2=None, energy_j=None, note=""):
        known.append({"id": id_, "owner": owner, "area_m2": area_m2, "energy_j_per_inference": energy_j, "note": note})

    e_wl = total("plus_wlcap_j")+total("minus_wlcap_j")+total("plus_drivers_j")+total("minus_drivers_j")
    e_col = total("plus_mlsa_j")+total("minus_mlsa_j")
    e_shift = total("plus_accum_j")
    e_sub = total("sub_j")
    e_total = _mean(stats, "energy_j")
    sub_level = e_wl+(e_col if ats else 0)+e_shift+e_sub
    e_ic, e_buf = _mean(stats, "ic_energy_j"), _mean(stats, "buffer_energy_j")
    add_known("cell_arrays", "per_plane", area("array_m2"), None,
              "two planes of the used subarrays; the cell read current power is inside column_read_and_sensing")
    add_known("row_drivers_and_column_mux", "per_plane", area("other_m2"), e_wl,
              "word-line drivers, column mux and decoders, once per plane")
    if ats:
        add_known("column_read_and_sensing", "per_plane", area("adc_m2"), e_col,
                  "current-mode MLSA and encoder of each plane (engine fit); includes the cell read current power")
        add_known("digital_subtractor", "shared", area("subtractor_m2"), e_sub,
                  "engine Adder model, ADC bits + sign, one per converted column group; pipelined with the converter")
    add_known("shift_add_accumulate", "shared", used*(slot["accum_m2"]-slot["subtractor_m2"]), e_shift,
              "bit-serial shift-add, counted once after the subtraction")
    chip_area = static["chip_area_m2"]
    periphery = chip_area-used*slot["area_m2"]-static["ic_area_m2"]
    add_known("pe_tile_chip_periphery", "shared", periphery, e_total-sub_level-(e_ic or 0)-(e_buf or 0),
              "adder trees, tile/chip accumulation, activation, input/output registers; counted once")
    add_known("input_output_buffers", "shared", None, e_buf, "register-file buffers (energy only; area is inside the periphery row)")
    add_known("interconnect", "shared", static["ic_area_m2"], e_ic, "XY-bus interconnect, once")
    for id_, body in UNKNOWN_BLOCKS.items():
        if order in body["applies_to"]:
            unknown.append({"id": id_, "detail": body["detail"]})

    clock = _mean(stats, "clock_period_s")
    latency_engine = _mean(stats, "latency_s")
    cycles = (latency_engine/clock) if clock else None
    col_delay = max(l["col_delay_max_s"] for l in layers)
    sense = max(l["sense_latency_max_s"] for l in layers)
    needed = max(clock, col_delay) if clock else None
    effective_cycle = max(read_window_s, needed) if needed else None
    schedule = {"read_window_s": read_window_s, "engine_clock_period_s": clock, "bitline_settling_s": col_delay,
                "sensing_latency_s": sense, "needed_cycle_s": needed, "effective_cycle_s": effective_cycle,
                "cycles_per_inference": cycles,
                "status": None if needed is None else ("feasible" if needed <= read_window_s else "infeasible"),
                "detail": None}
    if needed is not None:
        schedule["detail"] = ("Each input-bit cycle needs the read excitation window (%.3g ns); the circuit needs %.3g ns "
                              "(sensing/clock %.3g ns, bitline settling %.3g ns) -> cycle %.3g ns"
                              % (read_window_s*1e9, needed*1e9, clock*1e9, col_delay*1e9, effective_cycle*1e9))
    latency_window = None if (cycles is None or effective_cycle is None) else cycles*effective_cycle
    leak_power = static["leakage_power_w"]
    leakage_energy = None if (leak_power is None or latency_window is None) else leak_power*latency_window
    if ats and leakage_energy is not None:
        add_known("leakage", "shared", None, leakage_energy, "engine leakage power x window-adjusted latency")
    known_energy = None if e_total is None else e_total+(leakage_energy or 0)
    note = ("Sum of the known components only; %s have no cost model, so this is not a complete PPA and neither a lower nor "
            "an upper bound" % ", ".join(u["id"] for u in unknown))
    if not ats:
        note += ("; the converter's area, column read energy and sensing latency are also missing for this order, so its "
                 "energy and latency are not reported")
    known_total = {"complete": False, "area_m2": chip_area,
                   "energy_j_per_inference": known_energy if ats else None,
                   "latency_s_per_inference": latency_window if ats else None, "note": note}
    weights = total("weight_cells")
    spec = sum(spec_slots(layer_dims, tile))
    # converters: the engine builds ceil(width/columns_per_adc) per subarray slot whatever the layer's actual width; the spec
    # inventory counts ceil(columns/columns_per_adc) for the columns a tile really has
    per_plane_converters = 2 if ats else 1
    engine_converters = used*(-(-tile//columns_per_adc))*per_plane_converters
    spec_converters = sum(t_*(-(-min(tile, out)//columns_per_adc))*per_plane_converters
                          for t_, (fan_in, out) in zip(spec_slots(layer_dims, tile), layer_dims))
    placement = {"spec_slots_per_plane": spec, "used_slots_per_plane": used, "instantiated_slots_per_plane": inst,
                 "removed_unused_slots": agg["removed_unused_slots"], "planes": 2, "tile_size": tile,
                 "converters_engine": engine_converters if ats else None, "converters_spec_inventory": spec_converters if ats else None,
                 "weight_cells_per_plane": weights, "physical_cells": 2*used*tile*tile,
                 "padding_cells": 2*(used*tile*tile)-2*weights, "matches_spec_tiling": used == spec,
                 "padding_treatment": ("Cells of a partially filled subarray that hold no weight (rows or columns beyond the layer) "
                                       "are built and count in area and leakage, but carry no read current (their word lines "
                                       "are not driven) and their columns are not converted, so they add no dynamic energy; "
                                       "subarray slots of a PE that hold no weights at all are not built")}
    consistency = {"array_area_equals_slots": abs(static["array_area_m2"]-area("array_m2")) <= 2e-5*static["array_area_m2"],
                   "adc_area_equals_slots": ((abs(static["adc_area_m2"]-area("adc_m2")) <= 2e-5*max(static["adc_area_m2"], 1e-30))
                                             if ats else None),
                   "adc_class_energy_equals_ledger": None}
    adc_class = _mean(stats, "adc_class_energy_j")
    if adc_class is not None and ats:
        expected = total("plus_wlcap_j")+total("minus_wlcap_j")+e_col
        consistency["adc_class_energy_equals_ledger"] = abs(adc_class-expected) <= 1e-4*expected
    range_note = None
    if bounds and bounds.get("max_conductance_s") and adc_bounds:
        full_scale = tile*bounds["max_conductance_s"]
        range_note = {}
        for name, r in adc_bounds.items():
            value = r.get(order) if isinstance(r, dict) else r
            range_note[name] = {"accuracy_range_s": value, "engine_full_scale_s": full_scale,
                                "fraction": None if value is None else value/full_scale}
    return {"components": known, "unknown_components": unknown, "known_total": known_total, "schedule_check": schedule,
            "latency": {"engine_clock_s": latency_engine, "window_adjusted_s": latency_window},
            "placement": placement, "consistency": consistency, "adc_range_note": range_note,
            "excluded_by_scope": [dict(x) for x in EXCLUDED_SCOPE], "mismatches": diff_mismatches()}
