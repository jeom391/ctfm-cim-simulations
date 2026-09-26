"""Small deterministic check that the two-plane cost engine sees the conductances, input bits and cells it is meant to.

    python scripts/neurosim_alignment_check.py ENGINE_ROOT WORK_DIR OUT.json

ENGINE_ROOT is a clean checkout of the patch-0002 branch. Layers are 100 -> 128 -> 10 at array size 64 (a partial row
subarray and a partial column subarray). G+ and G- are different, non-uniform, deterministic patterns. Inputs are the
unsigned codes 0, 1, 127, 128, 255 and a mixed vector. Everything is compared with numbers computed here from the same
files, independently of the engine.
"""
import json
import sys
from pathlib import Path

import numpy as np

from ctfm.adapters import neurosim, neurosim_build, neurosim_diff as nd
from ctfm.adapters.proxy_preset import proxy_preset

root, work, out = Path(sys.argv[1]), Path(sys.argv[2]), Path(sys.argv[3])
work.mkdir(parents=True, exist_ok=True)
TILE = 64
G_MIN, G_MAX = 1e-6, 1e-4
dims = [(100, 128), (128, 10)]


def pattern(shape, a, b):
    o, i = np.indices(shape)
    frac = ((a*o + b*i) % 101)/100.0
    return G_MIN + (G_MAX-G_MIN)*frac**2          # deliberately not uniform


layers = [dict(name='fc%d' % (k+1), g_plus=pattern((n_out, n_in), 7, 13), g_minus=pattern((n_out, n_in), 11, 5))
          for k, (n_in, n_out) in enumerate(dims)]
special = {'zeros': 0, 'ones': 1, 'v127': 127, 'v128': 128, 'v255': 255}
rng = np.random.default_rng(12)
vectors = {name: [np.full(n_in, value, dtype=np.int64) for n_in, _ in dims] for name, value in special.items()}
vectors['mixed'] = [rng.integers(0, 256, n_in) for n_in, _ in dims]
vectors['mixed'][0][::3] = 0            # some zero rows

preset = proxy_preset(TILE)
bounds = nd.pool_bounds([{'conductance_s': G_MIN}, {'conductance_s': G_MAX}])
result = {'tile': TILE, 'layers': dims, 'orders': {}}
_, network_csv, weight_files = nd.stage_weights(layers, work/'weights')
for order in ('adc_then_subtract', 'subtract_then_adc'):
    hardware = dict(tile_size=TILE, adc_bits=6, adc_order=order, columns_per_adc=8, input_bits=8)
    config, extra = nd.build_config_diff(preset, hardware, bounds, order)
    built = neurosim_build.build(root, config, cache_root=Path.home()/'ctfm-engines/validate-cache')
    checks, rows = {}, []
    for name, codes_per_layer in vectors.items():
        inputs = nd.stage_sample(codes_per_layer, layers, work/order/name)
        code, text, err, argv = nd._run_once(built['binary'], root/'Inference_pytorch/NeuroSIM', network_csv, TILE, weight_files, inputs, 600)
        parsed = nd.parse_report(text) if code == 0 else None
        row = {'vector': name, 'returncode': code}
        if parsed:
            params = parsed['ledger']['params']
            per_layer = []
            for l, (layer, codes, ledger) in enumerate(zip(layers, codes_per_layer, parsed['ledger']['layers'])):
                planes = nd.unsigned_planes(codes)
                exp_plus = nd.expected_column_conductance(layer['g_plus'], planes, params, TILE)
                exp_minus = nd.expected_column_conductance(layer['g_minus'], planes, params, TILE)
                n_in, n_out = dims[l]
                per_layer.append({
                    'layer': l,
                    'active_rows_engine': ledger['active_rows'], 'active_rows_expected': nd.expected_activity(planes, TILE, n_out),
                    'colg_plus_rel_err': abs(ledger['plus_colg_s']-exp_plus)/max(exp_plus, 1e-300),
                    'colg_minus_rel_err': abs(ledger['minus_colg_s']-exp_minus)/max(exp_minus, 1e-300),
                    'weight_cells_engine': ledger['weight_cells'], 'weight_cells_expected': n_in*n_out,
                    'used_slots_engine': ledger['used_subarrays'], 'used_slots_expected': nd.spec_slots([dims[l]], TILE)[0],
                    'cycles': ledger['cycles'],
                    'decoded_codes_match': bool(np.array_equal(nd.decode_unsigned_planes(planes), codes)),
                })
            row.update(layers=per_layer, energy_j=parsed['summary']['energy_j'], latency_s=parsed['summary']['latency_s'],
                       array_area_m2=parsed['summary']['array_area_m2'], removed_unused_slots=parsed['ledger']['removed_unused_slots'],
                       flags=parsed['ledger']['flags'])
        else:
            row['stderr_tail'] = (err or '')[-400:]
            row['stdout_tail'] = (text or '')[-400:]
        rows.append(row)
    ok = [r for r in rows if r.get('layers')]
    checks['all_vectors_ran'] = len(ok) == len(rows) and len(ok) > 0
    checks['active_rows_exact'] = all(l['active_rows_engine'] == l['active_rows_expected'] for r in ok for l in r['layers'])
    checks['column_conductance_matches_files'] = all(max(l['colg_plus_rel_err'], l['colg_minus_rel_err']) < 1e-9 for r in ok for l in r['layers'])
    checks['weight_cells_match'] = all(l['weight_cells_engine'] == l['weight_cells_expected'] for r in ok for l in r['layers'])
    checks['used_slots_match_spec_tiling'] = all(l['used_slots_engine'] == l['used_slots_expected'] for r in ok for l in r['layers'])
    checks['bits_round_trip'] = all(l['decoded_codes_match'] for r in ok for l in r['layers'])
    if ok:
        first = ok[0]
        slots = sum(l['used_slots_engine'] for l in first['layers'])
        cell_area = 4*12*(22e-9)**2       # engine 1T1R footprint 4F x 12F at 22 nm (spec 08 section 3)
        expected_array = 2*slots*TILE*TILE*cell_area
        checks['array_area_is_two_planes_of_used_slots'] = abs(first['array_area_m2']-expected_array)/expected_array < 1e-5
        checks['array_area_expected_m2'] = expected_array
        checks['array_area_engine_m2'] = first['array_area_m2']
        checks['physical_cells_two_planes'] = 2*slots*TILE*TILE
        checks['flags_reported'] = first['flags']
    # G+ == G-: the two planes must cost the same; reversing the plane column order must not change the cost
    sym_layers = [dict(l, g_minus=l['g_plus']) for l in layers]
    _, sym_net, sym_files = nd.stage_weights(sym_layers, work/'weights-sym')
    inputs = nd.stage_sample(vectors['mixed'], layers, work/order/'mixed')
    code, text, err, argv = nd._run_once(built['binary'], root/'Inference_pytorch/NeuroSIM', sym_net, TILE, sym_files, inputs, 600)
    sym = nd.parse_report(text)['ledger']['layers'] if code == 0 else None
    if sym:
        plus = sum(l['plus_mlsa_j']+l['plus_wlcap_j']+l['plus_drivers_j'] for l in sym)
        minus = sum(l['minus_mlsa_j']+l['minus_wlcap_j']+l['minus_drivers_j'] for l in sym)
        checks['identical_planes_cost_the_same'] = abs(plus-minus) <= 1e-9*plus
    reversed_dir = work/order/'mixed-reversed'
    reversed_dir.mkdir(parents=True, exist_ok=True)
    rev_inputs = []
    for layer, codes in zip(layers, vectors['mixed']):
        path = reversed_dir/('codes_%s.csv' % layer['name'])
        np.savetxt(str(path), nd.unsigned_planes(codes)[:, ::-1], delimiter=',', fmt='%d')
        rev_inputs.append(path)
    code, text, err, argv = nd._run_once(built['binary'], root/'Inference_pytorch/NeuroSIM', network_csv, TILE, weight_files, rev_inputs, 600)
    if code == 0 and ok:
        rev = nd.parse_report(text)['summary']
        base = next(r for r in ok if r['vector'] == 'mixed')
        checks['plane_column_order_does_not_change_cost'] = (abs(rev['energy_j']-base['energy_j']) <= 1e-9*base['energy_j']
                                                             and abs(rev['latency_s']-base['latency_s']) <= 1e-9*base['latency_s'])
    result['orders'][order] = {'checks': checks, 'rows': rows, 'build_binary': built['binary'], 'applied': built['applied']}
Path(out).write_text(json.dumps(result, indent=1, default=str), encoding='utf-8')
for order, body in result['orders'].items():
    print(order, {k: v for k, v in body['checks'].items()})
