"""NeuroSim adapter checks that need no engine checkout.

The stdout fixture below is copied verbatim from a real run of the built binary
(commit ac828e6, gcc 13.3) captured by scripts/linux/verify_neurosim_adapter.py,
so the parser is tested against the engine's actual wording. Engine-dependent
checks (writer parity against upstream, live execution) live in that script.
"""
import json
import unittest
from pathlib import Path
import tempfile

import numpy as np

from ctfm.adapters import neurosim

# Real lines, including the buffer/ic rows that an unanchored pattern would grab.
REAL_STDOUT = """
------------------------------ Summary --------------------------------

ChipArea : 740627um^2
Chip total CIM array : 142103um^2
Total IC Area on chip (Global and Tile/PE local): 275656um^2
Total ADC (or S/As and precharger for SRAM) Area on chip : 103949um^2

Chip clock period is: 1.6974ns
Chip pipeline-system-clock-cycle (per image) is: 794.385ns
Chip pipeline-system readDynamicEnergy (per image) is: 10543.2pJ
Chip pipeline-system leakage Energy (per image) is: 2.72591pJ
Chip pipeline-system leakage Power (per image) is: 3.43146uW
Chip pipeline-system buffer readLatency (per image) is: 668.778ns
Chip pipeline-system buffer readDynamicEnergy (per image) is: 28.6505pJ
Chip pipeline-system ic readLatency (per image) is: 10.1844ns

----------------------------- Performance -------------------------------
Energy Efficiency TOPS/W (Pipelined Process): 15.5995
Throughput TOPS (Pipelined Process): 0.252653
Throughput FPS (Pipelined Process): 1.25883e+06
"""

# Same engine rebuilt with Param.cpp pipeline=false, which is the only way this
# wording appears; captured from a real 3-layer run.
REAL_STDOUT_LAYER_BY_LAYER = """
ChipArea : 2.15973e+06um^2
Chip total CIM array : 426309um^2
Chip layer-by-layer readLatency (per image) is: 2795.63ns
Chip total readDynamicEnergy is: 35491.9pJ
Chip total leakage Energy is: 91.7762pJ
Chip total leakage Power is: 44.0955uW

----------------------------- Performance -------------------------------
Energy Efficiency TOPS/W (Layer-by-Layer Process): 18.1155
Throughput TOPS (Layer-by-Layer Process): 0.281308
"""

STOCK_PRESET = {
    "preset_id": "neurosim-stock-sram-22nm",
    "technode_nm": 22, "read_voltage_v": 0.55, "read_pulse_width_s": 10e-9,
    "read_pulse_width_source": "engine_baseline_22nm",
    "cell_bit": 1, "synapse_bit": 8, "sub_array": 128, "parallel_rows": 128,
    "adc_architecture": "MLSA current mode", "columns_per_adc": 8,
    "interconnect": "XY bus", "memcell_type": "SRAM", "input_precision_bits": 8,
    "access_type": "CMOS_access",
}


class ParseStdoutTests(unittest.TestCase):
    def test_si_conversion_and_reported_modes(self):
        parsed = neurosim.parse_stdout(REAL_STDOUT)
        self.assertAlmostEqual(parsed["chip_area_m2"], 740627e-12)
        self.assertAlmostEqual(parsed["chip_adc_area_m2"], 103949e-12)
        self.assertEqual(parsed["modes_reported"], ["pipelined"])
        pipelined = parsed["modes"]["pipelined"]
        self.assertAlmostEqual(pipelined["latency_s"], 794.385e-9)
        self.assertAlmostEqual(pipelined["read_dynamic_energy_j"], 10543.2e-12)
        self.assertAlmostEqual(pipelined["leakage_power_w"], 3.43146e-6)
        self.assertAlmostEqual(pipelined["tops"], 0.252653)
        self.assertAlmostEqual(pipelined["tops_per_w"], 15.5995)

    def test_buffer_latency_is_not_mistaken_for_system_latency(self):
        # 668.778ns is the buffer row; picking it up would understate latency.
        parsed = neurosim.parse_stdout(REAL_STDOUT)
        self.assertNotAlmostEqual(parsed["modes"]["pipelined"]["latency_s"], 668.778e-9)

    def test_absent_mode_stays_none_not_zero(self):
        parsed = neurosim.parse_stdout(REAL_STDOUT)
        for value in parsed["modes"]["layer_by_layer"].values():
            self.assertIsNone(value)

    def test_layer_by_layer_build_is_parsed_from_its_own_wording(self):
        parsed = neurosim.parse_stdout(REAL_STDOUT_LAYER_BY_LAYER)
        self.assertEqual(parsed["modes_reported"], ["layer_by_layer"])
        values = parsed["modes"]["layer_by_layer"]
        self.assertAlmostEqual(values["latency_s"], 2795.63e-9)
        self.assertAlmostEqual(values["read_dynamic_energy_j"], 35491.9e-12)
        self.assertAlmostEqual(values["leakage_power_w"], 44.0955e-6)
        self.assertAlmostEqual(values["tops"], 0.281308)
        self.assertAlmostEqual(values["tops_per_w"], 18.1155)
        for value in parsed["modes"]["pipelined"].values():
            self.assertIsNone(value)

    def test_empty_output_yields_no_numbers(self):
        parsed = neurosim.parse_stdout("")
        self.assertIsNone(parsed["chip_area_m2"])
        self.assertEqual(parsed["modes_reported"], [])


class PresetGateTests(unittest.TestCase):
    def test_no_preset_is_unsupported(self):
        decision = neurosim.preset_decision()
        self.assertEqual(decision["status"], "unsupported")
        self.assertTrue(decision["problems"])

    def test_stock_upstream_values_are_not_a_ctfm_preset(self):
        decision = neurosim.preset_decision(STOCK_PRESET)
        self.assertEqual(decision["status"], "unsupported")
        self.assertEqual(decision["missing_fields"], [])
        self.assertTrue(any("validated_for_ctfm" in p for p in decision["problems"]))

    def test_write_sourced_read_window_is_refused_whatever_its_magnitude(self):
        for width in (1e-3, 10e-9):
            decision = neurosim.preset_decision(
                dict(STOCK_PRESET, validated_for_ctfm=True, read_pulse_width_s=width,
                     read_pulse_width_source="write_pulse"))
            self.assertEqual(decision["status"], "unsupported")
            self.assertTrue(any("write" in p for p in decision["problems"]))

    def test_read_window_equal_to_the_declared_write_pulse_is_refused(self):
        decision = neurosim.preset_decision(
            dict(STOCK_PRESET, validated_for_ctfm=True, read_pulse_width_s=1e-3,
                 write_pulse_width_s=1e-3, read_pulse_width_source="bench_read"))
        self.assertEqual(decision["status"], "unsupported")
        self.assertTrue(any("write_pulse_width_s" in p for p in decision["problems"]))

    def test_one_millisecond_is_admissible_when_it_is_sourced_as_a_read(self):
        """docs/spec/08 section 3: check the value's source and meaning, do not
        ban the number 1 ms outright."""
        decision = neurosim.preset_decision(
            dict(STOCK_PRESET, validated_for_ctfm=True, read_pulse_width_s=1e-3,
                 read_pulse_width_source="A1 pulse-read window, 1 ms per read"))
        self.assertEqual(decision["problems"], [])
        self.assertEqual(decision["status"], "supported")

    def test_unsourced_read_window_cannot_be_checked(self):
        preset = dict(STOCK_PRESET, validated_for_ctfm=True)
        preset.pop("read_pulse_width_source")
        decision = neurosim.preset_decision(preset)
        self.assertEqual(decision["status"], "unsupported")
        self.assertIn("read_pulse_width_source", decision["missing_fields"])

    def test_schedule_check_is_not_performed_rather_than_passed(self):
        """The engine summary reports no subarray read latency, so the 10 ns read
        window is not silently declared feasible."""
        parsed = neurosim.parse_stdout(REAL_STDOUT)
        check = neurosim.schedule_feasibility(STOCK_PRESET, parsed)
        self.assertEqual(check["status"], "not_performed")
        self.assertIsNone(check["engine_column_read_latency_s"])

    def test_schedule_check_reports_an_impossible_read_window(self):
        check = neurosim.schedule_feasibility(
            STOCK_PRESET, {"subarray_read_latency_s": 25e-9})
        self.assertEqual(check["status"], "infeasible")
        self.assertIn("does not hold", check["detail"])

    def test_missing_physical_values_are_named(self):
        decision = neurosim.preset_decision({"preset_id": "x", "validated_for_ctfm": True})
        self.assertEqual(decision["status"], "unsupported")
        self.assertEqual(set(decision["missing_fields"]), set(neurosim.REQUIRED_PRESET_FIELDS))

    def test_nonpositive_voltage_is_rejected(self):
        decision = neurosim.preset_decision(dict(STOCK_PRESET, validated_for_ctfm=True,
                                                 read_voltage_v=0))
        self.assertTrue(any("read_voltage_v" in p for p in decision["problems"]))

    def test_preset_file_is_hashed_and_bad_json_reported(self):
        with tempfile.TemporaryDirectory() as directory:
            good = Path(directory) / "preset.json"
            good.write_text(json.dumps(STOCK_PRESET))
            decision = neurosim.preset_decision(preset_path=good)
            self.assertEqual(len(decision["preset_hash"]), 64)
            bad = Path(directory) / "bad.json"
            bad.write_bytes(b"{not json")
            self.assertTrue(any("not valid JSON" in p
                                for p in neurosim.preset_decision(preset_path=bad)["problems"]))

    def test_model_mismatches_are_always_recorded(self):
        ids = {m["id"] for m in neurosim.preset_decision(STOCK_PRESET)["model_mismatches"]}
        self.assertIn("nonuniform_states", ids)
        self.assertIn("cells_per_weight", ids)
        self.assertIn("read_voltage", ids)


class TopologyAndResultTests(unittest.TestCase):
    def test_mnist_mlp_v1_depends_on_the_array_size(self):
        """Measured: 784x128x10 segfaults at subArray 64 and 128 and completes at
        256. The array size is part of the observation, not a detail."""
        mnist = [(784, 128), (128, 10)]
        for size in (64, 128):
            supported, reason = neurosim.topology_support(mnist, size)
            self.assertFalse(supported, size)
            self.assertIn("segfault", reason)
        self.assertEqual(neurosim.topology_support(mnist, 256), (True, None))

    def test_single_wide_layer_is_allowed(self):
        self.assertEqual(neurosim.topology_support([(784, 128)], 64), (True, None))

    def test_an_unmeasured_shape_is_allowed_to_try(self):
        # run_engine isolates the process, so an unmeasured pair is attempted
        # rather than guessed at.
        self.assertEqual(neurosim.topology_support([(1024, 128), (1024, 128)], 64), (True, None))
        self.assertEqual(neurosim.topology_support([(1024, 128)] * 3, 128), (True, None))

    def test_a_narrow_output_layer_is_not_refused_on_a_rule_that_was_wrong(self):
        """An earlier note claimed every layer under 96 output features crashed.
        Direct measurement refutes it: these all complete at subArray 64."""
        for shape in ([(1024, 10)], [(128, 10)], [(256, 10)], [(256, 64)]):
            self.assertEqual(neurosim.topology_support(shape, 64), (True, None), shape)
        # 784x64 really does crash at 64, so that one stays refused.
        self.assertFalse(neurosim.topology_support([(784, 64)], 64)[0])

    def test_without_an_array_size_only_a_shape_that_always_crashed_is_refused(self):
        self.assertFalse(neurosim.topology_support([(784, 64)])[0])
        # mnist_mlp_v1 completes at one measured size, so it is not refused outright.
        self.assertTrue(neurosim.topology_support([(784, 128), (128, 10)])[0])

    def test_a_preset_may_not_cost_a_different_array_than_the_run_used(self):
        result = neurosim.ppa_result(
            [(784, 128), (128, 10)], preset=dict(STOCK_PRESET, validated_for_ctfm=True,
                                                 sub_array=128),
            root="/nonexistent-engine-root",
            hardware={"tile_size": 256, "adc_bits": 5, "adc_order": "subtract_then_adc"})
        self.assertTrue(any("different circuit" in r for r in result["blocking_reasons"]))

    def test_ppa_result_never_fabricates_numbers(self):
        result = neurosim.ppa_result([(784, 128), (128, 10)], root="/nonexistent-engine-root")
        self.assertEqual(result["status"], "unsupported")
        for key in ("area_m2", "energy_j_per_inference", "latency_s_per_inference", "raw_output"):
            self.assertIsNone(result[key])
        self.assertTrue(result["reasons"])
        self.assertFalse(result["engine"]["available"])


class EncodingTests(unittest.TestCase):
    def test_weight_csv_is_transposed_to_in_by_out(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "w.csv"
            shape = neurosim.encode_weight_csv(np.zeros((10, 128)), path)
            self.assertEqual(shape, (128, 10))
            self.assertEqual(np.genfromtxt(path, delimiter=",").shape, (128, 10))

    def test_activation_bit_planes_match_the_documented_encoding(self):
        # delta = 1/8 for bits=4; 0.5 -> x_int 4 -> sign 0 then 100
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "i.csv"
            neurosim.encode_activation_csv(np.array([0.5, -0.5, 0.0]), 4, path)
            planes = np.genfromtxt(path, delimiter=",")
            self.assertEqual(planes.shape, (3, 4))
            np.testing.assert_array_equal(planes[0], [0, 1, 0, 0])
            np.testing.assert_array_equal(planes[2], [0, 0, 0, 0])
            # The sign plane carries weight -2**(bits-1)*delta, so -0.5 sets it.
            self.assertEqual(planes[1][0], 1)

    def test_the_planes_decode_back_to_what_was_written(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "i.csv"
            values = np.array([0.5, -0.5, 0.0, 0.25])
            neurosim.encode_activation_csv(values, 4, path)
            planes = np.genfromtxt(path, delimiter=",")
            np.testing.assert_allclose(neurosim.decode_activation_planes(planes, 4), values)

    def test_a_nonnegative_signal_only_reaches_half_the_signed_grid(self):
        """The engine's trace is signed, ours is unsigned: one bit is lost, and
        the result says so with a number rather than a remark."""
        fidelity = neurosim.activation_trace_fidelity(np.array([0.0, 0.3, 0.9, 1.0]), 8)
        self.assertTrue(fidelity["signal_is_nonnegative"])
        self.assertEqual(fidelity["levels_available_to_this_signal"], 128)
        self.assertEqual(fidelity["effective_bits_for_this_signal"], 7)
        self.assertEqual(fidelity["accuracy_path_levels"], 256)
        # One unsigned code is 1/255 of peak; losing a bit costs about twice that.
        self.assertGreater(fidelity["relative_to_peak"], 0)
        self.assertLess(fidelity["relative_to_peak"], 2.0/255)

    def test_the_fidelity_travels_with_the_assembled_engine_inputs(self):
        with tempfile.TemporaryDirectory() as directory:
            layers = [dict(name="fc", weights=np.full((96, 8), 0.1), bias=np.zeros(96))]
            inputs = neurosim.build_engine_inputs(
                layers, [np.abs(np.linspace(0, 1, 8)).reshape(1, 8)], Path(directory),
                input_bits=8, synapse_bit=8, profile_states=[])
            fidelity = inputs["normalization"][0]["activation_fidelity"]
            self.assertEqual(fidelity["effective_bits_for_this_signal"], 7)
            json.dumps(fidelity)

    def test_out_of_range_activation_is_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "i.csv"
            for bad in ([1.0], [-1.5], [float("nan")]):
                with self.assertRaises(ValueError):
                    neurosim.encode_activation_csv(np.array(bad), 8, path)

    def test_network_csv_encodes_fc_as_one_by_one(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "net.csv"
            rows = neurosim.write_network_csv([(784, 128), (128, 10)], path)
            self.assertEqual(rows, ["1,1,784,1,1,128,0,1", "1,1,128,1,1,10,0,1"])
            self.assertEqual(path.read_text().count("\n"), 2)


class BuildEngineInputsTests(unittest.TestCase):
    def layers(self):
        rng = np.random.default_rng(3)
        return ([{"name": "fc1", "weights": rng.normal(scale=0.12, size=(128, 784)),
                  "bias": np.zeros(128)}],
                [rng.random((256, 784))])

    def test_assembles_network_and_traces_from_a_nominal_mapping(self):
        layers, activations = self.layers()
        with tempfile.TemporaryDirectory() as directory:
            built = neurosim.build_engine_inputs(layers, activations, Path(directory),
                                                 input_bits=8, synapse_bit=8,
                                                 profile_states=[{"selected": True, "conductance_s": 1e-5},
                                                                 {"selected": True, "conductance_s": 5e-5}])
            self.assertEqual(built["layer_dims"], [(784, 128)])
            self.assertEqual(built["network_rows"], ["1,1,784,1,1,128,0,1"])
            self.assertEqual(len(built["trace_args"]), 2)
            for path in built["trace_args"]:
                self.assertTrue(Path(path).is_file())
            self.assertAlmostEqual(built["conductance"]["resistance_on_ohm"], 1 / 5e-5)

    def test_normalization_keeps_values_inside_the_engine_range(self):
        layers, activations = self.layers()
        with tempfile.TemporaryDirectory() as directory:
            built = neurosim.build_engine_inputs(layers, activations, Path(directory),
                                                 input_bits=8, synapse_bit=8)
            record = built["normalization"][0]
            self.assertGreater(record["weight_divisor"], 0)
            scaled = layers[0]["weights"] / record["weight_divisor"]
            # Must land strictly inside [-1, 1): NeuroSim's algoWeightMax is 1.
            self.assertLess(float(np.abs(scaled).max()), 1.0)

    def test_trace_count_mismatch_is_rejected(self):
        layers, _ = self.layers()
        with tempfile.TemporaryDirectory() as directory:
            with self.assertRaises(ValueError):
                neurosim.build_engine_inputs(layers, [], Path(directory),
                                             input_bits=8, synapse_bit=8)

    def test_all_zero_layer_does_not_divide_by_zero(self):
        layers = [{"name": "z", "weights": np.zeros((128, 784)), "bias": np.zeros(128)}]
        with tempfile.TemporaryDirectory() as directory:
            built = neurosim.build_engine_inputs(layers, [np.zeros((4, 784))], Path(directory),
                                                 input_bits=8, synapse_bit=8)
            self.assertEqual(built["normalization"][0]["weight_divisor"], 1.0)


class ExportPresetTests(unittest.TestCase):
    def test_preset_is_written_with_a_hash_even_when_refused(self):
        with tempfile.TemporaryDirectory() as directory:
            artifact = neurosim.export_preset(STOCK_PRESET, Path(directory))
            self.assertEqual(len(artifact["sha256"]), 64)
            # Server paths must not reach the response; only a relative filename.
            self.assertEqual(set(artifact), {"filename", "sha256"})
            written = json.loads((Path(directory) / artifact["filename"]).read_text(encoding="utf-8"))
            self.assertEqual(written["technode_nm"], 22)
            self.assertEqual(set(written["required_fields"]), set(neurosim.REQUIRED_PRESET_FIELDS))
            self.assertTrue(written["model_mismatches"])

    def test_missing_preset_still_records_what_would_be_required(self):
        with tempfile.TemporaryDirectory() as directory:
            artifact = neurosim.export_preset(None, Path(directory))
            written = json.loads((Path(directory) / artifact["filename"]).read_text(encoding="utf-8"))
            self.assertEqual(written["engine"], "neurosim_2d_inference_v1_4")
            self.assertTrue(written["required_fields"])


class DifferentialPlaneTests(unittest.TestCase):
    def test_second_plane_cost_is_named_as_unresolved_not_silently_ignored(self):
        result = neurosim.ppa_result([(784, 128)], root="/nonexistent-engine-root")
        self.assertIn(neurosim.DIFFERENTIAL_PLANE_UNRESOLVED, result["reasons"])
        self.assertEqual(result["status"], "unsupported")


class ConductanceBoundsTests(unittest.TestCase):
    def test_ron_roff_come_from_selected_positive_states(self):
        states = [{"selected": True, "conductance_s": 1e-5},
                  {"selected": True, "conductance_s": 5e-5},
                  {"selected": False, "conductance_s": 9e-5}]
        bounds = neurosim.conductance_bounds(states)
        self.assertAlmostEqual(bounds["resistance_on_ohm"], 1 / 5e-5)
        self.assertAlmostEqual(bounds["resistance_off_ohm"], 1 / 1e-5)
        self.assertIsNone(bounds["reason"])

    def test_no_usable_state_gives_null_not_a_substitute(self):
        bounds = neurosim.conductance_bounds([{"selected": True, "conductance_s": 0.0}])
        self.assertIsNone(bounds["resistance_on_ohm"])
        self.assertIsNone(bounds["resistance_off_ohm"])
        self.assertTrue(bounds["reason"])


if __name__ == "__main__":
    unittest.main()
