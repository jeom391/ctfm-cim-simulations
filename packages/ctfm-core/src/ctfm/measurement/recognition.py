"""Evidence-based source recognition; original cells and scientific rules remain intact."""
import hashlib
import re
from pathlib import PurePosixPath
from . import RETENTION_SOURCES, _load_raw, _prepare, analyze, parse_table
from .layouts import read_iv_blocks, read_retention_layout, retention_dataset, RETENTION_ROLES

RULE = 'measurement-recognition/1.0'
PULSE_MAPPING = dict(time_s='Time', id_a='MeasResult1_value', vgs_v='MeasResult2_value')
PULSE_UNITS = dict(time_s='s', id_a='A', vgs_v='V')


def evidence(source, field, value, scope, detail):
    source['evidence'].append(dict(field=field, value=value, scope=scope, rule=RULE, detail=detail))


def issue(source, code, detail, **location):
    source['issues'].append(dict(code=code, detail=detail, **location))


def pulse_onset(data, filename, item):
    """First sustained write departure, separately from its preceding j-2 read."""
    table = parse_table(data, filename, item.get('sheet'))
    dataset = dict(item, filename=filename, sha256=hashlib.sha256(data).hexdigest(), rows=table['rows'], source_rows=table['source_rows'])
    rows = _prepare(dataset, ['time_s', 'id_a', 'vgs_v'])
    read = [abs(r['vgs_v']) <= .05 for r in rows]
    departures, i = [], 0
    while i < len(rows):
        if read[i]:
            i += 1
            continue
        j = i
        while i < len(rows) and not read[i]:
            i += 1
        if not any(abs(r['vgs_v']) >= 5 for r in rows[j:i]):
            continue
        if i-j < 2 or j < 2 or not all(read[j-2:j]):
            raise ValueError('Write onset needs a sustained transition and two preceding read samples')
        expected = -1 if item['direction'] == 'ltp' else 1
        if any(r['vgs_v'] * expected <= 0 for r in rows[j:i]):
            raise ValueError(f'Pulse direction conflicts with waveform at source row {rows[j]["source_row"]}')
        departures.append(j)
    if not departures:
        raise ValueError('No sustained write transition reaches the project 5 V threshold')
    j = departures[0]
    return dict(write_onset_time_s=rows[j]['time_s'], write_onset_source_row=rows[j]['source_row'],
                preceding_read_time_s=rows[j-2]['time_s'], preceding_read_source_row=rows[j-2]['source_row'],
                recording_start_time_s=rows[0]['time_s'], row_count=len(rows), write_transition_count=len(departures),
                sample_offset_rows=2, read_tolerance_v=.05, write_threshold_v=5., pre_write_read_is_state=False), table['warnings']


def recognize_source(data, filename, file_id, snapshot_paths=(), resolution=None):
    resolution = resolution or {}
    digest = hashlib.sha256(data).hexdigest()
    source = dict(file_id=file_id, sha256=digest, name=filename, kind=None, condition_id=None, direction=None,
                  sheet=None, status='needs_choice', physical_identity='unverified', simulation_eligible=False,
                  evidence=[], issues=[], warnings=[], layout=None, pulse=None, measurement_group=None,
                  snapshot_paths=list(snapshot_paths), proposals=[])
    conditions = set(re.findall(r'(?<![A-Za-z0-9])A[1-5](?![0-9])', ' '.join([filename, *snapshot_paths])))
    if len(conditions) == 1:
        source['condition_id'] = next(iter(conditions))
        evidence(source, 'condition_id', source['condition_id'], 'snapshot_manifest' if snapshot_paths else 'filename', 'Condition token; not physical device identity')
    elif len(conditions) > 1:
        issue(source, 'conflicting_condition', f'Conflicting condition tokens: {sorted(conditions)}')
    if resolution.get('condition_id'):
        trusted_conditions = set(re.findall(r'(?<![A-Za-z0-9])A[1-5](?![0-9])', ' '.join(snapshot_paths)))
        if trusted_conditions and trusted_conditions != {resolution['condition_id']}:
            issue(source, 'conflicting_condition', 'Resolution conflicts with source condition evidence')
        else:
            source['condition_id'] = resolution['condition_id']
            if len(conditions) > 1:
                source['issues'] = [i for i in source['issues'] if i['code'] != 'conflicting_condition']
                evidence(source, 'observed_condition_tokens', sorted(conditions), 'filename', 'Conflict resolved explicitly; original tokens retained')
    directions = set(d.lower() for d in re.findall(r'(?i)(?<![a-z])lt[dp](?![a-z])', ' '.join([filename, *[PurePosixPath(p).name for p in snapshot_paths]])))
    if len(directions) == 1:
        source['direction'] = next(iter(directions))
        evidence(source, 'direction', source['direction'], 'snapshot_manifest' if snapshot_paths else 'filename', 'Direction token, checked against waveform')
    if resolution.get('direction'):
        source['direction'] = resolution['direction']
    try:
        raw, sheets, _, sheet = _load_raw(data, filename, resolution.get('sheet'))
        source['sheet'] = sheet
        if 'Origin_data' in sheets:
            source['kind'], source['sheet'] = 'c2c_detrended', 'Origin_data'
        elif 'Raw Data' in sheets:
            source['kind'], source['sheet'] = 'retention', 'Raw Data'
        elif raw and [str(v).strip() for v in raw[0][:3]] == ['Vg','Id','Ig']:
            source['kind'] = 'iv'
        elif source['direction'] or filename.lower().endswith('.csv'):
            source['kind'] = 'pulse_states'
        if resolution.get('kind'):
            source['kind'] = resolution['kind']
        if not source['kind']:
            source['status'] = 'unsupported'
            issue(source, 'unsupported_layout', 'No supported measurement layout recognized')
            return source
        for field, value in resolution.items():
            if field not in ('file_id','reason') and value is not None:
                evidence(source, field, value, 'user_confirmed', resolution['reason'])
        if not source['condition_id']:
            issue(source, 'condition_required', 'Select the measurement condition; it is not a physical device ID')
        base = dict(file_id=file_id, condition_id=source['condition_id'] or 'unresolved',
                    device_id='measurement-source:' + digest, sheet=source['sheet'], vds_v=.1, read_vgs_v=0.)
        if source['kind'] == 'pulse_states':
            if resolution.get('read_vgs_v') not in (None, 0.):
                source['status'] = 'invalid'
                issue(source, 'conflicting_pulse_read_bias', 'Pulse analysis requires read VGS=0 V; the supplied read_vgs_v conflicts with the fixed protocol')
            table = parse_table(data, filename, source['sheet'])
            metadata = _load_raw(data, filename, source['sheet'])[0]
            source['layout'] = dict(columns=table['columns'], metadata_rows=metadata[:table['source_rows'][0]-2] if table['source_rows'] else metadata)
            mapping, units = resolution.get('column_mapping'), resolution.get('units')
            if snapshot_paths and set(PULSE_MAPPING.values()) <= set(table['columns']):
                mapping, units = mapping or PULSE_MAPPING.copy(), units or PULSE_UNITS.copy()
                evidence(source, 'units', units, 'user_confirmed' if resolution.get('units') else 'project_assumption', 'Approved instrument mapping: time=s, result1=absolute A, result2=V')
                evidence(source, 'column_mapping', mapping, 'user_confirmed' if resolution.get('column_mapping') else 'project_assumption', 'Instrument mapping, not terminal names asserted by headers')
                source['measurement_group'] = 'snapshot:2026-09-29:' + str(PurePosixPath(sorted(snapshot_paths)[0]).parent)
                evidence(source, 'measurement_group', source['measurement_group'], 'snapshot_manifest', 'Byte-identical curated source and acquisition folder')
            if resolution.get('measurement_group'):
                source['measurement_group'] = 'user:' + resolution['measurement_group']
            if not mapping or not units:
                issue(source, 'mapping_units_required', 'Explicit channel mapping and units are needed for this source')
            if not source['direction']:
                issue(source, 'direction_required', 'Choose LTP or LTD; waveform polarity will be verified')
            if not source['measurement_group']:
                issue(source, 'measurement_group_required', 'Confirm the acquisition group containing this source and its opposite direction')
            if not source['issues']:
                item = dict(base, direction=source['direction'], column_mapping=mapping, units=units)
                source['pulse'], source['warnings'] = pulse_onset(data, filename, item)
                item['start_time_s'] = source['pulse']['write_onset_time_s']
                evidence(source, 'start_time_s', item['start_time_s'], 'waveform', 'First sustained write departure; preceding j-2 read preserved but excluded as pre-write')
                evidence(source, 'read_bias', dict(read_vgs_v=0., vds_v=.1), 'project_assumption', 'Approved pulse read bias; write/read duration 1 ms is a project protocol assumption')
                source['proposals'] = [dict(kind='pulse_states', inputs=[item], settings={})]
        elif source['kind'] == 'iv':
            layout = read_iv_blocks(data, filename, source['sheet'])
            source['sheet'], source['layout'] = layout['sheet'], layout
            units = resolution.get('units') or (dict(vgs_v='V', id_a='A') if snapshot_paths else None)
            if not units:
                issue(source, 'units_required', 'Vg/Id headers do not prove V/A units; confirm units')
            else:
                evidence(source, 'units', units, 'user_confirmed' if resolution.get('units') else 'project_assumption', 'IV instrument mapping')
                evidence(source, 'branch', 'increasing=erase; decreasing=program', 'project_assumption', 'Established IV branch convention')
                evidence(source, 'physical_identity', 'unverified', 'snapshot_manifest' if snapshot_paths else 'filename', 'Run labels and copied folders do not establish devices; D2D requires explicit identity evidence')
                for block in layout['blocks']:
                    if block['status'] != 'ok':
                        issue(source, 'invalid_iv_block', block['error'], block=block['index'])
                        continue
                    amplitude = block['proposed_amplitude_v'] * (1e-3 if units.get('vgs_v') == 'mV' else 1)
                    if not 1 <= amplitude <= 15:
                        issue(source, 'unsupported_iv_amplitude', f'Block amplitude {amplitude} V outside 1..15', block=block['index'])
                        continue
                    groups = {'erase': [], 'program': []}
                    for seg in block['segments']:
                        if seg['points'] < 2:
                            continue
                        branch = 'erase' if seg['direction'] == 'increasing' else 'program'
                        groups[branch].append(dict(base, sheet=layout['sheet'], branch=branch, units=units,
                            sweep_amplitude_v=amplitude, selection=dict(type='iv_block', block=block['index'], segment=seg['index'])))
                    combinations = [[e,p] for e in groups['erase'] for p in groups['program']]
                    if not combinations:
                        combinations = [[i] for i in groups['erase'] + groups['program']]
                    source['proposals'].extend(dict(kind='iv', inputs=items, settings={}) for items in combinations)
        elif source['kind'] == 'retention':
            source['layout'] = read_retention_layout(data, filename, 'Raw Data')
            units = resolution.get('units') or ({r:'s' if r.endswith('time_s') else 'A' for r in RETENTION_ROLES} if snapshot_paths else None)
            approved = RETENTION_SOURCES.get(source['condition_id']) if snapshot_paths else None
            label = resolution.get('source_label') or (approved[0] if approved else None)
            bias = resolution.get('read_vgs_v', approved[1] if approved else None)
            if not units or not label or bias is None:
                issue(source, 'retention_source_required', 'Confirm raw source label, per-column units and source-specific read VGS')
            else:
                headers = source['layout']['embedded_source_headers']
                header_bias = next((h['read_bias_v'][0] for h in headers if h['read_bias_v']), None)
                evidence(source, 'retention_source', dict(source_label=label, read_vgs_v=bias, vds_v=.1), 'project_source' if approved else 'user_confirmed', 'RETENTION_SOURCES approved mapping; embedded normalized headers remain provenance')
                evidence(source, 'units', units, 'project_assumption' if not resolution.get('units') else 'user_confirmed', 'Raw absolute currents and independent time axes')
                item = dict(base, sheet='Raw Data', source_label=label, read_vgs_v=bias, header_read_vgs_v=header_bias, units=units,
                            selection=dict(type='retention_columns', columns=dict(zip(RETENTION_ROLES, range(4)))))
                dataset = retention_dataset(data, filename, columns=item['selection']['columns'], condition_id=base['condition_id'], device_id=base['device_id'], file_id=file_id, sha256=digest,
                    source_label=label, units=units, read_vgs_v=bias, header_read_vgs_v=header_bias)
                analyze('retention', [dataset], {})
                source['layout'].update(source_rows=dataset['source_rows'], skipped_blank_rows=dataset['skipped_blank_rows'])
                source['proposals'] = [dict(kind='retention', inputs=[item], settings={})]
        elif source['kind'] == 'c2c_detrended':
            from .c2c import analyze_c2c_file, C2CAnalysisError
            try:
                result = analyze_c2c_file(data, filename, sheet='Origin_data', condition_id=base['condition_id'], device_id=base['device_id'])
                source['layout'] = dict(provenance=result['provenance'])
                source['warnings'].append('Statistical calculation is not independent-noise simulation approval; conditions remain unknown')
                source['proposals'] = [dict(kind='c2c_detrended', inputs=[dict(file_id=file_id, sheet='Origin_data', condition_id=base['condition_id'], device_id=base['device_id'])], settings={})]
            except ValueError as exc:
                source['status'] = 'invalid'
                for detail in getattr(exc, 'issues', [dict(code='invalid_c2c_layout', detail=str(exc))]):
                    match = re.search(r'(?:source row|Row) (\d+)', detail['detail'])
                    issue(source, detail['code'], detail['detail'], sheet='Origin_data', source_row=int(match[1]) if match else None)
            # Include original cells and gaps, even those hidden by the parser's first failure.
            cells = _load_raw(data, filename, 'Origin_data')[0]
            source['layout'] = {**(source['layout'] or {}), 'header': cells[0], 'source_row_first': 2, 'source_row_last': len(cells),
                'measurement_notes': _load_raw(data, filename, 'Measurement_note')[0] if 'Measurement_note' in sheets else []}
            prior = None
            for n, row in enumerate(cells[1:], 2):
                for c, value in enumerate(row[:4]):
                    if value is None or value == '--' or (c in (1,2) and isinstance(value,(float,int)) and value <= 0):
                        issue(source, 'invalid_c2c_cell', f'Original value {value!r}; no correction applied', sheet='Origin_data', source_row=n, cell=f'{chr(65+c)}{n}')
                for c, value in enumerate(row[4:], 4):
                    if value not in (None, '') and (len(cells[0]) <= c or cells[0][c] in (None, '')):
                        issue(source, 'unlabelled_c2c_cell', f'Unlabelled original value {value!r}; not a confirmed unit or condition', sheet='Origin_data', source_row=n, cell=f'{chr(65+c)}{n}')
                cycle = row[0]
                if isinstance(cycle,(float,int)):
                    if prior is not None and cycle-prior > 1:
                        issue(source, 'cycle_gaps', f'Missing cycles {int(prior)+1}..{int(cycle)-1}', sheet='Origin_data', source_row=n, cell=f'A{n}')
                    prior = cycle
            if source['issues']:
                source['status'], source['proposals'] = 'invalid', []
            evidence(source, 'measurement_conditions', None, 'unknown', 'Conflicting notes do not confirm write/read conditions')
        fatal = [i for i in source['issues'] if i['code'] not in ('invalid_iv_block','unsupported_iv_amplitude')]
        if source['proposals'] and not fatal:
            source['status'] = 'ready'
        elif fatal:
            source['proposals'] = []
    except (ValueError, TypeError, KeyError) as exc:
        source['status'], source['proposals'] = 'invalid', []
        issue(source, 'invalid_source', str(exc))
    return source
