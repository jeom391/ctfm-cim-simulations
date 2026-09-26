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

from ctfm.measurement.c2c import CONDITION_FIELDS, C2CAnalysisError, analyze_c2c_file


def parse_condition(text):
    key, _, raw = text.partition('=')
    if key not in CONDITION_FIELDS or not raw:
        raise SystemExit(f'--condition must be KEY=VALUE with KEY in {CONDITION_FIELDS}')
    try:
        return key, float(raw)
    except ValueError:
        return key, raw


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
        axes[1][0].plot([1, 2, 3, 4], [deg[str(d)]['relative_residual_std_percent'] or float('nan') for d in (1, 2, 3, 4)],
                        'o-', color=color, label=name)
    axes[0][0].set(title=f'Read current ({unit}) and cubic trend', xlabel='cycle'); axes[0][0].legend()
    axes[0][1].set(title='Relative residual vs cycle (%)', xlabel='cycle'); axes[0][1].legend()
    axes[1][0].set(title='Trend-corrected relative std (%) by degree', xlabel='polynomial degree', yscale='log'); axes[1][0].legend()
    axes[1][1].axis('off')
    lines = ['NOT a pure C2C / iid estimate; model- and lag-dependent.', '']
    for name in ('program', 'erase'):
        b = result[name]
        p = b['primary']
        lines.append(f"{name}: cubic rel. std = {p['relative_residual_std_percent']:.6f} %  "
                     f"lag-1 = {p['residual_lag1_correlation']:.3f}  deg4 vs deg3 = {b['degree4_vs_degree3_change_percent']:+.1f} %"
                     if p['relative_residual_std_percent'] is not None else f'{name}: blocked ({b["blocked_reason"]})')
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
    try:
        result = analyze_c2c_file(path.read_bytes(), path.name, sheet=args.sheet, device_id=args.device_id,
                                  condition_id=args.condition_id,
                                  measurement_conditions=dict(parse_condition(c) for c in args.condition))
    except C2CAnalysisError as exc:
        print(json.dumps(dict(error='invalid_c2c_input', issues=exc.issues), ensure_ascii=False, indent=2), file=sys.stderr)
        return 2
    if args.plot:
        plot(result, args.plot)
    if args.no_series:
        result = {k: v for k, v in result.items() if k != 'series'}
    text = json.dumps(result, ensure_ascii=False, indent=2)
    if args.out:
        Path(args.out).write_text(text, encoding='utf-8')
    for branch in ('program', 'erase'):
        b = result[branch]
        print(branch, b['status'], 'cubic relative std %:', b['primary']['relative_residual_std_percent'],
              'lag1:', b['primary']['residual_lag1_correlation'])
    for warning in result['warnings']:
        print('WARNING:', warning)
    return 0


if __name__ == '__main__':
    sys.exit(main())
