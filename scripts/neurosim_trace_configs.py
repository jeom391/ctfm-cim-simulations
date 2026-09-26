"""Trace NeuroSim failures per array size with a -g -O0 build of an isolated engine copy (run in WSL where the engine lives).

    python scripts/neurosim_trace_configs.py ENGINE_DIR WORK_DIR OUT.json [CASE ...]

ENGINE_DIR is a git checkout of DNN_NeuroSim_V1.4 whose objects were built with debug flags (the reference checkout is
never modified). For every case the tool copies ENGINE_DIR/Inference_pytorch/NeuroSIM to WORK_DIR/<case>, applies the
same Param.cpp substitutions the adapter uses (or none for the stock configuration), recompiles Param.o with -g -O0,
links, and runs the engine under gdb. It records the effective Param values, the floorplan inputs (novelMapping,
markNM, maxPESizeNM, maxTileSizeCM), stdout, and -- when the engine dies -- the backtrace with arguments and locals.
Nothing is patched in the engine sources: this is measurement only.
"""
import json
import re
import shutil
import subprocess
import sys
from pathlib import Path

from ctfm.adapters import neurosim, neurosim_build
from ctfm.adapters.proxy_preset import proxy_preset

HOME = Path.home()
SMOKE = HOME/'ctfm-engines/smoke/neurosim-binary'
FLAGS = '-fopenmp -O0 -g -std=c++0x -w'


def mnist_inputs():
    t = SMOKE/'traces'
    return SMOKE/'NetWork_ctfm_mlp.csv', [t/'weight_layer1.csv', t/'input_layer1.csv', t/'weight_layer2.csv', t/'input_layer2.csv']


def synth_inputs(name):
    d = HOME/'ctfm-engines'/name/'inputs'
    return d/'NetWork_ctfm.csv', [d/'weight_fc1.csv', d/'input_fc1.csv', d/'weight_fc2.csv', d/'input_fc2.csv']


def proxy(tile):
    preset = dict(proxy_preset(256), sub_array=tile, parallel_rows=tile)
    return neurosim.build_config(preset, dict(tile_size=tile, adc_bits=6, adc_order='subtract_then_adc',
                                              columns_per_adc=8, input_bits=8))


CASES = {}
for tile in (32, 64, 128, 256):
    CASES['proxy-mnist-%d' % tile] = (proxy(tile), tile, mnist_inputs)
for tile in (64, 128, 256):
    CASES['stock-mnist-%d' % tile] = ({}, tile, mnist_inputs)
CASES['proxy-synth768-64'] = (proxy(64), 64, lambda: synth_inputs('wiring-out-768,512,64-64'))
CASES['proxy-synth768-128'] = (proxy(128), 128, lambda: synth_inputs('wiring-out-768,512,64-128'))
CASES['proxy-synth784-64'] = (proxy(64), 64, lambda: synth_inputs('wiring-out-784,512,10-64'))

GDB = r'''
set pagination off
set confirm off
set print pretty off
break ChipFloorPlan
commands
silent
printf "FLOORPLAN findNumTile=%d findUtilization=%d findSpeedUp=%d maxPESizeNM=%g maxTileSizeCM=%g numPENM=%g\n", findNumTile, findUtilization, findSpeedUp, maxPESizeNM, maxTileSizeCM, numPENM
printf "PARAM novelMapping=%d rowSub=%d colSub=%d rowParallel=%d cellBit=%d synapseBit=%d colPerSynapse=%d rowPerSynapse=%d memcelltype=%d numColMuxed=%d\n", param->novelMapping, param->numRowSubArray, param->numColSubArray, param->numRowParallel, param->cellBit, param->synapseBit, param->numColPerSynapse, param->numRowPerSynapse, param->memcelltype, param->numColMuxed
p markNM
continue
end
run
echo \n=== BACKTRACE ===\n
bt
echo \n=== FRAME0 ===\n
frame 0
info args
info locals
echo \n=== FRAME1 ===\n
frame 1
info args
info locals
echo \n=== FRAME2 ===\n
frame 2
info locals
'''


def run_case(name, engine_dir, work):
    config, tile, inputs = CASES[name]
    net, traces = inputs()
    src = Path(engine_dir)/'Inference_pytorch/NeuroSIM'
    dst = work/name
    if dst.exists():
        shutil.rmtree(dst)
    shutil.copytree(src, dst, symlinks=True)
    effective = None
    if config:
        text, applied = neurosim_build.apply_config((dst/'Param.cpp').read_text(encoding='utf-8'), config)
        (dst/'Param.cpp').write_text(text, encoding='utf-8')
        effective = neurosim_build.read_effective(text)
    (dst/'Param.o').unlink(missing_ok=True)
    build = subprocess.run(['make', '-C', str(dst), 'main', 'CXXFLAGS='+FLAGS], capture_output=True, text=True)
    if build.returncode != 0:
        return dict(case=name, build_error=build.stderr[-1500:])
    argv = [str(net), '8', '8', str(tile), str(tile)] + [str(t) for t in traces]
    (dst/'trace.gdb').write_text(GDB.replace('run\n', 'run %s\n' % ' '.join('"%s"' % a for a in argv)), encoding='utf-8')
    gdb = subprocess.run(['gdb', '-batch', '-x', str(dst/'trace.gdb'), str(dst/'main')], capture_output=True, text=True, cwd=dst)
    out = gdb.stdout
    return dict(case=name, tile=tile, effective_param_patch=effective, argv=[Path(a).name for a in argv],
                floorplan=[l for l in out.splitlines() if l.startswith(('FLOORPLAN', 'PARAM', '$'))][:16],
                engine_errors=[l for l in out.splitlines() if 'ERROR' in l],
                crashed='SIGSEGV' in out or 'SIGABRT' in out,
                signal=next((l for l in out.splitlines() if l.startswith('Program received signal')), None),
                backtrace=out.split('=== BACKTRACE ===')[1][:6000] if '=== BACKTRACE ===' in out else None,
                finished=('Program exited normally' in out or 'exited with code' in out or '[Inferior 1 (process' in out and 'exited' in out))


if __name__ == '__main__':
    engine_dir, work, out = Path(sys.argv[1]), Path(sys.argv[2]), Path(sys.argv[3])
    work.mkdir(parents=True, exist_ok=True)
    names = sys.argv[4:] or list(CASES)
    results = json.loads(out.read_text(encoding='utf-8')) if out.exists() else []
    for n in names:
        r = run_case(n, engine_dir, work)
        results = [x for x in results if x.get('case') != n] + [r]
        print(n, 'crashed' if r.get('crashed') else 'ok/other', r.get('engine_errors'), flush=True)
        out.write_text(json.dumps(results, indent=1, default=str), encoding='utf-8')
