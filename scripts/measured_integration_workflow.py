"""Same-condition real-file integration over HTTP: LTP/LTD + Retention (+ D2D) -> profile -> one checkpoint -> inference.

    python scripts/measured_integration_workflow.py --base-url http://127.0.0.1:8100 --root "<관련 자료>" --out r.json [--condition A3]

Every data match is explicit: the Retention workbook and its label follow the approved A<n> <-> R<n> table, the two IV
files used for D2D are a DEVELOPMENT-VERIFICATION pair (chosen only to exercise the feature; not a research selection),
and the C2C analysis is the A3 workbook applied to the A3 profile (same condition, no cross-condition flag).
Retention beyond the measured interval (10-1000 s) is extrapolation and is reported as such.
"""
import argparse
import hashlib
import importlib.util
import json
import re
import time
from pathlib import Path

import httpx

REPO = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('measured_workflow', REPO / 'scripts/measured_workflow.py')
mw = importlib.util.module_from_spec(spec)
spec.loader.exec_module(mw)

RETENTION_LABEL = {'A1': ('R1', 0.0), 'A2': ('R2', 0.0), 'A3': ('R3(1)', 0.5), 'A4': ('R4(1)', 0.1), 'A5': ('R5(1)', 0.5)}
C2C_CONDITIONS = dict(program_voltage_v=10, program_pulse_width_s=0.01, erase_voltage_v=-10, erase_pulse_width_s=0.01, read_voltage_v=0)


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument('--base-url', required=True)
    parser.add_argument('--root', required=True)
    parser.add_argument('--out', required=True)
    parser.add_argument('--condition', default='A3')
    parser.add_argument('--d2d-files', default='227,228', help='development-verification IV file numbers (not a research selection)')
    parser.add_argument('--timeout', type=int, default=3600)
    args = parser.parse_args()
    root, cond = Path(args.root), args.condition
    manifest = json.loads((mw.DATA / 'manifest.json').read_text(encoding='utf-8'))['files']
    report = dict(condition=cond, note='d2d pair is development verification only; retention beyond 1000 s is extrapolation')
    with httpx.Client(base_url=args.base_url + '/api/v1', timeout=180) as client:
        def call(method, path, **kw):
            r = client.request(method, path, **kw)
            if r.status_code >= 400:
                raise SystemExit(f'{method} {path} -> {r.status_code}: {r.text[:1500]}')
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

        def upload(path):
            data = Path(path).read_bytes()
            saved = call('POST', '/files', files={'files': (Path(path).name, data)}).json()['files'][0]
            assert saved['sha256'] == hashlib.sha256(data).hexdigest()
            return saved

        def analyze(body):
            queued = call('POST', '/analyses', json=body).json()
            wait_job(queued['job_id'])
            result = call('GET', '/analyses/' + queued['analysis_id']).json()
            assert result['status'] == 'succeeded', result
            return result

        # --- state analysis (explicit LTP/LTD pair from the shared, hash-pinned CSVs)
        inputs = []
        for entry in manifest:
            if entry['condition_id'] != cond:
                continue
            saved = upload(mw.DATA / entry['file'])
            inputs.append(dict(file_id=saved['file_id'], column_mapping=entry['column_mapping'], units=entry['units'],
                               device_id=cond + '-pulse', condition_id=cond, direction=entry['direction'], vds_v=0.1, read_vgs_v=0))
        states = analyze(dict(kind='pulse_states', inputs=inputs, settings={}))
        report['state_analysis'] = dict(id=states['analysis_id'], candidates=len(states['states']), pools={k: v.get('available') for k, v in states['summaries']['pools'].items()})

        # --- Retention: explicit columns + approved source label
        label, read_vgs = RETENTION_LABEL[cond]
        ret_path = next((root / 'Retention').glob(f'_26CMFM_{cond}_Retention.xlsx'))
        ret_file = upload(ret_path)
        units = dict(erase_time_s='s', erase_id_a='A', program_time_s='s', program_id_a='A')
        retention = analyze(dict(kind='retention', settings={}, inputs=[dict(
            file_id=ret_file['file_id'], sheet='Raw Data', device_id=cond + '-retention', condition_id=cond, source_label=label,
            read_vgs_v=read_vgs, vds_v=0.1, units=units,
            selection=dict(type='retention_columns', columns=dict(erase_time_s=0, erase_id_a=1, program_time_s=2, program_id_a=3)))]))
        r = retention['retention']
        report['retention_analysis'] = dict(id=retention['analysis_id'], source_label=r['source_label'], read_vgs_v=r['read_vgs_v'], time_axes=r['time_axes'],
                                            program_fit=r['program_fit'], erase_fit=r['erase_fit'], exclusions=len(retention['exclusions']),
                                            warnings=retention['warnings'], file=ret_path.name, sha256=ret_file['sha256'])

        # --- D2D: two user-supplied devices (development pair), explicit block/segment
        d2d_inputs = []
        for number in args.d2d_files.split(','):
            path = next((root / 'IV Sweep' / cond).glob(f'*sweep_{number}_15V*.xlsx'))
            saved = upload(path)
            layout = call('GET', f"/files/{saved['file_id']}/layout", params=dict(kind='iv')).json()
            block = next(b for b in layout['blocks'] if b['status'] == 'ok' and b['proposed_amplitude_v'] == 15)
            width = lambda s: abs(s['vg_end'] - s['vg_start'])
            up = max((s for s in block['segments'] if s['direction'] == 'increasing'), key=lambda s: (width(s), s['index']))
            down = max((s for s in block['segments'] if s['direction'] == 'decreasing'), key=lambda s: (width(s), s['index']))
            for branch, seg in (('erase', up), ('program', down)):
                d2d_inputs.append(dict(file_id=saved['file_id'], sheet=layout['sheet'], device_id=f'{cond}-dev{number}', condition_id=cond, branch=branch,
                                       sweep_amplitude_v=15, vds_v=0.1, units=dict(vgs_v='V', id_a='A'),
                                       selection=dict(type='iv_block', block=block['index'], segment=seg['index'])))
        d2d = analyze(dict(kind='d2d', inputs=d2d_inputs, settings={}))
        report['d2d_analysis'] = dict(id=d2d['analysis_id'], status=d2d['d2d']['status'], cv=d2d['d2d']['cv'], matched_conditions=d2d['d2d']['matched_conditions'],
                                      physical_device_count=d2d['d2d']['physical_device_count'], devices=sorted({i['device_id'] for i in d2d_inputs}),
                                      warnings=d2d['warnings'], note='development-verification pair')

        # --- profile: create with explicit links, publish
        profile = call('POST', '/profiles', json=dict(condition_id=cond, state_analysis_id=states['analysis_id'],
                                                      selected_state_ids=[s['state_id'] for s in states['states']],
                                                      d2d_analysis_id=d2d['analysis_id'], retention_analysis_id=retention['analysis_id'],
                                                      display_name=f'{cond} measured + retention + d2d (integration verification)')).json()
        endpoint = f"/profiles/{profile['profile_id']}/revisions/1"
        published = call('POST', endpoint + '/publish', json=dict(reviewer='integration verification (10)', review_note='Development verification of the analysis->profile->inference path; d2d pair is not a research selection.')).json()
        export = call('GET', endpoint + '/export')
        report['profile'] = dict(profile_id=profile['profile_id'], revision=1, status=published['status'], profile_hash=published['profile_hash'],
                                 retention_link=dict(analysis_id=published['retention']['analysis_id'], status=published['retention']['status'], source_label=published['retention']['source_label']),
                                 d2d_link=dict(analysis_id=published['d2d']['analysis_id'], status=published['d2d']['status'], cv=published['d2d']['cv']),
                                 export_bytes=len(export.content), export_sha256=hashlib.sha256(export.content).hexdigest())

        # --- C2C: the same-condition measured analysis (A3 workbook -> A3 profile)
        c2c_analysis = None
        c2c_path = root / 'C2C' / '_26CTFM_A3_1000Cycle_.xlsx'
        if cond == 'A3' and c2c_path.is_file():
            c2c_file = upload(c2c_path)
            c2c_analysis = analyze(dict(kind='c2c_detrended', settings={}, inputs=[dict(
                file_id=c2c_file['file_id'], sheet='Origin_data', device_id='not provided by device team', condition_id='A3', measurement_conditions=C2C_CONDITIONS)]))
            report['c2c_analysis'] = dict(id=c2c_analysis['analysis_id'], program_percent=c2c_analysis['program']['primary']['relative_residual_std_percent'])

        base = json.loads((REPO / 'packages/contracts/fixtures/experiment-baseline.request.json').read_text())
        base.update(pools=['combined'], mappings=['fixed_reference'], arrays=1, years=[0], n_reprogram=1, schema_version='1.2.0')
        base['effects'].update(d2d=False, retention=False, adc=False, c2c=False)
        base['hardware'].update(tile_size=64, adc_bits=None, adc_order=None, range_policy=None)
        checkpoint_id = None

        def request(*, d2d=False, retention=False, years=(0,), arrays=1, c2c=None, n_reprogram=1):
            body = json.loads(json.dumps(base))
            body['effects'].update(d2d=d2d, retention=retention, c2c=c2c is not None)
            body.update(arrays=arrays, years=list(years), n_reprogram=n_reprogram, checkpoint_id=checkpoint_id,
                        schema_version='1.4.0' if (c2c and c2c['source'] == 'measured_detrended') else '1.3.0' if c2c else '1.2.0')
            ref = dict(id=profile['profile_id'], revision=1)
            if c2c:
                ref['c2c'] = c2c
            body['profile_refs'] = [ref]
            return body

        def run(name, body):
            nonlocal checkpoint_id
            exp = call('POST', '/experiments', json=body).json()
            wait_job(exp['job_id'])
            result = call('GET', '/experiments/' + exp['experiment_id']).json()
            checkpoint_id = checkpoint_id or result['checkpoint_id']
            all_runs = [x for x in result['runs'] if x['kind'] == 'ALL']
            downloads = {}
            for artifact in result['artifacts']:
                if artifact['filename'] in ('runs.csv', 'summary.json', 'tables.xlsx', 'plot.png'):
                    payload = call('GET', artifact['download_url'].replace('/api/v1', '')).content
                    downloads[artifact['filename']] = dict(bytes=len(payload), sha256=hashlib.sha256(payload).hexdigest())
            report.setdefault('experiments', {})[name] = dict(
                experiment_id=exp['experiment_id'], status=result['status'], checkpoint_id=result['checkpoint_id'], summary={k: result['summary'][k] for k in ('requested', 'completed', 'failed', 'skipped')},
                runs=[dict(years=x.get('years'), array=x.get('array_index'), reprogram=x.get('reprogram_index'), accuracy=x['accuracy'], retention_loss_pp=x.get('retention_loss_pp'),
                           retention_extrapolated=x.get('retention', {}).get('extrapolated') if isinstance(x.get('retention'), dict) else x.get('retention_extrapolated'),
                           retention=x.get('retention')) for x in all_runs],
                d0=[x['accuracy'] for x in result['runs'] if x['kind'] == 'D0'], warnings=[str(w)[:200] for w in (result.get('warnings') or [])],
                assumptions=[a['id'] for a in result['assumptions']], profile_provenance=result['effective_config']['candidates'][0].get('provenance') if result['effective_config']['candidates'] else None,
                c2c=result['effective_config']['candidates'][0].get('c2c'), downloads=downloads)
            return result

        run('baseline_effects_off', request())
        run('retention_years_0_1_10', request(retention=True, years=(0, 1, 10)))
        run('d2d_3_arrays', request(d2d=True, arrays=3))
        if c2c_analysis:
            run('retention_d2d_measured_c2c_same_condition', request(retention=True, years=(0, 1), d2d=True, arrays=2, n_reprogram=2, c2c=dict(
                source='measured_detrended', analysis_id=c2c_analysis['analysis_id'], approved_assumption=True)))
    Path(args.out).write_text(json.dumps(report, ensure_ascii=False, indent=2, allow_nan=False, default=str), encoding='utf-8')
    for name, e in report['experiments'].items():
        print(name, e['status'], e['summary'], [(x['years'], x['array'], x['reprogram'], x['accuracy']) for x in e['runs']])


if __name__ == '__main__':
    main()
