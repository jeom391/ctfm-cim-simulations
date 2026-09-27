"""Run the measured C2C detrending analysis on one workbook and write a reviewable result.

    python scripts/analyze_c2c.py --file <A3.xlsx> --out result.json --plot result.png \
        [--sheet Origin_data] [--device-id ID] [--condition-id ID] [--condition program_voltage_v=10 ...] [--no-series]

Measurement conditions are recorded only when passed with --condition (each is then marked user-confirmed);
they are never copied from LTP/LTD. The source file is only read.
"""
import argparse
import json
import sys
from pathlib import Path

from ctfm.measurement.c2c import (CONDITION_FIELDS, TEXT_FIELDS, VOLTAGE_FIELDS, C2CAnalysisError,
                                  analyze_c2c_file)


def parse_condition(text):
    """KEY=VALUE -> typed value; the core applies the same validation (finite/positive/non-empty) to it."""
    key, _, raw = text.partition('=')
    if key not in CONDITION_FIELDS:
        raise SystemExit(f'--condition KEY must be one of {CONDITION_FIELDS}, got {key!r}')
    if key in TEXT_FIELDS:
        return key, raw
    try:
        return key, float(raw)
    except ValueError:
        raise SystemExit(f'--condition {key} needs a number ({"voltage" if key in VOLTAGE_FIELDS else "positive"}), got {raw!r}')


def fmt(value, spec):
    return 'undefined' if value is None else format(value, spec)


def plot(result, path):
    import matplotlib
    matplotlib.use('Agg')
    import matplotlib.pyplot as plt
    s = result['series']
    fig, axes = plt.subplots(2, 2, figsize=(13, 8))
    unit = result['provenance']['unit']
    for name, color in (('program', 'tab:blue'), ('erase', 'tab:red')):
        raw, fit = s[f'{name}_current'], s[name]['trend']
        axes[0][0].plot(s['cycle'], raw, '.', ms=2, color=color, alpha=.5, label=f'{name} raw')
        axes[0][0].plot(s['cycle'], fit, '-', color=color, lw=1.5, label=f'{name} cubic trend')
        rel = s[name]['relative_residual']
        if rel is not None:
            axes[0][1].plot(s['cycle'], [100 * v for v in rel], '-', lw=.6, color=color, label=name)
        deg = result[name]['sensitivity']
        axes[1][0].plot([1, 2, 3, 4], [float('nan') if deg[str(d)]['relative_residual_std_percent'] is None else deg[str(d)]['relative_residual_std_percent'] for d in (1, 2, 3, 4)],
                        'o-', color=color, label=name)
    axes[0][0].set(title=f'Read current ({unit}) and cubic trend', xlabel='cycle'); axes[0][0].legend()
    axes[0][1].set(title='Relative residual vs cycle (%)', xlabel='cycle'); axes[0][1].legend()
    axes[1][0].set(title='Trend-corrected relative std (%) by degree', xlabel='polynomial degree', yscale='log'); axes[1][0].legend()
    axes[1][1].axis('off')
    lines = ['NOT a pure C2C / iid estimate; model- and lag-dependent.', '']
    for name in ('program', 'erase'):
        b = result[name]
        p = b['primary']
        lines.append(f"{name}: cubic rel. std = {fmt(p['relative_residual_std_percent'], '.6f')} %  "
                     f"lag-1 = {fmt(p['residual_lag1_correlation'], '.3f')}  "
                     f"deg4 vs deg3 = {fmt(b['degree4_vs_degree3_change_percent'], '+.1f')} %"
                     + (f"  [{b['status']}: {b['blocked_reason']}]" if b['status'] != 'ok' else ''))
    lines += ['', 'Only Program is a simulator candidate (unapproved); Erase is analysis-only.',
              f"file sha256: {result['provenance']['sha256'][:16]}...  cycles {result['provenance']['cycle_min']}-{result['provenance']['cycle_max']}"]
    axes[1][1].text(0, 1, '\n'.join(lines), va='top', fontsize=9, family='monospace', wrap=True)
    fig.tight_layout()
    fig.savefig(path, dpi=110)


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument('--file', required=True)
    parser.add_argument('--sheet')
    parser.add_argument('--device-id')
    parser.add_argument('--condition-id')
    parser.add_argument('--condition', action='append', default=[])
    parser.add_argument('--out')
    parser.add_argument('--plot')
    parser.add_argument('--no-series', action='store_true', help='omit per-cycle raw/trend arrays from the JSON')
    args = parser.parse_args()
    path = Path(args.file)
    conditions = dict(parse_condition(c) for c in args.condition)
    try:
        result = analyze_c2c_file(path.read_bytes(), path.name, sheet=args.sheet, device_id=args.device_id,
                                  condition_id=args.condition_id, measurement_conditions=conditions)
    except C2CAnalysisError as exc:
        print(json.dumps(dict(error='invalid_c2c_input', issues=exc.issues), ensure_ascii=False, indent=2), file=sys.stderr)
        return 2
    except (OSError, ValueError) as exc:  # unreadable file, invalid workbook/CSV, parser limits
        print(json.dumps(dict(error='unreadable_input', detail=str(exc)), ensure_ascii=False), file=sys.stderr)
        return 2
    if args.plot:
        plot(result, args.plot)
    if args.no_series:
        result = {k: v for k, v in result.items() if k != 'series'}
    text = json.dumps(result, ensure_ascii=False, indent=2, allow_nan=False)  # strict JSON; never NaN/Infinity
    if args.out:
        Path(args.out).write_text(text, encoding='utf-8')
    for branch in ('program', 'erase'):
        b = result[branch]
        print(branch, b['status'], 'cubic relative std %:', b['primary']['relative_residual_std_percent'],
              'lag1:', b['primary']['residual_lag1_correlation'])
    print('sheet:', result['provenance']['sheet'], f"({result['provenance']['sheet_selection']})")
    for warning in result['warnings']:
        print('WARNING:', warning)
    return 0


if __name__ == '__main__':
    sys.exit(main())
