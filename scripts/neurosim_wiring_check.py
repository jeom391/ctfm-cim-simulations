"""Engine wiring check for the assumed_proxy path on a shape the engine can floor-plan (run where NeuroSim is built).

    python scripts/neurosim_wiring_check.py OUT_DIR OUT.json [IN,HIDDEN,OUT [TILE]]

mnist_mlp_v1 cannot be costed with the spec-08 preset (see neurosim_proxy_tile_probe.py). This check therefore uses a
SYNTHETIC network (default 784 -> 512 -> 10) with random weights and activations, only to prove that the configuration-specific
build, the engine run and the stdout parser connect end to end and that the result stays partial with null totals. The
numbers say nothing about CTFM or about mnist_mlp_v1 and must not be quoted as PPA.
"""
import json
import sys
from pathlib import Path

import numpy as np

from ctfm.adapters import neurosim
from ctfm.adapters.proxy_preset import proxy_preset

out_dir, out_json = Path(sys.argv[1]), Path(sys.argv[2])
rng = np.random.default_rng(20260926)
shape = [int(v) for v in sys.argv[3].split(',')] if len(sys.argv) > 3 else [784, 512, 10]
tile = int(sys.argv[4]) if len(sys.argv) > 4 else 64
dims = list(zip(shape[:-1], shape[1:]))
layers = [dict(name='fc%d' % (i+1), weights=rng.normal(0, .1, (o, n)).astype(np.float32)) for i, (n, o) in enumerate(dims)]
acts = [rng.uniform(0, 1, (1, n)).astype(np.float32) for n, _ in dims]
hardware = dict(tile_size=tile, adc_bits=6, adc_order='subtract_then_adc', columns_per_adc=8, input_bits=8)
preset = proxy_preset(tile)
inputs = neurosim.build_engine_inputs(layers, acts, out_dir/'inputs', input_bits=8, synapse_bit=preset['synapse_bit'])
result = neurosim.ppa_result(dims, preset=preset, inputs=inputs, out_dir=out_dir, hardware=hardware)
report = dict(note='SYNTHETIC wiring check, not CTFM and not mnist_mlp_v1', layer_dims=dims, status=result['status'],
              model_status=result['preset'].get('model_status'), blocking_reasons=result['blocking_reasons'],
              engine_totals=result.get('engine_totals'), area_m2=result['area_m2'],
              energy_j_per_inference=result['energy_j_per_inference'], latency_s_per_inference=result['latency_s_per_inference'],
              missing_components=[m['id'] for m in (result['coverage'] or {}).get('missing_components', [])],
              inventory=(result['coverage'] or {}).get('inventory'),
              build={k: v for k, v in (result.get('build') or {}).items() if k in ('applied', 'cached', 'effective', 'binary')},
              schedule_check=result['schedule_check'])
out_json.write_text(json.dumps(report, indent=2, default=str), encoding='utf-8')
print(json.dumps({k: report[k] for k in ('status', 'model_status', 'blocking_reasons', 'engine_totals', 'area_m2', 'missing_components')}, indent=1))
