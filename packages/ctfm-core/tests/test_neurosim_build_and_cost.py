"""Isolated build/cache (decision C1) and the structural cost inventory (spec 08 s5).

The build tests use a stand-in build command, so they exercise the caching,
locking, atomic registration and effective-config check without a NeuroSim
checkout or a C++ toolchain. The engine-dependent half lives in
scripts/linux/verify_neurosim_adapter.py.
"""
import json
import shutil
import tempfile
import unittest
from pathlib import Path

from ctfm.adapters import neurosim, neurosim_build

# Copied from 2DInferenceV1.4 Param.cpp (commit ac828e6): the statements this
# module rewrites, in the engine's actual shape -- bare assignments with a
# leading tab, NOT through a `param->` pointer -- including the two conditional
# re-assignments and a `technode` comparison that must never be mistaken for the
# assignment.
PARAM_SOURCE = """
Param::Param() {
\toperationmode = 2;     \t\t// 1: conventionalSequential
\tmemcelltype = 1;        \t// 1: SRAM  2: RRAM  3: FeFET
\taccesstype = 1;         \t// 1: CMOS_access
\tglobalBusType = false;\t\t// false: X-Y Bus
\tSARADC = false;              // false: MLSA
\tcurrentMode = true;         // true: MLSA use CSA
\tpipeline = true;            // false: layer-by-layer process
\tspeedUpDegree = 8;          // 1 = no speed up
\ttemp = 300;                         // Temperature (K)
\ttechnode = 22;\t\t\t\t\t    // Technology node (nm)
\tnumRowSubArray = 128;               // # of rows in single subArray
\tnumColSubArray = 128;               // # of columns in single subArray
\tparallelRead = 0;
\tif(conventionalParallel || BNNparallelMode || XNORparallelMode) {
\t\tparallelRead = 1;
\t}
\tnumColMuxed = 8;                    // How many columns share 1 ADC
\tif ((conventionalSequential == 1) && (memcelltype==1))
\t{
\tnumColMuxed=numColPerSynapse;
\t}
\tlevelOutput = 32;                   // 32 levels --> 5-bit ADC
\tcellBit = 1;                        // precision of memory device
\tdumcolshared = levelOutput;
\treadPulseWidth = 10e-9;             // read pulse width in sec
\tif (memcelltype == 1) {
\t\tcellBit = 1;             // force cellBit = 1 for all SRAM cases
\t}
\telse if (technode == 14) {readVoltage=0.277;}
}
"""

# A build command that just creates the expected binary, so the cache logic is
# what is under test rather than a compiler.
FAKE_BUILD = ("python", "-c",
              "import pathlib;p=pathlib.Path('Inference_pytorch/NeuroSIM/main');"
              "p.parent.mkdir(parents=True,exist_ok=True);p.write_text('binary')")


def checkout(root):
    source = Path(root)/neurosim_build.PARAM_RELPATH
    source.parent.mkdir(parents=True, exist_ok=True)
    source.write_text(PARAM_SOURCE, encoding="utf-8")
    return Path(root)


def config(**overrides):
    base = dict(adc_bits=5, columns_per_adc=8, technode_nm=22, cell_bit=1, sub_array=64,
                read_pulse_width_s=10e-9)
    base.update(overrides)
    return neurosim_build.resolve_config(**base)


class BuildCacheTests(unittest.TestCase):
    def test_adc_bits_become_the_compile_time_level_count(self):
        resolved = config(adc_bits=6)
        self.assertEqual(resolved["adc_levels"], 64)
        patched, applied = neurosim_build.apply_config(PARAM_SOURCE, resolved)
        self.assertIn("levelOutput = 64;", patched)
        self.assertEqual(applied["levelOutput"], 64)
        self.assertEqual(neurosim_build.read_effective(patched)["adc_levels"], 64)

    def test_every_baseline_field_round_trips_through_the_engine_source(self):
        """The whole docs/spec/08 section 2 baseline, read back from the text that
        would be compiled rather than from what we meant to write."""
        resolved = config()
        patched, _ = neurosim_build.apply_config(PARAM_SOURCE, resolved)
        effective = neurosim_build.read_effective(patched)
        for key in neurosim_build.PARAM_FIELDS:
            if key in resolved:
                self.assertEqual(effective[key], resolved[key], key)
        # 22 nm, 300 K, XY bus, current-mode MLSA, pipeline off, square subarray.
        self.assertEqual((effective["technode_nm"], effective["temperature_k"]), (22, 300))
        self.assertEqual((effective["global_bus_type"], effective["sar_adc"],
                          effective["current_mode"]), (0, 0, 1))
        self.assertEqual(effective["pipeline"], 0)
        self.assertEqual(effective["sub_array_rows"], effective["sub_array_cols"])

    def test_a_technode_comparison_is_not_mistaken_for_the_assignment(self):
        patched, _ = neurosim_build.apply_config(PARAM_SOURCE, config(technode_nm=32))
        self.assertIn("technode = 32;", patched)
        # The `else if (technode == 14)` line must survive untouched.
        self.assertIn("technode == 14", patched)

    def test_the_read_pulse_width_is_written_as_a_number_the_compiler_accepts(self):
        patched, _ = neurosim_build.apply_config(PARAM_SOURCE, config(read_pulse_width_s=2e-8))
        self.assertEqual(neurosim_build.read_effective(patched)["read_pulse_width_s"], 2e-8)

    def test_engine_derived_values_are_recorded_and_never_patched(self):
        """parallelRead and readVoltage are computed by the constructor; writing
        them would be overwritten, so they must not be in the patch set."""
        for field in neurosim_build.DERIVED_FIELDS:
            self.assertNotIn(field, neurosim_build.PARAM_FIELDS.values())
        self.assertIn("readVoltage", neurosim_build.DERIVED_FIELDS)
        self.assertIn("parallelRead", neurosim_build.DERIVED_FIELDS)

    def test_a_configuration_that_reaches_a_later_assignment_is_refused(self):
        """memcelltype=1 forces cellBit=1 further down, so a patched cellBit would
        not be the effective one."""
        with self.assertRaises(ValueError) as error:
            neurosim_build.apply_config(PARAM_SOURCE, config(cell_bit=4, memcell_type=1))
        self.assertIn("cellBit", str(error.exception))
        # The analog cell this project uses does not reach that branch.
        neurosim_build.apply_config(PARAM_SOURCE, config(cell_bit=4, memcell_type=2))

    def test_a_field_reassigned_for_no_known_reason_is_refused(self):
        doubled = PARAM_SOURCE + "\n\tlevelOutput = 8;\n"
        with self.assertRaises(ValueError) as error:
            neurosim_build.apply_config(doubled, config())
        self.assertIn("levelOutput", str(error.exception))

    def test_the_key_separates_every_input_that_changes_the_binary(self):
        common = dict(upstream_commit="abc123", patch_sha256="p",
                      compiler={"compiler": "g++", "version": "13.3", "flags": []},
                      target={"system": "Linux", "machine": "x86_64", "libc": "glibc 2.39"})
        base = neurosim_build.cache_key(config=config(), **common)
        self.assertNotEqual(base, neurosim_build.cache_key(config=config(adc_bits=6), **common))
        self.assertNotEqual(base, neurosim_build.cache_key(
            config=config(), **dict(common, upstream_commit="def456")))
        self.assertNotEqual(base, neurosim_build.cache_key(
            config=config(), **dict(common, patch_sha256="q")))
        self.assertNotEqual(base, neurosim_build.cache_key(
            config=config(), **dict(common, compiler={"compiler": "g++", "version": "9.4",
                                                      "flags": []})))
        self.assertNotEqual(base, neurosim_build.cache_key(
            config=config(), **dict(common, target={"system": "Darwin", "machine": "arm64",
                                                    "libc": None})))
        self.assertEqual(base, neurosim_build.cache_key(config=config(), **common))

    def test_an_unpinned_upstream_commit_is_refused(self):
        with self.assertRaises(ValueError):
            neurosim_build.cache_key(upstream_commit=None, patch_sha256="p", config=config(),
                                     compiler={}, target={})

    def test_a_build_is_registered_once_and_reused_by_key(self):
        with tempfile.TemporaryDirectory() as directory:
            root = checkout(Path(directory)/"src")
            cache = Path(directory)/"cache"
            first = neurosim_build.build(root, config(), cache_root=cache,
                                         upstream_commit="abc123", build_command=FAKE_BUILD)
            self.assertFalse(first["cached"])
            self.assertTrue(Path(first["binary"]).is_file())
            self.assertEqual(first["effective"]["adc_levels"], 32)
            self.assertIn("parallelRead", first["derived_by_engine"])
            second = neurosim_build.build(root, config(), cache_root=cache,
                                          upstream_commit="abc123", build_command=FAKE_BUILD)
            self.assertTrue(second["cached"])
            self.assertEqual(second["binary"], first["binary"])
            other = neurosim_build.build(root, config(adc_bits=8), cache_root=cache,
                                         upstream_commit="abc123", build_command=FAKE_BUILD)
            self.assertNotEqual(other["binary"], first["binary"])
            self.assertEqual(other["effective"]["adc_levels"], 256)
            # The reference checkout is copied, never edited in place.
            self.assertEqual((root/neurosim_build.PARAM_RELPATH).read_text(encoding="utf-8"),
                             PARAM_SOURCE)
            entries = {p.name for p in cache.iterdir() if p.is_dir()}
            self.assertEqual(len(entries), 2)
            self.assertFalse(any(name.startswith("building-") for name in entries))

    def test_a_failed_build_leaves_no_cache_entry(self):
        with tempfile.TemporaryDirectory() as directory:
            root = checkout(Path(directory)/"src")
            cache = Path(directory)/"cache"
            with self.assertRaises(RuntimeError):
                neurosim_build.build(root, config(), cache_root=cache, upstream_commit="abc123",
                                     build_command=("python", "-c", "raise SystemExit(3)"))
            self.assertEqual([p for p in cache.iterdir() if p.is_dir()], [])

    def test_a_build_that_produces_no_binary_is_a_failure_not_an_empty_entry(self):
        with tempfile.TemporaryDirectory() as directory:
            root = checkout(Path(directory)/"src")
            cache = Path(directory)/"cache"
            with self.assertRaises(RuntimeError):
                neurosim_build.build(root, config(), cache_root=cache, upstream_commit="abc123",
                                     build_command=("python", "-c", "pass"))
            self.assertEqual([p for p in cache.iterdir() if p.is_dir()], [])

    def test_a_source_that_does_not_take_the_patch_fails_loudly(self):
        with tempfile.TemporaryDirectory() as directory:
            root = checkout(Path(directory)/"src")
            (root/neurosim_build.PARAM_RELPATH).write_text("void Param::Param() {}\n",
                                                           encoding="utf-8")
            with self.assertRaises(ValueError):
                neurosim_build.build(root, config(), cache_root=Path(directory)/"cache",
                                     upstream_commit="abc123", build_command=FAKE_BUILD)

    def test_a_held_lock_is_waited_for_and_a_stale_one_is_reclaimed(self):
        with tempfile.TemporaryDirectory() as directory:
            cache = Path(directory)/"cache"
            lock = cache/"key.lock"
            neurosim_build._acquire(lock)
            with self.assertRaises(TimeoutError):
                neurosim_build._acquire(lock, timeout=0.3)
            shutil.rmtree(lock)
            neurosim_build._acquire(lock, timeout=0.3)
            self.assertTrue((lock/"owner").is_file())


VALID_PRESET = {
    "preset_id": "ctfm-equivalent-v0", "validated_for_ctfm": True,
    "technode_nm": 22, "read_voltage_v": 0.55, "read_pulse_width_s": 10e-9,
    "read_pulse_width_source": "engine_baseline_22nm", "cell_bit": 1, "synapse_bit": 8,
    "sub_array": 64, "parallel_rows": 64, "adc_architecture": "MLSA current mode",
    "columns_per_adc": 8, "interconnect": "XY bus", "memcell_type": "RRAM",
    "access_type": "CMOS_access", "input_precision_bits": 8,
}
HARDWARE = {"tile_size": 64, "adc_bits": 5, "adc_order": "subtract_then_adc"}


class PresetToBuildConfigTests(unittest.TestCase):
    """The preset is what decides the compile-time configuration; nothing is
    defaulted behind it."""

    def test_the_baseline_preset_maps_onto_neurosim_numbering(self):
        resolved = neurosim.build_config(VALID_PRESET, HARDWARE)
        self.assertEqual(resolved["memcell_type"], 2)     # RRAM
        self.assertEqual(resolved["access_type"], 1)      # CMOS_access
        self.assertEqual(resolved["operation_mode"], 2)   # parallel read is derived
        self.assertEqual(resolved["sar_adc"], 0)          # MLSA, not SAR
        self.assertEqual(resolved["current_mode"], 1)     # current-mode sensing
        self.assertEqual(resolved["global_bus_type"], 0)  # XY bus
        self.assertEqual(resolved["adc_levels"], 32)      # 5 bit
        self.assertEqual(resolved["sub_array_rows"], 64)
        self.assertEqual(resolved["read_pulse_width_s"], 10e-9)
        self.assertEqual(resolved["temperature_k"], 300)

    def test_the_requested_adc_bits_reach_the_compile_time_level_count(self):
        for bits, levels in ((3, 8), (6, 64), (8, 256)):
            resolved = neurosim.build_config(VALID_PRESET, dict(HARDWARE, adc_bits=bits))
            self.assertEqual(resolved["adc_levels"], levels)

    def test_an_h_tree_preset_selects_the_other_bus(self):
        resolved = neurosim.build_config(dict(VALID_PRESET, interconnect="H-tree"), HARDWARE)
        self.assertEqual(resolved["global_bus_type"], 1)

    def test_a_cell_or_access_model_neurosim_does_not_have_is_refused(self):
        for override in ({"memcell_type": "CTFM"}, {"access_type": "ferroelectric_gate"}):
            with self.assertRaises(ValueError):
                neurosim.build_config(dict(VALID_PRESET, **override), HARDWARE)


class BuildWiringTests(unittest.TestCase):
    def test_run_engine_prefers_the_binary_the_cache_built(self):
        result = neurosim.run_engine("net.csv", [], synapse_bit=8, input_bit=8, sub_array=64,
                                     parallel_rows=64, root="/nonexistent-engine-root",
                                     binary="/nonexistent-cache/main")
        self.assertEqual(result["status"], "unsupported")
        self.assertIn("Built binary missing", result["reason"])

    def test_an_admitted_preset_goes_through_the_build_and_fails_loudly(self):
        """With the gate open the run needs a configuration-specific binary. A
        checkout the cache cannot build from is a failure, not a silent fall back
        to the reference binary compiled with upstream's constants."""
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)/"checkout"
            binary = root/neurosim_build.BINARY_RELPATH
            binary.parent.mkdir(parents=True, exist_ok=True)
            binary.write_text("not a real engine")
            # No Param.cpp next to it, so the cache has nothing to patch.
            result = neurosim.ppa_result([(1024, 128)], preset=VALID_PRESET, root=root,
                                         inputs={"network_csv": "n.csv", "trace_args": [],
                                                 "synapse_bit": 8, "input_bits": 8,
                                                 "normalization": [], "conductance": {},
                                                 "trace_sample": "fixture"},
                                         hardware=HARDWARE,
                                         cache_root=Path(directory)/"cache")
            self.assertEqual(result["status"], "failed")
            self.assertTrue(any("build failed" in r for r in result["reasons"]), result["reasons"])
            for key in ("area_m2", "energy_j_per_inference", "latency_s_per_inference"):
                self.assertIsNone(result[key])


class CircuitInventoryTests(unittest.TestCase):
    """docs/spec/08 acceptance 4, on an array small enough to count by hand."""
    def test_a_small_array_has_two_planes_of_cells_and_no_bit_sliced_columns(self):
        inventory = neurosim.circuit_inventory([(4, 4)], tile_size=2, columns_per_adc=2,
                                               adc_bits=5, adc_order="adc_then_subtract")
        layer = inventory["layers"][0]
        self.assertEqual(layer["physical_cells"], 2*4*4)
        self.assertEqual(layer["cells_per_plane"], 16)
        self.assertEqual(inventory["cells_per_weight_per_plane"], 1)
        self.assertEqual(layer["logical_tiles"], 4)
        self.assertEqual(layer["physical_arrays"], 8)

    def test_converting_first_needs_a_converter_on_each_plane(self):
        separate = neurosim.circuit_inventory([(4, 4)], tile_size=2, columns_per_adc=2,
                                              adc_bits=5, adc_order="adc_then_subtract")
        combined = neurosim.circuit_inventory([(4, 4)], tile_size=2, columns_per_adc=2,
                                              adc_bits=5, adc_order="subtract_then_adc")
        self.assertEqual(separate["adc_count"], 8)
        self.assertEqual(combined["adc_count"], 4)
        # Same bit count, different cost: the two orders must not look identical.
        self.assertNotEqual(separate["adc_count"], combined["adc_count"])

    def test_every_bit_plane_is_converted_on_the_fixed_eight_cycle_schedule(self):
        inventory = neurosim.circuit_inventory([(4, 4)], tile_size=2, columns_per_adc=2,
                                               adc_bits=5, adc_order="adc_then_subtract")
        self.assertEqual(inventory["conversion_cycles_per_inference"], 8*8)
        self.assertEqual(inventory["input_bits"], 8)

    def test_shared_blocks_are_counted_once_and_plane_blocks_per_plane(self):
        layer = neurosim.circuit_inventory([(4, 4)], tile_size=2, columns_per_adc=2, adc_bits=5,
                                           adc_order="subtract_then_adc")["layers"][0]
        self.assertIn("input_buffer", layer["shared_once"])
        self.assertIn("final_accumulator", layer["shared_once"])
        self.assertIn("array", layer["per_plane"])
        self.assertNotIn("input_buffer", layer["per_plane"])

    def test_an_order_is_required_before_any_count_is_produced(self):
        with self.assertRaises(ValueError):
            neurosim.circuit_inventory([(4, 4)], tile_size=2, columns_per_adc=2, adc_bits=5,
                                       adc_order=None)


def block(area, energy, latency):
    return {"area_m2": area, "energy_j": energy, "latency_s": latency}


def full_blocks():
    """Round numbers so the composition can be checked by hand.

    per-plane: array 10 + row_driver 2 + column_multiplexer 1 = 13 per plane
    shared:    input_buffer 5 + final_accumulator 4 + interconnect 3 + shift_add 2 = 14
    """
    per_plane = {"array": block(10, 100, 7), "row_driver": block(2, 20, 2),
                 "column_multiplexer": block(1, 10, 1)}
    shared = {"input_buffer": block(5, 50, 0.5), "final_accumulator": block(4, 40, 0.25),
              "interconnect": block(3, 30, 0.25), "bit_significance_shift_add": block(2, 20, 0)}
    return per_plane, shared


class DifferentialCompositionTests(unittest.TestCase):
    """docs/spec/08 section 5: how the two planes combine. The rule is fixed by
    decision A5; the per-block numbers still have to come from an engine run."""

    def test_per_plane_blocks_add_and_shared_blocks_are_counted_once(self):
        per_plane, shared = full_blocks()
        composed = neurosim.compose_differential_cost(
            per_plane, shared, adc_order="adc_then_subtract", converter=block(6, 60, 3))
        self.assertEqual(composed["missing"], [])
        # per-plane 13 + converter 6 = 19 per plane, twice, plus 14 shared once.
        self.assertEqual(composed["area_m2"], 2*19+14)
        self.assertEqual(composed["energy_j_per_inference"], 2*190+140)

    def test_the_total_is_not_the_single_plane_total_times_two(self):
        per_plane, shared = full_blocks()
        composed = neurosim.compose_differential_cost(
            per_plane, shared, adc_order="adc_then_subtract", converter=block(6, 60, 3))
        single_plane_total = 19+14
        self.assertNotEqual(composed["area_m2"], 2*single_plane_total)
        self.assertLess(composed["area_m2"], 2*single_plane_total)

    def test_latency_is_the_parallel_read_maximum_plus_common_time(self):
        per_plane, shared = full_blocks()
        composed = neurosim.compose_differential_cost(
            per_plane, shared, adc_order="adc_then_subtract", converter=block(6, 60, 3),
            common_latency_s=0.5)
        # Each plane: 7+2+1+3 = 13; they are read at the same time, so max = 13.
        self.assertEqual(composed["plane_latencies_s"], [13, 13])
        # Shared latency 0.5+0.25+0.25+0 plus the caller's common 0.5.
        self.assertEqual(composed["common_latency_s"], 1.5)
        self.assertEqual(composed["latency_s_per_inference"], 14.5)

    def test_a_slower_plane_sets_the_read_latency_not_their_sum(self):
        per_plane, shared = full_blocks()
        per_plane["array"] = {"plane_a": block(10, 100, 7), "plane_b": block(10, 100, 11)}
        composed = neurosim.compose_differential_cost(
            per_plane, shared, adc_order="adc_then_subtract", converter=block(6, 60, 3))
        self.assertEqual(composed["plane_latencies_s"], [13, 17])
        self.assertEqual(composed["latency_s_per_inference"], 17+1.0)

    def test_subtracting_first_shares_one_converter_between_the_planes(self):
        per_plane, shared = full_blocks()
        converter = block(6, 60, 3)
        separate = neurosim.compose_differential_cost(
            per_plane, shared, adc_order="adc_then_subtract", converter=converter)
        combined = neurosim.compose_differential_cost(
            per_plane, shared, adc_order="subtract_then_adc", converter=converter)
        # One converter instead of two: exactly one converter's area less.
        self.assertEqual(separate["area_m2"]-combined["area_m2"], 6)

    def test_a_missing_block_leaves_every_total_null_and_names_itself(self):
        per_plane, shared = full_blocks()
        del per_plane["row_driver"]
        composed = neurosim.compose_differential_cost(
            per_plane, shared, adc_order="adc_then_subtract", converter=block(6, 60, 3))
        self.assertIn("row_driver", composed["missing"])
        for key in ("area_m2", "energy_j_per_inference", "latency_s_per_inference"):
            self.assertIsNone(composed[key])

    def test_a_block_with_a_missing_number_is_not_treated_as_zero(self):
        per_plane, shared = full_blocks()
        per_plane["array"] = {"area_m2": 10, "energy_j": None, "latency_s": 7}
        composed = neurosim.compose_differential_cost(
            per_plane, shared, adc_order="adc_then_subtract", converter=block(6, 60, 3))
        self.assertIn("array.energy_j", composed["missing"])
        self.assertIsNone(composed["energy_j_per_inference"])

    def test_with_no_block_costs_at_all_the_rule_still_reports_what_it_needs(self):
        composed = neurosim.compose_differential_cost({}, {}, adc_order="subtract_then_adc")
        self.assertIsNone(composed["area_m2"])
        for name in neurosim.PER_PLANE_BLOCKS+neurosim.SHARED_BLOCKS:
            self.assertIn(name, composed["missing"])
        self.assertIn("adc", composed["missing"])

    def test_the_order_is_required(self):
        with self.assertRaises(ValueError):
            neurosim.compose_differential_cost({}, {}, adc_order="whatever")


class CostCoverageTests(unittest.TestCase):
    def test_the_analog_subtraction_front_end_is_named_as_missing(self):
        coverage = neurosim.cost_coverage(neurosim.circuit_inventory(
            [(4, 4)], tile_size=2, columns_per_adc=2, adc_bits=5,
            adc_order="subtract_then_adc"))
        ids = {m["id"] for m in coverage["missing_components"]}
        self.assertIn("analog_subtraction_frontend", ids)
        self.assertIn("bipolar_range_conversion", ids)
        self.assertIn("differential_plane_pair", ids)
        self.assertEqual(coverage["status"], "partial")

    def test_digital_subtraction_is_missing_for_the_other_order(self):
        coverage = neurosim.cost_coverage(neurosim.circuit_inventory(
            [(4, 4)], tile_size=2, columns_per_adc=2, adc_bits=5,
            adc_order="adc_then_subtract"))
        ids = {m["id"] for m in coverage["missing_components"]}
        self.assertIn("digital_subtraction", ids)
        self.assertNotIn("analog_subtraction_frontend", ids)

    def test_totals_are_null_not_zero_and_say_why(self):
        for order in neurosim.ADC_ORDERS:
            coverage = neurosim.cost_coverage(neurosim.circuit_inventory(
                [(4, 4)], tile_size=2, columns_per_adc=2, adc_bits=5, adc_order=order))
            for key in ("area_m2", "energy_j_per_inference", "latency_s_per_inference"):
                self.assertIsNone(coverage[key])
            self.assertIn("null", coverage["totals_reason"])

    def test_the_write_datapath_is_excluded_by_scope_not_silently_dropped(self):
        coverage = neurosim.cost_coverage(neurosim.circuit_inventory(
            [(4, 4)], tile_size=2, columns_per_adc=2, adc_bits=5,
            adc_order="subtract_then_adc"))
        self.assertIn("write_datapath", {e["id"] for e in coverage["excluded_by_scope"]})

    def test_the_gate_publishes_the_inventory_with_its_refusal(self):
        result = neurosim.ppa_result([(784, 128), (128, 10)], root="/nonexistent-engine-root",
                                     hardware={"tile_size": 64, "adc_bits": 5,
                                               "adc_order": "subtract_then_adc"})
        self.assertEqual(result["coverage"]["inventory"]["layers"][0]["physical_cells"],
                         2*784*128)
        for key in ("area_m2", "energy_j_per_inference", "latency_s_per_inference"):
            self.assertIsNone(result[key])
        self.assertTrue(any("analog_subtraction_frontend" in r for r in result["reasons"]))
        # Serializable: the result travels to the browser as JSON.
        json.dumps(result["coverage"])


if __name__ == "__main__":
    unittest.main()
