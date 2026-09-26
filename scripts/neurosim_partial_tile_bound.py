"""Sanity bound for the partial-tile fix: a layer whose rows end in a partial PE must cost between its neighbours.

    python scripts/neurosim_partial_tile_bound.py REFERENCE_ROOT FIXED_ROOT OUT.json

Single-layer networks R x 128 (spec 08 proxy preset, subArray 64, PE 128) with R = 768 (six full PE tiles), 784 (six full
tiles plus a 16-row partial tile -- the case the reference crashes on), 896 (seven full tiles). The reference engine runs
768 and 896; the fixed engine runs all three. Required: fixed == reference on 768 and 896 (no behaviour change), and the
784 result lies between them for the additive quantities (array/ADC read energy). This does not prove the partial-tile
number is exact; it shows it is a sensible partial cost rather than garbage or zero.
"""
import json
import re
import subprocess
import sys
from pathlib import Path

import numpy as np

from ctfm.adapters import neurosim, neurosim_build
from ctfm.adapters.proxy_preset import proxy_preset

ref_root, fixed_root, out = Path(sys.argv[1]), Path(sys.argv[2]), Path(sys.argv[3])
cache = Path.home()/'ctfm-engines/validate-cache'
tile = 64
preset = proxy_preset(tile)
config = neurosim.build_config(preset, dict(tile_size=tile, adc_bits=6, adc_order='subtract_then_adc', columns_per_adc=8, input_bits=8))
FIELDS = {'readDynamicEnergy_pJ': r"layer1's readDynamicEnergy is: ([0-9.e+-]+)pJ",
          'readLatency_ns': r"layer1's readLatency is: ([0-9.e+-]+)ns",
          'adcEnergy_pJ': r"ADC \(or S/As and precharger for SRAM\) readDynamicEnergy is : ([0-9.e+-]+)pJ",
          'accumEnergy_pJ': r"Accumulation Circuits[^:]*readDynamicEnergy is : ([0-9.e+-]+)pJ"}


def run(root, rows):
    work = Path.home()/('ctfm-engines/partial-bound/%s-%d' % (root.name, rows))
    rng = np.random.default_rng(rows)  # identical data for the reference and the fixed engine
    layers = [dict(name='fc1', weights=rng.normal(0, .1, (128, rows)).astype(np.float32))]
    acts = [rng.uniform(0, 1, (1, rows)).astype(np.float32)]
    inputs = neurosim.build_engine_inputs(layers, acts, work, input_bits=8, synapse_bit=8)
    built = neurosim_build.build(root, config, cache_root=cache)
    p = subprocess.run([built['binary'], str(inputs['network_csv']), '8', '8', str(tile), str(tile)] + [str(a) for a in inputs['trace_args']],
                       capture_output=True, text=True, timeout=900, cwd=work)
    values = {k: (float(re.search(rx, p.stdout).group(1)) if p.returncode == 0 and re.search(rx, p.stdout) else None) for k, rx in FIELDS.items()}
    return dict(rows=rows, returncode=p.returncode, values=values)


rows = []
for name, root in (('reference', ref_root), ('fixed', fixed_root)):
    for r in (768, 784, 896):
        res = dict(engine=name, **run(root, r))
        rows.append(res)
        print(res, flush=True)
by = {(x['engine'], x['rows']): x for x in rows}
checks = {'fixed_equals_reference_768': by[('fixed', 768)]['values'] == by[('reference', 768)]['values'],
          'fixed_equals_reference_896': by[('fixed', 896)]['values'] == by[('reference', 896)]['values'],
          'reference_crashes_on_784': by[('reference', 784)]['returncode'] != 0,
          'fixed_completes_784': by[('fixed', 784)]['returncode'] == 0}
for key in ('adcEnergy_pJ', 'readDynamicEnergy_pJ'):
    lo, mid, hi = (by[('fixed', r)]['values'][key] for r in (768, 784, 896))
    checks['784_between_768_and_896_' + key] = bool(lo is not None and mid is not None and hi is not None and lo <= mid <= hi)
out.write_text(json.dumps(dict(rows=rows, checks=checks), indent=1), encoding='utf-8')
print(json.dumps(checks, indent=1))
