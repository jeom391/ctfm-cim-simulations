"""Measured C2C detrending analysis (docs/c2c-detrending-decision-2026-09-26.md)."""
import hashlib
import io
import os
from copy import deepcopy
from pathlib import Path

import numpy as np
import pytest
from openpyxl import Workbook

from ctfm.measurement import parse_table
from ctfm.measurement.c2c import C2CAnalysisError, _lag1, analyze_c2c, analyze_c2c_file

A3_SHA256 = '488877d82c3a191945dcf749bb76637807d521b93392ef7f81d6f6a570ce6ae3'
A3_PATH = Path(os.environ.get('CTFM_A3_C2C_FILE') or
               Path(__file__).resolve().parents[5] / '관련 자료/C2C/_26CTFM_A3_1000Cycle_.xlsx')


def trend(n, coefficients, n_min, n_max):
    x = 2 * (n - n_min) / (n_max - n_min) - 1
    return sum(c * x ** k for k, c in enumerate(coefficients))


def workbook(cycles, program, erase, unit='uA', difference=True, sheet='Origin_data'):
    wb = Workbook()
    ws = wb.active
    ws.title = sheet
    header = ['Cycle', f'Program_Id_{unit}', f'Erase_Id_{unit}'] + ([f'Erase_minus_Program_{unit}'] if difference else [])
    ws.append(header)
    for c, p, e in zip(cycles, program, erase):
        ws.append([c, p, e] + ([e - p] if difference else []))
    buffer = io.BytesIO()
    wb.save(buffer)
    return buffer.getvalue()


def synthetic(n=1000, seed=7, noise=0.01):
    cycles = np.arange(1, n + 1)
    rng = np.random.default_rng(seed)
    program = trend(cycles, [75, 3, -2, 1], 1, n) * (1 + noise * rng.standard_normal(n))
    erase = trend(cycles, [92, 2, -1.5, .5], 1, n) * (1 + noise * rng.standard_normal(n))
    return cycles, program, erase


def analyze(data, **kw):
    return analyze_c2c_file(data, 'synthetic.xlsx', **kw)


def test_pure_cubic_is_recovered_exactly_with_zero_deviation():
    cycles = np.arange(1, 201)
    program = trend(cycles, [75, 3, -2, 1], 1, 200)
    erase = trend(cycles, [92, 2, -1.5, .5], 1, 200)
    result = analyze(workbook(cycles.tolist(), program.tolist(), erase.tolist()))
    assert result['program']['primary']['coefficients'] == pytest.approx([75, 3, -2, 1], rel=1e-9)
    assert result['erase']['primary']['coefficients'] == pytest.approx([92, 2, -1.5, .5], rel=1e-9)
    assert result['program']['primary']['relative_residual_std_percent'] < 1e-9
    assert result['erase']['primary']['relative_residual_std_percent'] < 1e-9


def test_known_relative_deviation_is_recovered_and_is_not_the_raw_std():
    cycles, program, erase = synthetic()
    result = analyze(workbook(cycles.tolist(), program.tolist(), erase.tolist()))
    z = program / trend(cycles, [75, 3, -2, 1], 1, 1000) - 1
    truth = 100 * np.std(z, ddof=1)
    got = result['program']['primary']['relative_residual_std_percent']
    assert got == pytest.approx(truth, rel=0.02)
    assert 0.9 < got < 1.1
    raw = result['program']['raw_statistics']['relative_std_percent']
    assert raw > 2 * got, 'raw std must be preserved and larger than the detrended value'


def test_scale_invariance_between_ua_and_na_headers():
    cycles, program, erase = synthetic(n=300)
    a = analyze(workbook(cycles.tolist(), program.tolist(), erase.tolist(), unit='uA'))
    b = analyze(workbook(cycles.tolist(), (program * 1e3).tolist(), (erase * 1e3).tolist(), unit='nA'))
    for branch in ('program', 'erase'):
        for degree in ('1', '2', '3', '4'):
            x, y = a[branch]['sensitivity'][degree], b[branch]['sensitivity'][degree]
            assert x['relative_residual_std_percent'] == pytest.approx(y['relative_residual_std_percent'], rel=1e-9)
            assert x['residual_lag1_correlation'] == pytest.approx(y['residual_lag1_correlation'], rel=1e-9)
            assert np.array(y['coefficients']) == pytest.approx(np.array(x['coefficients']) * 1e3, rel=1e-9)
    assert a['provenance']['unit_scale_to_ampere'] == 1e-6 and b['provenance']['unit_scale_to_ampere'] == 1e-9


def test_program_and_erase_are_independent_and_never_combined():
    cycles, program, erase = synthetic(n=300)
    a = analyze(workbook(cycles.tolist(), program.tolist(), erase.tolist()))
    b = analyze(workbook(cycles.tolist(), program.tolist(), (erase * 1.7 + 3).tolist()))
    assert a['program'] == b['program']
    assert a['erase']['primary']['relative_residual_std_percent'] != b['erase']['primary']['relative_residual_std_percent'] or \
        a['erase']['primary']['coefficients'] != b['erase']['primary']['coefficients']
    use = a['simulator_use']
    assert use['candidate_branch'] == 'program' and use['erase_role'] == 'analysis_only'
    assert use['candidate_relative_std_percent'] == a['program']['primary']['relative_residual_std_percent']
    assert use['approved_for_simulator'] is False
    assert not any('average' in key or 'mean_cv' in key for key in a)


def test_difference_column_is_check_only():
    cycles, program, erase = synthetic(n=100)
    good = workbook(cycles.tolist(), program.tolist(), erase.tolist())
    assert analyze(good)['difference_check']['status'] == 'consistent'
    table = parse_table(good, 'x.xlsx')
    table['rows'][10]['Erase_minus_Program_uA'] += 5
    bad = analyze_c2c(table, filename='x.xlsx')
    reference = analyze_c2c(parse_table(good, 'x.xlsx'), filename='x.xlsx')
    assert bad['difference_check']['status'] == 'mismatch'
    assert any('disagrees' in w for w in bad['warnings'])
    assert bad['program'] == reference['program'] and bad['erase'] == reference['erase']
    assert analyze(workbook(cycles.tolist(), program.tolist(), erase.tolist(), difference=False))['difference_check']['status'] == 'not_provided'


def test_result_flags_model_dependence_and_records_reproducibility_fields():
    cycles, program, erase = synthetic(n=200)
    data = workbook(cycles.tolist(), program.tolist(), erase.tolist())
    r = analyze(data, device_id='dev-1', condition_id='A3')
    assert r['is_pure_c2c_iid_estimate'] is False
    assert any('NOT a pure C2C' in w for w in r['warnings'])
    assert r['method']['ddof'] == 1 and r['method']['primary_degree'] == 3 and r['method']['extrapolation'] is False
    p = r['provenance']
    assert p['sha256'] == hashlib.sha256(data).hexdigest() and (p['cycle_min'], p['cycle_max'], p['cycle_count']) == (1, 200, 200)
    assert p['unit'] == 'uA' and p['device_id'] == 'dev-1' and p['columns']['program'] == 'Program_Id_uA'
    assert r['program']['degree4_vs_degree3_change_percent'] is not None
    assert set(r['program']['sensitivity']) == {'1', '2', '3', '4'}


def test_measurement_conditions_default_unconfirmed_and_never_borrowed():
    cycles, program, erase = synthetic(n=50)
    data = workbook(cycles.tolist(), program.tolist(), erase.tolist())
    r = analyze(data)
    assert all(c == dict(value=None, confirmed=False) for c in r['measurement_conditions'].values())
    assert r['measurement_conditions']['vds_v']['value'] is None
    assert any('not confirmed' in w and 'LTP/LTD' in w for w in r['warnings'])
    r2 = analyze(data, measurement_conditions=dict(program_voltage_v=10, vds_v=0.1))
    assert r2['measurement_conditions']['program_voltage_v'] == dict(value=10, confirmed=True)
    assert r2['measurement_conditions']['read_time_s']['confirmed'] is False
    with pytest.raises(C2CAnalysisError) as e:
        analyze(data, measurement_conditions=dict(bogus=1))
    assert e.value.issues[0]['code'] == 'unknown_condition_field'


def test_original_table_and_bytes_are_not_modified():
    cycles, program, erase = synthetic(n=60)
    data = workbook(cycles.tolist(), program.tolist(), erase.tolist())
    table = parse_table(data, 'x.xlsx')
    before = deepcopy(table)
    analyze_c2c(table, filename='x.xlsx')
    assert table == before
    digest = hashlib.sha256(data).hexdigest()
    result = analyze(data)
    assert hashlib.sha256(data).hexdigest() == digest == result['provenance']['sha256']
    assert result['series']['program_current'] == [float(v) for v in program]


def issues_of(fn):
    with pytest.raises(C2CAnalysisError) as e:
        fn()
    return {i['code'] for i in e.value.issues}


def table_for(cycles, program, erase):
    return parse_table(workbook(cycles, program, erase), 'x.xlsx')


def test_invalid_inputs_are_rejected_not_repaired():
    cycles, program, erase = synthetic(n=30)
    c, p, e = cycles.tolist(), program.tolist(), erase.tolist()
    t = table_for(c, p, e)
    t['rows'][5]['Program_Id_uA'] = None
    assert issues_of(lambda: analyze_c2c(t, filename='x')) == {'missing_value'}
    t = table_for(c, p, e); t['rows'][5]['Erase_Id_uA'] = 'abc'
    assert issues_of(lambda: analyze_c2c(t, filename='x')) == {'non_numeric'}
    for bad in (float('nan'), float('inf')):
        t = table_for(c, p, e); t['rows'][5]['Program_Id_uA'] = bad
        assert issues_of(lambda: analyze_c2c(t, filename='x')) == {'non_finite'}
    t = table_for(c, p, e); t['rows'][6]['Cycle'] = 6
    assert 'duplicate_cycle' in issues_of(lambda: analyze_c2c(t, filename='x'))
    t = table_for(c, p, e); t['rows'][6]['Cycle'] = 6.5
    assert 'non_integer_cycle' in issues_of(lambda: analyze_c2c(t, filename='x'))
    gap = table_for(c[:10] + c[12:], p[:10] + p[12:], e[:10] + e[12:])
    assert issues_of(lambda: analyze_c2c(gap, filename='x')) == {'cycle_gaps'}
    assert issues_of(lambda: analyze_c2c(table_for(c[:4], p[:4], e[:4]), filename='x')) == {'too_few_cycles'}
    t = table_for(c, p, e); t['rows'][5] = {k: None for k in t['rows'][5]}
    assert 'missing_value' in issues_of(lambda: analyze_c2c(t, filename='x'))


def test_missing_columns_unit_mismatch_and_ambiguity():
    cycles, program, erase = synthetic(n=20)
    t = table_for(cycles.tolist(), program.tolist(), erase.tolist())
    renamed = deepcopy(t)
    renamed['columns'][2] = 'Erase_Id_nA'
    for row in renamed['rows']:
        row['Erase_Id_nA'] = row.pop('Erase_Id_uA')
    assert 'unit_mismatch' in issues_of(lambda: analyze_c2c(renamed, filename='x'))
    missing = deepcopy(t); missing['columns'] = [c for c in missing['columns'] if c != 'Erase_Id_uA']
    assert issues_of(lambda: analyze_c2c(missing, filename='x')) == {'missing_column'}


def test_trailing_blank_rows_are_excluded_but_reported_and_unsorted_rows_are_sorted():
    cycles, program, erase = synthetic(n=40)
    t = table_for(cycles.tolist(), program.tolist(), erase.tolist())
    t['rows'].append({k: None for k in t['rows'][0]}); t['source_rows'].append(t['source_rows'][-1] + 1)
    reference = analyze_c2c(table_for(cycles.tolist(), program.tolist(), erase.tolist()), filename='x')
    padded = analyze_c2c(t, filename='x')
    assert padded['provenance']['trailing_blank_rows_excluded'] == 1
    assert padded['program'] == reference['program'] and padded['provenance']['cycle_count'] == 40
    shuffled = table_for(cycles.tolist(), program.tolist(), erase.tolist())
    order = list(range(40)); order.reverse()
    shuffled['rows'] = [shuffled['rows'][i] for i in order]; shuffled['source_rows'] = [shuffled['source_rows'][i] for i in order]
    result = analyze_c2c(shuffled, filename='x')
    assert result['program'] == reference['program'] and result['provenance']['sorted_input'] is False
    assert any('not in ascending' in w for w in result['warnings'])
    assert (result['provenance']['source_row_first'], result['provenance']['source_row_last']) == (2, 41)


def test_non_positive_trend_withholds_relative_output():
    cycles = np.arange(1, 41)
    program = np.linspace(1.0, -3.0, 40)
    erase = trend(cycles, [90, 1, 0, 0], 1, 40)
    result = analyze_c2c(table_for(cycles.tolist(), program.tolist(), erase.tolist()), filename='x')
    assert result['program']['status'] == 'blocked'
    assert result['program']['primary']['relative_residual_std_percent'] is None
    assert all(s['relative_residual_std_percent'] is None for s in result['program']['primary']['segments'])
    assert result['program']['raw_statistics']['relative_std_percent'] is None
    assert result['erase']['status'] == 'ok'
    assert result['simulator_use']['candidate_relative_std_percent'] is None
    assert any('program' in w and 'not positive' in w for w in result['warnings'])


def test_short_and_partial_segments_are_honest_not_padded():
    cycles, program, erase = synthetic(n=101)
    r = analyze_c2c(table_for(cycles.tolist(), program.tolist(), erase.tolist()), filename='x')
    seg = r['program']['primary']['segments']
    assert [s['count'] for s in seg] == [100, 1]
    assert seg[1]['relative_residual_std_percent'] is None and seg[1]['note']
    five = analyze_c2c(table_for(list(range(1, 6)), [70, 71, 70.5, 71.5, 72], [90, 91, 90.2, 91.4, 92]), filename='x')
    assert len(five['program']['primary']['segments']) == 1
    assert five['program']['sensitivity']['4']['exact_interpolation'] is True
    assert five['program']['sensitivity']['4']['relative_residual_std_percent'] == pytest.approx(0, abs=1e-6)
    assert _lag1(np.array([1.0, 1.0, 1.0]))[0] is None and _lag1(np.array([1.0, 2.0]))[0] is None


@pytest.mark.skipif(not A3_PATH.is_file(), reason='local A3 C2C workbook is not shared; set CTFM_A3_C2C_FILE')
def test_measured_a3_reproduces_the_decision_document_numbers():
    data = A3_PATH.read_bytes()
    assert hashlib.sha256(data).hexdigest() == A3_SHA256
    r = analyze_c2c_file(data, A3_PATH.name)
    expected = {'program': {'1': .685337, '2': .158631, '3': .047767, '4': .047234},
                'erase': {'1': .371592, '2': .074304, '3': .051833, '4': .042839}}
    for branch, degrees in expected.items():
        for degree, value in degrees.items():
            assert r[branch]['sensitivity'][degree]['relative_residual_std_percent'] == pytest.approx(value, abs=5e-7)
    assert r['program']['primary']['residual_lag1_correlation'] == pytest.approx(.615, abs=5e-4)
    assert r['erase']['primary']['residual_lag1_correlation'] == pytest.approx(.745, abs=5e-4)
    assert r['erase']['degree4_vs_degree3_change_percent'] == pytest.approx(-17, abs=0.5)
    linear = r['program']['sensitivity']['1']['segments']
    assert [linear[i]['mean_residual'] for i in (0, 4, 9)] == pytest.approx([-1.036, .604, -.703], abs=5e-4)
    assert r['difference_check']['status'] == 'consistent'
    assert (r['provenance']['cycle_min'], r['provenance']['cycle_max'], r['provenance']['cycle_count']) == (1, 1000, 1000)
