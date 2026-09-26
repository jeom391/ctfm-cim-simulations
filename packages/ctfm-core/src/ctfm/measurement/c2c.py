"""Measured C2C analysis: detrended relative deviation of repeated P/E read currents.

Implements docs/c2c-detrending-decision-2026-09-26.md. Program and Erase are
analysed independently; the Erase-minus-Program column is a cross-check only.
The result is a trend-corrected relative deviation, NOT an iid pure C2C noise
estimate, and nothing here writes into a device profile or the simulator.
"""
from __future__ import annotations

import hashlib
import math
import re
from copy import deepcopy

import numpy as np

from . import parse_table

C2C_ANALYSIS_VERSION = '1.0.0'
PRIMARY_DEGREE = 3
SENSITIVITY_DEGREES = (1, 2, 3, 4)
MIN_CYCLES = 5
SEGMENT_SIZE = 100
UNIT_TO_AMPERE = {'A': 1.0, 'mA': 1e-3, 'uA': 1e-6, 'nA': 1e-9}
_UNITS = '|'.join(UNIT_TO_AMPERE)
HEADER_PATTERNS = {
    'cycle': re.compile(r'^Cycle$', re.I),
    'program': re.compile(rf'^Program_Id_({_UNITS})$'),
    'erase': re.compile(rf'^Erase_Id_({_UNITS})$'),
    'difference': re.compile(rf'^Erase_minus_Program_({_UNITS})$'),
}
CONDITION_FIELDS = ('program_voltage_v', 'program_pulse_width_s', 'erase_voltage_v', 'erase_pulse_width_s',
                    'read_voltage_v', 'read_terminal_meaning', 'vds_v', 'read_time_s', 'read_extraction_point')


class C2CAnalysisError(ValueError):
    def __init__(self, issues):
        self.issues = issues
        super().__init__('; '.join(f"{i['code']}: {i['detail']}" for i in issues))


def _recognize_columns(columns):
    found, issues = {}, []
    for key, pattern in HEADER_PATTERNS.items():
        hits = [(c, m) for c in columns if (m := pattern.match(c))]
        if len(hits) > 1:
            issues.append(dict(code='ambiguous_header', detail=f'{key}: {[h[0] for h in hits]}'))
        elif hits:
            found[key] = dict(header=hits[0][0], unit=hits[0][1].group(1) if key != 'cycle' else None)
    for key in ('cycle', 'program', 'erase'):
        if key not in found:
            issues.append(dict(code='missing_column', detail=f'required header for {key} not found in {list(columns)}'))
    units = {found[k]['unit'] for k in ('program', 'erase', 'difference') if k in found}
    if len(units) > 1:
        issues.append(dict(code='unit_mismatch', detail=f'program/erase/difference units differ: {sorted(units)}'))
    if issues:
        raise C2CAnalysisError(issues)
    return found


def _number(value, row, column, issues):
    if value is None or (isinstance(value, str) and not value.strip()):
        issues.append(dict(code='missing_value', detail=f'source row {row}, {column}'))
        return None
    if isinstance(value, bool):
        issues.append(dict(code='non_numeric', detail=f'source row {row}, {column}: {value!r}'))
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        issues.append(dict(code='non_numeric', detail=f'source row {row}, {column}: {value!r}'))
        return None
    if not math.isfinite(number):
        issues.append(dict(code='non_finite', detail=f'source row {row}, {column}: {value!r}'))
        return None
    return number


def _read_series(table, found):
    """Original-order rows -> validated arrays. Trailing fully blank rows are excluded; nothing else is dropped."""
    keys = [found[k]['header'] for k in ('cycle', 'program', 'erase', 'difference') if k in found]
    rows = list(zip(table['rows'], table['source_rows']))
    trailing = 0
    while rows and all(rows[-1][0].get(k) in (None, '') for k in keys):
        rows.pop()
        trailing += 1
    issues, records = [], []
    for row, source_row in rows:
        cycle = _number(row.get(found['cycle']['header']), source_row, 'cycle', issues)
        if cycle is not None and cycle != int(cycle):
            issues.append(dict(code='non_integer_cycle', detail=f'source row {source_row}: {cycle}'))
        program = _number(row.get(found['program']['header']), source_row, 'program', issues)
        erase = _number(row.get(found['erase']['header']), source_row, 'erase', issues)
        difference = _number(row.get(found['difference']['header']), source_row, 'difference', issues) if 'difference' in found else None
        records.append((cycle, program, erase, difference, source_row))
    if issues:
        raise C2CAnalysisError(issues)
    seen = {}
    for cycle, *_rest, source_row in records:
        if int(cycle) in seen:
            issues.append(dict(code='duplicate_cycle', detail=f'cycle {int(cycle)} at source rows {seen[int(cycle)]} and {source_row}'))
        seen[int(cycle)] = source_row
    if issues:
        raise C2CAnalysisError(issues)
    was_sorted = all(records[i][0] < records[i + 1][0] for i in range(len(records) - 1))
    records.sort(key=lambda r: r[0])
    if len(records) < MIN_CYCLES:
        raise C2CAnalysisError([dict(code='too_few_cycles', detail=f'{len(records)} distinct cycles; at least {MIN_CYCLES} required')])
    cycles = [int(r[0]) for r in records]
    gaps = [(a, b) for a, b in zip(cycles, cycles[1:]) if b != a + 1]
    if gaps:
        raise C2CAnalysisError([dict(code='cycle_gaps', detail=f'missing cycles between {a} and {b}') for a, b in gaps])
    series = dict(cycle=np.array(cycles, dtype=float), program=np.array([r[1] for r in records]),
                  erase=np.array([r[2] for r in records]),
                  difference=np.array([r[3] for r in records]) if 'difference' in found else None,
                  source_rows=[r[4] for r in records])
    return series, dict(sorted_input=was_sorted, trailing_blank_rows_excluded=trailing)


def _std(values):
    return float(np.std(values, ddof=1)) if len(values) >= 2 else None


def _lag1(values):
    if len(values) < 3:
        return None, 'fewer than 3 points'
    a, b = values[:-1], values[1:]
    if np.std(a) == 0 or np.std(b) == 0:
        return None, 'zero variance'
    return float(np.corrcoef(a, b)[0, 1]), None


def _segments(cycles, residual, relative, trend_ok):
    origin = int(cycles[0])
    out = []
    for index in sorted({int((c - origin) // SEGMENT_SIZE) for c in cycles}):
        low = origin + index * SEGMENT_SIZE
        mask = np.array([low <= c < low + SEGMENT_SIZE for c in cycles])
        n = int(mask.sum())
        std_percent = 100 * _std(relative[mask]) if trend_ok and n >= 2 else None
        out.append(dict(cycle_start=int(cycles[mask][0]), cycle_end=int(cycles[mask][-1]), count=n,
                        mean_residual=float(residual[mask].mean()),
                        relative_residual_std_percent=std_percent,
                        note=None if std_percent is not None else 'undefined: fewer than 2 points or non-positive trend'))
    return out


def _fit_branch(cycles, current, degree):
    span = cycles[-1] - cycles[0]
    x = 2 * (cycles - cycles[0]) / span - 1
    coefficients = np.linalg.lstsq(np.vander(x, degree + 1, increasing=True), current, rcond=None)[0]
    trend = np.vander(x, degree + 1, increasing=True) @ coefficients
    residual = current - trend
    trend_ok = bool(np.all(trend > 0))
    relative = residual / trend if trend_ok else None
    lag1, lag1_note = _lag1(residual)
    return dict(
        degree=degree, coefficients=[float(c) for c in coefficients],
        exact_interpolation=bool(len(cycles) <= degree + 1),
        trend_positive_at_all_points=trend_ok,
        relative_residual_std_percent=100 * _std(relative) if trend_ok and len(cycles) >= 2 else None,
        residual_std_absolute=_std(residual), residual_lag1_correlation=lag1, lag1_note=lag1_note,
        segments=_segments(cycles, residual, relative if trend_ok else residual, trend_ok),
        _trend=trend, _residual=residual, _relative=relative)


def _branch(name, cycles, current, unit):
    fits = {d: _fit_branch(cycles, current, d) for d in SENSITIVITY_DEGREES}
    primary = fits[PRIMARY_DEGREE]
    p, s = primary['relative_residual_std_percent'], fits[4]['relative_residual_std_percent']
    change = 100 * (s - p) / p if p not in (None, 0) and s is not None else None
    mean_value = float(current.mean())
    raw_std = _std(current)
    result = dict(
        branch=name, unit=unit, status='ok' if primary['trend_positive_at_all_points'] else 'blocked',
        blocked_reason=None if primary['trend_positive_at_all_points'] else 'fitted trend is not positive at every used cycle; relative deviation withheld',
        raw_statistics=dict(count=int(len(current)), mean=mean_value, std_ddof1=raw_std,
                            relative_std_percent=100 * raw_std / mean_value if mean_value > 0 and raw_std is not None else None,
                            min=float(current.min()), max=float(current.max())),
        primary=dict(method='ols_polynomial_normalized_x', degree=PRIMARY_DEGREE,
                     coefficients=primary['coefficients'], coefficient_basis='x=2*(n-n_min)/(n_max-n_min)-1, ascending powers',
                     relative_residual_std_percent=p, residual_std_absolute=primary['residual_std_absolute'],
                     residual_lag1_correlation=primary['residual_lag1_correlation'], lag1_note=primary['lag1_note'],
                     segments=primary['segments']),
        sensitivity={str(d): {k: v for k, v in f.items() if not k.startswith('_')} for d, f in fits.items()},
        degree4_vs_degree3_change_percent=change)
    series = dict(trend=primary['_trend'].tolist(), residual=primary['_residual'].tolist(),
                  relative_residual=None if primary['_relative'] is None else primary['_relative'].tolist())
    return result, series


def analyze_c2c(table, *, filename, sha256=None, sheet=None, device_id=None, condition_id=None,
                measurement_conditions=None):
    """Analyse a parsed table (``ctfm.measurement.parse_table`` output). The input is never modified."""
    table = deepcopy(table)
    found = _recognize_columns(table['columns'])
    series, read_notes = _read_series(table, found)
    cycles = series['cycle']
    unit = found['program']['unit']
    conditions = {field: dict(value=None, confirmed=False) for field in CONDITION_FIELDS}
    unknown = set(measurement_conditions or {}) - set(CONDITION_FIELDS)
    if unknown:
        raise C2CAnalysisError([dict(code='unknown_condition_field', detail=str(sorted(unknown)))])
    for field, value in (measurement_conditions or {}).items():
        conditions[field] = dict(value=value, confirmed=True)
    program, program_series = _branch('program', cycles, series['program'], unit)
    erase, erase_series = _branch('erase', cycles, series['erase'], unit)
    check = dict(status='not_provided', max_abs_difference=None)
    if series['difference'] is not None:
        gap = float(np.max(np.abs(series['difference'] - (series['erase'] - series['program']))))
        scale = float(np.max(np.abs(series['erase']))) or 1.0
        check = dict(status='consistent' if gap <= 1e-9 * scale else 'mismatch', max_abs_difference=gap,
                     note='verification only; never used as an individual-conductance deviation')
    warnings = [
        'Trend-corrected relative deviation; NOT a pure C2C / iid noise estimate. Residuals include read noise, remaining trend and model error.',
        'Independent random sampling in the simulator does not reproduce the temporal correlation of the measured residuals.',
    ]
    for branch in (program, erase):
        lag1 = branch['primary']['residual_lag1_correlation']
        change = branch['degree4_vs_degree3_change_percent']
        warnings.append(f"{branch['branch']}: cubic residual lag-1 correlation = "
                        f"{'undefined (' + str(branch['primary']['lag1_note']) + ')' if lag1 is None else format(lag1, '.3f')}; "
                        f"degree-4 estimate differs from degree-3 by "
                        f"{'undefined' if change is None else format(change, '+.1f') + '%'} (model dependence).")
        if branch['status'] == 'blocked':
            warnings.append(f"{branch['branch']}: {branch['blocked_reason']}")
    if check['status'] == 'mismatch':
        warnings.append('Erase_minus_Program column disagrees with Erase-Program beyond floating-point tolerance.')
    if not read_notes['sorted_input']:
        warnings.append('Input rows were not in ascending cycle order; sorted by cycle for analysis (source rows preserved).')
    missing = [f for f, c in conditions.items() if not c['confirmed']]
    if missing:
        warnings.append(f'Measurement conditions not confirmed: {missing}. They are not copied from LTP/LTD.')
    return dict(
        kind='c2c_detrended', analysis_version=C2C_ANALYSIS_VERSION,
        method=dict(name='cubic_ols_detrended_relative_deviation', primary_degree=PRIMARY_DEGREE,
                    sensitivity_degrees=list(SENSITIVITY_DEGREES), ddof=1, segment_size_cycles=SEGMENT_SIZE,
                    normalization='x = 2*(n-n_min)/(n_max-n_min)-1', trend='T(n)=a+b*x+c*x^2+d*x^3',
                    residual='r=I-T', relative_residual='z=r/T',
                    statistic='relative_residual_std_percent = 100*std(z, ddof=1)',
                    solver='numpy.linalg.lstsq (SVD)', extrapolation=False),
        provenance=dict(filename=filename, sha256=sha256, sheet=sheet, device_id=device_id, condition_id=condition_id,
                        columns={k: v['header'] for k, v in found.items()}, unit=unit,
                        unit_scale_to_ampere=UNIT_TO_AMPERE[unit],
                        cycle_min=int(cycles[0]), cycle_max=int(cycles[-1]), cycle_count=int(len(cycles)),
                        source_row_first=series['source_rows'][0], source_row_last=series['source_rows'][-1], **read_notes),
        measurement_conditions=conditions,
        is_pure_c2c_iid_estimate=False,
        program=program, erase=erase, difference_check=check,
        simulator_use=dict(
            candidate_branch='program', candidate_relative_std_percent=program['primary']['relative_residual_std_percent'],
            erase_role='analysis_only', approved_for_simulator=False,
            note='Only the Program result may later be offered to the simulator, after explicit user approval. '
                 'Erase is not applied, not averaged with Program, and not mapped to G+/G-.'),
        series=dict(cycle=cycles.tolist(), program_current=series['program'].tolist(), erase_current=series['erase'].tolist(),
                    program=program_series, erase=erase_series),
        warnings=warnings)


def analyze_c2c_file(data: bytes, filename: str, *, sheet=None, **kwargs):
    table = parse_table(data, filename, sheet=sheet)
    if not table['columns']:
        raise C2CAnalysisError([dict(code='sheet_not_selected', detail=str(table.get('warnings')))])
    return analyze_c2c(table, filename=filename, sha256=hashlib.sha256(data).hexdigest(), sheet=sheet, **kwargs)
