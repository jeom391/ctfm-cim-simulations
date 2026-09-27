"""Measured C2C through the real API + isolated worker, plus explicit IV/Retention layout selections.

All workbooks are synthetic fixtures built here; the numbers are not device measurements."""
import io
import json
from copy import deepcopy
from pathlib import Path

import numpy as np
import pytest
from httpx import ASGITransport, AsyncClient
from openpyxl import Workbook

from ctfm_api.app import create_app
from ctfm_worker.runner import run_once

pytestmark = pytest.mark.anyio
FIXTURE = Path(__file__).resolve().parents[2] / 'packages/contracts/fixtures/experiment-c2c.request.json'
CONDITIONS = dict(program_voltage_v=10, program_pulse_width_s=0.01, erase_voltage_v=-10, erase_pulse_width_s=0.01, read_voltage_v=0)


@pytest.fixture(scope='module')
def anyio_backend():
    return 'asyncio'


def xlsx(rows, title='Sheet', extra=None):
    wb = Workbook()
    ws = wb.active
    ws.title = title
    for row in rows:
        ws.append(row)
    for name, more in (extra or {}).items():
        sheet = wb.create_sheet(name)
        for row in more:
            sheet.append(row)
    buffer = io.BytesIO()
    wb.save(buffer)
    return buffer.getvalue()


def c2c_book(n=200, seed=3, noise=0.004):
    rng = np.random.default_rng(seed)
    cycles = np.arange(1, n + 1)
    x = 2 * (cycles - 1) / (n - 1) - 1
    program = (75 + 3 * x - 2 * x ** 2 + x ** 3) * (1 + noise * rng.standard_normal(n))
    erase = (92 + 2 * x - 1.5 * x ** 2 + .5 * x ** 3) * (1 + noise * rng.standard_normal(n))
    rows = [['Cycle', 'Program_Id_uA', 'Erase_Id_uA', 'Erase_minus_Program_uA']]
    rows += [[int(c), float(p), float(e), float(e - p)] for c, p, e in zip(cycles, program, erase)]
    return xlsx(rows, 'Origin_data')


def iv_book(*amplitudes):
    amplitudes = amplitudes or (6,)

    def sweep(a):
        path = list(range(0, -a - 1, -1)) + list(range(-a + 1, a + 1)) + list(range(a - 1, -a - 1, -1))
        return [(float(v), 1e-6 * (v + 6) + 5e-7, 1e-9) for v in path]
    blocks = [sweep(a) for a in amplitudes]
    rows = [[' Vg', ' Id', ' Ig'] * len(blocks)]
    for i in range(max(len(b) for b in blocks)):
        rows.append([cell for b in blocks for cell in (b[i] if i < len(b) else (None, None, None))])
    return xlsx(rows)


def retention_book():
    times_e = [10.0, 22.0, 47.0, 100.0, 1000.0]
    times_p = [10.4, 31.0, 90.0, 400.0, 999.0]
    rows = [['Erase_-15V_time', 'Erase_-15V_전류', 'Programing_15V_time', 'Programing_15V_전류'], [None] * 4]
    for te, tp in zip(times_e, times_p):
        rows.append([te, 9e-6 - 1e-6 * np.log10(te), tp, 1e-6 + 2e-7 * np.log10(tp)])
    return xlsx(rows, 'Raw Data', {'Normalized Data': [['read_retention_0V(1)_x.csv (Time)', 'x', 'y', 'z']]})


async def upload(client, name, data):
    response = await client.post('/api/v1/files', files={'files': (name, data)})
    assert response.status_code == 201, response.text
    return response.json()['files'][0]['file_id']


def c2c_input(file_id, condition='A1', **extra):
    return dict(file_id=file_id, sheet='Origin_data', device_id='dev-A', condition_id=condition, measurement_conditions=CONDITIONS, **extra)


async def run_analysis(client, store, body):
    response = await client.post('/api/v1/analyses', json=body)
    assert response.status_code == 202, response.text
    assert run_once(store)
    return (await client.get('/api/v1/analyses/' + response.json()['analysis_id'])).json()


async def published_profile(client, store, condition='A1'):
    rows = ['synthetic fixture; not measured', 'time,current,gate']
    for direction, gate, values in (('ltp', -6, (1e-6, 2e-6, 3e-6)),):
        for i, value in enumerate(values):
            t = 6 + i * 5
            rows += [f'{t},{value},0', f'{t + 1},{value},0', f'{t + 2},0,{gate / 6}', f'{t + 3},0,{gate}']
        rows += ['30,0.000001,0', '31,0.000001,0']
    file_id = await upload(client, 'ltp.csv', ('\n'.join(rows) + '\n').encode())
    dataset = dict(file_id=file_id, column_mapping=dict(time_s='time', id_a='current', vgs_v='gate'), units=dict(time_s='s', id_a='A', vgs_v='V'),
                   condition_id=condition, device_id='synthetic-only', direction='ltp', vds_v=.1, read_vgs_v=0)
    result = await run_analysis(client, store, dict(kind='pulse_states', inputs=[dataset], settings={}))
    assert result['status'] == 'succeeded'
    created = await client.post('/api/v1/profiles', json=dict(condition_id=condition, state_analysis_id=result['analysis_id'],
                                                              selected_state_ids=[s['state_id'] for s in result['states']], display_name='SYNTHETIC'))
    assert created.status_code == 201, created.text
    profile_id = created.json()['profile_id']
    published = await client.post(f'/api/v1/profiles/{profile_id}/revisions/1/publish',
                                  json=dict(reviewer='automated', review_note='Synthetic software verification only.'))
    assert published.status_code == 200, published.text
    return profile_id


def experiment(profile_id, c2c, version='1.4.0'):
    body = json.loads(FIXTURE.read_text())
    body.update(schema_version=version, arrays=1, n_reprogram=2)
    body['effects']['d2d'] = False
    body['profile_refs'] = [dict(id=profile_id, revision=1, c2c=c2c)]
    return body


async def test_measured_c2c_analysis_then_server_resolved_experiment(tmp_path):
    app = create_app(tmp_path)
    store = app.state.storage()
    async with AsyncClient(transport=ASGITransport(app=app), base_url='http://test') as client:
        data = c2c_book()
        file_id = await upload(client, 'c2c.xlsx', data)
        stored_hash = store.get_entity('file', file_id)['sha256']

        # ---- boundary: bad inputs never reach the worker
        for bad in (dict(c2c_input(file_id), measurement_conditions=dict(vds_v='nan')),
                    dict(c2c_input(file_id), measurement_conditions=dict(read_time_s=-1)),
                    dict(c2c_input(file_id), measurement_conditions=dict(read_terminal_meaning='')),
                    dict(c2c_input(file_id), column_mapping=dict(a='b')),
                    dict(c2c_input(file_id), row_start=2)):
            response = await client.post('/api/v1/analyses', json=dict(kind='c2c_detrended', inputs=[bad], settings={}))
            assert response.status_code == 422, (bad, response.text)
        two = await client.post('/api/v1/analyses', json=dict(kind='c2c_detrended', inputs=[c2c_input(file_id)] * 2, settings={}))
        assert two.status_code == 422
        leaked = await client.post('/api/v1/analyses', json=dict(kind='iv', inputs=[dict(file_id=file_id, device_id='d', condition_id='A1', column_mapping=dict(vgs_v='a', id_a='b'),
                                                                                       units=dict(vgs_v='V', id_a='A'), branch='erase', sweep_amplitude_v=1, measurement_conditions=CONDITIONS)]))
        assert leaked.status_code == 422

        # ---- analysis
        analysis = await run_analysis(client, store, dict(kind='c2c_detrended', inputs=[c2c_input(file_id)], settings={}))
        assert analysis['status'] == 'succeeded', analysis
        assert analysis['kind'] == 'c2c_detrended' and analysis['condition_id'] == 'A1'
        assert analysis['summaries']['simulator_candidate'] == 'program' and analysis['summaries']['is_pure_c2c_iid_estimate'] is False
        percent = analysis['program']['primary']['relative_residual_std_percent']
        assert 0 < percent < 1 and analysis['erase']['status'] == 'ok'
        assert len(analysis['tables']['cycles']) == 200 and 'series' not in analysis
        assert analysis['provenance']['sheet'] == 'Origin_data' and analysis['provenance']['sha256'] == stored_hash
        assert analysis['measurement_conditions']['vds_v']['confirmed'] is False
        assert analysis['measurement_conditions']['program_voltage_v'] == dict(value=10.0, confirmed=True)
        assert {a['filename'] for a in analysis['artifacts']} >= {'plot.png', 'cycles.csv', 'summary.json', 'tables.xlsx'}
        assert store.get_entity('file', file_id)['sha256'] == stored_hash  # source untouched

        profile_id = await published_profile(client, store, 'A1')
        ref = dict(source='measured_detrended', analysis_id=analysis['analysis_id'], approved_assumption=True)

        # ---- experiment: the server, not the browser, supplies the number
        response = await client.post('/api/v1/experiments', json=experiment(profile_id, dict(ref)))
        assert response.status_code == 202, response.text
        queued = store.get_entity('experiment', response.json()['experiment_id'])['request']['profile_refs'][0]['c2c']
        assert queued['cv_percent'] == percent
        prov = queued['provenance']
        assert prov['analysis_id'] == analysis['analysis_id'] and prov['analysis_result_sha256'] == analysis['analysis_result_sha256']
        assert prov['source_file_sha256'] == stored_hash and prov['cycle_count'] == 200 and prov['cross_condition_acknowledged'] is False
        assert prov['erase_role'] == 'analysis_only' and prov['is_pure_c2c_iid_estimate'] is False and prov['profile_condition_id'] == 'A1'

        # ---- refusals
        forged = await client.post('/api/v1/experiments', json=experiment(profile_id, dict(ref, cv_percent=0.001)))
        assert forged.status_code == 422 and forged.json()['error']['code'] == 'c2c_server_fields'
        forged = await client.post('/api/v1/experiments', json=experiment(profile_id, dict(ref, provenance={})))
        assert forged.json()['error']['code'] == 'c2c_server_fields'
        assert (await client.post('/api/v1/experiments', json=experiment(profile_id, dict(ref, approved_assumption=False)))).status_code == 422
        assert (await client.post('/api/v1/experiments', json=experiment(profile_id, dict(source='measured_detrended', analysis_id=ref['analysis_id'])))).status_code == 422
        assert (await client.post('/api/v1/experiments', json=experiment(profile_id, dict(ref), version='1.3.0'))).status_code == 422
        missing = await client.post('/api/v1/experiments', json=experiment(profile_id, dict(ref, analysis_id='99999999-2222-4333-8444-555555555555')))
        assert missing.status_code == 404
        wrong_kind = await client.post('/api/v1/experiments', json=experiment(profile_id, dict(ref, analysis_id=store.list_entities('analysis')[0]['id'] if False else
                                                                                               next(a['id'] for a in store.list_entities('analysis') if a.get('kind') == 'pulse_states'))))
        assert wrong_kind.status_code == 422 and wrong_kind.json()['error']['code'] == 'c2c_analysis_invalid'

        # ---- manual 1.3.0 keeps its meaning next to measured
        manual = await client.post('/api/v1/experiments', json=experiment(profile_id, dict(cv_percent=5, source='manual_assumption'), version='1.3.0'))
        assert manual.status_code == 202, manual.text
        stored = store.get_entity('experiment', manual.json()['experiment_id'])['request']
        assert stored['schema_version'] == '1.3.0' and stored['profile_refs'][0]['c2c'] == dict(cv_percent=5, source='manual_assumption')

        # ---- tamper check: a changed stored result no longer matches its pin
        entity = store.get_entity('analysis', analysis['analysis_id'])
        entity['program']['primary']['relative_residual_std_percent'] = 4.0
        store.put_entity('analysis', analysis['analysis_id'], entity, replace=True)
        tampered = await client.post('/api/v1/experiments', json=experiment(profile_id, dict(ref)))
        assert tampered.status_code == 422 and tampered.json()['error']['code'] == 'c2c_analysis_tampered'


async def test_cross_condition_use_needs_explicit_acknowledgement_and_is_recorded(tmp_path):
    app = create_app(tmp_path)
    store = app.state.storage()
    async with AsyncClient(transport=ASGITransport(app=app), base_url='http://test') as client:
        file_id = await upload(client, 'c2c.xlsx', c2c_book(80))
        analysis = await run_analysis(client, store, dict(kind='c2c_detrended', inputs=[c2c_input(file_id, condition='A3')], settings={}))
        profile_id = await published_profile(client, store, 'A1')
        ref = dict(source='measured_detrended', analysis_id=analysis['analysis_id'], approved_assumption=True)
        refused = await client.post('/api/v1/experiments', json=experiment(profile_id, dict(ref)))
        assert refused.status_code == 422 and refused.json()['error']['code'] == 'c2c_condition_mismatch'
        assert refused.json()['error']['details'] == dict(analysis_condition_id='A3', profile_condition_id='A1')
        accepted = await client.post('/api/v1/experiments', json=experiment(profile_id, dict(ref, cross_condition_acknowledged=True)))
        assert accepted.status_code == 202, accepted.text
        prov = store.get_entity('experiment', accepted.json()['experiment_id'])['request']['profile_refs'][0]['c2c']['provenance']
        assert prov['cross_condition_acknowledged'] is True and prov['condition_id'] == 'A3' and prov['profile_condition_id'] == 'A1'


async def test_invalid_c2c_workbook_fails_the_job_with_a_readable_reason(tmp_path):
    app = create_app(tmp_path)
    store = app.state.storage()
    async with AsyncClient(transport=ASGITransport(app=app), base_url='http://test') as client:
        rows = [['Cycle', 'Program_Id_uA', 'Erase_Id_uA']] + [[n, 70 + n / 10, 90 + n / 9] for n in range(1, 31)]
        rows[10][1] = None
        file_id = await upload(client, 'gap.xlsx', xlsx(rows, 'Origin_data'))
        analysis = await run_analysis(client, store, dict(kind='c2c_detrended', inputs=[c2c_input(file_id)], settings={}))
        assert analysis['status'] == 'failed' and 'missing_value' in analysis['error']['message']


async def test_iv_block_and_retention_column_selections_run_through_the_worker(tmp_path):
    app = create_app(tmp_path)
    store = app.state.storage()
    async with AsyncClient(transport=ASGITransport(app=app), base_url='http://test') as client:
        iv_id = await upload(client, 'iv.xlsx', iv_book(6))
        base = dict(file_id=iv_id, sheet='Sheet', units=dict(vgs_v='V', id_a='A'), device_id='dev-1', condition_id='A3', sweep_amplitude_v=6, vds_v=0.1)
        erase = dict(base, branch='erase', selection=dict(type='iv_block', block=0, segment=1))
        program = dict(base, branch='program', selection=dict(type='iv_block', block=0, segment=2))
        result = await run_analysis(client, store, dict(kind='iv', inputs=[erase, program], settings={}))
        assert result['status'] == 'succeeded', result
        vth = {r['branch']: r['vth_v'] for r in result['tables']['vth']}
        assert vth['erase'] == pytest.approx(-5.5) and vth['program'] == pytest.approx(-5.5)
        assert result['provenance'][0]['block'] == dict(index=0, segment=1, columns=[0, 1, 2])

        # boundary refusals: nothing is inferred
        for bad in (dict(erase, column_mapping=dict(vgs_v='Vg', id_a='Id')), dict(erase, row_start=2), dict(erase, sheet=None),
                    dict(erase, units=dict(vgs_v='V')), dict(erase, selection=dict(type='retention_columns', columns={})),
                    dict(erase, selection=dict(type='iv_block', block=-1, segment=0))):
            bad = {k: v for k, v in bad.items() if v is not None}
            assert (await client.post('/api/v1/analyses', json=dict(kind='iv', inputs=[bad], settings={}))).status_code == 422
        wrong = await run_analysis(client, store, dict(kind='iv', inputs=[dict(erase, selection=dict(type='iv_block', block=0, segment=0))], settings={}))
        assert wrong['status'] == 'failed' and 'needs a increasing segment' in wrong['error']['message']

        ret_id = await upload(client, 'ret.xlsx', retention_book())
        columns = dict(erase_time_s=0, erase_id_a=1, program_time_s=2, program_id_a=3)
        units = dict(erase_time_s='s', erase_id_a='A', program_time_s='s', program_id_a='A')
        item = dict(file_id=ret_id, sheet='Raw Data', device_id='ret-1', condition_id='A1', source_label='R1', read_vgs_v=0, vds_v=0.1, units=units,
                    selection=dict(type='retention_columns', columns=columns))
        retention = await run_analysis(client, store, dict(kind='retention', inputs=[item], settings={}))
        assert retention['status'] == 'succeeded', retention
        assert retention['retention']['time_axes'] == 'per_direction'
        assert retention['retention']['erase_fit']['b'] == pytest.approx(-1e-6, rel=1e-6)
        assert retention['retention']['program_fit']['b'] == pytest.approx(2e-7, rel=1e-6)
        assert retention['provenance'][0]['selected_columns']['program_time_s']['index'] == 2
        for bad in (dict(item, selection=dict(type='retention_columns', columns=dict(columns, program_id_a=0))), dict(item, sheet=None),
                    dict(item, source_label=None), dict(item, units=dict(units, erase_time_s='h'))):
            bad = {k: v for k, v in bad.items() if v is not None}
            assert (await client.post('/api/v1/analyses', json=dict(kind='retention', inputs=[bad], settings={}))).status_code == 422
        wrong_label = await run_analysis(client, store, dict(kind='retention', inputs=[dict(item, condition_id='A3', source_label='R3(2)', read_vgs_v=0.5)], settings={}))
        assert wrong_label['status'] == 'failed' and 'R3(1)' in wrong_label['error']['message']


async def test_layout_endpoint_lists_blocks_and_columns_without_selecting(tmp_path):
    app = create_app(tmp_path)
    async with AsyncClient(transport=ASGITransport(app=app), base_url='http://test') as client:
        iv_id = await upload(client, 'iv.xlsx', iv_book(6, 7))
        preview = await client.get(f'/api/v1/files/{iv_id}/preview')
        assert preview.status_code == 422  # repeated headers stay refused by the name-based preview
        layout = (await client.get(f'/api/v1/files/{iv_id}/layout', params=dict(kind='iv'))).json()
        assert layout['block_count'] == 2 and layout['sheet'] == 'Sheet' and layout['file_id'] == iv_id
        segments = layout['blocks'][0]['segments']
        assert [s['direction'] for s in segments] == ['decreasing', 'increasing', 'decreasing']
        assert layout['blocks'][0]['proposed_amplitude_v'] == 6 and 'selected' not in layout
        ret_id = await upload(client, 'ret.xlsx', retention_book())
        ret = (await client.get(f'/api/v1/files/{ret_id}/layout', params=dict(kind='retention'))).json()
        assert [c['index'] for c in ret['columns']] == [0, 1, 2, 3] and ret['sheet'] == 'Raw Data'
        assert ret['embedded_source_headers'][0]['sheet'] == 'Normalized Data'
        assert (await client.get(f'/api/v1/files/{iv_id}/layout', params=dict(kind='bogus'))).status_code == 422
        assert (await client.get(f'/api/v1/files/{ret_id}/layout', params=dict(kind='retention', sheet='nope'))).status_code == 422
