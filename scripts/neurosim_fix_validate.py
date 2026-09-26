"""Compare the reference NeuroSim build with the CTFM-fixed one on every traced case (run in WSL).

    python scripts/neurosim_fix_validate.py REFERENCE_ROOT FIXED_ROOT OUT_DIR

Both roots are clean checkouts (no objects). For each case the same Param.cpp substitutions and inputs are used with
both roots; stdout of every run is saved. The expectation, checked and reported per case:
  * a case the reference completes must give byte-identical stdout with the fix (no behaviour change);
  * a case the reference crashes in CopyPEArray must complete with the fix;
  * a case the engine rejects with its own hierarchy error must still print that error and exit non-zero (cleanly).
"""
import hashlib
import json
import sys
from pathlib import Path

from ctfm.adapters import neurosim, neurosim_build
import importlib.util

spec = importlib.util.spec_from_file_location('trace', Path(__file__).with_name('neurosim_trace_configs.py'))
# neurosim_trace_configs runs nothing on import (main guarded), so its case table is reusable.
trace = importlib.util.module_from_spec(spec)
spec.loader.exec_module(trace)


def run(root, name, out_dir):
    config, tile, inputs = trace.CASES[name]
    net, traces = inputs()
    built = neurosim_build.build(root, config, cache_root=Path.home()/'ctfm-engines/validate-cache')
    argv = [str(built['binary']), str(net), '8', '8', str(tile), str(tile)] + [str(t) for t in traces]
    import subprocess
    p = subprocess.run(argv, capture_output=True, text=True, timeout=1200, cwd=out_dir)
    text = p.stdout
    return dict(returncode=p.returncode, stdout_sha256=hashlib.sha256(text.encode()).hexdigest(), text=text,
                errors=[l for l in text.splitlines() if 'ERROR' in l],
                parsed=neurosim.parse_stdout(text) if p.returncode == 0 else None)


if __name__ == '__main__':
    ref, fixed, out = Path(sys.argv[1]), Path(sys.argv[2]), Path(sys.argv[3])
    (out/'stdout').mkdir(parents=True, exist_ok=True)
    rows = []
    for name in trace.CASES:
        r = run(ref, name, out)
        f = run(fixed, name, out)
        (out/'stdout'/(name+'-reference.txt')).write_text(r['text'], encoding='utf-8')
        (out/'stdout'/(name+'-fixed.txt')).write_text(f['text'], encoding='utf-8')
        if r['returncode'] == 0:
            verdict = 'identical' if r['stdout_sha256'] == f['stdout_sha256'] and f['returncode'] == 0 else 'CHANGED'
        elif f['returncode'] == 0:
            verdict = 'fixed (reference crashed with %s)' % r['returncode']
        elif f['errors']:
            verdict = 'engine constraint kept (rc %s, "%s")' % (f['returncode'], f['errors'][0][:60])
        else:
            verdict = 'STILL FAILS rc %s' % f['returncode']
        totals = (f['parsed'] or {}) if f['returncode'] == 0 else {}
        rows.append(dict(case=name, reference_rc=r['returncode'], fixed_rc=f['returncode'], verdict=verdict,
                         chip_area_m2=totals.get('chip_area_m2'), chip_array_area_m2=totals.get('chip_array_area_m2'),
                         chip_adc_area_m2=totals.get('chip_adc_area_m2'), modes=totals.get('modes')))
        print(name, verdict, flush=True)
        (out/'validation.json').write_text(json.dumps(rows, indent=1, default=str), encoding='utf-8')
