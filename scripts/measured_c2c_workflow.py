"""Real-file measured-C2C flow over HTTP against a running API + worker (use an isolated storage root/port).

    python scripts/measured_c2c_workflow.py --base-url http://127.0.0.1:8100 --c2c-file "<A3 1000Cycle.xlsx>" --out result.json

A1 LTP/LTD (shared, hash-pinned CSVs) -> published profile; the local A3 C2C workbook -> c2c_detrended analysis
with the device team's stated Program/Erase/Read conditions; then ONE trained checkpoint is reused for
C2C off / manual 5 % / measured (server-resolved) requests on the same profile revision.
The A3 result is applied to an A1 profile only because cross_condition_acknowledged=true is sent explicitly.
"""
import argparse
import hashlib
import importlib.util
import json
import time
from pathlib import Path

import httpx

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('measured_workflow', ROOT / 'scripts/measured_workflow.py')
mw = importlib.util.module_from_spec(spec)
spec.loader.exec_module(mw)

DEVICE_TEAM_CONDITIONS = dict(program_voltage_v=10, program_pulse_width_s=0.01, erase_voltage_v=-10, erase_pulse_width_s=0.01, read_voltage_v=0)


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument('--base-url', required=True)
    parser.add_argument('--c2c-file', required=True)
    parser.add_argument('--out', required=True)
    parser.add_argument('--condition', default='A1')
    parser.add_argument('--timeout', type=int, default=1800)
    parser.add_argument('--n-reprogram', type=int, default=3)
    args = parser.parse_args()
    manifest = json.loads((mw.DATA / 'manifest.json').read_text(encoding='utf-8'))['files']
    c2c_path = Path(args.c2c_file)
    c2c_bytes = c2c_path.read_bytes()
    report = dict(c2c_source=dict(filename=c2c_path.name, sha256=hashlib.sha256(c2c_bytes).hexdigest()))
    with httpx.Client(base_url=args.base_url + '/api/v1', timeout=120) as client:
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
                time.sleep(1)
            raise SystemExit('timeout waiting for ' + identifier)

        profile, row = mw._publish_condition(call, wait_job, manifest, args.condition)
        report['profile'] = dict(profile_id=profile['profile_id'], revision=1, condition_id=args.condition, states=row['states'])

        up = call('POST', '/files', files={'files': (c2c_path.name, c2c_bytes)}).json()['files'][0]
        body = dict(kind='c2c_detrended', settings={}, inputs=[dict(
            file_id=up['file_id'], sheet='Origin_data', condition_id='A3', device_id='not provided by device team',
            measurement_conditions=DEVICE_TEAM_CONDITIONS)])
        queued = call('POST', '/analyses', json=body).json()
        wait_job(queued['job_id'])
        analysis = call('GET', '/analyses/' + queued['analysis_id']).json()
        assert up['sha256'] == report['c2c_source']['sha256'] == analysis['provenance']['sha256']
        report['c2c_analysis'] = dict(
            analysis_id=analysis['analysis_id'], analysis_result_sha256=analysis['analysis_result_sha256'], status=analysis['status'],
            program_relative_std_percent=analysis['program']['primary']['relative_residual_std_percent'],
            erase_relative_std_percent=analysis['erase']['primary']['relative_residual_std_percent'],
            program_lag1=analysis['program']['primary']['residual_lag1_correlation'], erase_lag1=analysis['erase']['primary']['residual_lag1_correlation'],
            cycles=analysis['provenance']['cycle_count'], sheet=analysis['provenance']['sheet'],
            conditions_confirmed=[k for k, v in analysis['measurement_conditions'].items() if v['confirmed']],
            conditions_unconfirmed=[k for k, v in analysis['measurement_conditions'].items() if not v['confirmed']],
            artifacts=[a['filename'] for a in analysis['artifacts']], warnings=analysis['warnings'])

        base = json.loads((ROOT / 'packages/contracts/fixtures/experiment-baseline.request.json').read_text())
        base['engines']['accuracy'] = 'torch_reference'
        base.update(pools=['combined'], mappings=['fixed_reference'], arrays=1, years=[0])
        base['effects'].update(d2d=False, retention=False, adc=False, c2c=False)
        base['hardware'].update(tile_size=64, adc_bits=None, adc_order=None, range_policy=None)

        def request(schema_version, c2c, n_reprogram):
            body = json.loads(json.dumps(base))
            body.update(schema_version=schema_version, n_reprogram=n_reprogram, checkpoint_id=checkpoint_id)
            ref = dict(id=profile['profile_id'], revision=1)
            body['effects']['c2c'] = c2c is not None
            if c2c is not None:
                ref['c2c'] = c2c
            body['profile_refs'] = [ref]
            return body

        def run(name, body):
            exp = call('POST', '/experiments', json=body).json()
            wait_job(exp['job_id'])
            result = call('GET', '/experiments/' + exp['experiment_id']).json()
            all_runs = [r for r in result['runs'] if r['kind'] == 'ALL']
            summary = dict(experiment_id=exp['experiment_id'], checkpoint_id=result['checkpoint_id'], status=result['status'],
                           summary=result['summary'], all_accuracies=[r['accuracy'] for r in all_runs],
                           d0=[r['accuracy'] for r in result['runs'] if r['kind'] == 'D0'], m0=[r['accuracy'] for r in result['runs'] if r['kind'] == 'M0'],
                           c2c_candidate=result['effective_config']['candidates'][0].get('c2c'),
                           c2c_diagnostics=[r.get('c2c_diagnostics') for r in all_runs],
                           assumption_ids=[a['id'] for a in result['assumptions']], schema_version=result['schema_version'])
            report.setdefault('experiments', {})[name] = summary
            return result

        checkpoint_id = None
        first = run('off', request('1.2.0', None, 1))
        checkpoint_id = first['checkpoint_id']
        run('off_again_same_checkpoint', request('1.2.0', None, 1))
        run('manual_5pct', request('1.3.0', dict(cv_percent=5, source='manual_assumption'), args.n_reprogram))
        measured = dict(source='measured_detrended', analysis_id=analysis['analysis_id'], approved_assumption=True, cross_condition_acknowledged=True)
        run('measured', request('1.4.0', measured, args.n_reprogram))
        run('measured_repeat', request('1.4.0', measured, args.n_reprogram))
        forged = client.post('/experiments', json=request('1.4.0', dict(measured, cv_percent=0.001), args.n_reprogram))
        report['forged_cv_response'] = dict(status=forged.status_code, code=forged.json().get('error', {}).get('code'))
        unacked = client.post('/experiments', json=request('1.4.0', dict(source='measured_detrended', analysis_id=analysis['analysis_id'], approved_assumption=True), 1))
        report['unacknowledged_cross_condition_response'] = dict(status=unacked.status_code, code=unacked.json().get('error', {}).get('code'))
    Path(args.out).write_text(json.dumps(report, ensure_ascii=False, indent=2, allow_nan=False), encoding='utf-8')
    print(json.dumps({k: v for k, v in report.items() if k != 'experiments'}, ensure_ascii=False, indent=2))
    for name, e in report['experiments'].items():
        print(name, e['status'], e['all_accuracies'], (e['c2c_candidate'] or {}).get('source'))


if __name__ == '__main__':
    main()
