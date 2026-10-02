"""Handoff 06 API scope: D2D pair matching, >5 profile cards, C2C basis on save, download roles."""
import json
from pathlib import Path
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from ctfm_api.app import create_app
from ctfm_api.storage import Store
from ctfm_worker.runner import run_once

ROOT = Path(__file__).resolve().parents[3]
FILES = ROOT / 'data/team-snapshot/2026-10-02/files'


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setenv('CTFM_STORAGE_ROOT', str(tmp_path))
    with TestClient(create_app(tmp_path)) as client:
        yield client


def upload(client, paths):
    response = client.post('/api/v1/files', files=[('files', (p.name, p.read_bytes())) for p in paths])
    assert response.status_code == 201, response.text
    return response.json()['files']


def test_d2d_pair_matches_every_condition_and_records_the_a5_duplicate_amplitude(client):
    files = upload(client, sorted((FILES / 'D2D/A5').glob('*.xlsx')))
    devices = [dict(file_id=f['file_id'], device_id=f'A5 소자 {n}', identity_evidence='소자팀 지정 D2D 파일 쌍') for n, f in enumerate(files, 1)]
    plan = client.post('/api/v1/measurements/resolve-d2d-pair', json=dict(condition_id='A5', devices=devices))
    assert plan.status_code == 200, plan.text
    request = plan.json()['requests'][0]
    keys = {(i['sweep_amplitude_v'], i['branch']) for i in request['inputs']}
    assert len(keys) == 28 and (11.0, 'erase') not in keys and (11.0, 'program') not in keys
    assert len(request['inputs']) == 56
    # the program branch is the full +A -> -A sweep (segment 2), never the initial 0 -> -A half sweep
    assert {i['selection']['segment'] for i in request['inputs'] if i['branch'] == 'program'} == {2}
    issues = [i['detail'] for s in plan.json()['sources'] for i in s['issues'] if i['code'] == 'd2d_condition_excluded']
    assert any('11 V 블록이 2개' in d for d in issues)
    same = client.post('/api/v1/measurements/resolve-d2d-pair', json=dict(condition_id='A5', devices=[devices[0], devices[0]]))
    assert same.status_code == 422


def test_sweep_c2c_is_recognized_and_only_user_results_are_downloads(client, tmp_path):
    files = upload(client, [FILES / 'C2C/A2_C2C_50Cycles.xlsx'])
    plan = client.post('/api/v1/measurements/recognize', json={'file_ids': [files[0]['file_id']]}).json()
    assert plan['sources'][0]['kind'] == 'c2c_sweep' and plan['sources'][0]['status'] == 'ready'
    queued = client.post('/api/v1/analyses', json=plan['requests'][0])
    assert queued.status_code == 202, queued.text
    assert run_once(Store(tmp_path))
    analysis = client.get(f"/api/v1/analyses/{queued.json()['analysis_id']}").json()
    assert analysis['status'] == 'succeeded', analysis.get('error')
    roles = {a['filename']: a['role'] for a in analysis['artifacts']}
    assert sorted(n for n, r in roles.items() if r == 'user') == ['A2_C2C_결과.csv', 'A2_C2C_그래프.png']
    assert roles['summary.json'] == 'internal' and roles['tables.xlsx'] == 'internal'
    user_csv = next(a for a in analysis['artifacts'] if a['filename'] == 'A2_C2C_결과.csv')
    body = client.get(user_csv['download_url']).content.decode('utf-8-sig')
    assert '전체 변동 CV (%)' in body and '추세 제거 후 상대 잔차 표준편차 (%)' in body and 'B202:AY202' in body


def _common():
    return dict(schema_version='1.4.0', model_id='mnist_mlp_v1', checkpoint_id=None, pools=['combined'], mappings=['fixed_reference'],
                effects=dict(adc=True, d2d=False, c2c=True, retention=False), arrays=1, n_reprogram=1, years=[0], seed=20260917,
                hardware=dict(tile_size=64, adc_bits=5, adc_order='adc_then_subtract', range_policy='validation_max_abs', preset_id=None),
                engines=dict(accuracy='torch_reference', ppa='off'))


def test_six_profile_cards_run_as_one_job_and_c2c_basis_is_saved(client, tmp_path):
    pairs = [sorted((FILES / f'LTD,LTP/{c}').glob('*.csv')) for c in ('A1', 'A2', 'A3', 'A4', 'A5', 'A1')]
    cards = []
    for n, (ltd, ltp) in enumerate(pairs, 1):
        r = client.post('/api/v1/profiles/quick', data={'display_name': f'card {n}'},
                        files={'ltp_file': (ltp.name, ltp.read_bytes()), 'ltd_file': (ltd.name, ltd.read_bytes())})
        assert r.status_code == 201, r.text
        p = r.json()
        cards.append(dict(card_id=str(uuid4()), display_name=f'card {n}', profile_ref=dict(id=p['profile_id'], revision=p['revision']),
                          manual_c2c_cv_percent=2.9179))
    draft = client.post('/api/v1/comparisons', json=dict(common_settings=_common(), cards=cards))
    assert draft.status_code == 201, draft.text
    ran = client.post(f"/api/v1/comparisons/{draft.json()['comparison_id']}/run", json=dict(expected_version=1))
    assert ran.status_code == 200, ran.text
    record = ran.json()
    assert record['lifecycle'] == 'running' and all(c['status'] == 'queued' for c in record['cards'])
    experiment = client.get(f"/api/v1/experiments/{record['experiment_id']}").json()
    refs = experiment['request']['profile_refs']
    assert len(refs) == 6 and all(r['c2c'] == dict(source='manual_assumption', cv_percent=2.9179) for r in refs)
    assert client.get('/api/v1/capabilities').json()['limits']['max_profiles'] >= 6
    # cancel instead of training; a terminal temporary result can then be saved with its C2C basis
    store = Store(tmp_path)
    store.cancel(record['job_id'])
    assert store.get_job(record['job_id'])['state'] == 'cancelled'
    ident = record['comparison_id']
    assert client.get(f'/api/v1/comparisons/{ident}').json()['lifecycle'] == 'temporary'
    bad = client.post(f'/api/v1/comparisons/{ident}/save', json=dict(name='x', c2c_basis='nonsense'))
    assert bad.status_code == 422
    saved = client.post(f'/api/v1/comparisons/{ident}/save', json=dict(name='A 전체 비교 · 추세 제거 후 변동', c2c_basis='detrended'))
    assert saved.status_code == 200, saved.text
    assert saved.json()['c2c_basis'] == 'detrended' and saved.json()['lifecycle'] == 'saved'
    listed = client.get('/api/v1/comparisons?scope=saved').json()['items']
    assert [r['c2c_basis'] for r in listed] == ['detrended']
