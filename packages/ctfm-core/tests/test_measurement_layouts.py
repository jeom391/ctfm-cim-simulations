"""Explicit-selection readers for repeated-block IV sheets and independent-time-axis Retention sheets."""
import hashlib
import io
import math
from pathlib import Path

import pytest
from openpyxl import Workbook

from ctfm.measurement import analyze
from ctfm.measurement.layouts import iv_dataset, read_iv_blocks, read_retention_layout, retention_dataset

ROOT = Path(__file__).resolve().parents[5] / '관련 자료'
UNITS = dict(vgs_v='V', id_a='A')


def book(rows, sheets=None, title='Sheet'):
    wb = Workbook()
    ws = wb.active
    ws.title = title
    for row in rows:
        ws.append(row)
    for name, extra in (sheets or {}).items():
        other = wb.create_sheet(name)
        for row in extra:
            other.append(row)
    buffer = io.BytesIO()
    wb.save(buffer)
    return buffer.getvalue()


def sweep(amplitude, id_at):
    """0 -> -A -> +A -> -A in 1 V steps (3 segments), Id from id_at(vg)."""
    path = list(range(0, -amplitude - 1, -1)) + list(range(-amplitude + 1, amplitude + 1)) + list(range(amplitude - 1, -amplitude - 1, -1))
    return [(float(v), id_at(v), 1e-9) for v in path]


def iv_book(amplitudes=(1, 2, 3), id_at=lambda v: 1e-6 * (v + 6), damaged=None):
    blocks = [sweep(a, id_at) for a in amplitudes]
    n = max(len(b) for b in blocks)
    rows = [[' Vg', ' Id', ' Ig'] * len(blocks)]
    for i in range(n):
        row = []
        for k, b in enumerate(blocks):
            row += list(b[i]) if i < len(b) else [None, None, None]
        rows.append(row)
    if damaged is not None:
        rows[3][3 * damaged] = ' '
    return book(rows)


def meta(data, name='iv.xlsx'):
    return dict(file_id=name, sha256=hashlib.sha256(data).hexdigest(), device_id='dev-' + name, condition_id='A3', units=UNITS)


def test_blocks_amplitudes_and_segments_are_listed_without_choosing_any():
    layout = read_iv_blocks(iv_book(), 'iv.xlsx')
    assert layout['block_count'] == 3 and layout['sheet'] == 'Sheet'
    assert [b['proposed_amplitude_v'] for b in layout['blocks']] == [1, 2, 3]
    segs = layout['blocks'][2]['segments']
    assert [(s['direction'], s['vg_start'], s['vg_end']) for s in segs] == [('decreasing', 0, -3), ('increasing', -3, 3), ('decreasing', 3, -3)]
    assert segs[1]['source_row_start'] == 5 and segs[1]['source_row_end'] == 11


def test_a_damaged_block_is_reported_and_the_others_stay_usable():
    data = iv_book(damaged=0)
    layout = read_iv_blocks(data, 'iv.xlsx')
    assert layout['blocks'][0]['status'] == 'invalid' and 'finite' in layout['blocks'][0]['error']
    assert [b['status'] for b in layout['blocks'][1:]] == ['ok', 'ok']
    with pytest.raises(ValueError, match='not usable'):
        iv_dataset(data, 'iv.xlsx', block=0, segment=1, branch='erase', sweep_amplitude_v=1, **meta(data))
    assert iv_dataset(data, 'iv.xlsx', block=1, segment=1, branch='erase', sweep_amplitude_v=2, **meta(data))['block']['index'] == 1


def test_unrecognised_header_layouts_are_refused_with_the_reason():
    for header in ([' Vg', ' Id', ' Ig', ' Id', ' Ig'], ['Time', 'MeasResult1_value', 'MeasResult2_value']):
        with pytest.raises(ValueError, match='repeated Vg/Id/Ig'):
            read_iv_blocks(book([header, [1, 2, 3, 4, 5][:len(header)]]), 'x.xlsx')


def test_selection_guards_refuse_instead_of_correcting():
    data = iv_book()
    m = meta(data)
    with pytest.raises(ValueError, match='needs a increasing segment'):
        iv_dataset(data, 'iv.xlsx', block=2, segment=0, branch='erase', sweep_amplitude_v=3, **m)
    with pytest.raises(ValueError, match='needs a decreasing segment'):
        iv_dataset(data, 'iv.xlsx', block=2, segment=1, branch='program', sweep_amplitude_v=3, **m)
    with pytest.raises(ValueError, match='does not match block'):
        iv_dataset(data, 'iv.xlsx', block=2, segment=1, branch='erase', sweep_amplitude_v=15, **m)
    with pytest.raises(ValueError, match='block must be'):
        iv_dataset(data, 'iv.xlsx', block=9, segment=1, branch='erase', sweep_amplitude_v=3, **m)
    with pytest.raises(ValueError, match='segment must be'):
        iv_dataset(data, 'iv.xlsx', block=2, segment=7, branch='erase', sweep_amplitude_v=3, **m)
    with pytest.raises(ValueError):
        iv_dataset(data, 'iv.xlsx', block=2, segment=1, branch='sideways', sweep_amplitude_v=3, **m)


def test_explicit_block_segment_gives_the_known_linear_interpolated_vth_and_original_rows():
    data = iv_book(id_at=lambda v: 1e-6 * (v + 6) + 5e-7)  # Id = 1 uA at Vg = -5.5
    m = meta(data)
    erase = iv_dataset(data, 'iv.xlsx', block=2, segment=1, branch='erase', sweep_amplitude_v=3, **m)
    program = iv_dataset(data, 'iv.xlsx', block=2, segment=2, branch='program', sweep_amplitude_v=3, **m)
    assert erase['source_rows'] == list(range(5, 12)) and erase['block'] == dict(index=2, segment=1, columns=[6, 7, 8])
    # blocks that never reach 1 uA inside the chosen segment give no crossing rather than a guess
    result = analyze('iv', [erase, program], {})
    assert {r['branch']: r['status'] for r in result['tables']['vth']} == {'erase': 'no_crossing', 'program': 'no_crossing'}
    wide = iv_book(amplitudes=(8,), id_at=lambda v: 1e-6 * (v + 6) + 5e-7)
    m = meta(wide, 'wide.xlsx')
    e = iv_dataset(wide, 'wide.xlsx', block=0, segment=1, branch='erase', sweep_amplitude_v=8, **m)
    p = iv_dataset(wide, 'wide.xlsx', block=0, segment=2, branch='program', sweep_amplitude_v=8, **m)
    result = analyze('iv', [e, p], {})
    vth = {r['branch']: r['vth_v'] for r in result['tables']['vth']}
    assert vth['erase'] == pytest.approx(-5.5) and vth['program'] == pytest.approx(-5.5)
    assert result['tables']['memory_window'][0]['mw_v'] == pytest.approx(0)
    assert result['provenance'][0]['block']['index'] == 0 and result['provenance'][0]['sheet'] == 'Sheet'


def test_two_selected_devices_reach_d2d_and_a_third_is_not_silently_picked():
    files = {}
    for name, scale in (('a.xlsx', 1.0), ('b.xlsx', 1.2)):
        files[name] = iv_book(amplitudes=(4,), id_at=lambda v, s=scale: s * (1e-6 * (v + 6) + 5e-7))
    datasets = []
    for name, data in files.items():
        m = meta(data, name)
        datasets += [iv_dataset(data, name, block=0, segment=s, branch=br, sweep_amplitude_v=4, **m)
                     for s, br in ((1, 'erase'), (2, 'program'))]
    result = analyze('d2d', datasets, {})
    assert result['d2d']['status'] == 'available' and result['d2d']['physical_device_count'] == 2
    assert result['d2d']['matched_conditions'] == 2 and result['d2d']['cv'] > 0
    third = iv_book(amplitudes=(4,))
    m = meta(third, 'c.xlsx')
    datasets.append(iv_dataset(third, 'c.xlsx', block=0, segment=1, branch='erase', sweep_amplitude_v=4, **m))
    with pytest.raises(ValueError, match='exactly two'):
        analyze('d2d', datasets, {})


# ---------------------------------------------------------------- retention

def retention_book(erase, program, header=('Erase_-15V_time', 'Erase_-15V_전류', 'Programing_15V_time', 'Programing_15V_전류'),
                   blank_second_row=True, normalized_header=None):
    rows = [list(header)] + ([[None] * 4] if blank_second_row else [])
    for i in range(max(len(erase), len(program))):
        e = erase[i] if i < len(erase) else (None, None)
        p = program[i] if i < len(program) else (None, None)
        rows.append([e[0], e[1], p[0], p[1]])
    extra = {'Normalized Data': [normalized_header, [10, 0, 10, 0]]} if normalized_header else None
    return book(rows, extra, title='Raw Data')


def log_series(times, a, b):
    return [(t, a + b * math.log10(t)) for t in times]


COLUMNS = dict(erase_time_s=0, erase_id_a=1, program_time_s=2, program_id_a=3)
RUNITS = dict(erase_time_s='s', erase_id_a='A', program_time_s='s', program_id_a='A')


def retention(data, condition='A1', label='R1', **kw):
    m = dict(file_id='r.xlsx', sha256=hashlib.sha256(data).hexdigest(), device_id='dev', read_vgs_v=0.) | kw
    ds = retention_dataset(data, 'r.xlsx', columns=COLUMNS, condition_id=condition, source_label=label, units=RUNITS, **m)
    return analyze('retention', [ds], {}), ds


def test_independent_direction_time_axes_are_fitted_on_their_own_times():
    erase = log_series([10.0, 22.0, 47.0, 100.0, 1000.0], 9e-6, -1e-6)
    program = log_series([10.4, 31.0, 90.0, 400.0, 999.0], 1e-6, 2e-7)  # same rows, different times
    result, ds = retention(retention_book(erase, program))
    r = result['retention']
    assert r['time_axes'] == 'per_direction'
    assert r['erase_fit']['a'] == pytest.approx(9e-6, rel=1e-9) and r['erase_fit']['b'] == pytest.approx(-1e-6, rel=1e-9)
    assert r['program_fit']['a'] == pytest.approx(1e-6, rel=1e-9) and r['program_fit']['b'] == pytest.approx(2e-7, rel=1e-9)
    assert (r['erase_fit']['n'], r['program_fit']['n']) == (5, 5)
    assert (r['program_fit']['time_min_s'], r['program_fit']['time_max_s']) == (10.4, 999.0)
    assert r['program_reference_current_a'] == pytest.approx(1e-6 + 2e-7)
    assert ds['skipped_blank_rows'] == [2] and ds['source_rows'][0] == 3
    curves = {(f['direction'], f['time_s']) for f in result['tables']['retention_fit']}
    assert ('program', 10.4) in curves and ('erase', 22.0) in curves and ('erase', 10.4) not in curves


def test_points_before_ten_seconds_are_excluded_per_direction_and_reported():
    erase = [(0.028, 4.4e-5)] + log_series([10.0, 30.0, 100.0, 1000.0], 9e-6, -1e-6)
    program = [(0.037, 6.1e-6)] + log_series([10.2, 40.0, 200.0, 1000.0], 1e-6, 2e-7)
    result, _ = retention(retention_book(erase, program, blank_second_row=False))
    assert [(e['direction'], e['source_row'], e['reason']) for e in result['exclusions']] == \
        [('program', 2, 'before_fit_start'), ('erase', 2, 'before_fit_start')]
    assert result['retention']['erase_fit']['n'] == 4 and result['retention']['program_fit']['n'] == 4


def test_retention_needs_three_distinct_times_in_each_direction():
    erase = log_series([10.0, 20.0, 30.0], 9e-6, -1e-6)
    program = log_series([10.0, 10.0, 20.0], 1e-6, 2e-7)
    with pytest.raises(ValueError, match='three distinct valid program times'):
        retention(retention_book(erase, program))


def test_partial_rows_and_bad_column_selections_are_errors_not_guesses():
    good = log_series([10.0, 20.0, 40.0, 80.0], 9e-6, -1e-6)
    broken = retention_book(good, good)
    with pytest.raises(ValueError, match='finite number'):  # a row with only one direction present is not silently padded
        retention_dataset(retention_book(good, good[:3]), 'r.xlsx', columns=COLUMNS, condition_id='A1', device_id='d', file_id='f',
                          sha256='0' * 64, source_label='R1', units=RUNITS)
    wb_rows = [['t', 'i', 't2', 'i2'], [10.0, 1e-6, 10.0, None]]
    with pytest.raises(ValueError, match='finite number'):
        retention_dataset(book(wb_rows, title='Raw Data'), 'r.xlsx', columns=COLUMNS, condition_id='A1', device_id='d', file_id='f',
                          sha256='0' * 64, source_label='R1', units=RUNITS)
    for bad in (dict(erase_time_s=0, erase_id_a=1, program_time_s=2), dict(erase_time_s=0, erase_id_a=1, program_time_s=1, program_id_a=3)):
        with pytest.raises(ValueError, match='distinct column index'):
            retention_dataset(broken, 'r.xlsx', columns=bad, condition_id='A1', device_id='d', file_id='f', sha256='0' * 64,
                              source_label='R1', units=RUNITS)


def test_source_label_must_match_the_approved_mapping_and_normalized_sheet_is_never_used():
    good = log_series([10.0, 20.0, 40.0, 80.0], 9e-6, -1e-6)
    data = retention_book(good, good)
    with pytest.raises(ValueError, match='must be R3\\(1\\)'):
        retention(data, condition='A3', label='R3(2)', read_vgs_v=0.5) if False else analyze(
            'retention', [retention_dataset(data, 'r.xlsx', columns=COLUMNS, condition_id='A3', device_id='d', file_id='f',
                                            sha256='0' * 64, source_label='R3(2)', units=RUNITS, read_vgs_v=.5)], {})
    layout = read_retention_layout(retention_book(good, good, normalized_header=[
        'read_retention_0.5V(1)_x_A1.csv (Time)', 'read_retention_0.5V(1)_x_A1.csv (Norm I)', 'read_retention_0.5V_x.csv (Time)', 'y']), 'r.xlsx')
    assert [c['header'] for c in layout['columns']][0] == 'Erase_-15V_time'
    ev = layout['embedded_source_headers']
    assert ev[0]['read_bias_v'] == [0.5] and ev[0]['embedded_numbers'] == [1] and ev[0]['sheet'] == 'Normalized Data'
    with pytest.raises(ValueError, match='raw absolute current'):
        analyze('retention', [dict(retention_dataset(data, 'r.xlsx', columns=COLUMNS, condition_id='A1', device_id='d', file_id='f',
                                                     sha256='0' * 64, source_label='R1', units=RUNITS), sheet='Normalized Data')], {})


# ---------------------------------------------------------------- real files (skipped where the private folder is absent)

needs_data = pytest.mark.skipif(not (ROOT / 'IV Sweep').is_dir(), reason='private measurement folder 관련 자료 not present')


@needs_data
@pytest.mark.parametrize('cond,name,team_vth', [
    ('A3', '_26CTFM_A3_vgid_sweep_227_15V.xlsx', -10.05816), ('A3', '_26CTFM_A3_vgid_sweep_228_15V.xlsx', -9.970667),
    ('A4', '_26CTFM_A4_IdVg_sweep_234_15V_.xlsx', -9.157939), ('A5', '_26CTFM_A5_IdVg_sweep_224_15V.xlsx', -8.344557)])
def test_real_iv_files_reproduce_the_team_vth_table_with_an_explicit_selection(cond, name, team_vth):
    data = (ROOT / 'IV Sweep' / cond / name).read_bytes()
    layout = read_iv_blocks(data, name)
    block = next(b for b in layout['blocks'] if b['proposed_amplitude_v'] == 15)
    up = max((s for s in block['segments'] if s['direction'] == 'increasing'), key=lambda s: abs(s['vg_end'] - s['vg_start']))
    down = [s for s in block['segments'] if s['direction'] == 'decreasing'][-1]
    m = meta(data, name)
    m['condition_id'] = cond
    datasets = [iv_dataset(data, name, block=block['index'], segment=up['index'], branch='erase', sweep_amplitude_v=15, **m),
                iv_dataset(data, name, block=block['index'], segment=down['index'], branch='program', sweep_amplitude_v=15, **m)]
    rows = {r['branch']: r for r in analyze('iv', datasets, {})['tables']['vth']}
    assert rows['erase']['status'] == 'ok' and rows['erase']['vth_v'] == pytest.approx(team_vth, abs=2e-3)


@needs_data
def test_real_retention_raw_sheet_is_read_with_independent_axes_and_a3_early_point_excluded():
    data = (ROOT / 'Retention' / '_26CMFM_A3_Retention.xlsx').read_bytes()
    result, ds = retention(data, condition='A3', label='R3(1)', read_vgs_v=.5)
    assert len(ds['rows']) == 101 and ds['skipped_blank_rows'] == []
    assert [(e['direction'], e['source_row']) for e in result['exclusions']] == [('program', 2), ('erase', 2)]
    assert result['retention']['erase_fit']['n'] == 100 and result['retention']['erase_fit']['time_min_s'] > 10
    layout = read_retention_layout(data, '_26CMFM_A3_Retention.xlsx')
    assert any('RESET' in e['header'] for e in layout['embedded_source_headers'])
