"""Immutable, reviewed Device Profile manifests and canonical state artifacts."""
from __future__ import annotations

import csv
import hashlib
import io
import json
import math
from copy import deepcopy
from datetime import datetime, timezone
from typing import Literal
from uuid import UUID, uuid4

from pydantic import BaseModel, ConfigDict, Field
from ctfm.measurement import PARSER_VERSION, make_pools, RETENTION_SOURCES

STATE_COLUMNS = ['state_id','source_id','source_row','transition_row','time_s','direction','pulse_step','extraction_index','id_a','vgs_v','conductance_s','selected','exclusion_reason']


class StrictModel(BaseModel):
    model_config = ConfigDict(extra='forbid', allow_inf_nan=False)


class Measurement(StrictModel):
    vds_v: float = 0.1
    read_vgs_v: float = 0
    pulse_width_s: float = 0.001
    interval_s: float = 0.001
    applied_pulse_count: int = 512
    saturation_verified: bool = False


class Pool(StrictModel):
    state_ids: list[str]
    available: bool
    reason: str | None
    g_min_s: float | None
    g_max_s: float | None
    common_lo_s: float | None = None
    common_hi_s: float | None = None


class Assumption(StrictModel):
    id: str
    description: str
    evidence_kind: Literal['measured','derived','assumed']
    source_ref: str | None


class Review(StrictModel):
    reviewer: str | None = None
    reviewed_at: str | None = None
    note: str | None = None


class ImportOrigin(StrictModel):
    profile_id: UUID
    revision: int = Field(ge=1, strict=True)
    profile_hash: str = Field(pattern=r'^[0-9a-f]{64}$')
    status: Literal['draft','published']


class Extraction(StrictModel):
    parser_version: Literal['1.0.0']
    read_tolerance_v: float = Field(ge=0)
    write_threshold_v: float = Field(gt=0)
    start_time_s: float = Field(ge=0)
    sample_offset_rows: Literal[2]
    iref_a: float = Field(gt=0)
    vds_v: float
    read_vgs_v: float
    retention_start_time_s: float = Field(ge=10)
    crossing_segments: dict
    excluded_conditions: dict
    exclusions: list[dict]
    import_origin: ImportOrigin | None = None


class D2D(StrictModel):
    status: Literal['available','unavailable']
    cv: float | None
    analysis_id: str | None
    source_kind: Literal['iv_proxy']
    distribution: Literal['assumed_lognormal']
    physical_device_count: Literal[2]
    matched_conditions: int = Field(ge=0, strict=True)
    assumption_ids: list[str]
    reason: str | None = None


class C2C(StrictModel):
    status: Literal['unavailable']
    cv: None
    reason: Literal['not_provided']


class RetentionFit(StrictModel):
    a: float
    b: float
    rmse: float = Field(ge=0)
    r_squared: float | None
    n: int = Field(ge=3, strict=True)
    time_min_s: float = Field(ge=10)
    time_max_s: float = Field(ge=10)
    a_unit: Literal['A'] = 'A'
    b_unit: Literal['A/decade'] = 'A/decade'


class Retention(StrictModel):
    status: Literal['available','unavailable']
    analysis_id: str | None
    source_label: str | None
    vds_v: float | None
    read_vgs_v: float | None
    program_fit: RetentionFit | None
    erase_fit: RetentionFit | None
    current_basis: Literal['raw'] | None = None
    reference_time_s: float | None = None
    program_reference_current_a: float | None = None
    simulation_available: bool | None = None
    reason: str | None = None


class ProfileManifest(StrictModel):
    schema_version: Literal['1.0.0']
    profile_id: UUID
    revision: int = Field(ge=1, strict=True)
    profile_hash: str = Field(pattern=r'^[0-9a-f]{64}$')
    condition_id: str = Field(min_length=1)
    display_name: str = Field(min_length=1)
    status: Literal['draft','published']
    created_at: str
    published_at: str | None
    measurement: Measurement
    sources: list[dict]
    extraction: Extraction
    states_file: Literal['states.csv']
    states_sha256: str = Field(pattern=r'^[0-9a-f]{64}$')
    pools: dict[str,Pool]
    d2d: D2D
    c2c: C2C
    retention: Retention
    assumptions: list[Assumption]
    review: Review


def _canonical(value):
    try:
        return json.dumps(value,sort_keys=True,separators=(',',':'),ensure_ascii=False,allow_nan=False).encode('utf-8')
    except (ValueError,TypeError) as exc:
        raise ValueError('Profile values must be finite JSON values') from exc


def compute_profile_hash(manifest: dict) -> str:
    return hashlib.sha256(_canonical({k:v for k,v in manifest.items() if k!='profile_hash'})).hexdigest()


def _number(value,label):
    if isinstance(value,bool) or not isinstance(value,(int,float)) or not math.isfinite(value):
        raise ValueError(f'{label} must be a finite number')
    return value


def _validate_states(states):
    if not isinstance(states,list): raise ValueError('states must be a list')
    seen=set()
    for state in states:
        for key in ('source_id', 'exclusion_reason'):
            value = state.get(key)
            if isinstance(value, str) and value.lstrip().startswith(('=', '+', '-', '@')):
                raise ValueError('State CSV text cannot begin with a spreadsheet formula prefix')
        if set(state)!=set(STATE_COLUMNS): raise ValueError('State fields do not match the canonical CSV schema')
        if not isinstance(state['state_id'],str) or not state['state_id'] or state['state_id'] in seen:
            raise ValueError('State IDs must be nonempty and unique')
        seen.add(state['state_id'])
        if not isinstance(state['source_id'],str) or not state['source_id']: raise ValueError('State source_id is required')
        for key in ('source_row','transition_row','extraction_index'):
            if isinstance(state[key],bool) or not isinstance(state[key],int) or state[key]<1: raise ValueError(f'{key} must be a positive integer')
        if state['transition_row'] != state['source_row']+2: raise ValueError('State must preserve the j-2 source row')
        if state['direction'] not in ('ltp','ltd'): raise ValueError('State direction must be ltp/ltd')
        if state['pulse_step'] is not None and (isinstance(state['pulse_step'],bool) or not isinstance(state['pulse_step'],int) or state['pulse_step']<0):
            raise ValueError('pulse_step must be null or a nonnegative verified integer')
        for key in ('time_s','id_a','vgs_v','conductance_s'): _number(state[key],key)
        if state['time_s']<0 or not isinstance(state['selected'],bool): raise ValueError('Invalid state time or selection')
        if state['exclusion_reason'] is not None and not isinstance(state['exclusion_reason'],str): raise ValueError('Invalid exclusion reason')
        if not state['selected'] and not state['exclusion_reason']: raise ValueError('Excluded state requires a reason')
        if state['selected'] and state['exclusion_reason']: raise ValueError('Selected state cannot carry an exclusion reason')
        if state['selected'] and state['conductance_s']<=0: raise ValueError('Selected conductance must be positive')


def states_csv(states: list[dict]) -> bytes:
    _validate_states(states)
    out=io.StringIO(newline='')
    writer=csv.DictWriter(out,fieldnames=STATE_COLUMNS,lineterminator='\n')
    writer.writeheader()
    for state in states:
        row={}
        for key in STATE_COLUMNS:
            value=float(state[key]) if key in ('time_s','id_a','vgs_v','conductance_s') else state[key]
            row[key]='' if value is None else 'true' if value is True else 'false' if value is False else repr(value) if isinstance(value,float) else str(value)
        writer.writerow(row)
    return out.getvalue().encode('utf-8')


def parse_states_csv(data: bytes) -> list[dict]:
    try:
        reader=csv.DictReader(io.StringIO(data.decode('utf-8-sig'),newline=''),strict=True)
        if reader.fieldnames != STATE_COLUMNS: raise ValueError('Invalid states CSV columns or ordering')
        states=[]
        for row in reader:
            if set(row)!=set(STATE_COLUMNS) or any(v is None for v in row.values()): raise ValueError('Invalid states CSV row')
            for key in ('source_row','transition_row','extraction_index'): row[key]=int(row[key])
            row['pulse_step']=int(row['pulse_step']) if row['pulse_step'] else None
            for key in ('time_s','id_a','vgs_v','conductance_s'): row[key]=float(row[key])
            if row['selected'] not in ('true','false'): raise ValueError('selected must be true/false')
            row['selected']=row['selected']=='true'
            row['exclusion_reason']=row['exclusion_reason'] or None
            states.append(row)
    except (UnicodeError,csv.Error,TypeError,OverflowError) as exc:
        raise ValueError('Invalid states CSV') from exc
    _validate_states(states)
    return states


def _now():
    return datetime.now(timezone.utc).isoformat().replace('+00:00','Z')


def _unavailable_d2d():
    return dict(status='unavailable',cv=None,analysis_id=None,source_kind='iv_proxy',distribution='assumed_lognormal',physical_device_count=2,matched_conditions=0,assumption_ids=['d2d_lognormal','d2d_state_common'],reason='not_provided')


def build_profile(condition_id, state_analysis, selected_state_ids, d2d_analysis=None, retention_analysis=None, profile_id=None, revision=1, display_name=None):
    if state_analysis.get('kind')!='pulse_states' or state_analysis.get('condition_id')!=condition_id:
        raise ValueError('State analysis must contain pulse states from the selected condition')
    states=deepcopy(state_analysis.get('states',[]))
    ids=[s['state_id'] for s in states]
    selected=set(selected_state_ids)
    if len(selected)!=len(selected_state_ids) or not selected<=set(ids): raise ValueError('Selected state IDs must be unique and exist in the analysis')
    for state in states:
        state['selected']=state['state_id'] in selected
        state['exclusion_reason']=None if state['selected'] else state.get('exclusion_reason') or 'user_not_selected'
    _validate_states(states)
    sources=deepcopy(state_analysis.get('provenance',[]))
    for source in sources: source['source_type']='pulse_states'
    if not sources: raise ValueError('State source provenance is required')
    d2d=_unavailable_d2d(); retention=dict(status='unavailable',analysis_id=None,reason='not_provided',source_label=None,vds_v=None,read_vgs_v=None,program_fit=None,erase_fit=None)
    assumptions=[dict(id='raw_observed_states',description='State candidates are directly extracted signed-current observations without offset, smoothing or monotonic correction.',evidence_kind='measured',source_ref=state_analysis.get('analysis_id') or state_analysis.get('id')),
                 dict(id='common_range',description='Common pool is the union of observed candidates inside the overlap of directional ranges; it does not establish reversible pulse updates.',evidence_kind='derived',source_ref=None)]
    for analysis,kind in ((d2d_analysis,'d2d'),(retention_analysis,'retention')):
        if analysis is None: continue
        if analysis.get('kind')!=kind or analysis.get('condition_id')!=condition_id: raise ValueError(f'{kind} analysis condition does not match the profile')
        value=deepcopy(analysis[kind]); value['analysis_id']=analysis.get('analysis_id') or analysis.get('id') or value.get('analysis_id')
        if kind=='d2d':
            d2d=value
            assumptions.extend([dict(id='d2d_lognormal',description='Two-device IV CV is applied using an assumed lognormal distribution.',evidence_kind='assumed',source_ref=value['analysis_id']),dict(id='d2d_state_common',description='The IV proxy variation is assumed common across all conductance states.',evidence_kind='assumed',source_ref=value['analysis_id'])])
        else:
            retention=value
            assumptions.append(dict(id='retention_program_ratio',description='All conductance states use the Program current ratio relative to 10 seconds; long-time use is extrapolation.',evidence_kind='assumed',source_ref=value['analysis_id']))
            if retention.get('read_vgs_v') != 0:
                assumptions.append(dict(id='retention_read_bias_transfer',description='Retention measured at a different read gate bias is transferred to pulse states read at 0 V.',evidence_kind='assumed',source_ref=value['analysis_id']))
        for source in deepcopy(analysis.get('provenance',[])):
            source['source_type']=kind
            if source not in sources: sources.append(source)
    manifest=dict(schema_version='1.0.0',profile_id=str(profile_id or uuid4()),revision=revision,profile_hash='0'*64,condition_id=condition_id,display_name=display_name or condition_id,status='draft',created_at=_now(),published_at=None,measurement=Measurement().model_dump(),sources=sources,extraction=dict(parser_version=PARSER_VERSION,**deepcopy(state_analysis['settings']),exclusions=deepcopy(state_analysis.get('exclusions',[]))),states_file='states.csv',states_sha256=hashlib.sha256(states_csv(states)).hexdigest(),pools=make_pools(states),d2d=d2d,c2c=dict(status='unavailable',cv=None,reason='not_provided'),retention=retention,assumptions=assumptions,review=Review().model_dump())
    manifest['profile_hash']=compute_profile_hash(manifest)
    validate_profile(manifest,states)
    return dict(manifest=manifest,states=states)


def _iso_utc(value,label):
    if not isinstance(value,str): raise ValueError(f'{label} must be UTC ISO8601')
    try: dt=datetime.fromisoformat(value.replace('Z','+00:00'))
    except ValueError as exc: raise ValueError(f'{label} must be UTC ISO8601') from exc
    if dt.utcoffset() is None or dt.utcoffset().total_seconds()!=0: raise ValueError(f'{label} must be UTC ISO8601')
    return dt


def validate_profile(manifest, states, published_required=False):
    _canonical(manifest)
    try: ProfileManifest.model_validate(manifest)
    except Exception as exc: raise ValueError(f'Invalid profile manifest schema: {exc}') from exc
    _validate_states(states)
    if published_required and manifest['status']!='published': raise ValueError('A published profile revision is required')
    if manifest['states_sha256'] != hashlib.sha256(states_csv(states)).hexdigest(): raise ValueError('States SHA256 mismatch')
    if manifest['profile_hash'] != compute_profile_hash(manifest): raise ValueError('Profile hash mismatch')
    created=_iso_utc(manifest['created_at'],'created_at')
    m=manifest['measurement']
    if set(m)!=set(Measurement.model_fields): raise ValueError('Complete measurement conditions are required')
    for key in ('vds_v','read_vgs_v','pulse_width_s','interval_s','applied_pulse_count'): _number(m[key],key)
    if not math.isclose(m['vds_v'],.1,abs_tol=1e-12) or m['read_vgs_v']!=0 or m['pulse_width_s']!=.001 or m['interval_s']!=.001 or m['applied_pulse_count']!=512 or m['saturation_verified'] is not False:
        raise ValueError('Unsupported pulse measurement contract')
    sources={}
    for source in manifest['sources']:
        if not isinstance(source,dict) or any(not source.get(k) for k in ('file_id','sha256','filename','device_id','condition_id','columns','units')):
            raise ValueError('Every source requires complete provenance')
        if len(source['sha256'])!=64 or any(c not in '0123456789abcdef' for c in source['sha256']): raise ValueError('Invalid source SHA256')
        if source['condition_id']!=manifest['condition_id']: raise ValueError('Mixed source conditions in profile')
        if source.get('source_type','pulse_states')=='pulse_states':
            if source.get('read_vgs_v')!=m['read_vgs_v'] or source.get('vds_v')!=m['vds_v']: raise ValueError('Mixed pulse read biases in profile')

            sources.setdefault(source['file_id'],[]).append(source)
    extraction=manifest['extraction']
    for key in ('read_tolerance_v','write_threshold_v','start_time_s','iref_a','vds_v','read_vgs_v','retention_start_time_s'): _number(extraction.get(key),key)
    if extraction['write_threshold_v']<=extraction['read_tolerance_v'] or extraction['vds_v']!=.1 or extraction['read_vgs_v']!=0: raise ValueError('Invalid extraction thresholds or read bias')
    if extraction.get('parser_version')!=PARSER_VERSION or extraction.get('sample_offset_rows')!=2 or extraction.get('start_time_s') is None:
        raise ValueError('Extraction parser and thresholds are required')
    for state in states:
        if state['source_id'] not in sources: raise ValueError('State source is missing from provenance')
        candidates=[s for s in sources[state['source_id']] if s.get('direction')==state['direction'] and state['source_row'] in s.get('source_rows',[])]
        if len(candidates)!=1: raise ValueError('State must identify one explicit source row segment')
        source=candidates[0]
        if state['transition_row'] not in source['source_rows']: raise ValueError('Transition row missing from source provenance')
        identity=json.dumps([source['sha256'],source.get('sheet'),state['source_row'],extraction['parser_version']],separators=(',',':'),ensure_ascii=False)
        if state['state_id']!=hashlib.sha256(identity.encode()).hexdigest(): raise ValueError('State ID does not match immutable source coordinates')
        if not math.isclose(state['conductance_s'],state['id_a']/m['vds_v'],rel_tol=1e-12,abs_tol=1e-18): raise ValueError('State G is inconsistent with ID/VDS')
        if state['direction']!=source.get('direction'): raise ValueError('State direction conflicts with source')
        if state['time_s']<extraction['start_time_s'] or abs(state['vgs_v'])>extraction['read_tolerance_v']: raise ValueError('State violates extraction read constraints')
    if manifest['pools']!=make_pools(states): raise ValueError('Pools and G bounds must be calculated from the selected measured states')
    if manifest['c2c']!=dict(status='unavailable',cv=None,reason='not_provided'): raise ValueError('C2C is unavailable; do not fabricate a CV')
    d=manifest['d2d']
    if d.get('status') not in ('available','unavailable') or d.get('source_kind')!='iv_proxy' or d.get('physical_device_count')!=2 or d.get('distribution')!='assumed_lognormal': raise ValueError('Invalid D2D provenance contract')
    if d['status']=='available':
        if _number(d.get('cv'),'D2D cv')<0 or not isinstance(d.get('matched_conditions'),int) or d['matched_conditions']<1: raise ValueError('Available D2D requires nonnegative CV and matched conditions')
    elif d.get('cv') is not None: raise ValueError('Unavailable D2D must have cv=null')
    ret=manifest['retention']
    if ret.get('status') not in ('available','unavailable'): raise ValueError('Invalid retention status')
    if ret['status']=='unavailable' and (ret.get('program_fit') is not None or ret.get('erase_fit') is not None): raise ValueError('Unavailable retention cannot contain fitted values')
    if ret['status']=='available':
        for direction in ('program','erase'):
            fit=ret.get(direction+'_fit')
            if not isinstance(fit,dict): raise ValueError('Available retention requires both raw fits')
            for key in ('a','b','rmse','time_min_s','time_max_s'): _number(fit.get(key),'retention '+key)
            if fit['rmse']<0 or fit['time_min_s']<10 or fit['time_max_s']<=fit['time_min_s'] or not isinstance(fit.get('n'),int) or fit['n']<3: raise ValueError('Invalid retention fit bounds or sample count')
            if fit.get('r_squared') is not None: _number(fit['r_squared'],'retention r_squared')
        _number(ret.get('read_vgs_v'),'retention read_vgs_v')
        if ret.get('vds_v')!=.1: raise ValueError('Retention VDS must equal 0.1 V')
        expected=RETENTION_SOURCES.get(manifest['condition_id'])
        if ret.get('source_label')=='R3(2)': raise ValueError('R3(2) is explicitly excluded by the device team')
        if expected and (ret.get('source_label')!=expected[0] or not math.isclose(ret['read_vgs_v'],expected[1],abs_tol=1e-12)):
            raise ValueError('Retention source label/read bias conflicts with the approved condition')
        for source in manifest['sources']:
            if source.get('source_type')=='retention':
                same_bias=all(math.isclose(_number(source.get(k),'retention source '+k),ret[k],abs_tol=1e-12) for k in ('read_vgs_v','vds_v'))
                if source.get('source_label')!=ret.get('source_label') or not same_bias:
                    raise ValueError('Retention source provenance conflicts with fitted metadata')
        reference=ret['program_fit']['a']+ret['program_fit']['b']
        if not math.isfinite(reference): raise ValueError('Retention reference current is nonfinite')
        if ret.get('reference_time_s') is not None and _number(ret['reference_time_s'],'retention reference_time_s')!=10:
            raise ValueError('Retention reference time must be 10 seconds')
        if ret.get('program_reference_current_a') is not None:
            supplied=_number(ret['program_reference_current_a'],'retention program_reference_current_a')
            if not math.isclose(supplied,reference,rel_tol=1e-12,abs_tol=0.):
                raise ValueError('Retention reference current conflicts with Program fit at 10 seconds')
        if ret.get('simulation_available') is not None and ret['simulation_available'] is not (reference>0):
            raise ValueError('Retention simulation_available conflicts with Program reference current')
    if manifest['status']=='published':
        if not any(p['available'] for p in manifest['pools'].values()): raise ValueError('Publish requires at least one pool with two distinct positive conductances')
        published=_iso_utc(manifest['published_at'],'published_at')
        review=manifest['review']
        if not review.get('reviewer') or not review['reviewer'].strip() or not review.get('note') or not review['note'].strip(): raise ValueError('Publish requires a reviewer and adoption/exclusion note')
        reviewed=_iso_utc(review.get('reviewed_at'),'reviewed_at')
        if published<created or reviewed<created: raise ValueError('Review/publication cannot precede creation')
    elif manifest['published_at'] is not None: raise ValueError('Draft cannot have a publication timestamp')
    return deepcopy(manifest)


def publish_profile(manifest,states,reviewer,review_note):
    validate_profile(manifest,states)
    if manifest['status']!='draft': raise ValueError('Published revisions are immutable; create a new draft revision')
    if not isinstance(reviewer,str) or not reviewer.strip() or not isinstance(review_note,str) or not review_note.strip(): raise ValueError('Reviewer and review note are required')
    result=deepcopy(manifest); timestamp=_now()
    result.update(status='published',published_at=timestamp,review=dict(reviewer=reviewer.strip(),reviewed_at=timestamp,note=review_note.strip()))
    result['profile_hash']=compute_profile_hash(result)
    validate_profile(result,states,published_required=True)
    return result




def revise_profile(manifest, states, selected_state_ids=None, revision=None, display_name=None):
    """Create a distinct draft revision without editing its source revision."""
    validate_profile(manifest,states)
    next_revision=manifest['revision']+1 if revision is None else revision
    if isinstance(next_revision,bool) or not isinstance(next_revision,int) or next_revision<=manifest['revision']:
        raise ValueError('A new revision number must be greater than the source revision')
    result=deepcopy(manifest); copied=deepcopy(states)
    if selected_state_ids is not None:
        selected=set(selected_state_ids)
        if len(selected)!=len(selected_state_ids) or not selected<={s['state_id'] for s in copied}: raise ValueError('Selected state IDs must be unique and exist')
        for state in copied:
            state['selected']=state['state_id'] in selected
            state['exclusion_reason']=None if state['selected'] else state.get('exclusion_reason') or 'user_not_selected'
    result.update(revision=next_revision,status='draft',created_at=_now(),published_at=None,review=Review().model_dump(),pools=make_pools(copied),states_sha256=hashlib.sha256(states_csv(copied)).hexdigest())
    if display_name is not None: result['display_name']=display_name
    result['profile_hash']=compute_profile_hash(result)
    validate_profile(result,copied)
    return dict(manifest=result,states=copied)



