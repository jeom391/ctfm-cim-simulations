"""Real-file assumed_proxy PPA flow over HTTP (run where the NeuroSim engine is built, i.e. the Linux API+worker).

    python scripts/measured_ppa_workflow.py --base-url http://127.0.0.1:8200 --out ppa.json [--condition A1] [--tile 256]

Publishes the shared A1 LTP/LTD profile, trains ONE checkpoint, then requests the same profile/checkpoint/array with the
ADC on in both orders and engines.ppa=assumed_proxy. The result is a conditional cost estimate of a virtual analog
circuit that uses the measured conductances (docs/spec/08); it is not a CTFM chip result and totals stay null while
cost blocks are unmodelled. Unsupported configurations (tile 64/128, ADC off) are requested too and must be refused
with explicit reasons, never substituted.
"""
import argparse
import importlib.util
import json
import time
from pathlib import Path

import httpx

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('measured_workflow', ROOT / 'scripts/measured_workflow.py')
mw = importlib.util.module_from_spec(spec)
spec.loader.exec_module(mw)


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument('--base-url', required=True)
    parser.add_argument('--out', required=True)
    parser.add_argument('--condition', default='A1')
    parser.add_argument('--tile', type=int, default=64)
    parser.add_argument('--adc-bits', type=int, default=6)
    parser.add_argument('--timeout', type=int, default=3600)
    args = parser.parse_args()
    manifest = json.loads((mw.DATA / 'manifest.json').read_text(encoding='utf-8'))['files']
    report = {}
    with httpx.Client(base_url=args.base_url + '/api/v1', timeout=180) as client:
        def call(method, path, **kw):
            r = client.request(method, path, **kw)
            if r.status_code >= 400:
                raise SystemExit(f'{method} {path} -> {r.status_code}: {r.text[:1200]}')
            return r

        def wait_job(identifier):
            deadline = time.monotonic() + args.timeout
            while time.monotonic() < deadline:
                job = call('GET', '/jobs/' + identifier).json()
                if job['state'] == 'succeeded':
                    return
                if job['state'] in ('failed', 'cancelled'):
                    raise SystemExit(json.dumps(job, ensure_ascii=False))
                time.sleep(2)
            raise SystemExit('timeout waiting for ' + identifier)

        caps = call('GET', '/capabilities').json()
        report['neurosim_capability'] = caps['engines']['neurosim']
        if not caps['engines']['neurosim']['available']:
            raise SystemExit('NeuroSim engine unavailable in this API process: ' + str(caps['engines']['neurosim']))
        profile, row = mw._publish_condition(call, wait_job, manifest, args.condition)
        report['profile'] = dict(profile_id=profile['profile_id'], revision=1, condition_id=args.condition, states=row['states'])
        base = json.loads((ROOT / 'packages/contracts/fixtures/experiment-baseline.request.json').read_text())
        base.update(schema_version='1.4.0', pools=['combined'], mappings=['fixed_reference'], arrays=1, years=[0], n_reprogram=1)
        base['effects'].update(d2d=False, retention=False, adc=True, c2c=False)
        base['profile_refs'] = [dict(id=profile['profile_id'], revision=1)]
        checkpoint_id = None

        def request(order, tile, ppa='assumed_proxy', adc=True):
            body = json.loads(json.dumps(base))
            body['effects']['adc'] = adc
            body['hardware'] = dict(tile_size=tile, adc_bits=args.adc_bits if adc else None, adc_order=order if adc else None,
                                    range_policy='validation_max_abs' if adc else None, preset_id=None)
            body['engines'] = dict(accuracy='torch_reference', ppa=ppa)
            body['checkpoint_id'] = checkpoint_id
            return body

        refusals = {}
        supported = caps['hardware'].get('ppa_tile_sizes') or []
        probes = [('tile_%d' % s, request('subtract_then_adc', s)) for s in (64, 128, 256) if s not in supported]
        probes.append(('adc_off', request(None, args.tile, adc=False)))
        for name, body in probes:
            r = client.post('/experiments', json=body)
            error = r.json().get('error', {}) if r.status_code >= 400 else {}
            refusals[name] = dict(status=r.status_code, code=error.get('code'), message=error.get('message'),
                                  experiment_id=None if r.status_code >= 400 else r.json().get('experiment_id'))
        report['refused_configurations'] = refusals
        report['ppa_tile_sizes'] = supported
        report['ppa_unsupported'] = caps['hardware'].get('ppa_unsupported')
        if args.tile not in supported:
            report['experiments'] = {}
            report['note'] = ('the engine cannot cost the spec-08 preset at the requested array size; no PPA experiment was '
                              'run and nothing was substituted (see ppa_unsupported)')
            Path(args.out).write_text(json.dumps(report, ensure_ascii=False, indent=2, allow_nan=False), encoding='utf-8')
            print(json.dumps(report, ensure_ascii=False, indent=2))
            return

        report['experiments'] = {}
        for order in ('subtract_then_adc', 'adc_then_subtract'):
            exp = call('POST', '/experiments', json=request(order, args.tile)).json()
            wait_job(exp['job_id'])
            result = call('GET', '/experiments/' + exp['experiment_id']).json()
            checkpoint_id = checkpoint_id or result['checkpoint_id']
            ppa = result['ppa']
            report['experiments'][order] = dict(
                experiment_id=exp['experiment_id'], status=result['status'], checkpoint_id=result['checkpoint_id'],
                accuracy=[r['accuracy'] for r in result['runs'] if r['kind'] == 'ALL'],
                requested_config_ppa=result['requested_config']['engines']['ppa'], schema_version=result['schema_version'],
                ppa={k: ppa.get(k) for k in ('status', 'model_status', 'label', 'requested', 'area_m2', 'energy_j_per_inference', 'latency_s_per_inference',
                                             'engine_totals', 'blocking_reasons', 'incomplete_reasons', 'schedule_check', 'build', 'trace_sample',
                                             'time_basis', 'candidate', 'conductance', 'engine_cross_check', 'model_mismatches')},
                coverage=ppa.get('coverage'), preset=ppa.get('preset'), preset_artifact=ppa.get('preset_artifact'),
                engine=ppa.get('engine'), normalization=ppa.get('normalization'),
                raw_output_tail=((ppa.get('raw_output') or {}).get('stdout') or '')[-1500:],
                artifacts=[a['filename'] for a in result['artifacts'] if 'neurosim' in a['filename'].lower() or a['filename'].startswith(('weight_', 'input_', 'NetWork'))])
    Path(args.out).write_text(json.dumps(report, ensure_ascii=False, indent=2, allow_nan=False), encoding='utf-8')
    print(json.dumps({k: v for k, v in report.items() if k != 'experiments'}, ensure_ascii=False, indent=2))
    for order, e in report['experiments'].items():
        print(order, e['status'], e['accuracy'], e['ppa']['status'], e['ppa']['model_status'], e['ppa']['engine_totals'])


if __name__ == '__main__':
    main()
