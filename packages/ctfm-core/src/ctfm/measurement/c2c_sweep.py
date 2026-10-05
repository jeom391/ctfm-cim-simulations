"""C2C from repeated I-V sweeps: overall and linearly detrended relative deviation.

Implements handoff/06_final-implementation-2026-10-02.md section 2. The workbook holds one
column of drain current per sweep cycle (``Cycle_NN_Id_<unit>``) against the gate voltage
(``Vg_V``), plus a ``Sweep_segment`` label per row. Three read points are analysed separately
and never pooled: the very first 0 V sample, the 0 V sample of the ascending sweep and the 0 V
sample of the descending sweep. For each point, two figures are reported side by side:

* overall:   CV = s_I / |mean_I| over every cycle (sample SD, N-1), no trend removed;
* residual:  T_n = a + b*n by OLS over every cycle, e_n = (I_n - T_n) / T_n,
             CV = SD(e, N-1). Only reported when every T_n is finite and positive.

Neither is "the" C2C value and neither is chosen here. No cycle or outlier is dropped.
"""
from __future__ import annotations

import hashlib
import math
import re

import numpy as np

from . import _load_raw

C2C_SWEEP_VERSION = '1.0.0'
SHEET = 'Id_sweeps'
MIN_CYCLES = 3
UNIT_TO_AMPERE = {'A': 1.0, 'mA': 1e-3, 'uA': 1e-6, 'nA': 1e-9}
CYCLE_HEADER = re.compile(r'^Cycle_(\d+)_Id_(A|mA|uA|nA)$')
POINTS = (('initial_0v', '최초 0 V'), ('ascending_0v', '상승 중 0 V'), ('descending_0v', '하강 중 0 V'))


class C2CSweepError(ValueError):
    def __init__(self, issues):
        self.issues = issues
        super().__init__('; '.join(f"{i['code']}: {i['detail']}" for i in issues))


def _column_letter(index):
    letters = ''
    index += 1
    while index:
        index, rem = divmod(index - 1, 26)
        letters = chr(65 + rem) + letters
    return letters


def _number(value):
    if value is None or isinstance(value, bool) or (isinstance(value, str) and not value.strip()):
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) else None


def _layout(raw):
    header = [str(v).strip() if v is not None else '' for v in raw[0]]
    if not header or header[0] != 'Vg_V':
        raise C2CSweepError([dict(code='missing_column', detail='first column must be Vg_V')])
    cycles, units = [], set()
    for col, name in enumerate(header):
        match = CYCLE_HEADER.match(name)
        if match:
            cycles.append((int(match[1]), col))
            units.add(match[2])
    if 'Sweep_segment' not in header:
        raise C2CSweepError([dict(code='missing_column', detail='Sweep_segment column is required to identify sweep direction')])
    if len(units) > 1:
        raise C2CSweepError([dict(code='unit_mismatch', detail=f'cycle columns use different units: {sorted(units)}')])
    if len(cycles) < MIN_CYCLES:
        raise C2CSweepError([dict(code='too_few_cycles', detail=f'{len(cycles)} cycle columns; at least {MIN_CYCLES} required')])
    numbers = [n for n, _ in cycles]
    if numbers != list(range(1, len(numbers) + 1)):
        raise C2CSweepError([dict(code='cycle_gaps', detail=f'cycle columns must be Cycle_01..Cycle_{len(numbers):02d} in order; found {numbers}')])
    return cycles, units.pop(), header.index('Sweep_segment')


def _segments(raw, label_col):
    """Contiguous runs of one Sweep_segment label, with the direction read from Vg itself."""
    runs = []
    for row_index in range(1, len(raw)):
        label = raw[row_index][label_col] if label_col < len(raw[row_index]) else None
        if runs and runs[-1]['label'] == label:
            runs[-1]['rows'].append(row_index)
        else:
            runs.append(dict(label=label, rows=[row_index]))
    for run in runs:
        vg = [_number(raw[r][0]) for r in run['rows']]
        if any(v is None for v in vg):
            bad = run['rows'][vg.index(None)] + 1
            raise C2CSweepError([dict(code='non_numeric', detail=f'Vg_V at source row {bad} is not a finite number')])
        diffs = np.diff(vg)
        run['direction'] = ('increasing' if len(diffs) and np.all(diffs > 0) else
                            'decreasing' if len(diffs) and np.all(diffs < 0) else 'mixed')
        run['vg'] = vg
    return runs


def _locate_points(raw, label_col):
    """Row index of each read point; a point that cannot be identified unambiguously is reported, not guessed."""
    runs = _segments(raw, label_col)
    located, notes = {}, {}
    first = runs[0]
    if first['vg'][0] == 0:
        located['initial_0v'] = first['rows'][0]
    else:
        notes['initial_0v'] = f'first sweep sample is Vg={first["vg"][0]} V, not 0 V'
    for key, direction in (('ascending_0v', 'increasing'), ('descending_0v', 'decreasing')):
        candidates = [run['rows'][i] for run in runs if run['direction'] == direction
                      for i, v in enumerate(run['vg']) if v == 0 and not (run is first and i == 0)]
        if len(candidates) == 1:
            located[key] = candidates[0]
        else:
            notes[key] = f'{len(candidates)} Vg=0 V samples inside {direction} sweep segments; exactly one is required'
    return located, notes, [dict(label=r['label'], direction=r['direction'], source_row_start=r['rows'][0] + 1,
                                 source_row_end=r['rows'][-1] + 1) for r in runs]


def overall_variation(values):
    """Sample SD over |mean| without any trend removal; None when the mean is 0."""
    values = np.asarray(values, dtype=float)
    mean = float(values.mean())
    sd = float(values.std(ddof=1))
    if mean == 0:
        return dict(mean=mean, sd=sd, cv_percent=None, reason='mean is 0; relative deviation undefined')
    return dict(mean=mean, sd=sd, cv_percent=100 * sd / abs(mean), reason=None)


def residual_variation(values):
    """Linear OLS trend over n=1..N, relative residual e=(I-T)/T, sample SD of e (N-1)."""
    values = np.asarray(values, dtype=float)
    n = np.arange(1, len(values) + 1, dtype=float)
    slope, intercept = np.polyfit(n, values, 1)
    trend = intercept + slope * n
    residual = values - trend
    lag1 = float(np.corrcoef(residual[:-1], residual[1:])[0, 1]) if len(values) >= 3 and residual[:-1].std() > 0 and residual[1:].std() > 0 else None
    base = dict(intercept=float(intercept), slope_per_cycle=float(slope), trend=trend.tolist(),
                residual=residual.tolist(), residual_lag1_correlation=lag1)
    if not np.all(np.isfinite(trend)) or not np.all(trend > 0):
        return dict(base, relative_residual=None, cv_percent=None,
                    reason='linear trend is not finite and positive at every cycle; relative residual withheld')
    relative = residual / trend
    return dict(base, relative_residual=relative.tolist(), cv_percent=100 * float(relative.std(ddof=1)), reason=None)


def analyze_c2c_sweep(data: bytes, filename: str, *, condition_id=None, device_id=None):
    try:
        raw = _load_raw(data, filename, SHEET)[0]
    except ValueError as exc:
        raise C2CSweepError([dict(code='sheet_missing', detail=f'{filename}: {SHEET} worksheet unreadable ({exc})')]) from exc
    cycles, unit, label_col = _layout(raw)
    scale = UNIT_TO_AMPERE[unit]
    located, notes, segments = _locate_points(raw, label_col)
    first_col, last_col = cycles[0][1], cycles[-1][1]
    points, rows, warnings = [], [dict(cycle=n) for n, _ in cycles], []
    for key, label in POINTS:
        entry = dict(point=key, label=label, n=len(cycles), unit='A')
        if key not in located:
            points.append(dict(entry, status='unavailable', reason=notes[key], source_row=None, cell_range=None))
            continue
        row = located[key]
        cell_range = f'{_column_letter(first_col)}{row + 1}:{_column_letter(last_col)}{row + 1}'
        entry.update(source_row=row + 1, cell_range=cell_range, vg_v=_number(raw[row][0]), segment=raw[row][label_col])
        values, issues = [], []
        for n, col in cycles:
            cell = raw[row][col] if col < len(raw[row]) else None
            number = _number(cell)
            if number is None:
                issues.append(dict(code='missing_or_non_numeric', cell=f'{_column_letter(col)}{row + 1}', cycle=n, value=None if cell is None else str(cell)))
            values.append(number)
        if issues:
            # A missing cycle is never skipped silently: the point is not computed at all.
            points.append(dict(entry, status='invalid', reason='missing or non-numeric cells; not computed', issues=issues))
            continue
        values = np.array(values) * scale
        negatives = int((values < 0).sum())
        if negatives:
            warnings.append(f'{label}: 음수 전류 {negatives}개를 측정값 그대로 사용했습니다 (절댓값 처리 안 함).')
        overall = overall_variation(values)
        residual = residual_variation(values)
        points.append(dict(entry, status='ok', negative_values=negatives,
                           mean_a=overall['mean'], sd_a=overall['sd'], cv_overall_percent=overall['cv_percent'], overall_reason=overall['reason'],
                           trend_intercept_a=residual['intercept'], trend_slope_a_per_cycle=residual['slope_per_cycle'],
                           cv_residual_percent=residual['cv_percent'], residual_reason=residual['reason'],
                           residual_lag1_correlation=residual['residual_lag1_correlation']))
        for i, r in enumerate(rows):
            r[f'{key}_current_a'] = float(values[i])
            r[f'{key}_trend_a'] = residual['trend'][i]
            r[f'{key}_relative_residual'] = None if residual['relative_residual'] is None else residual['relative_residual'][i]
    # Empty cells elsewhere in the sweep (e.g. the tail of one cycle) are reported with their location. They do not
    # touch the three analysed 0 V rows (an empty cell there makes that point 'invalid' above), and nothing is repaired.
    analysed_rows = {p['source_row'] for p in points if p.get('source_row')}
    gaps = {}
    for r in range(1, len(raw)):
        for n, col in cycles:
            if r + 1 not in analysed_rows and _number(raw[r][col] if col < len(raw[r]) else None) is None:
                gaps.setdefault(n, []).append(r + 1)
    unused_empty = [dict(cycle=n, source_rows=f'{min(rs)}-{max(rs)}', count=len(rs)) for n, rs in sorted(gaps.items())]
    for g in unused_empty:
        warnings.append(f"Cycle_{g['cycle']:02d}: 원본 행 {g['source_rows']}의 {g['count']}칸이 비어 있습니다. 분석 대상 0 V 행이 아니어서 "
                        '세 구간의 계산에는 쓰이지 않았고, 값을 채우거나 사이클을 제외하지 않았습니다.')
    for p in points:
        lag1 = p.get('residual_lag1_correlation')
        if lag1 is not None:
            warnings.append(f"{p['label']}: 선형 잔차 lag-1 상관 {lag1:.3f}. 잔차에 연속성이 남아 있어 추세 제거 값을 독립 무작위 변동만의 "
                            '추정으로 볼 수 없습니다. C2C 분석이 불가능하다는 뜻은 아닙니다.')
    warnings += [
        '전체 변동에는 사이클에 따른 추세가 포함될 수 있고, 추세 제거 후 값은 선형 모델과 사이클별 정규화 방식에 의존합니다.',
        '두 값을 모두 제공하며 자동 선택하지 않습니다. 대표 스윕 구간은 소자팀 확인 후 사용자가 정합니다.',
        '이 파일은 VDS와 기록 절차를 확인해 주지 않습니다. 사이클마다 같은 양수 VDS라면 전류 CV와 전도도 CV는 같습니다.',
        '0 V 값은 스윕 중 측정점이며 별도 읽기 펄스가 아닙니다. 사이클 간 같은 초기 상태를 가정하지 않습니다.',
    ]
    result = dict(
        kind='c2c_sweep', analysis_version=C2C_SWEEP_VERSION, condition_id=condition_id,
        method=dict(overall='CV = 100 * SD(I, ddof=1) / |mean(I)|',
                    residual='T_n = a + b*n (OLS over n=1..N); e_n = (I_n - T_n) / T_n; CV = 100 * SD(e, ddof=1)',
                    residual_name='추세 제거 후 상대 잔차 표준편차(%)',
                    note='N-1 reports the sample SD of the computed relative residuals; it is not claimed to be an unbiased noise-variance estimator, '
                         'and it differs from the regression residual SD sqrt(sum(r^2)/(N-p))/mean.'),
        provenance=dict(filename=filename, sha256=hashlib.sha256(data).hexdigest(), sheet=SHEET, device_id=device_id,
                        unit=unit, unit_scale_to_ampere=scale, cycle_count=len(cycles),
                        cycle_columns=f'{_column_letter(first_col)}..{_column_letter(last_col)}', segments=segments,
                        unused_empty_cells=unused_empty),
        summaries=dict(points=points, cycles=len(cycles)),
        tables=dict(c2c_points=[{k: v for k, v in p.items() if k != 'issues'} for p in points], cycles=rows),
        exclusions=[dict(point=p['point'], reason=p['reason'], issues=p.get('issues', [])) for p in points if p['status'] != 'ok'],
        warnings=warnings)
    return result
