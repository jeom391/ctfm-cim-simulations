"""Production parser regressions against the shared, hash-pinned measurements."""
import hashlib
import json
from pathlib import Path

import pytest
from ctfm.measurement import parse_table, analyze
from ctfm.profiles import build_profile, publish_profile

BASE = Path(__file__).resolve().parents[3] / 'data/reference/ltp-ltd-2026-09-21'
FILES = json.loads((BASE / 'manifest.json').read_text(encoding='utf-8'))['files']


def load_dataset(f):
    raw = (BASE / f['file']).read_bytes()
    assert hashlib.sha256(raw).hexdigest() == f['sha256']
    table = parse_table(raw, Path(f['file']).name)
    assert len(table['rows']) == f['data_count']
    assert table['source_rows'] == list(range(f['data_start_row'], f['data_end_row'] + 1))
    return dict(file_id=f['file'], filename=Path(f['file']).name, sha256=f['sha256'],
                device_id=f['condition_id']+'-regression', condition_id=f['condition_id'],
                direction=f['direction'], column_mapping=f['column_mapping'], units=f['units'],
                read_vgs_v=0., vds_v=.1, rows=table['rows'], source_rows=table['source_rows'])


@pytest.mark.parametrize('f', FILES, ids=[f['file'] for f in FILES])
def test_latest_files_extract_original_rows_and_measured_values(f):
    result = analyze('pulse_states', [load_dataset(f)], {})
    states = result['states']
    assert len(states) == f['reference_candidate_count']
    for state, expected in [(states[0], f['reference_first_sample']),
                            (states[-1], f['reference_last_sample'])]:
        for key, value in expected.items():
            assert state[key] == pytest.approx(value, rel=1e-12, abs=1e-14)
    for state in states:
        assert state['source_row'] == state['transition_row'] - 2
        assert state['time_s'] >= 6
        assert state['conductance_s'] == pytest.approx(state['id_a'] / .1)


HEADER = 'Time,MeasResult1_value,MeasResult2_value'


@pytest.mark.parametrize('condition', ['A1', 'A2', 'A3', 'A4', 'A5'])
def test_latest_direction_pair_builds_and_publishes_profile(condition):
    datasets = [load_dataset(f) for f in FILES if f['condition_id'] == condition]
    result = analyze('pulse_states', datasets, {})
    profile = build_profile(condition, result, [s['state_id'] for s in result['states']])
    manifest, states = profile['manifest'], profile['states']
    published = publish_profile(manifest, states, 'regression-test', 'Verify current shared data')
    assert published['status'] == 'published'
    assert len(states) == 1020



def test_unknown_trailing_table_is_not_silently_discarded():
    with pytest.raises(ValueError, match='trailing|auxiliary'):
        parse_table((HEADER+'\n6,1e-6,0\n\n,,,unknown\n').encode(), 'raw.csv')


def test_multiple_primary_tables_are_ambiguous():
    with pytest.raises(ValueError, match='Multiple'):
        parse_table((HEADER+'\n6,1e-6,0\n\n'+HEADER+'\n7,2e-6,0').encode(), 'raw.csv')


def test_blank_inside_measurements_is_not_a_license_to_drop_data():
    with pytest.raises(ValueError, match='trailing|auxiliary'):
        parse_table((HEADER+'\n6,1e-6,0\n\n7,2e-6,0').encode(), 'raw.csv')


def test_bad_measurement_value_remains_visible():
    t = parse_table((HEADER+'\n6,bad,0\n6.1,1e-6,0\n6.2,0,10').encode(), 'raw.csv')
    assert t['rows'][0]['MeasResult1_value'] == 'bad'
    assert t['source_rows'] == [2, 3, 4]


def test_metadata_exclusion_is_reported():
    t = parse_table(('Device ID,\nRemarks,test\n'+HEADER+'\n6,1e-6,0\n\n,,,MeasResult1_time,MeasResult1_value\n,,,6,1e-6').encode(), 'raw.csv')
    assert t['source_rows'] == [4]
    assert any('metadata' in w for w in t['warnings'])
    assert any('auxiliary' in w for w in t['warnings'])


def test_numeric_prefix_is_not_discarded_as_metadata():
    with pytest.raises(ValueError, match='metadata'):
        parse_table(('5,1e-6,0\n'+HEADER+'\n6,1e-6,0').encode(), 'raw.csv')


def test_bad_measurement_value_fails_analysis_with_source_row():
    dataset = load_dataset(FILES[0])
    dataset['rows'][0]['MeasResult1_value'] = 'bad'
    with pytest.raises(ValueError, match='row .*finite number'):
        analyze('pulse_states', [dataset], {})
