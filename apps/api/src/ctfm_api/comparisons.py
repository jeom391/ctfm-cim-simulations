"""One durable comparison owns one existing experiment job; inputs stay shared."""
from copy import deepcopy
import json
from typing import Literal
from uuid import UUID, uuid4
from fastapi import Depends, HTTPException
from ctfm_contracts.models import ExperimentRequest
from ctfm_contracts.product_policy import validate_product_scope
from ctfm.profiles import validate_profile, analysis_link
from jsonschema.exceptions import ValidationError as SchemaValidationError
from .storage import encode, now, sha256
from .comparison_models import (ComparisonCard, ComparisonDraft, ComparisonUpdate, ComparisonRun,
    ComparisonSave, ComparisonClone, ComparisonResult, ComparisonList)


def read(db, identifier):
    row = db.execute("SELECT data FROM entities WHERE kind='comparison' AND id=?", (identifier,)).fetchone()
    if row is None: raise KeyError(identifier)
    return json.loads(row[0])


def write(db, item):
    db.execute("UPDATE entities SET data=? WHERE kind='comparison' AND id=?", (encode(item), item['comparison_id']))


def create(db, draft):
    timestamp = now()
    item = dict(comparison_id=str(uuid4()), version=1, lifecycle='drafting', name=None,
                common_settings=draft['common_settings'], cards=[dict(c,status='draft') for c in draft['cards']],
                created_at=timestamp, updated_at=timestamp, origin_id=None, clone_operation_id=None,
                experiment_id=None, job_id=None, outcome=None, snapshot=None, discard_requested=False)
    db.execute("INSERT INTO entities VALUES('comparison',?,?,?)", (item['comparison_id'], encode(item), timestamp))
    return item


def reconcile(db, experiment):
    """Called inside terminal job transaction, including cancellation/recovery."""
    identifier = experiment.get('comparison_id')
    if not identifier: return
    item = read(db, identifier)
    if item['lifecycle'] != 'running': return
    status = experiment['status']
    if status in ('queued','running'): return
    for card in item['cards']:
        if card['status'] == 'blocked': continue
        ref = card['profile_ref']
        rows = [r for r in experiment.get('runs',[]) if r.get('profile_id') == ref['id'] and r.get('profile_revision') == ref['revision']]
        card['runs'] = rows
        card['candidate_ids'] = list(dict.fromkeys(r['candidate_id'] for r in rows if r.get('candidate_id')))
        evaluated = [r for r in rows if r['kind'] in ('ALL','candidate')]
        successful = sum(r['status']=='succeeded' for r in evaluated)
        if status == 'cancelled': card['status'] = 'cancelled'
        elif successful and status in ('succeeded','partial') and all(r['status']=='succeeded' for r in evaluated): card['status']='succeeded'
        elif successful: card['status']='partial'
        else: card['status']='failed'
        reasons = list(dict.fromkeys(r['reason'] for r in rows if r.get('reason')))
        if card['status'] != 'succeeded' and not reasons:
            reasons = [experiment.get('error',{}).get('message') or status]
        card['reason'] = '; '.join(reasons) or None
    statuses = [c['status'] for c in item['cards']]
    item['outcome'] = ('cancelled' if status=='cancelled' else 'succeeded' if statuses and all(s=='succeeded' for s in statuses)
                       else 'partial' if any(s in ('succeeded','partial') for s in statuses) else 'failed')
    item.update(lifecycle='temporary', updated_at=now())
    write(db,item)


def cleanup(store, identifier):
    """Retryable terminal cleanup: never remove a directory or checkpoint file."""
    with store.connection() as db:
        db.execute('BEGIN IMMEDIATE')
        item=read(db,identifier)
        if not item['discard_requested'] or item['lifecycle']=='discarded': return item
        if item['job_id']:
            job=db.execute('SELECT state FROM jobs WHERE id=?',(item['job_id'],)).fetchone()
            if job and job[0] in ('queued','running'): return item
            owned=store.job_dir(item['job_id'])
            expected=store.root/'artifacts'/str(UUID(item['job_id']))
            if owned!=expected or owned.resolve()!=expected:
                raise ValueError('Cleanup requires the exact owned job directory')
            protected={store.managed_path(json.loads(r[0])['relative_path']) for r in db.execute("SELECT data FROM entities WHERE kind='checkpoint'")}
            shared_ids=set()
            for row in db.execute("SELECT kind,id,data FROM entities WHERE kind IN ('experiment','analysis')"):
                if row['kind']=='experiment' and row['id']==item['experiment_id']: continue
                shared_ids.update(a['id'] for a in json.loads(row['data']).get('artifacts',[]) if a.get('id'))
            artifacts=db.execute("SELECT id,data FROM entities WHERE kind='artifact'").fetchall()
            protected.update(store.managed_path(json.loads(row['data'])['relative_path']) for row in artifacts if row['id'] in shared_ids)
            for row in artifacts:
                artifact=json.loads(row['data']); path=store.managed_path(artifact['relative_path'])
                if path.is_relative_to(owned) and path not in protected and path.suffix != '.pt':
                    path.unlink(missing_ok=True)
                    db.execute("DELETE FROM entities WHERE kind='artifact' AND id=?",(row['id'],))
            # Unregistered files from an interrupted worker still belong to this job.
            if owned.is_dir():
                for path in owned.rglob('*'):
                    resolved=path.resolve()
                    if resolved.is_relative_to(owned) and resolved.is_file() and resolved not in protected and resolved.suffix != '.pt':
                        resolved.unlink(missing_ok=True)
            db.execute("DELETE FROM entities WHERE kind='experiment' AND id=?",(item['experiment_id'],))
            db.execute('DELETE FROM jobs WHERE id=?',(item['job_id'],))
        item.update(lifecycle='discarded',updated_at=now(),cards=[],common_settings={},snapshot=None)
        write(db,item)
        return item


def register_comparisons(app, storage, resolve_c2c, capabilities):
    def current(store,identifier):
        item=store.get_entity('comparison',identifier)
        return cleanup(store,identifier) if item['discard_requested'] else item

    @app.post('/api/v1/comparisons', status_code=201, response_model=ComparisonResult)
    def new(request: ComparisonDraft, store=Depends(storage)):
        with store.connection() as db:
            return create(db,request.model_dump(mode='json'))

    @app.get('/api/v1/comparisons', response_model=ComparisonList)
    def listing(scope: Literal['saved','temporary','all']='saved',store=Depends(storage)):
        items=[current(store,r['comparison_id']) for r in store.list_entities('comparison')]
        return dict(items=[r for r in items if r['lifecycle']!='discarded' and (scope=='all' or (r['lifecycle']=='saved' if scope=='saved' else r['lifecycle']!='saved'))])

    @app.get('/api/v1/comparisons/{identifier}', response_model=ComparisonResult)
    def get(identifier: UUID,store=Depends(storage)):
        return current(store,str(identifier))

    @app.put('/api/v1/comparisons/{identifier}/draft', response_model=ComparisonResult)
    def update(identifier: UUID,request: ComparisonUpdate,store=Depends(storage)):
        with store.connection() as db:
            db.execute('BEGIN IMMEDIATE'); item=read(db,str(identifier))
            if item['discard_requested'] or item['lifecycle']!='drafting' or item['version']!=request.expected_version:
                raise HTTPException(409,'Draft changed or has already run; reload or clone it')
            item.update(common_settings=request.common_settings,cards=[dict(c.model_dump(mode='json'),status='draft') for c in request.cards],version=item['version']+1,updated_at=now())
            write(db,item); return item

    @app.post('/api/v1/comparisons/{identifier}/run', response_model=ComparisonResult)
    def run(identifier: UUID,request: ComparisonRun,store=Depends(storage)):
        # Phase 1 (read-only, no write lock): fetch the draft to validate and verify against.
        with store.connection() as db:
            item=read(db,str(identifier))
        if item['discard_requested']: raise HTTPException(409,'Comparison discard has already been requested')
        if item['lifecycle'] in ('running','temporary','saved'): return item
        if item['lifecycle']!='drafting' or item['version']!=request.expected_version:
            raise HTTPException(409,'Draft version changed; reload before running')
        # Phase 2 (no write lock held): engine/checkpoint/profile/C2C verification. This can be
        # slow (file hashing, schema validation of large profiles, first-time engine import) and must
        # not hold the single SQLite writer lock, or it starves the worker's claim/progress/finish
        # writes until they exceed their busy timeout and the worker crashes.
        common=deepcopy(item['common_settings'])
        placeholders=[dict(id=c['card_id'],revision=1,**({'c2c':dict(source='manual_assumption',cv_percent=0)} if common.get('effects',{}).get('c2c') else {})) for c in item['cards']]
        ExperimentRequest.model_validate(dict(common,profile_refs=placeholders or [dict(id=str(uuid4()),revision=1)]))
        validate_product_scope(common)
        engine=capabilities().engines[common['engines']['accuracy']]
        if not engine.available: raise ValueError('Requested accuracy engine is unavailable: '+str(engine.reason))
        if common['checkpoint_id']:
            checkpoint=store.get_entity('checkpoint',common['checkpoint_id'])
            if sha256(store.managed_path(checkpoint['relative_path']).read_bytes())!=checkpoint['sha256']:
                raise ValueError('Checkpoint hash mismatch')
        refs=[]; manifests=[]; seen=set()
        for card in item['cards']:
            try:
                if not card.get('profile_ref'): raise ValueError('Choose and explicitly publish a profile revision before running')
                ref=deepcopy(card['profile_ref'])
                if ref['id'] in seen: raise ValueError('Only one revision per profile is allowed; explicitly clone the profile identity for side-by-side revisions')
                record=store.get_profile(ref['id'],ref['revision']); manifest=record['manifest']
                validate_profile(**record,published_required=True)
                links=manifest.get('analysis_links') or {}
                for effect in ('state','d2d','retention','c2c'):
                    selected=card.get(effect+'_analysis_id')
                    if selected and selected != (links.get(effect) or {}).get('analysis_id'):
                        raise ValueError('Selected '+effect+' analysis differs from the published revision; compose and publish the replacement first')
                if card.get('selected_state_ids') is not None and set(card['selected_state_ids'])!={s['state_id'] for s in record['states'] if s['selected']}:
                    raise ValueError('State selection differs from the published revision')
                if common['effects']['retention'] and manifest['retention']['status']!='available': raise ValueError('retention measurement is unavailable; disable it or select reviewed data')
                if common['effects']['retention'] and manifest['retention']['program_fit']['a']+manifest['retention']['program_fit']['b']<=0:
                    raise ValueError('Retention reference current must be positive')
                if common['effects']['d2d']:
                    # A manual per-profile CV (simplified upload flow) takes precedence; otherwise
                    # fall back to the profile's own measured D2D, exactly as before this existed.
                    if card.get('manual_d2d_cv_percent') is not None:
                        ref['d2d']=dict(source='manual_assumption',cv_percent=card['manual_d2d_cv_percent'])
                    elif manifest['d2d']['status']!='available':
                        raise ValueError('D2D data is unavailable; disable it or enter a manual relative CV(%) for this profile')
                if common['effects']['c2c']:
                    linked=links.get('c2c') or {}
                    analysis_id=card.get('c2c_analysis_id') or linked.get('analysis_id')
                    if analysis_id:
                        if not card['c2c_approved_assumption']: raise ValueError('Measured C2C requires explicit approval for this comparison')
                        if linked and analysis_link(store.get_entity('analysis',analysis_id))['scientific_sha256']!=linked['scientific_sha256']:
                            raise ValueError('C2C analysis differs from the published profile link')
                        ref['c2c']=dict(source='measured_detrended',analysis_id=analysis_id,approved_assumption=True,cross_condition_acknowledged=card['cross_condition_acknowledged'])
                    elif card.get('manual_c2c_cv_percent') is not None:
                        ref['c2c']=dict(source='manual_assumption',cv_percent=card['manual_c2c_cv_percent'])
                    else: raise ValueError('C2C data is unavailable; disable it or select and approve an analysis')
                candidate=resolve_c2c(store,dict(common,profile_refs=[ref]))
                ref=candidate['profile_refs'][0]
                seen.add(ref['id']);refs.append(ref);manifests.append(deepcopy(manifest))
                card.update(status='queued',profile_hash=manifest['profile_hash'],reason=None)
            except (ValueError,KeyError,SchemaValidationError) as exc:
                card.update(status='blocked',reason=str(exc))
            except Exception as exc:
                # APIError carries a safe user-facing validation message.
                if not hasattr(exc,'code'): raise
                card.update(status='blocked',reason=exc.message)
        timestamp=now()
        item.update(snapshot=dict(common_settings=common,cards=deepcopy(item['cards']),profiles=manifests),updated_at=timestamp,version=item['version']+1)
        if refs:
            config=ExperimentRequest.model_validate(dict(common,profile_refs=refs)).root
        # Phase 3 (short write transaction): re-verify the draft is exactly the one just validated.
        # Published profiles are immutable, so an unchanged version/lifecycle/discard_requested here
        # guarantees every card and common_settings field verified in phase 2 is still current.
        with store.connection() as db:
            db.execute('BEGIN IMMEDIATE'); fresh=read(db,str(identifier))
            if fresh['discard_requested']: raise HTTPException(409,'Comparison discard has already been requested')
            if fresh['lifecycle'] in ('running','temporary','saved'): return fresh
            if fresh['lifecycle']!='drafting' or fresh['version']!=request.expected_version:
                raise HTTPException(409,'Draft changed while validating; reload and try again')
            if refs:
                count=db.execute("SELECT COUNT(*) FROM jobs WHERE state IN ('queued','running')").fetchone()[0]
                if count>=100: raise ValueError('The queue is full (100 pending jobs)')
                eid,jid=str(uuid4()),str(uuid4())
                experiment=dict(id=eid,experiment_id=eid,job_id=jid,status='queued',request=config,created_at=timestamp,artifacts=[],comparison_id=item['comparison_id'])
                db.execute("INSERT INTO entities VALUES('experiment',?,?,?)",(eid,encode(experiment),timestamp))
                db.execute("INSERT INTO jobs(id,kind,entity_id,state,stage,created_at) VALUES(?,'experiment',?,'queued','queued',?)",(jid,eid,timestamp))
                item.update(lifecycle='running',experiment_id=eid,job_id=jid)
                for card in item['cards']:
                    if card['status']=='queued': card.update(experiment_id=eid,job_id=jid)
            else: item.update(lifecycle='temporary',outcome='failed')
            write(db,item);return item

    @app.post('/api/v1/comparisons/{identifier}/save',response_model=ComparisonResult)
    def save(identifier: UUID,request: ComparisonSave,store=Depends(storage)):
        name=request.name.strip()
        if not name: raise ValueError('A nonempty name is required')
        with store.connection() as db:
            db.execute('BEGIN IMMEDIATE');item=read(db,str(identifier))
            if item['lifecycle']=='saved' and item['name']==name:return item
            if item['lifecycle']!='temporary' or item['discard_requested']:raise HTTPException(409,'Only a terminal temporary comparison can be saved')
            item.update(lifecycle='saved',name=name,updated_at=now());write(db,item);return item

    @app.post('/api/v1/comparisons/{identifier}/clone',response_model=ComparisonResult)
    def clone(identifier: UUID,request: ComparisonClone,store=Depends(storage)):
        with store.connection() as db:
            db.execute('BEGIN IMMEDIATE');source=read(db,str(identifier))
            for row in db.execute("SELECT data FROM entities WHERE kind='comparison'"):
                existing=json.loads(row[0])
                if existing.get('origin_id')==str(identifier) and existing.get('clone_operation_id')==str(request.operation_id):return existing
            if source['lifecycle']=='discarded':raise HTTPException(409,'Discarded comparisons cannot be cloned')
            cards=[{k:v for k,v in c.items() if k in ComparisonCard.model_fields} for c in source['cards']]
            for card in cards:
                card.update(c2c_approved_assumption=False,cross_condition_acknowledged=False)
            item=create(db,dict(common_settings=source['common_settings'],cards=cards))
            item.update(origin_id=str(identifier),clone_operation_id=str(request.operation_id));write(db,item);return item

    @app.post('/api/v1/comparisons/{identifier}/discard',response_model=ComparisonResult)
    def discard(identifier: UUID,store=Depends(storage)):
        with store.connection() as db:
            db.execute('BEGIN IMMEDIATE');item=read(db,str(identifier))
            if item['lifecycle']=='saved':raise HTTPException(409,'Saved comparisons cannot be discarded')
            if item['lifecycle']=='discarded':return item
            item.update(discard_requested=True,updated_at=now());write(db,item)
        if item['job_id']:
            try: store.cancel(item['job_id'])
            except KeyError:
                if store.get_entity('comparison',str(identifier))['lifecycle']!='discarded': raise
        return cleanup(store,str(identifier))
