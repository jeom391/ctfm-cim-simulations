"""Durable comparisons reuse the existing queue and never own shared inputs."""
import json
from copy import deepcopy
from pathlib import Path
from uuid import uuid4
import pytest
from httpx import ASGITransport, AsyncClient
from ctfm_api.app import create_app
from ctfm_api.storage import Store

pytestmark = pytest.mark.anyio
@pytest.fixture
def anyio_backend(): return "asyncio"

def common():
    cfg=json.loads((Path(__file__).resolve().parents[3]/"packages/contracts/fixtures/experiment-baseline.request.json").read_text())
    cfg.pop("profile_refs")
    cfg["hardware"]["tile_size"]=64
    return cfg

async def test_incomplete_draft_survives_reopen_version_checks_save_clone_discard(tmp_path):
    async with AsyncClient(transport=ASGITransport(app=create_app(tmp_path)),base_url="http://test") as c:
        card={"card_id":str(uuid4()),"display_name":"A3 draft","state_analysis_id":str(uuid4()),"c2c_analysis_id":str(uuid4())}
        r=await c.post("/api/v1/comparisons",json={"common_settings":common(),"cards":[card]})
        assert r.status_code==201,r.text
        draft=r.json(); ident=draft["comparison_id"]
        assert draft["lifecycle"]=="drafting"
        assert (await c.get("/api/v1/comparisons")).json()["items"]==[]
    async with AsyncClient(transport=ASGITransport(app=create_app(tmp_path)),base_url="http://test") as c:
        loaded=(await c.get(f"/api/v1/comparisons/{ident}")).json()
        assert loaded["cards"][0]["c2c_analysis_id"]==card["c2c_analysis_id"]
        patch={"expected_version":1,"common_settings":common(),"cards":[]}
        assert (await c.put(f"/api/v1/comparisons/{ident}/draft",json=patch)).status_code==200
        assert (await c.put(f"/api/v1/comparisons/{ident}/draft",json=patch)).status_code==409
        patch.update(expected_version=2,cards=[card])
        assert (await c.put(f"/api/v1/comparisons/{ident}/draft",json=patch)).status_code==200
        r=await c.post(f"/api/v1/comparisons/{ident}/run",json={"expected_version":3})
        assert r.status_code==200,r.text
        terminal=r.json(); assert terminal["lifecycle"]=="temporary"
        assert terminal["cards"][0]["status"]=="blocked"
        assert terminal["cards"][0]["reason"]
        assert Store(tmp_path).list_jobs()==[]
        assert (await c.put(f"/api/v1/comparisons/{ident}/draft",json=patch)).status_code==409
        for _ in range(2):
            saved=(await c.post(f"/api/v1/comparisons/{ident}/save",json={"name":"Reviewed comparison"})).json()
            assert saved["comparison_id"]==ident and saved["lifecycle"]=="saved"
        assert len((await c.get("/api/v1/comparisons")).json()["items"])==1
        op={"operation_id":str(uuid4())}
        clone=(await c.post(f"/api/v1/comparisons/{ident}/clone",json=op)).json()
        assert clone["lifecycle"]=="drafting" and clone["experiment_id"] is None
        assert (await c.post(f"/api/v1/comparisons/{ident}/clone",json=op)).json()==clone
        assert (await c.post(f"/api/v1/comparisons/{ident}/discard")).status_code==409
        cid=clone["comparison_id"]
        for _ in range(2):
            assert (await c.post(f"/api/v1/comparisons/{cid}/discard")).json()["lifecycle"]=="discarded"
        assert (await c.get("/api/v1/comparisons?scope=temporary")).json()["items"]==[]

async def test_legacy_store_records_are_not_migrated_or_reinterpreted(tmp_path):
    store=Store(tmp_path)
    legacy={"id":str(uuid4()),"status":"succeeded","request":{"hardware":{"tile_size":256}},"runs":[{"accuracy":0.9}]}
    store.put_entity("experiment",legacy["id"],legacy)
    async with AsyncClient(transport=ASGITransport(app=create_app(tmp_path)),base_url="http://test") as c:
        assert (await c.post("/api/v1/comparisons",json={})).status_code==201
    assert Store(tmp_path).get_entity("experiment",legacy["id"])==legacy


def seed_analysis(store):
    from ctfm.measurement import analyze
    aid,fid=str(uuid4()),str(uuid4())
    rows=[{'time_s':t,'id_a':i,'vgs_v':v} for t,i,v in [(1,1e-6,0),(2,1e-6,0),(3,0,-1),(4,0,-6),(5,2e-6,0),(6,2e-6,0),(7,0,-1),(8,0,-6)]]
    data=dict(file_id=fid,sha256='a'*64,filename='synthetic.csv',sheet=None,rows=rows,source_rows=list(range(2,10)),column_mapping={k:k for k in rows[0]},units={'time_s':'s','id_a':'A','vgs_v':'V'},device_id='d',condition_id='A1',direction='ltp',read_vgs_v=0,vds_v=.1,start_time_s=1)
    analysis=analyze('pulse_states',[data],{})
    analysis.update(id=aid,analysis_id=aid,status='succeeded')
    store.put_entity('analysis',aid,analysis)
    return analysis

async def test_c2c_only_revision_keeps_original_hash_states_and_other_links(tmp_path):
    store=Store(tmp_path);analysis=seed_analysis(store)
    c2c_id=str(uuid4())
    store.put_entity('analysis',c2c_id,dict(analysis_id=c2c_id,kind='c2c_detrended',status='succeeded',condition_id='A1',analysis_version='test',program={'status':'blocked'}))
    async with AsyncClient(transport=ASGITransport(app=create_app(tmp_path)),base_url='http://test') as c:
        r=await c.post('/api/v1/profiles',json=dict(condition_id='A1',state_analysis_id=analysis['analysis_id'],selected_state_ids=[s['state_id'] for s in analysis['states']]))
        assert r.status_code==201,r.text
        base=r.json();pid=base['profile_id']
        pub=await c.post(f'/api/v1/profiles/{pid}/revisions/1/publish',json={'reviewer':'reviewer','review_note':'Explicit adoption'})
        assert pub.status_code==200,pub.text
        original=store.get_profile(pid,1)
        revised=await c.post(f'/api/v1/profiles/{pid}/revisions',json={'base_revision':1,'c2c_analysis_id':c2c_id})
        assert revised.status_code==201,revised.text
        new=revised.json()
        assert new['status']=='draft' and new['review']['reviewer'] is None
        assert new['analysis_links']['c2c']['analysis_id']==c2c_id
        assert new['analysis_links']['state']==original['manifest']['analysis_links']['state']
        assert new['states_sha256']==original['manifest']['states_sha256']
        assert new['d2d']==original['manifest']['d2d'] and new['retention']==original['manifest']['retention']
        assert store.get_profile(pid,1)==original
        assert store.get_profile(pid,2)['states']==original['states']
        exported=await c.get(f'/api/v1/profiles/{pid}/revisions/2/export')
        imported=await c.post('/api/v1/profiles/import',files={'file':('profile.zip',exported.content)})
        assert imported.status_code==201,imported.text
        assert imported.json()['analysis_links']['c2c']==new['analysis_links']['c2c']


async def published_card(c,store,*,c2c=False):
    a=seed_analysis(store)
    payload=dict(condition_id='A1',state_analysis_id=a['analysis_id'],selected_state_ids=[s['state_id'] for s in a['states']])
    if c2c:
        cid=str(uuid4());store.put_entity('analysis',cid,dict(analysis_id=cid,kind='c2c_detrended',status='succeeded',condition_id='A1',program={'status':'blocked'}))
        payload['c2c_analysis_id']=cid
    r=await c.post('/api/v1/profiles',json=payload);assert r.status_code==201,r.text
    pid=r.json()['profile_id']
    r=await c.post(f'/api/v1/profiles/{pid}/revisions/1/publish',json={'reviewer':'test','review_note':'Explicit adoption'})
    assert r.status_code==200,r.text
    return dict(card_id=str(uuid4()),display_name='A1',profile_ref={'id':pid,'revision':1},**({'c2c_analysis_id':cid} if c2c else {}))

async def test_one_atomic_run_off_bypasses_unapproved_c2c_terminal_peers_save(tmp_path):
    import asyncio
    store=Store(tmp_path)
    async with AsyncClient(transport=ASGITransport(app=create_app(tmp_path)),base_url='http://test') as c:
        card=await published_card(c,store,c2c=True)
        card2=await published_card(c,store)
        blocked=dict(card_id=str(uuid4()),display_name='Incomplete')
        draft=(await c.post('/api/v1/comparisons',json={'common_settings':common(),'cards':[card,card2,blocked]})).json();cid=draft['comparison_id']
        rs=await asyncio.gather(*[c.post(f'/api/v1/comparisons/{cid}/run',json={'expected_version':1}) for _ in range(2)])
        assert all(r.status_code==200 for r in rs),[r.text for r in rs]
        run=rs[0].json();assert rs[1].json()==run
        assert len(store.list_jobs())==1
        exp=store.get_entity('experiment',run['experiment_id'])
        assert len(exp['request']['profile_refs'])==2 and all('c2c' not in r for r in exp['request']['profile_refs'])
        assert run['snapshot']['cards'][0]['c2c_analysis_id']==card['c2c_analysis_id']
        claimed=store.claim()
        rows=[dict(profile_id=card['profile_ref']['id'],profile_revision=1,candidate_id='candidate-1',kind='ALL',status='succeeded',accuracy=.9),dict(profile_id=card2['profile_ref']['id'],profile_revision=1,candidate_id='candidate-2',kind='ALL',status='failed',accuracy=None,reason='mapping failure')]
        store.finish(claimed['id'],state='succeeded',result={'status':'partial','runs':rows})
        result=(await c.get(f'/api/v1/comparisons/{cid}')).json()
        assert result['outcome']=='partial'
        assert [x['status'] for x in result['cards']]==['succeeded','failed','blocked']
        assert result['cards'][0]['runs'][0]['accuracy']==.9
        before=store.list_jobs()
        await asyncio.gather(*[c.post(f'/api/v1/comparisons/{cid}/save',json={'name':'Shared checkpoint comparison'}) for _ in range(2)])
        assert store.list_jobs()==before
        assert (await c.get(f'/api/v1/comparisons/{cid}')).json()['lifecycle']=='saved'

async def test_discard_waits_terminal_preserves_shared_checkpoint_and_measurements(tmp_path):
    store=Store(tmp_path)
    async with AsyncClient(transport=ASGITransport(app=create_app(tmp_path)),base_url='http://test') as c:
        card=await published_card(c,store)
        draft=(await c.post('/api/v1/comparisons',json={'common_settings':common(),'cards':[card]})).json();cid=draft['comparison_id']
        run=(await c.post(f'/api/v1/comparisons/{cid}/run',json={'expected_version':1})).json()
        store.claim();out=store.job_dir(run['job_id']);out.mkdir()
        checkpoint=out/'checkpoint.pt';checkpoint.write_bytes(b'shared checkpoint')
        cp_id=str(uuid4());from ctfm_api.storage import sha256
        store.put_entity('checkpoint',cp_id,dict(checkpoint_id=cp_id,relative_path=checkpoint.relative_to(store.root).as_posix(),sha256=sha256(checkpoint.read_bytes())))
        cp_artifact=store.register_artifact(checkpoint,'pt')
        disposable=out/'result.json';disposable.write_text('{}');artifact=store.register_artifact(disposable,'json')
        consumer,_=store.enqueue('experiment',dict(common(),profile_refs=[card['profile_ref']],checkpoint_id=cp_id))
        r=await c.post(f'/api/v1/comparisons/{cid}/discard')
        assert r.json()['lifecycle']=='running' and disposable.exists()
        assert store.get_job(run['job_id'])['cancel_requested']
        store.finish(run['job_id'],state='cancelled')
        done=(await c.get(f'/api/v1/comparisons/{cid}')).json()
        assert done['lifecycle']=='discarded' and not disposable.exists()
        assert store.artifact_path(cp_artifact['id']).read_bytes()==b'shared checkpoint'
        assert store.get_entity('experiment',consumer['id'])['request']['checkpoint_id']==cp_id
        assert store.get_profile(card['profile_ref']['id'],1)['manifest']['status']=='published'
        assert store.list_entities('analysis')
        assert (await c.post(f'/api/v1/comparisons/{cid}/discard')).status_code==200

async def test_interrupted_comparison_retains_completed_candidate_rows(tmp_path):
    store=Store(tmp_path)
    async with AsyncClient(transport=ASGITransport(app=create_app(tmp_path)),base_url='http://test') as c:
        card=await published_card(c,store)
        draft=(await c.post('/api/v1/comparisons',json={'common_settings':common(),'cards':[card]})).json();cid=draft['comparison_id']
        run=(await c.post(f'/api/v1/comparisons/{cid}/run',json={'expected_version':1})).json();store.claim()
        out=store.job_dir(run['job_id']);out.mkdir()
        row=dict(profile_id=card['profile_ref']['id'],profile_revision=1,candidate_id='candidate-1',kind='ALL',status='succeeded',accuracy=.9)
        (out/'comparison-partial.json').write_text(json.dumps({'runs':[row]}))
        assert store.recover_interrupted()==1
        restored=(await c.get(f'/api/v1/comparisons/{cid}')).json()
        assert restored['lifecycle']=='temporary'
        assert restored['cards'][0]['runs']==[row]
        assert restored['outcome']=='partial'


async def test_worker_comparison_revalidates_snapshot_and_keeps_peer_metrics(tmp_path,monkeypatch):
    import numpy as np
    import ctfm.simulation as simulation
    from ctfm.simulation.torch_runner import create_model
    from ctfm_worker.execute import execute
    from ctfm_api.storage import encode
    monkeypatch.setenv('CTFM_STORAGE_ROOT',str(tmp_path));store=Store(tmp_path)
    async with AsyncClient(transport=ASGITransport(app=create_app(tmp_path)),base_url='http://test') as c:
        cards=[await published_card(c,store),await published_card(c,store)]
        settings=common();settings['pools']=['combined'];settings['mappings']=['fixed_reference']
        draft=(await c.post('/api/v1/comparisons',json={'common_settings':settings,'cards':cards})).json();cid=draft['comparison_id']
        run=(await c.post(f'/api/v1/comparisons/{cid}/run',json={'expected_version':1})).json()
        record=store.get_profile(cards[0]['profile_ref']['id'],1);record['manifest']['profile_hash']='0'*64
        with store.connection() as db:
            db.execute('UPDATE profiles SET manifest=? WHERE id=?',(encode(record['manifest']),cards[0]['profile_ref']['id']))
        store.claim()
        train=np.zeros((60000,784),dtype=np.uint8);test=np.zeros((10000,784),dtype=np.uint8)
        monkeypatch.setattr(simulation,'load_mnist',lambda *a:(train,np.zeros(60000,dtype=np.uint8),test,np.zeros(10000,dtype=np.uint8),[{'synthetic':True}]))
        trained=[]
        def training(*a):trained.append(1);return create_model(),[]
        monkeypatch.setattr(simulation,'train_model',training)
        execute(run['job_id'])
        result=json.loads((store.job_dir(run['job_id'])/'worker-result.json').read_text())
        assert trained==[1]
        assert result['summary']['failed']==1 and result['summary']['completed']==1 and result['summary']['skipped']==0
        rows=[r for r in result['runs'] if r['kind']=='ALL']
        assert rows[0]['status']=='failed' and rows[1]['status']=='succeeded'
        store.finish(run['job_id'],state='succeeded',result=result)
        read=(await c.get(f'/api/v1/comparisons/{cid}')).json()
        assert read['outcome']=='partial' and 'snapshot' in read['cards'][0]['reason']
        assert read['cards'][1]['runs'][-1]['accuracy']==rows[1]['accuracy']

async def test_comparison_run_rejects_out_of_scope_common_settings_without_jobs(tmp_path):
    store=Store(tmp_path)
    async with AsyncClient(transport=ASGITransport(app=create_app(tmp_path)),base_url='http://test') as c:
        card=await published_card(c,store)
        for mutate in ('tile','ppa','order'):
            cfg=common()
            cfg['schema_version']='1.4.0'
            cfg['effects']['adc']=True
            cfg['hardware'].update(adc_bits=5,adc_order='adc_then_subtract',range_policy='validation_max_abs')
            if mutate=='tile':cfg['hardware']['tile_size']=128
            elif mutate=='ppa':cfg['engines']['ppa']='assumed_proxy'
            else:cfg['hardware']['adc_order']='subtract_then_adc'
            draft=(await c.post('/api/v1/comparisons',json={'common_settings':cfg,'cards':[card]})).json()
            r=await c.post('/api/v1/comparisons/'+draft['comparison_id']+'/run',json={'expected_version':1})
            assert r.status_code==422,r.text
        assert store.list_jobs()==[]


async def test_c2c_link_requires_matching_kind_and_on_requires_fresh_approval(tmp_path):
    store=Store(tmp_path)
    async with AsyncClient(transport=ASGITransport(app=create_app(tmp_path)),base_url='http://test') as c:
        a=seed_analysis(store)
        wrong=await c.post('/api/v1/profiles',json=dict(condition_id='A1',state_analysis_id=a['analysis_id'],selected_state_ids=[s['state_id'] for s in a['states']],c2c_analysis_id=a['analysis_id']))
        assert wrong.status_code==422,wrong.text
        card=await published_card(c,store,c2c=True)
        cfg=common();cfg['schema_version']='1.4.0';cfg['effects']['c2c']=True
        draft=(await c.post('/api/v1/comparisons',json={'common_settings':cfg,'cards':[card]})).json()
        run=(await c.post('/api/v1/comparisons/'+draft['comparison_id']+'/run',json={'expected_version':1})).json()
        assert run['lifecycle']=='temporary' and 'approval' in run['cards'][0]['reason']
        assert store.list_jobs()==[]

async def test_concurrent_discard_of_queued_job_is_idempotent(tmp_path):
    import asyncio
    store=Store(tmp_path)
    async with AsyncClient(transport=ASGITransport(app=create_app(tmp_path)),base_url='http://test') as c:
        card=await published_card(c,store)
        draft=(await c.post('/api/v1/comparisons',json={'common_settings':common(),'cards':[card]})).json();cid=draft['comparison_id']
        await c.post(f'/api/v1/comparisons/{cid}/run',json={'expected_version':1})
        responses=await asyncio.gather(*[c.post(f'/api/v1/comparisons/{cid}/discard') for _ in range(3)])
        assert all(r.status_code==200 for r in responses),[r.text for r in responses]
        assert (await c.get(f'/api/v1/comparisons/{cid}')).json()['lifecycle']=='discarded'
        assert store.list_jobs()==[]


def test_cleanup_rejects_a_job_directory_resolving_into_shared_uploads(tmp_path,monkeypatch):
    from ctfm_api.comparisons import create,write,cleanup
    store=Store(tmp_path)
    upload=store.root/'uploads'/'shared.csv';upload.write_bytes(b'original raw data')
    with store.connection() as db:
        item=create(db,dict(common_settings={},cards=[]))
        item.update(lifecycle='temporary',discard_requested=True,job_id=str(uuid4()),experiment_id=str(uuid4()))
        write(db,item)
    monkeypatch.setattr(store,'job_dir',lambda job_id:store.root/'uploads')
    with pytest.raises(ValueError,match='owned job directory'):
        cleanup(store,item['comparison_id'])
    assert upload.read_bytes()==b'original raw data'


def test_cleanup_preserves_artifact_referenced_by_another_experiment(tmp_path):
    from ctfm_api.comparisons import create,write,cleanup
    store=Store(tmp_path)
    with store.connection() as db:item=create(db,dict(common_settings={},cards=[]))
    eid,jid=str(uuid4()),str(uuid4());out=store.job_dir(jid);out.mkdir()
    file=out/'shared-result.json';file.write_text('{"legacy":true}')
    artifact=store.register_artifact(file,'json')
    store.put_entity('experiment','other',dict(id='other',artifacts=[artifact]))
    item.update(lifecycle='temporary',discard_requested=True,job_id=jid,experiment_id=eid)
    with store.connection() as db:write(db,item)
    cleanup(store,item['comparison_id'])
    assert store.artifact_path(artifact['id']).read_text()=='{"legacy":true}'
