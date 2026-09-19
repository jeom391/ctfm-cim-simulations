"""Check the NeuroSim adapter against the real engine checkout and binary.

Three things are verified here and nowhere else, because all three need the
actual NeuroSim checkout present:

  1. ctfm.adapters.neurosim's trace writers produce byte-identical output to
     upstream's utee.hook writers, so reimplementing them cannot drift.
  2. parse_stdout() reads real engine stdout, not a fixture of it.
  3. the preset gate stays closed on NeuroSim's own stock values.
"""
import json
import os
import sys
import tempfile
from pathlib import Path

ENGINE = Path(os.environ.get("CTFM_ENGINE_ROOT", "/opt/ctfm-engines"))
INFERENCE = ENGINE / "neurosim" / "Inference_pytorch"
sys.path.insert(0, str(INFERENCE))

import numpy as np  # noqa: E402

from ctfm.adapters import neurosim  # noqa: E402
from utee.hook import write_matrix_activation_fc, write_matrix_weight  # noqa: E402


def writer_parity(tmp):
    rng = np.random.default_rng(20260919)
    checks = []
    for name, shape, bits in (("fc1", (128, 784), 8), ("fc2", (10, 128), 8), ("narrow", (4, 16), 4)):
        weight = rng.normal(scale=0.12, size=shape).clip(-1, 1 - 2 ** -7)
        activation = (rng.random(shape[1]).astype(np.float64) * 2 - 1).clip(-1, 1 - 2 ** -7)

        ours_w, theirs_w = tmp / f"ours_w_{name}.csv", tmp / f"up_w_{name}.csv"
        neurosim.encode_weight_csv(weight, ours_w)
        write_matrix_weight(weight, str(theirs_w))

        ours_a, theirs_a = tmp / f"ours_a_{name}.csv", tmp / f"up_a_{name}.csv"
        neurosim.encode_activation_csv(activation, bits, ours_a)
        write_matrix_activation_fc(activation.reshape(1, -1), None, bits, str(theirs_a))

        # Upstream writes the bit planes as numpy str_ ('0'/'1'); compare values.
        theirs_planes = np.genfromtxt(theirs_a, delimiter=",", dtype=float)
        ours_planes = np.genfromtxt(ours_a, delimiter=",", dtype=float)
        checks.append({
            "layer": name,
            "weight_bytes_identical": ours_w.read_bytes() == theirs_w.read_bytes(),
            "activation_values_identical": bool(np.array_equal(ours_planes, theirs_planes)),
            "activation_shape": list(np.atleast_2d(ours_planes).shape),
        })
    return checks


def engine_roundtrip(tmp):
    """Run one topology this build survives and parse the real stdout."""
    dims = [(784, 128)]
    network = tmp / "net.csv"
    neurosim.write_network_csv(dims, network)
    rng = np.random.default_rng(5)
    weight = rng.normal(scale=0.12, size=(128, 784)).clip(-1, 1 - 2 ** -7)
    activation = (rng.random(784) * 2 - 1).clip(-1, 1 - 2 ** -7)
    weight_csv, input_csv = tmp / "w.csv", tmp / "i.csv"
    neurosim.encode_weight_csv(weight, weight_csv)
    neurosim.encode_activation_csv(activation, 8, input_csv)

    supported, reason = neurosim.topology_support(dims)
    run = neurosim.run_engine(network, [weight_csv, input_csv], synapse_bit=8, input_bit=8,
                             sub_array=128, parallel_rows=128,
                             root=str(ENGINE / "neurosim"), timeout=1800)
    return {
        "topology_supported": supported,
        "topology_reason": reason,
        "status": run["status"],
        "returncode": run["returncode"],
        "seconds": run.get("seconds"),
        "parsed_si": run.get("parsed"),
        "engine_commit": run["engine"]["commit"],
        "engine_binary_sha256": run["engine"]["binary_sha256"],
    }


def gate_checks():
    """The gate must reject: nothing, stock SRAM values, and write-pulse reuse."""
    stock = {
        "preset_id": "neurosim-stock-sram-22nm",
        "technode_nm": 22, "read_voltage_v": 0.55, "read_pulse_width_s": 10e-9,
        "cell_bit": 1, "synapse_bit": 8, "sub_array": 128, "parallel_rows": 128,
        "adc_architecture": "MLSA current mode", "columns_per_adc": 8,
        "interconnect": "XY bus", "memcell_type": "SRAM", "input_precision_bits": 8,
    }
    write_pulse = dict(stock, validated_for_ctfm=True, read_pulse_width_s=1e-3)
    return {
        "no_preset": neurosim.preset_decision(),
        "stock_unvalidated": neurosim.preset_decision(stock),
        "write_pulse_as_read": neurosim.preset_decision(write_pulse),
        "missing_fields": neurosim.preset_decision({"preset_id": "empty", "validated_for_ctfm": True}),
    }


def assembled_inputs_run_on_the_real_engine(tmp):
    """Feed build_engine_inputs' output straight into the built binary.

    Uses a topology this build survives (a single wide FC layer) so the check is
    about whether the assembler's files are acceptable, not about the segfault.
    """
    rng = np.random.default_rng(11)
    layers = [{"name": "fc1", "weights": rng.normal(scale=0.12, size=(128, 784)),
               "bias": np.zeros(128)}]
    activations = [rng.random((256, 784))]  # 256-sample trace; row 0 is written
    built = neurosim.build_engine_inputs(layers, activations, tmp / "assembled",
                                         input_bits=8, synapse_bit=8,
                                         profile_states=[{"selected": True, "conductance_s": 1e-5},
                                                         {"selected": True, "conductance_s": 5e-5}])
    run = neurosim.run_engine(built["network_csv"], built["trace_args"],
                              synapse_bit=built["synapse_bit"], input_bit=built["input_bits"],
                              sub_array=128, parallel_rows=128,
                              root=str(ENGINE / "neurosim"), timeout=1800)
    preset = neurosim.export_preset({"preset_id": "probe"}, tmp / "assembled")
    return {
        "layer_dims": built["layer_dims"],
        "network_rows": built["network_rows"],
        "normalization": built["normalization"],
        "conductance": built["conductance"],
        "preset_artifact_sha256": preset["sha256"],
        "status": run["status"],
        "returncode": run["returncode"],
        "chip_area_m2": (run.get("parsed") or {}).get("chip_area_m2"),
        "modes_reported": (run.get("parsed") or {}).get("modes_reported"),
    }


def main():
    with tempfile.TemporaryDirectory() as directory:
        tmp = Path(directory)
        report = {
            "writer_parity": writer_parity(tmp),
            "engine_roundtrip": engine_roundtrip(tmp),
            "preset_gate": gate_checks(),
            "assembled_inputs": assembled_inputs_run_on_the_real_engine(tmp),
            "ppa_result_mnist_mlp_v1": neurosim.ppa_result([(784, 128), (128, 10)],
                                                           root=str(ENGINE / "neurosim")),
        }

    out = ENGINE / "smoke" / "neurosim-adapter"
    out.mkdir(parents=True, exist_ok=True)
    (out / "report.json").write_text(json.dumps(report, indent=2, default=str))

    parity_ok = all(c["weight_bytes_identical"] and c["activation_values_identical"]
                    for c in report["writer_parity"])
    round_ok = report["engine_roundtrip"]["status"] == "succeeded" \
        and report["engine_roundtrip"]["parsed_si"]["chip_area_m2"] is not None \
        and bool(report["engine_roundtrip"]["parsed_si"]["modes_reported"])
    gate_ok = all(d["status"] == "unsupported" for d in report["preset_gate"].values()) \
        and report["ppa_result_mnist_mlp_v1"]["status"] == "unsupported" \
        and report["ppa_result_mnist_mlp_v1"]["area_m2"] is None

    print(json.dumps(report, indent=2, default=str))
    print("\nwriter_parity:", "OK" if parity_ok else "FAIL")
    print("engine_roundtrip:", "OK" if round_ok else "FAIL")
    assembled = report["assembled_inputs"]
    assembled_ok = (assembled["status"] == "succeeded"
                    and assembled["chip_area_m2"] is not None
                    and assembled["conductance"]["resistance_on_ohm"] == 1 / 5e-5)
    print("preset_gate_closed:", "OK" if gate_ok else "FAIL")
    print("assembled_inputs_accepted:", "OK" if assembled_ok else "FAIL")
    return 0 if (parity_ok and round_ok and gate_ok and assembled_ok) else 1


if __name__ == "__main__":
    raise SystemExit(main())
