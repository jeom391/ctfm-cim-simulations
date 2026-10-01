"""Recognition must not invent units/groups, lose rows, or trust client provenance."""
import copy
import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from ctfm_api.app import create_app
from ctfm.measurement import analyze, parse_table

ROOT = Path(__file__).resolve().parents[3]
SNAPSHOT = ROOT / 'data/team-snapshot/2026-09-29'

@pytest.fixture
def client(tmp_path):
    with TestClient(create_app(tmp_path)) as client:
        yield client

def upload(client, paths):
    response = client.post('/api/v1/files', files=[('files', (p.name, p.read_bytes())) for p in paths])
    assert response.status_code == 201, response.text
    return response.json()['files']

def recognize(client, files, **extra):
    response = client.post('/api/v1/measurements/recognize', json={'file_ids': [f['file_id'] for f in files], **extra})
    assert response.status_code == 200, response.text
    return response.json()

def pulse_paths():
    return sorted(SNAPSHOT.glob('files/**/*.csv'))

def test_ten_snapshot_pulses_are_five_order_independent_executable_pairs(client):
    paths = pulse_paths()
    assert len(paths) == 10
    files = upload(client, paths)
    plan = recognize(client, files)
    reverse = recognize(client, files[::-1])
    assert len(plan['requests']) == 5
    assert [p['pair_key'] for p in plan['pulse_pairs']] == [p['pair_key'] for p in reverse['pulse_pairs']]
    assert all(s['status'] == 'ready' for s in plan['sources'])
    for source in plan['sources']:
        assert source['pulse']['write_onset_time_s'] == pytest.approx(6.00005)
        assert source['pulse']['preceding_read_time_s'] == pytest.approx(5.99985)
        assert source['pulse']['preceding_read_source_row'] in (1001, 1002)
        assert source['physical_identity'] == 'unverified'
        assert any(e['scope'] == 'project_assumption' and e['field'] == 'units' for e in source['evidence'])
    by_id = {f['file_id']: p for f,p in zip(files, paths)}
    for request in plan['requests']:
        datasets = []
        for item in request['inputs']:
            path = by_id[item['file_id']]
            table = parse_table(path.read_bytes(), path.name)
            record = next(f for f in files if f['file_id'] == item['file_id'])
            datasets.append(dict(item, filename=path.name, sha256=record['sha256'], rows=table['rows'], source_rows=table['source_rows']))
        result = analyze(request['kind'], datasets, request['settings'])
        assert result['summaries']['positive_candidate_count'] == 1020
        assert len(result['tables']['raw']) == 24000
        assert [e['reason'] for e in result['exclusions']].count('before_start_time') == 2
        response = client.post('/api/v1/analyses', json=request)
        assert response.status_code == 202, response.text

def test_missing_duplicate_and_forged_recognition_are_not_enqueued(client):
    paths = pulse_paths()
    pair = [p for p in paths if 'A1' in str(p)]
    files = upload(client, pair)
    assert not recognize(client, files[:1])['requests']
    duplicate = upload(client, pair[:1])
    plan = recognize(client, files + duplicate)
    assert not plan['requests']
    assert any(i['code'] == 'duplicate_source' for s in plan['sources'] for i in s['issues'])
    request = recognize(client, files)['requests'][0]
    forged = copy.deepcopy(request)
    forged['inputs'][0]['units']['id_a'] = 'uA'
    assert client.post('/api/v1/analyses', json=forged).status_code == 422
    store = client.app.state.storage()
    record = store.get_entity('file', files[0]['file_id'])
    store.managed_path(record['relative_path']).write_bytes(b'changed')
    assert client.post('/api/v1/analyses', json=request).status_code == 422

def test_unknown_units_and_group_require_explicit_resolution_and_one_second_onset(client):
    files=[]
    for direction, sign in [('LTP', -1), ('LTD', 1)]:
        data = 'time,current,gate\n0.8,0.000001,0\n0.9,0.000001,0\n1.0,0.000001,%s\n1.1,0.000001,%s\n1.2,0.000002,0\n1.3,0.000002,0\n1.4,0.000002,%s\n1.5,0.000002,%s\n1.6,0.000003,0\n' % (sign*10, sign*10, sign*10, sign*10)
        response=client.post('/api/v1/files', files={'files': (f'A1_{direction}.csv', data.encode())})
        files.extend(response.json()['files'])
    plan=recognize(client, files)
    assert not plan['requests']
    resolutions=[dict(file_id=f['file_id'], kind='pulse_states', column_mapping={'time_s':'time','id_a':'current','vgs_v':'gate'}, units={'time_s':'s','id_a':'A','vgs_v':'V'}, measurement_group='session-1', reason='Operator confirms channel units and same acquisition group') for f in files]
    resolved=recognize(client, files, resolutions=resolutions)
    assert len(resolved['requests']) == 1
    assert resolved['requests'][0]['settings']['start_time_s'] == 1.0
    assert resolved['sources'][0]['pulse']['preceding_read_time_s'] == .8
    assert client.post('/api/v1/analyses', json=resolved['requests'][0]).status_code == 202

def test_iv_inventory_and_retention_source_biases_are_not_first_block_fallback(client):
    iv=next(SNAPSHOT.glob('files/IV Sweep/A3/*229*.xlsx'))
    files=upload(client, [iv])
    plan=recognize(client, files)
    source=plan['sources'][0]
    assert source['layout']['block_count'] >= 14
    assert source['layout']['blocks'][0]['status'] == 'invalid'
    selected={(i['selection']['block'],i['selection']['segment']) for r in plan['requests'] for i in r['inputs']}
    eligible={(b['index'],s['index']) for b in source['layout']['blocks'] if b['status']=='ok' for s in b['segments'] if s['points']>=2}
    assert selected == eligible
    paths=sorted(SNAPSHOT.glob('files/Retention/**/*.xlsx'))
    assert len(paths)==5
    plan=recognize(client, upload(client,paths))
    assert len(plan['requests'])==5
    assert {r['inputs'][0]['condition_id']:r['inputs'][0]['read_vgs_v'] for r in plan['requests']} == {'A1':0.,'A2':0.,'A3':.5,'A4':.1,'A5':.5}
    assert all(r['inputs'][0]['sheet']=='Raw Data' for r in plan['requests'])

def test_c2c_reports_bad_rows_without_confirming_conditions(client):
    plan=recognize(client, upload(client,sorted(SNAPSHOT.glob('files/C2C/*.xlsx'))))
    by_condition={s['condition_id']:s for s in plan['sources']}
    assert [by_condition[c]['status'] for c in ('A1','A3','A5')] == ['ready']*3
    for c in ('A2','A4'):
        assert by_condition[c]['status']=='invalid'
        assert any(i.get('source_row') for i in by_condition[c]['issues'])
    assert len(plan['requests'])==3
    assert all(r['inputs'][0].get('measurement_conditions') is None for r in plan['requests'])
    assert all(s['simulation_eligible'] is False for s in plan['sources'])

def test_renamed_snapshot_uses_hash_direction_and_conflicting_name_stays_unresolved(client):
    path=next(p for p in pulse_paths() if p.name=='A1_LTP.csv')
    files=[]
    for name in ('renamed.csv','A2_LTP.csv'):
        files.extend(client.post('/api/v1/files', files={'files': (name,path.read_bytes())}).json()['files'])
    good=recognize(client, files[:1])['sources'][0]
    assert good['direction']=='ltp'
    assert good['pulse']['row_count']==12000
    bad=recognize(client, files[1:])['sources'][0]
    assert bad['status']!='ready'
    assert any(i['code']=='conflicting_condition' for i in bad['issues'])
    resolved=recognize(client,files[1:],resolutions=[dict(file_id=files[1]['file_id'],condition_id='A1',reason='Resolve renamed filename using the original snapshot condition')])['sources'][0]
    assert resolved['condition_id']=='A1'
    assert not any(i['code']=='conflicting_condition' for i in resolved['issues'])


def test_d2d_resolution_requires_distinct_physical_sources_and_keeps_identity_evidence(client):
    paths=sorted(SNAPSHOT.glob('files/D2D/A1/*.xlsx'))[:2]
    files=upload(client,paths)
    plan=recognize(client, files)
    assert all(r['kind']=='iv' for r in plan['requests'])
    selections=[]
    for n,file in enumerate(files):
        source=next(s for s in plan['sources'] if s['file_id']==file['file_id'])
        block=next(b for b in source['layout']['blocks'] if b['status']=='ok' and b['proposed_amplitude_v']==15)
        segment=next(s for s in block['segments'] if s['direction']=='decreasing')
        selections.append(dict(file_id=file['file_id'], device_id=f'confirmed-device-{n}', identity_evidence=f'Operator confirms wafer die {n}', block=block['index'], segment=segment['index'], units={'vgs_v':'V','id_a':'A'}))
    response=client.post('/api/v1/measurements/resolve-d2d', json={'condition_id':'A1','selections':selections})
    assert response.status_code==200, response.text
    request=response.json()['requests'][0]
    assert request['kind']=='d2d'
    assert client.post('/api/v1/analyses', json=request).status_code==202
    duplicate=copy.deepcopy(selections)
    duplicate[1]['file_id']=duplicate[0]['file_id']
    assert client.post('/api/v1/measurements/resolve-d2d', json={'condition_id':'A1','selections':duplicate}).status_code==422
    forged=copy.deepcopy(request)
    forged.pop('recognition_id')
    forged['inputs'][0]['device_id']='measurement-source:unverified'
    assert client.post('/api/v1/analyses', json=forged).status_code==422


def test_bad_unit_resolution_is_per_source_and_does_not_hide_valid_sources(client):
    paths=[next(p for p in pulse_paths() if p.name=='A1_LTP.csv'), *sorted(SNAPSHOT.glob('files/Retention/**/*.xlsx'))[:1]]
    files=upload(client,paths)
    plan=recognize(client,files,resolutions=[dict(file_id=files[0]['file_id'],units={'time_s':'s','id_a':'bananas','vgs_v':'V'},reason='Incorrect unit must remain an issue')])
    assert len(plan['requests'])==1
    assert plan['requests'][0]['kind']=='retention'
    assert next(s for s in plan['sources'] if s['file_id']==files[0]['file_id'])['status']=='invalid'

def test_uncertain_source_exposes_columns_and_polarity_conflict_is_not_ready(client):
    path=next(p for p in pulse_paths() if p.name=='A1_LTP.csv')
    data=path.read_bytes().replace(b'A1_LTP',b'unknown')
    files=client.post('/api/v1/files', files={'files':('unknown.csv',data)}).json()['files']
    source=recognize(client,files)['sources'][0]
    assert 'Time' in source['layout']['columns']
    response=recognize(client,files,resolutions=[dict(file_id=files[0]['file_id'],kind='pulse_states',condition_id='A1',direction='ltd',
        column_mapping={'time_s':'Time','id_a':'MeasResult1_value','vgs_v':'MeasResult2_value'}, units={'time_s':'s','id_a':'A','vgs_v':'V'},measurement_group='new',reason='Wrong polarity must be rejected')])
    assert response['sources'][0]['status']=='invalid'
    assert not response['requests']

def test_recognized_request_runs_worker_with_server_provenance_and_original_rows(client):
    from ctfm_worker.runner import run_once
    files=upload(client,[p for p in pulse_paths() if p.name in ('A1_LTP.csv','A1_LTD.csv')])
    plan=recognize(client, files)
    response=client.post('/api/v1/analyses', json=plan['requests'][0])
    assert response.status_code==202
    assert run_once(client.app.state.storage())
    result=client.get('/api/v1/analyses/'+response.json()['analysis_id']).json()
    assert result['status']=='succeeded', client.app.state.storage().get_job(response.json()['job_id'])
    assert result['summaries']['positive_candidate_count']==1020
    assert len(result['tables']['raw'])==24000
    assert len(result['recognition']['sources'])==2
    assert result['recognition']['recognition_id']==plan['recognition_id']
    assert all(p['start_time_s']==pytest.approx(6.00005) for p in result['provenance'])
    assert all(s['source_row']!=1001 for s in result['states'])
    assert any(r['source_row']==1001 for r in result['tables']['raw'])

def test_profiles_quick_uploads_a_ltp_ltd_pair_and_auto_publishes_every_valid_state(client):
    """The simplified upload flow: one multipart POST with both files, no analysis-page visit, no
    separate review/publish step. Must reproduce the exact 1020-state figure every other round of
    manual recognize+analyze+publish on this same A1 pair already established."""
    ltp=next(p for p in pulse_paths() if p.name=='A1_LTP.csv')
    ltd=next(p for p in pulse_paths() if p.name=='A1_LTD.csv')
    response=client.post('/api/v1/profiles/quick', files={'ltp_file':(ltp.name,ltp.read_bytes()),'ltd_file':(ltd.name,ltd.read_bytes())}, data={'display_name':'A1 quick'})
    assert response.status_code==201, response.text
    profile=response.json()
    assert profile['status']=='published'
    assert profile['condition_id']=='A1'
    assert profile['display_name']=='A1 quick'
    assert profile['pools']['combined']['state_ids'].__len__()==1020
    assert profile['review']['reviewer']=='system'
    # No analysis entity is created for this flow -- it never shows up for a user to pick on the
    # measurements page, matching "no analysis-record selection/review step" for the simulator.
    assert client.get('/api/v1/analyses').json()['items']==[]

def test_profiles_quick_rejects_an_unpaired_upload_with_a_clear_reason(client):
    """Two copies of the same file can never become an LTP/LTD pair (duplicate-source guard); the
    error must name the problem instead of silently producing a broken or empty profile."""
    ltp=next(p for p in pulse_paths() if p.name=='A1_LTP.csv')
    data=ltp.read_bytes()
    response=client.post('/api/v1/profiles/quick', files={'ltp_file':('a.csv',data),'ltd_file':('b.csv',data)}, data={'display_name':'Broken'})
    assert response.status_code==422, response.text
    error=response.json()['error']
    assert error['code']=='pulse_pair_not_recognized'
    assert error['details']['problems']

def test_resolution_with_extra_unit_role_does_not_abort_other_files(client):
    files=upload(client,[next(p for p in pulse_paths() if p.name=='A1_LTP.csv'), *sorted(SNAPSHOT.glob('files/Retention/**/*.xlsx'))[:1]])
    plan=recognize(client,files,resolutions=[dict(file_id=files[0]['file_id'],units={'time_s':'s','id_a':'A','vgs_v':'V','invented':'A'},reason='Invalid channel key')])
    assert len(plan['requests'])==1
    assert next(s for s in plan['sources'] if s['file_id']==files[0]['file_id'])['status']=='invalid'


def test_retention_resolution_cannot_mark_conflicting_source_bias_ready(client):
    files=upload(client,sorted(SNAPSHOT.glob('files/Retention/**/*A3*.xlsx')))
    plan=recognize(client,files,resolutions=[dict(file_id=files[0]['file_id'],read_vgs_v=0.,reason='Conflicting bias must not produce an executable request')])
    assert not plan['requests']
    assert plan['sources'][0]['status']=='invalid'

@pytest.mark.parametrize('read_vgs_v', [None, 0., .5])
def test_pulse_resolution_rejects_conflicting_bias_and_preserves_fixed_zero(client, read_vgs_v):
    files=upload(client,[p for p in pulse_paths() if p.name in ('A1_LTP.csv','A1_LTD.csv')])
    resolved_file=files[0]['file_id']
    resolutions=[] if read_vgs_v is None else [dict(file_id=resolved_file,read_vgs_v=read_vgs_v,reason='Explicit read bias from operator')]
    plan=recognize(client,files,resolutions=resolutions)
    source=next(s for s in plan['sources'] if s['file_id']==resolved_file)
    if read_vgs_v == .5:
        assert not plan['requests']
        assert source['status']=='invalid'
        assert any(i['code']=='conflicting_pulse_read_bias' for i in source['issues'])
        assert any(e['field']=='read_vgs_v' and e['value']==.5 and e['scope']=='user_confirmed' for e in source['evidence'])
        assert all(p['status']!='ready' for p in plan['pulse_pairs'])
    else:
        assert source['status']=='ready'
        assert len(plan['requests'])==1
        assert all(i['read_vgs_v']==0. for i in plan['requests'][0]['inputs'])
        assert client.post('/api/v1/analyses',json=plan['requests'][0]).status_code==202
