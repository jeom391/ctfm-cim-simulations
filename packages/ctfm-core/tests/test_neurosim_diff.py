"""Two-plane cost path: trace writers, independent expectations, composition, gates. No engine binary needed."""
import tempfile
import unittest
from pathlib import Path

import numpy as np

from ctfm.adapters import neurosim, neurosim_compose as compose_mod, neurosim_diff as nd, neurosim_ppa
from ctfm.adapters.proxy_preset import proxy_preset


class TraceWriters(unittest.TestCase):
    def test_unsigned_planes_use_all_eight_bits_lsb_first(self):
        planes = nd.unsigned_planes(np.array([0, 1, 127, 128, 255]))
        self.assertEqual(planes.shape, (5, 8))
        self.assertEqual(planes[0].tolist(), [0]*8)
        self.assertEqual(planes[1].tolist(), [1, 0, 0, 0, 0, 0, 0, 0])          # bit 0 is the first cycle
        self.assertEqual(planes[2].tolist(), [1, 1, 1, 1, 1, 1, 1, 0])
        self.assertEqual(planes[3].tolist(), [0, 0, 0, 0, 0, 0, 0, 1])          # 128 lives in the last plane
        self.assertEqual(planes[4].tolist(), [1]*8)                              # 255 keeps all eight bits (no sign bit lost)
        self.assertEqual(nd.decode_unsigned_planes(planes).tolist(), [0, 1, 127, 128, 255])

    def test_mixed_vector_round_trips_and_weighted_sum_is_the_code(self):
        rng = np.random.default_rng(3)
        codes = rng.integers(0, 256, 300)
        planes = nd.unsigned_planes(codes)
        self.assertTrue(np.array_equal(nd.decode_unsigned_planes(planes), codes))
        self.assertEqual(int((planes*(2**np.arange(8))).sum()), int(codes.sum()))

    def test_out_of_range_or_fractional_codes_are_refused_not_clipped(self):
        for bad in ([256], [-1], [1.5]):
            with self.assertRaises(ValueError):
                nd.unsigned_planes(np.array(bad))

    def test_the_old_signed_writer_lost_a_bit_and_the_new_one_does_not(self):
        codes = np.array([255, 128, 100])
        with tempfile.TemporaryDirectory() as tmp:
            old = Path(tmp)/"old.csv"
            neurosim.encode_activation_csv(codes/256.0, 8, old)                    # the previous two's-complement path
            old_planes = np.loadtxt(old, delimiter=",", ndmin=2)
        self.assertEqual(old_planes[:, 0].sum(), 0)                                # its first plane is a sign bit, always 0 here
        self.assertEqual(nd.unsigned_planes(codes)[:, 7].tolist(), [1, 1, 0])      # 128 and 255 both set the top plane

    def test_conductance_file_is_exact_transposed_and_positive(self):
        g = np.array([[1.234567890123456e-6, 2.5e-5, 3e-6], [4e-6, 5.0000000000000004e-5, 6.1e-6]])   # [out=2, in=3]
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp)/"g.csv"
            self.assertEqual(nd.write_conductance_csv(g, path), (3, 2))
            back = np.loadtxt(path, delimiter=",")
        self.assertTrue(np.array_equal(back, g.T))                                 # bit-exact, no re-quantisation
        for bad in (np.array([[0.0, 1e-6]]), np.array([[np.nan, 1e-6]]), np.array([[-1e-6, 1e-6]])):
            with self.assertRaises(ValueError):
                nd.write_conductance_csv(bad, Path(tmp)/"bad.csv")


class Expectations(unittest.TestCase):
    PARAMS = dict(wire_res_row_ohm=1.5, wire_res_col_ohm=0.7, resistance_access_ohm=300.0)

    def brute_force(self, g_out_in, planes, tile):
        n_out, n_in = g_out_in.shape
        total = 0.0
        for r0 in range(0, n_in, tile):
            rows = min(tile, n_in-r0)
            for c0 in range(0, n_out, tile):
                cols = min(tile, n_out-c0)
                for k in range(planes.shape[1]):
                    for j in range(cols):
                        column = 0.0
                        for i in range(rows):
                            if planes[r0+i, k] == 1:
                                column += 1.0/(1.0/g_out_in[c0+j, r0+i] + (j+1)*1.5 + (rows-i)*0.7 + 300.0)
                        total += column
        return total

    def test_column_conductance_matches_a_loop_written_from_the_engine_formula(self):
        rng = np.random.default_rng(5)
        g = rng.uniform(1e-6, 1e-4, (7, 11))
        planes = nd.unsigned_planes(rng.integers(0, 256, 11))
        self.assertAlmostEqual(nd.expected_column_conductance(g, planes, self.PARAMS, 4),
                               self.brute_force(g, planes, 4), delta=1e-12*abs(self.brute_force(g, planes, 4)))

    def test_all_zero_input_reads_nothing(self):
        g = np.full((4, 6), 2e-5)
        planes = nd.unsigned_planes(np.zeros(6, dtype=int))
        self.assertEqual(nd.expected_column_conductance(g, planes, self.PARAMS, 4), 0.0)
        self.assertEqual(nd.expected_activity(planes, 4, 4), 0.0)

    def test_rows_read_counts_each_bit_once_per_column_subarray(self):
        planes = nd.unsigned_planes(np.array([255, 1, 0]))                        # 9 set bits
        self.assertEqual(nd.expected_activity(planes, 64, 128), 9*2)              # 128 outputs -> two column subarrays
        self.assertEqual(nd.expected_activity(planes, 64, 10), 9)

    def test_spec_tiling_of_mnist_mlp_v1(self):
        self.assertEqual(nd.spec_slots([(784, 128), (128, 10)], 64), [13*2, 2*1])
        self.assertEqual(sum(nd.spec_slots([(784, 128), (128, 10)], 64)), 28)      # 28 subarrays per plane -> 114688 cells per plane


class ConfigAndBounds(unittest.TestCase):
    def test_pool_bounds_use_the_pool_not_the_engine_default(self):
        bounds = nd.pool_bounds([{"conductance_s": 4e-6}, {"conductance_s": 8e-5}, {"conductance_s": 2e-5}])
        self.assertAlmostEqual(bounds["resistance_on_ohm"], 1/8e-5)
        self.assertAlmostEqual(bounds["resistance_off_ohm"], 1/4e-6)
        self.assertIsNone(nd.pool_bounds([{"conductance_s": None}])["resistance_on_ohm"])

    def test_build_config_carries_the_accounting_flags_and_avoids_write_circuits(self):
        hardware = dict(tile_size=64, adc_bits=6, adc_order="adc_then_subtract", columns_per_adc=8, input_bits=8)
        bounds = nd.pool_bounds([{"conductance_s": 4e-6}, {"conductance_s": 8e-5}])
        config, extra = nd.build_config_diff(proxy_preset(64), hardware, bounds, "adc_then_subtract")
        for key, value in (("ctfm_conductance_input", 1), ("ctfm_differential", 1), ("ctfm_adc_order", 1), ("ctfm_no_duplication", 1),
                           ("ctfm_read_only", 1), ("ctfm_used_only", 1), ("write_voltage_v", 1.0), ("cell_bit", 8)):
            self.assertEqual(config[key], value, key)
        self.assertEqual(config["resistance_on_ohm"], 1/8e-5)
        other, _ = nd.build_config_diff(proxy_preset(64), dict(hardware, adc_order="subtract_then_adc"), bounds, "subtract_then_adc")
        self.assertEqual(other["ctfm_adc_order"], 2)
        with self.assertRaises(ValueError):
            nd.build_config_diff(proxy_preset(64), hardware, nd.pool_bounds([]), "adc_then_subtract")


SAMPLE_REPORT = """ChipArea : 1000um^2
Chip total CIM array : 100um^2
Total IC Area on chip (Global and Tile/PE local): 50um^2
Total ADC (or S/As and precharger for SRAM) Area on chip : 200um^2
Total Accumulation Circuits (subarray level: adders, shiftAdds; PE/Tile/Global level: accumulation units) on chip : 300um^2
Other Peripheries (e.g. decoders, mux, switchmatrix, buffers, pooling and activation units) : 350um^2
Chip clock period is: 2ns
Chip layer-by-layer readLatency (per image) is: 200ns
Chip total readDynamicEnergy is: 10pJ
Chip total leakage Energy is: 1pJ
Chip total leakage Power is: 5uW
Chip buffer readLatency is: 1ns
Chip buffer readDynamicEnergy is: 1pJ
Chip ic readLatency is: 1ns
Chip ic readDynamicEnergy is: 2pJ
----------- ADC (or S/As and precharger for SRAM) readDynamicEnergy is : 3pJ
CTFM used-only: removed 4 unused subarray slot(s)
CTFM_LEDGER_BEGIN
CTFM_FLAGS conductance_input=1 differential=1 adc_order=1 no_duplication=1 read_only=1 used_only=1
CTFM_CLK period_s=2.000000000e-09
CTFM_PARAMS read_voltage_v=5.5e-01 resistance_on_ohm=1e4 wire_res_row_ohm=1 wire_res_col_ohm=2 resistance_access_ohm=3
CTFM_SLOT area_m2=1e-10 array_m2=2e-11 adc_m2=3e-11 accum_m2=1e-11 other_m2=2e-11 subtractor_m2=1e-12
CTFM_LAYER l=0 cycles=8 used_subarrays=2 instantiated_subarrays=4 active_rows=5 total_rows=64 plus_wlcap_j=1e-13 plus_mlsa_j=2e-13 \
plus_drivers_j=3e-13 plus_accum_j=4e-13 minus_wlcap_j=1e-13 minus_mlsa_j=2e-13 minus_drivers_j=3e-13 minus_accum_j=4e-13 sub_j=5e-13 \
col_delay_max_s=1e-10 sense_latency_max_s=1.5e-9 sub_latency_s=0 plus_colg_s=1e-3 minus_colg_s=2e-3 weight_cells=8192
CTFM_LEDGER_END
"""


class Parsing(unittest.TestCase):
    def test_chip_level_breakdown_wins_over_the_per_layer_blocks(self):
        adc = "----------- ADC (or S/As and precharger for SRAM) readDynamicEnergy is : %dpJ"
        acc = "----------- Accumulation Circuits (subarray level: adders, shiftAdds; PE/Tile/Global level: accumulation units) readDynamicEnergy is : %dpJ"
        text = "\n".join([adc % 4, acc % 5, adc % 6, acc % 7]) + "\n"
        summary = nd.parse_report(text)["summary"]
        self.assertAlmostEqual(summary["adc_class_energy_j"], 6e-12)
        self.assertAlmostEqual(summary["accum_class_energy_j"], 7e-12)

    def test_report_and_ledger_are_parsed_into_si(self):
        parsed = nd.parse_report(SAMPLE_REPORT.replace("\\\n", ""))
        s, ledger = parsed["summary"], parsed["ledger"]
        self.assertAlmostEqual(s["chip_area_m2"], 1000e-12)
        self.assertAlmostEqual(s["energy_j"], 10e-12)
        self.assertAlmostEqual(s["latency_s"], 200e-9)
        self.assertAlmostEqual(s["leakage_power_w"], 5e-6)
        self.assertEqual(ledger["flags"]["adc_order"], 1)
        self.assertEqual(ledger["removed_unused_slots"], 4.0)
        self.assertEqual(len(ledger["layers"]), 1)
        self.assertEqual(ledger["layers"][0]["used_subarrays"], 2.0)
        self.assertAlmostEqual(ledger["slot"]["subtractor_m2"], 1e-12)


def synthetic_aggregate(order="adc_then_subtract"):
    text = SAMPLE_REPORT.replace("\\\n", "")
    runs = [(0, text, "", []), (0, text, "", [])]
    return nd.aggregate(runs)


class Composition(unittest.TestCase):
    def test_adc_then_subtract_lists_only_grounded_unknowns_and_keeps_totals_incomplete(self):
        composed = compose_mod.compose(synthetic_aggregate(), order="adc_then_subtract", tile=64, layer_dims=[(100, 128)])
        self.assertEqual([u["id"] for u in composed["unknown_components"]], ["adc_range_scaling", "digital_bias_add"])
        known = {c["id"] for c in composed["components"]}
        self.assertTrue({"cell_arrays", "row_drivers_and_column_mux", "column_read_and_sensing", "digital_subtractor",
                         "shift_add_accumulate", "pe_tile_chip_periphery", "interconnect", "leakage"} <= known)
        self.assertFalse(composed["known_total"]["complete"])
        self.assertIn("not a complete PPA", composed["known_total"]["note"])

    def test_subtract_then_adc_reports_no_energy_or_latency_for_the_unmodelled_converter(self):
        composed = compose_mod.compose(synthetic_aggregate(), order="subtract_then_adc", tile=64, layer_dims=[(100, 128)])
        ids = [u["id"] for u in composed["unknown_components"]]
        self.assertEqual(ids, ["adc_range_scaling", "digital_bias_add", "analog_subtraction_frontend", "signed_column_sensing"])
        self.assertNotIn("column_read_and_sensing", {c["id"] for c in composed["components"]})
        total = composed["known_total"]
        self.assertIsNone(total["energy_j_per_inference"])
        self.assertIsNone(total["latency_s_per_inference"])

    def test_unknown_blocks_are_never_summed_as_zero(self):
        composed = compose_mod.compose(synthetic_aggregate(), order="adc_then_subtract", tile=64, layer_dims=[(100, 128)])
        self.assertTrue(all(c["id"] not in ("adc_range_scaling", "digital_bias_add") for c in composed["components"]))

    def test_placement_separates_spec_used_instantiated_and_padding(self):
        composed = compose_mod.compose(synthetic_aggregate(), order="adc_then_subtract", tile=64, layer_dims=[(100, 128)])
        placement = composed["placement"]
        self.assertEqual(placement["spec_slots_per_plane"], 4)
        self.assertEqual(placement["used_slots_per_plane"], 2)
        self.assertEqual(placement["instantiated_slots_per_plane"], 4)
        self.assertEqual(placement["physical_cells"], 2*2*64*64)
        self.assertEqual(placement["weight_cells_per_plane"], 8192)
        self.assertEqual(placement["padding_cells"], 2*2*4096-2*8192)
        self.assertFalse(placement["matches_spec_tiling"])                        # 2 used vs 4 in the spec tiling of this toy

    def test_converter_count_is_reported_for_both_the_engine_and_the_spec_inventory(self):
        composed = compose_mod.compose(synthetic_aggregate(), order="adc_then_subtract", tile=64, layer_dims=[(100, 128)])
        placement = composed["placement"]
        self.assertEqual(placement["converters_engine"], 2*8*2)          # 2 used slots x 8 per slot x 2 planes
        self.assertEqual(placement["converters_spec_inventory"], 4*8*2)  # spec tiling of the toy: 4 tiles
        self.assertIsNone(compose_mod.compose(synthetic_aggregate(), order="subtract_then_adc", tile=64,
                                              layer_dims=[(100, 128)])["placement"]["converters_engine"])

    def test_schedule_is_reported_when_the_window_is_not_met(self):
        text = SAMPLE_REPORT.replace("\\\n", "").replace("Chip clock period is: 2ns", "Chip clock period is: 30ns")
        agg = nd.aggregate([(0, text, "", [])])
        composed = compose_mod.compose(agg, order="adc_then_subtract", tile=64, layer_dims=[(100, 128)])
        schedule = composed["schedule_check"]
        self.assertEqual(schedule["status"], "infeasible")
        self.assertAlmostEqual(schedule["effective_cycle_s"], 30e-9)
        ok = compose_mod.compose(synthetic_aggregate(), order="adc_then_subtract", tile=64, layer_dims=[(100, 128)])["schedule_check"]
        self.assertEqual(ok["status"], "feasible")
        self.assertAlmostEqual(ok["effective_cycle_s"], 1e-8)                     # the 10 ns excitation window sets the cycle
        # 100 cycles at 2 ns in the engine become 100 cycles at 10 ns
        self.assertAlmostEqual(composed["latency"]["engine_clock_s"], 200e-9)


class FailureReasons(unittest.TestCase):
    def test_a_cell_that_does_not_fit_the_footprint_is_explained_with_the_engines_numbers(self):
        text = "FloorPlan Done\nTransistor width of 1T1R=37.62F is larger than the assigned cell width=12.00F in layout\n"
        bounds = nd.pool_bounds([{"conductance_s": 1.57e-4}, {"conductance_s": 5.44e-4}])
        code, reason, details = neurosim_ppa.explain_failure(text, 255, bounds)
        self.assertEqual(code, "cell_footprint_exceeded")
        self.assertAlmostEqual(details["access_transistor_width_f"], 37.62)
        self.assertAlmostEqual(details["largest_admissible_gmax_s"], 12.0/(37.62/5.44e-4), delta=1e-9)
        self.assertLess(details["largest_admissible_gmax_s"], details["pool_gmax_s"])
        self.assertIn("not evaluable", reason)
        self.assertIn("not changed", reason)

    def test_any_other_exit_reports_the_engines_last_message(self):
        code, reason, details = neurosim_ppa.explain_failure("a\nERROR: something broke\n", 255)
        self.assertEqual(code, "engine_failed")
        self.assertIn("something broke", reason)

    def test_effective_settings_of_a_refused_build_are_recorded_without_claiming_a_run(self):
        ppa = {"build": {"applied": {"numRowSubArray": 64, "numColSubArray": 64, "levelOutput": 32, "ctfmAdcOrder": 1, "cellBit": 8,
                                     "resistanceOn": 1836.6, "resistanceOff": 6369.4, "writeVoltage": 1.0, "ctfmNoDuplication": 1,
                                     "ctfmReadOnly": 1, "ctfmUsedOnly": 1}},
               "conductance": {"resistance_on_ohm": 1836.6, "resistance_off_ohm": 6369.4}}
        effective = neurosim_ppa.effective_ppa(dict(tile_size=64, adc_bits=5, adc_order="adc_then_subtract"), ppa)
        self.assertFalse(effective["engine_ran"])
        self.assertTrue(effective["all_agree"])
        self.assertIsNone(effective["agreement"]["input_bits"])
        wrong = neurosim_ppa.effective_ppa(dict(tile_size=128, adc_bits=5, adc_order="adc_then_subtract"), ppa)
        self.assertFalse(wrong["agreement"]["tile_size"])
        self.assertFalse(wrong["all_agree"])


class Gates(unittest.TestCase):
    def test_an_engine_without_patch_0002_is_refused_with_the_reason(self):
        with tempfile.TemporaryDirectory() as tmp:
            self.assertFalse(neurosim_ppa.engine_root_supports_two_planes(tmp))
            result = neurosim_ppa.assumed_proxy_result(
                [(784, 128), (128, 10)], preset=proxy_preset(64),
                hardware=dict(tile_size=64, adc_bits=6, adc_order="adc_then_subtract", input_bits=8),
                layers=[], codes=[], states=[], out_dir=Path(tmp)/"out", root=tmp)
        self.assertEqual(result["status"], "unsupported")
        self.assertTrue(any("patch 0002" in r for r in result["blocking_reasons"]))
        self.assertIsNone(result["area_m2"])


if __name__ == "__main__":
    unittest.main()
