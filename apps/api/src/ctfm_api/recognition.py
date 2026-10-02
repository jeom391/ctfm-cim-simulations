"""Persist server-built recognition plans and verify their exact requests at enqueue."""
import json
from collections import defaultdict
from pathlib import Path
from uuid import uuid4

from ctfm.measurement.recognition import RULE, SNAPSHOT_DATE, recognize_source, issue
from .contracts import AnalysisRequest, RecognitionResult
from .storage import sha256


def snapshot_index():
    path = Path(__file__).resolve().parents[4] / f'data/team-snapshot/{SNAPSHOT_DATE}/manifest.json'
    index = defaultdict(list)
    if path.is_file():
        for entry in json.loads(path.read_text(encoding='utf-8-sig'))['files']:
            index[entry['sha256']].append(entry['path'])
    return index


def source_bytes(store, file_id):
    record = store.get_entity('file', str(file_id))
    data = store.managed_path(record['relative_path']).read_bytes()
    if sha256(data) != record['sha256']:
        raise ValueError('Source file hash mismatch')
    return record, data


def create_recognition(store, request):
    ids = [str(f) for f in request.file_ids]
    if len(ids) != len(set(ids)):
        raise ValueError('Recognition file_ids must be distinct')
    resolutions = {str(r.file_id): r.model_dump(mode='json', exclude_none=True) for r in request.resolutions}
    if len(resolutions) != len(request.resolutions) or not set(resolutions) <= set(ids):
        raise ValueError('Each resolution must name one distinct requested source')
    index, sources, proposals = snapshot_index(), [], {}
    for identifier in sorted(ids):
        record, data = source_bytes(store, identifier)
        source = recognize_source(data, record['name'], identifier, index.get(record['sha256'], []), resolutions.get(identifier))
        proposals[identifier] = source.pop('proposals')
        try:
            for proposal in proposals[identifier]:
                AnalysisRequest.model_validate(proposal)
        except ValueError as exc:
            source['status'] = 'invalid'
            issue(source, 'invalid_resolution', str(exc))
            proposals[identifier] = []
        sources.append(source)
    # Identical bytes cannot become an additional acquisition/device through re-upload.
    hashes = defaultdict(list)
    for source in sources:
        hashes[source['sha256']].append(source)
    for group in hashes.values():
        if len(group) > 1:
            for source in group:
                source['status'] = 'needs_choice'
                issue(source, 'duplicate_source', 'Identical bytes supplied more than once; select one upload ID')
                proposals[source['file_id']] = []
    recognition_id = str(uuid4())
    requests, pairs, groups = [], [], defaultdict(list)
    for source in sources:
        if source['kind'] == 'pulse_states':
            if source['measurement_group']:
                groups[(source['condition_id'], source['measurement_group'])].append(source)
        elif source['status'] == 'ready':
            requests.extend(proposals[source['file_id']])
    for (condition, key), group in sorted(groups.items(), key=lambda item: (item[0][0] or '', item[0][1])):
        good = (len(group) == 2 and {s['direction'] for s in group} == {'ltp','ltd'} and all(s['status']=='ready' for s in group))
        pair = dict(pair_key=key, condition_id=condition or 'unresolved', file_ids=sorted(s['file_id'] for s in group),
                    status='ready' if good else 'needs_choice', basis='snapshot_manifest' if key.startswith('snapshot:') else 'user_confirmed')
        pairs.append(pair)
        if good:
            inputs = [proposals[s['file_id']][0]['inputs'][0] for s in sorted(group, key=lambda s:s['direction'])]
            onsets = {i['start_time_s'] for i in inputs}
            requests.append(dict(kind='pulse_states', inputs=inputs, settings=dict(start_time_s=min(onsets))))
        else:
            for source in group:
                if source['status'] == 'ready':
                    source['status'] = 'needs_choice'
                issue(source, 'pulse_pair_required', 'Need exactly one LTP and one LTD in this acquisition; select a pair or upload its missing direction')
    validated = []
    for proposal in requests:
        validated.append(AnalysisRequest(**proposal, recognition_id=recognition_id).model_dump(mode='json', exclude_none=True))
    result = RecognitionResult(recognition_id=recognition_id, rule=RULE, sources=sorted(sources,key=lambda s:(s['condition_id'] or '',s['name'],s['file_id'])), pulse_pairs=pairs, requests=validated)
    payload = result.model_dump(mode='json')
    payload['requests'] = validated
    store.put_entity('recognition', recognition_id, payload)
    return payload


def verify_recognized_request(store, request):
    """Client can select a stored proposal but cannot invent or modify its evidence."""
    if not request.recognition_id:
        return None
    plan = store.get_entity('recognition', str(request.recognition_id))
    canonical = request.model_dump(mode='json', exclude_none=True)
    if canonical not in plan['requests']:
        raise ValueError('Recognition request differs from the server plan; resolve choices through measurements/recognize')
    by_id = {s['file_id']:s for s in plan['sources']}
    used = sorted({str(i.file_id) for i in request.inputs})
    for identifier in used:
        record, _ = source_bytes(store, identifier)
        if record['sha256'] != by_id[identifier]['sha256']:
            raise ValueError('Recognition source hash is stale')
    return dict(recognition_id=plan['recognition_id'], rule=plan['rule'], sources=[by_id[i] for i in used],
                pulse_pairs=[p for p in plan['pulse_pairs'] if set(p['file_ids']) == set(used)])



def resolve_d2d(store, request, exclusions=None):
    """User identifies two devices; server verifies source, condition, block and branch.

    ``exclusions`` (pair flow) lists matched-condition gaps found before analysis, kept as
    per-source issues so the analysis result carries them through ``recognition``."""
    from ctfm.measurement import analyze
    from ctfm.measurement.layouts import read_iv_blocks, iv_dataset
    from ctfm.measurement.recognition import evidence
    devices = {s.device_id.strip() for s in request.selections}
    if len(devices) != 2 or any(not d or d.startswith('measurement-source:') for d in devices):
        raise ValueError('D2D requires exactly two explicitly confirmed physical device IDs')
    index, sources, inputs, datasets, ownership, files = snapshot_index(), {}, [], [], {}, {}
    for selection in request.selections:
        identifier = str(selection.file_id)
        if not selection.identity_evidence.strip():
            raise ValueError('Physical device identity evidence is required')
        if identifier not in files:
            record, data = source_bytes(store, identifier)
            files[identifier] = (record, data, read_iv_blocks(data, record['name'], selection.sheet))
        record, data, layout = files[identifier]
        digest = record['sha256']
        if digest in ownership and ownership[digest] != selection.device_id:
            raise ValueError('One physical source cannot be assigned to two distinct devices')
        ownership[digest] = selection.device_id
        if identifier not in sources:
            source = recognize_source(data, record['name'], identifier, index.get(digest, []),
                                      dict(file_id=identifier, condition_id=request.condition_id, kind='iv', sheet=selection.sheet,
                                           units=selection.units, reason=selection.identity_evidence))
            source.pop('proposals')
            if any(i['code'] not in ('invalid_iv_block','unsupported_iv_amplitude') for i in source['issues']):
                raise ValueError('D2D source has unresolved/conflicting evidence: ' + str(source['issues']))
            source['physical_identity'], source['status'] = 'user_confirmed', 'ready'
            evidence(source, 'physical_identity', selection.device_id, 'user_confirmed', selection.identity_evidence)
            sources[identifier] = source
        if selection.block >= len(layout['blocks']):
            raise ValueError('D2D block does not exist')
        block = layout['blocks'][selection.block]
        if block['status'] != 'ok' or selection.segment >= len(block['segments']):
            raise ValueError('D2D block or segment is invalid')
        segment = block['segments'][selection.segment]
        branch = 'erase' if segment['direction']=='increasing' else 'program'
        amplitude = block['proposed_amplitude_v'] * (1e-3 if selection.units.get('vgs_v')=='mV' else 1)
        item = dict(file_id=identifier, device_id=selection.device_id, condition_id=request.condition_id,
                    sheet=layout['sheet'], units=selection.units, branch=branch, sweep_amplitude_v=amplitude,
                    read_vgs_v=0., vds_v=.1, selection=dict(type='iv_block', block=selection.block, segment=selection.segment))
        inputs.append(item)
        datasets.append(iv_dataset(data, record['name'], block=selection.block, segment=selection.segment, branch=branch,
            sweep_amplitude_v=amplitude, device_id=selection.device_id, condition_id=request.condition_id,
            file_id=identifier, sha256=digest, sheet=layout['sheet'], units=selection.units))
    for item in exclusions or []:
        issue(sources[item['file_id']], 'd2d_condition_excluded', item['detail'], block=item.get('block'))
    matched = {(i['sweep_amplitude_v'],i['branch']) for i in inputs}
    if any({i['device_id'] for i in inputs if (i['sweep_amplitude_v'],i['branch'])==key} != devices for key in matched):
        raise ValueError('D2D needs matched amplitude/branch for both physical devices')
    analyze('d2d', datasets, {})
    recognition_id = str(uuid4())
    proposal = AnalysisRequest(kind='d2d', inputs=inputs, recognition_id=recognition_id)
    payload = RecognitionResult(recognition_id=recognition_id, rule=RULE, sources=list(sources.values()), pulse_pairs=[], requests=[proposal]).model_dump(mode='json')
    payload['requests'] = [proposal.model_dump(mode='json', exclude_none=True)]
    store.put_entity('recognition', recognition_id, payload)
    return payload


def pair_conditions(layouts):
    """Every (amplitude, branch) both files measure exactly once -> {key: [(block, segment) per file]}.

    Erase is the increasing sweep; Program is the decreasing sweep that follows it (the full +A -> -A
    branch). An initial 0 -> -A half sweep is not a Program branch and is never mixed in. A file with
    a repeated amplitude block cannot be matched without guessing, so that amplitude is excluded."""
    found, exclusions = [], []
    for position, layout in enumerate(layouts):
        per, seen = {}, {}
        for block in layout['blocks']:
            if block['status'] != 'ok':
                continue
            seen.setdefault(block['proposed_amplitude_v'], []).append(block['index'])
            segments = block['segments']
            erase = [s for s in segments if s['direction'] == 'increasing']
            program = [s for k, s in enumerate(segments) if s['direction'] == 'decreasing' and k and segments[k-1]['direction'] == 'increasing']
            for branch, chosen in (('erase', erase), ('program', program)):
                if len(chosen) == 1:
                    per[(block['proposed_amplitude_v'], branch)] = (block['index'], chosen[0]['index'])
                else:
                    exclusions.append(dict(position=position, block=block['index'], detail=f"{block['proposed_amplitude_v']:g} V {branch}: 블록 {block['index']}에 후보 구간이 {len(chosen)}개라 대응시키지 않음"))
        for amplitude, blocks in seen.items():
            if len(blocks) > 1:
                for branch in ('erase', 'program'):
                    per.pop((amplitude, branch), None)
                exclusions.append(dict(position=position, block=blocks[0], detail=f'{amplitude:g} V 블록이 {len(blocks)}개 {blocks} 있어 하나를 임의로 고르지 않고 이 진폭을 제외'))
        found.append(per)
    keys = sorted(set(found[0]) & set(found[1]))
    for position, per in enumerate(found):
        for key in sorted(set(per) - set(keys)):
            exclusions.append(dict(position=position, block=per[key][0], detail=f'{key[0]:g} V {key[1]}: 다른 파일에 하나로 대응되는 조건이 없음'))
    return {key: [found[0][key], found[1][key]] for key in keys}, exclusions


def resolve_d2d_pair(store, request):
    """Two designated files (one per physical device): the server matches every common condition."""
    from ctfm.measurement.layouts import read_iv_blocks
    from .contracts import D2DRecognitionRequest
    if len({str(d.file_id) for d in request.devices}) != 2:
        raise ValueError('Choose two different files')
    layouts = []
    for device in request.devices:
        record, data = source_bytes(store, str(device.file_id))
        layouts.append(read_iv_blocks(data, record['name'], device.sheet))
    keys, exclusions = pair_conditions(layouts)
    if not keys:
        raise ValueError('The two files share no uniquely matched amplitude/branch condition')
    selections = [dict(file_id=device.file_id, device_id=device.device_id, identity_evidence=device.identity_evidence,
                       sheet=layouts[n]['sheet'], block=pair[n][0], segment=pair[n][1], units=request.units)
                  for pair in keys.values() for n, device in enumerate(request.devices)]
    for item in exclusions:
        item['file_id'] = str(request.devices[item.pop('position')].file_id)
    return resolve_d2d(store, D2DRecognitionRequest(condition_id=request.condition_id, selections=selections), exclusions)
