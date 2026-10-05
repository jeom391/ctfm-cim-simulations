"""Handoff 06: sweep C2C (overall + linear-detrended), retention extrapolation, D2D pair matching."""
import io
import math
import statistics
from pathlib import Path

import pytest
from openpyxl import Workbook

from ctfm.measurement import retention_extrapolation, TEN_YEARS_S
from ctfm.measurement.c2c_sweep import analyze_c2c_sweep, residual_variation, overall_variation

SNAPSHOT = Path(__file__).resolve().parents[3] / 'data/team-snapshot/2026-10-02/files'


def test_a2_snapshot_matches_handoff_table_and_independent_residual():
    path = SNAPSHOT / 'C2C/A2_C2C_50Cycles.xlsx'
    result = analyze_c2c_sweep(path.read_bytes(), path.name, condition_id='A2')
    points = {p['point']: p for p in result['summaries']['points']}
    # handoff 06 section 2.3 (overall variation; mean/SD in uA, CV in %)
    expected = {'initial_0v': ('B2:AY2', 19.024840, 0.681346, 3.581349),
                'ascending_0v': ('B202:AY202', 25.255400, 1.534398, 6.075524),
                'descending_0v': ('B402:AY402', 4.538944, 0.113931, 2.510084)}
    for key, (cells, mean, sd, cv) in expected.items():
        p = points[key]
        assert p['status'] == 'ok' and p['n'] == 50 and p['cell_range'] == cells
        assert p['mean_a'] * 1e6 == pytest.approx(mean, abs=5e-7)
        assert p['sd_a'] * 1e6 == pytest.approx(sd, abs=5e-7)
        assert p['cv_overall_percent'] == pytest.approx(cv, abs=5e-7)
    # residual: recomputed here with normal equations + statistics.stdev, not numpy.polyfit
    for p in points.values():
        values = [r[p['point'] + '_current_a'] for r in result['tables']['cycles']]
        n = list(range(1, 51)); nm = sum(n) / 50; m = sum(values) / 50
        b = sum((x - nm) * (y - m) for x, y in zip(n, values)) / sum((x - nm) ** 2 for x in n); a = m - b * nm
        e = [(y - (a + b * x)) / (a + b * x) for x, y in zip(n, values)]
        assert p['cv_residual_percent'] == pytest.approx(100 * statistics.stdev(e), rel=1e-9)
    # the earlier regression-SD figures (3.083357 / 2.506502 %) are a different definition
    assert points['ascending_0v']['cv_residual_percent'] == pytest.approx(2.917903, abs=1e-6)
    assert points['descending_0v']['cv_residual_percent'] == pytest.approx(2.492470, abs=1e-6)


SUPPLEMENT = Path(__file__).resolve().parents[3] / 'data/team-snapshot/2026-10-03/files'
# (overall CV %, linear-trend relative-residual SD %) for initial / ascending / descending 0 V, recomputed independently
# from the raw workbooks (local_report/33-evidence/recompute_c2c_all.py); nothing excluded, A4/A5 outliers included.
LATEST_C2C = {
    'A1': ((8.962230, 3.171725), (7.929512, 2.787384), (11.869619, 4.568632)),
    'A2': ((3.581349, 2.337826), (6.075524, 2.917903), (2.510084, 2.492470)),
    'A3': ((9.734714, 1.898242), (12.840609, 3.463368), (35.100133, 16.531713)),
    'A4': ((10.625534, 2.939228), (12.465748, 3.701655), (14.613091, 14.955397)),
    'A5': ((16.081324, 6.491459), (20.970215, 14.440904), (15.618871, 12.397612)),
}


@pytest.mark.parametrize('condition', sorted(LATEST_C2C))
def test_latest_c2c_files_match_independent_values_without_excluding_anything(condition):
    path = SUPPLEMENT / f'C2C/{condition}_C2C_50Cycles.xlsx'
    result = analyze_c2c_sweep(path.read_bytes(), path.name, condition_id=condition)
    assert result['exclusions'] == []
    for p, (overall, residual) in zip(result['summaries']['points'], LATEST_C2C[condition]):
        assert p['status'] == 'ok' and p['n'] == 50
        assert p['cv_overall_percent'] == pytest.approx(overall, abs=5e-7)
        assert p['cv_residual_percent'] == pytest.approx(residual, abs=5e-7)
    gaps = result['provenance']['unused_empty_cells']
    if condition == 'A5':
        # cycle 11 is missing the last four samples of its descending sweep; the analysed 0 V rows are intact
        assert gaps == [dict(cycle=11, source_rows='499-502', count=4)]
        assert any('Cycle_11' in w and '499-502' in w for w in result['warnings'])
    else:
        assert gaps == []


def _workbook(rows_by_cycle, labels=None):
    """Tiny synthetic sweep: 0 -> -1 -> +1 -> -1 V in 0.5 V steps."""
    vg = [0, -.5, -1, -.5, 0, .5, 1, .5, 0, -.5, -1]
    labels = labels or ['0 to -1'] * 3 + ['-1 to +1'] * 4 + ['+1 to -1'] * 4
    wb = Workbook(); ws = wb.active; ws.title = 'Id_sweeps'
    ws.append(['Vg_V', *[f'Cycle_{n:02d}_Id_A' for n in range(1, len(rows_by_cycle) + 1)], 'Sweep_segment'])
    for i, v in enumerate(vg):
        ws.append([v, *[cycle[i] for cycle in rows_by_cycle], labels[i]])
    buffer = io.BytesIO(); wb.save(buffer)
    return buffer.getvalue()


def test_missing_cell_blocks_only_its_point_and_negative_values_are_not_abs():
    cycles = [[1e-6 * (k + 1)] * 11 for k in range(4)]
    cycles[2][4] = None          # ascending 0 V of cycle 3 missing
    cycles[1][8] = -1e-6         # descending 0 V negative in cycle 2
    result = analyze_c2c_sweep(_workbook(cycles), 'x.xlsx')
    points = {p['point']: p for p in result['summaries']['points']}
    assert points['ascending_0v']['status'] == 'invalid'
    assert points['ascending_0v']['issues'][0]['cell'] == 'D6'  # data index 4 -> sheet row 6 (row 1 is the header)
    assert points['initial_0v']['status'] == 'ok'
    desc = points['descending_0v']
    assert desc['negative_values'] == 1
    values = [1e-6, -1e-6, 3e-6, 4e-6]
    assert desc['mean_a'] == pytest.approx(statistics.mean(values))
    assert desc['cv_overall_percent'] == pytest.approx(100 * statistics.stdev(values) / abs(statistics.mean(values)))
    assert any('절댓값 처리 안 함' in w for w in result['warnings'])


def test_zero_mean_and_nonpositive_trend_are_withheld_not_forced():
    assert overall_variation([1.0, -1.0, 0.0])['cv_percent'] is None
    falling = residual_variation([3.0, 1.0, -1.0, -3.0])
    assert falling['cv_percent'] is None and falling['relative_residual'] is None and falling['reason']


def test_ambiguous_zero_crossing_is_reported_not_guessed():
    labels = ['0 to -1'] * 3 + ['-1 to +1'] * 8          # no descending segment at all
    result = analyze_c2c_sweep(_workbook([[1e-6] * 11] * 3, labels), 'x.xlsx')
    points = {p['point']: p for p in result['summaries']['points']}
    assert points['descending_0v']['status'] == 'unavailable'
    assert points['ascending_0v']['status'] == 'unavailable'  # the merged run is not monotone


def test_retention_extrapolation_flags_nonpositive_model_values_without_clipping():
    fit = lambda a, b: dict(a=a, b=b, time_min_s=10., time_max_s=1000.)
    output = dict(program_fit=fit(1e-7, 1e-7), erase_fit=fit(4e-6, -5e-7))
    summary, rows = retention_extrapolation(output)
    erase_10y = 4e-6 - 5e-7 * math.log10(TEN_YEARS_S)
    assert summary['erase']['ten_year_a'] == pytest.approx(erase_10y) and erase_10y < 0
    assert summary['erase']['ten_year_valid'] is False
    assert summary['erase']['zero_crossing_s'] == pytest.approx(10 ** 8)
    assert summary['window_closing_s'] == pytest.approx(10 ** ((4e-6 - 1e-7) / (1e-7 + 5e-7)))
    assert rows[-1]['time_s'] == pytest.approx(TEN_YEARS_S) and rows[-1]['erase_fit_a'] < 0 and rows[-1]['erase_valid'] is False
    assert {r['region'] for r in rows} == {'measured', 'extrapolated'}
    assert all(r['region'] == 'measured' for r in rows if r['time_s'] <= 1000)
