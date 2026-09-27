"""Probe which physical array sizes the built NeuroSim survives for mnist_mlp_v1 under the assumed_proxy preset.

    python scripts/neurosim_proxy_tile_probe.py SMOKE_DIR OUT.json

SMOKE_DIR holds NetWork_ctfm_mlp.csv and traces/{weight,input}_layer{1,2}.csv (engine input files of any content: the
probe only decides whether the engine finishes, not what it costs). One binary is built per array size from the fixed
spec-08 preset (no bit slicing, one physical column per weight and plane), then run once. Results are recorded, not
interpreted: a crash or the engine's own hierarchy error is a measured refusal.
"""
import json
import sys
from pathlib import Path

from ctfm.adapters import neurosim, neurosim_build
from ctfm.adapters.proxy_preset import proxy_preset

smoke = Path(sys.argv[1])
trace_args = [str(smoke / 'traces' / n) for n in
              ('weight_layer1.csv', 'input_layer1.csv', 'weight_layer2.csv', 'input_layer2.csv')]
rows = []
for tile in (32, 64, 128, 256):
    preset = dict(proxy_preset(256), sub_array=tile, parallel_rows=tile)
    hardware = dict(tile_size=tile, adc_bits=6, adc_order='subtract_then_adc', columns_per_adc=8, input_bits=8)
    built = neurosim_build.build(neurosim.ENGINE_ROOT, neurosim.build_config(preset, hardware))
    run = neurosim.run_engine(str(smoke / 'NetWork_ctfm_mlp.csv'), trace_args, synapse_bit=8, input_bit=8, sub_array=tile,
                              parallel_rows=tile, binary=built['binary'], timeout=900)
    rows.append(dict(tile=tile, status=run['status'], reason=run.get('reason'), returncode=run.get('returncode'),
                     engine_message=[l for l in (run.get('stdout') or '').splitlines() if 'ERROR' in l][:2],
                     chip_area_m2=(run.get('parsed') or {}).get('chip_area_m2')))
    print(rows[-1], flush=True)
Path(sys.argv[2]).write_text(json.dumps(dict(preset='assumed_proxy (cell_bit 8, synapse_bit 8, RRAM+CMOS access)', rows=rows),
                                        indent=2), encoding='utf-8')
