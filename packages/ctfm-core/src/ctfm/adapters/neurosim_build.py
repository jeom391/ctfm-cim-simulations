"""Isolated NeuroSim builds, one per resolved configuration (decision C1).

Several of the values the hardware baseline fixes are compile-time constants in
NeuroSim's ``Param.cpp`` -- ``levelOutput = 2^adc_bits`` above all -- so a run at
5 bits and a run at 6 bits are two different binaries, not two arguments. This
module gives each resolved configuration its own build, keyed by everything that
can change the produced binary:

    upstream commit + patch hash + resolved hardware config + compiler and flags
    + target platform

A build happens in a temporary directory and is registered into the cache with a
single atomic rename, so a reader never sees a half-built entry. Concurrent
builds of the same key are serialized on a directory lock. After the build the
patched source is read back and compared against the request: if the effective
configuration is not what was asked for, the build fails rather than returning a
binary that silently computes something else.

Nothing here decides whether a configuration is physically meaningful. That is
the preset gate in :mod:`ctfm.adapters.neurosim`.
"""
import hashlib
import json
import os
import platform
import re
import shutil
import subprocess
import time
import uuid
from pathlib import Path

CACHE_ROOT = Path(os.environ.get("CTFM_NEUROSIM_CACHE", "/opt/ctfm-engines/cache"))
PARAM_RELPATH = Path("Inference_pytorch/NeuroSIM/Param.cpp")
BINARY_RELPATH = Path("Inference_pytorch/NeuroSIM/main")
BUILD_COMMAND = ("make", "-C", "Inference_pytorch/NeuroSIM", "-j4")
LOCK_TIMEOUT_S = 1800.0
# A lock older than this lost its owner (killed worker, reboot) and is reclaimed.
LOCK_STALE_S = 3600.0

# Resolved-configuration keys and the Param.cpp field each one sets. Verified
# against 2DInferenceV1.4 Param.cpp: the constructor assigns these as bare
# statements (``levelOutput = 32;``), not through a ``param->`` pointer. Only
# compile-time constants belong here; anything the binary takes on argv stays
# out of the cache key.
PARAM_FIELDS = {
    "operation_mode": "operationmode",
    "memcell_type": "memcelltype",
    "global_bus_type": "globalBusType",
    "sar_adc": "SARADC",
    "current_mode": "currentMode",
    "pipeline": "pipeline",
    "speed_up_degree": "speedUpDegree",
    "temperature_k": "temp",
    "access_type": "accesstype",
    "technode_nm": "technode",
    "sub_array_rows": "numRowSubArray",
    "sub_array_cols": "numColSubArray",
    "columns_per_adc": "numColMuxed",
    "adc_levels": "levelOutput",
    "cell_bit": "cellBit",
    "read_pulse_width_s": "readPulseWidth",
}

# Values the engine computes from the ones above. Patching them would be
# overwritten by the constructor, so they are recorded and never written.
DERIVED_FIELDS = {
    "parallelRead": "derived from operationmode (2 = conventionalParallel -> 1)",
    "numRowParallel": "numRowSubArray when parallelRead, else 1",
    "dumcolshared": "set to levelOutput",
    "readVoltage": "selected from the technode table (22 nm -> 0.55 V); the measured "
                   "VDS cannot be substituted here",
}

# Fields the constructor assigns more than once. The last assignment is the one
# that counts at compile time, so each of these carries the condition under which
# the later one fires. The condition is evaluated against the configuration being
# built -- if it would fire, the patch is refused rather than silently ignored.
CONDITIONAL_FIELDS = {
    "numColMuxed": {
        "detail": "reassigned to numColPerSynapse when conventionalSequential and "
                  "memcelltype==1 (SRAM)",
        "fires": lambda config: (config.get("operation_mode") in (1, 3, 5)
                                 and config.get("memcell_type") == 1)},
    "cellBit": {
        "detail": "forced to 1 when memcelltype==1, because NeuroSim treats every SRAM cell "
                  "as single-bit",
        "fires": lambda config: config.get("memcell_type") == 1},
}

# Anchored to the start of a statement and refusing '==', so a comparison such as
# 'else if (technode == 14)' can never be mistaken for the assignment.
_ASSIGNMENT = r"^([ \t]*{name}\s*=\s*)([^;=][^;]*)(;)"


def _flag(value):
    return 1 if value else 0


def resolve_config(*, adc_bits, columns_per_adc, technode_nm, cell_bit, sub_array,
                   read_pulse_width_s, operation_mode=2, memcell_type=2, access_type=1,
                   global_bus_type=False, sar_adc=False, current_mode=True,
                   pipeline=False, speed_up_degree=1, temperature_k=300):
    """The compile-time half of a run's hardware configuration.

    ``adc_bits`` becomes ``levelOutput = 2**adc_bits``; the spec's ADC bit count
    and NeuroSim's level count are not the same number and must not be confused.
    The defaults are the docs/spec/08 baseline: current-mode MLSA, XY bus,
    22 nm at 300 K, pipeline off, parallel read via operationmode 2.
    """
    if not isinstance(adc_bits, int) or isinstance(adc_bits, bool) or not 3 <= adc_bits <= 8:
        raise ValueError("adc_bits must be an integer in 3..8")
    for name, value in (("columns_per_adc", columns_per_adc), ("technode_nm", technode_nm),
                        ("cell_bit", cell_bit), ("sub_array", sub_array),
                        ("operation_mode", operation_mode), ("memcell_type", memcell_type),
                        ("access_type", access_type), ("speed_up_degree", speed_up_degree),
                        ("temperature_k", temperature_k)):
        if not isinstance(value, int) or isinstance(value, bool) or value < 1:
            raise ValueError(name + " must be a positive integer")
    if not isinstance(read_pulse_width_s, (int, float)) or isinstance(read_pulse_width_s, bool) \
            or not read_pulse_width_s > 0:
        raise ValueError("read_pulse_width_s must be a positive number of seconds")
    return {"adc_bits": adc_bits, "adc_levels": 2**adc_bits, "columns_per_adc": columns_per_adc,
            "technode_nm": technode_nm, "cell_bit": cell_bit,
            "sub_array_rows": sub_array, "sub_array_cols": sub_array,
            "read_pulse_width_s": float(read_pulse_width_s),
            "operation_mode": operation_mode, "memcell_type": memcell_type,
            "access_type": access_type,
            "global_bus_type": _flag(global_bus_type), "sar_adc": _flag(sar_adc),
            "current_mode": _flag(current_mode), "pipeline": _flag(pipeline),
            "speed_up_degree": speed_up_degree, "temperature_k": temperature_k}


def _digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":"),
                                     ensure_ascii=False).encode("utf-8")).hexdigest()


def compiler_identity(compiler=None, flags=()):
    """Compiler name, reported version and flags -- all of which change the binary."""
    compiler = compiler or os.environ.get("CXX") or "g++"
    try:
        completed = subprocess.run([compiler, "--version"], capture_output=True, text=True,
                                   timeout=60)
        version = (completed.stdout or completed.stderr).splitlines()[0].strip()
    except (OSError, subprocess.SubprocessError, IndexError):
        version = None
    return {"compiler": compiler, "version": version, "flags": list(flags)}


def target_platform():
    return {"system": platform.system(), "machine": platform.machine(),
            "libc": " ".join(platform.libc_ver()).strip() or None}


def cache_key(*, upstream_commit, patch_sha256, config, compiler, target):
    """Every input that can change the produced binary, and nothing else."""
    if not upstream_commit:
        raise ValueError("A build must be pinned to an upstream commit")
    return _digest({"upstream_commit": upstream_commit, "patch_sha256": patch_sha256,
                    "config": config, "compiler": compiler, "target": target})


def _pattern(field):
    return re.compile(_ASSIGNMENT.format(name=re.escape(field)), re.MULTILINE)


def _render(value):
    return repr(float(value)) if isinstance(value, float) else str(value)


def apply_config(source, config):
    """Rewrite the Param.cpp assignments this configuration owns.

    Returns the patched text and the substitutions applied, so the cache key
    distinguishes two configurations that differ only in a patched value.

    A field the constructor assigns twice is refused unless the second
    assignment is a documented conditional, because at compile time the last
    assignment is the one that counts.
    """
    patched = source
    applied = {}
    for name, field in PARAM_FIELDS.items():
        if name not in config:
            continue
        pattern = _pattern(field)
        occurrences = len(pattern.findall(patched))
        if not occurrences:
            raise ValueError("Param.cpp has no statement assigning " + field)
        if occurrences > 1:
            known = CONDITIONAL_FIELDS.get(field)
            if known is None:
                raise ValueError("Param.cpp assigns %s %d times; patching the first would be "
                                 "overwritten" % (field, occurrences))
            if known["fires"](config):
                raise ValueError("This configuration reaches the later assignment of %s (%s), "
                                 "so the patched value would not be the effective one"
                                 % (field, known["detail"]))
        rendered = _render(config[name])
        patched = pattern.sub(lambda m: m.group(1)+rendered+m.group(3), patched, count=1)
        applied[field] = config[name]
    return patched, applied


def read_effective(source):
    """Read back what the patched source actually says, field by field."""
    effective = {}
    for name, field in PARAM_FIELDS.items():
        match = _pattern(field).search(source)
        if match is None:
            continue
        value = match.group(2).strip()
        for cast in (int, float):
            try:
                effective[name] = cast(value)
                break
            except ValueError:
                continue
        else:
            effective[name] = value
    return effective


def _acquire(lock, timeout=LOCK_TIMEOUT_S):
    """Directory lock: mkdir is atomic on every platform we target."""
    deadline = time.monotonic()+timeout
    while True:
        try:
            lock.mkdir(parents=True)
            (lock/"owner").write_text("%d@%s" % (os.getpid(), platform.node()))
            return
        except FileExistsError:
            age = time.time()-lock.stat().st_mtime if lock.exists() else 0
            if age > LOCK_STALE_S:
                shutil.rmtree(lock, ignore_errors=True)
                continue
            if time.monotonic() > deadline:
                raise TimeoutError("Timed out waiting for the NeuroSim build lock at "+str(lock))
            time.sleep(0.2)


def build(root, config, *, cache_root=None, compiler=None, flags=(), upstream_commit=None,
          build_command=None, timeout=3600.0):
    """Return the cached binary for this configuration, building it if needed.

    ``root`` is a clean upstream checkout; it is copied rather than modified, so
    the reference checkout keeps producing the reference binary.
    """
    root = Path(root)
    cache_root = Path(cache_root or CACHE_ROOT)
    source_path = root/PARAM_RELPATH
    if not source_path.is_file():
        raise ValueError("No Param.cpp at "+str(source_path))
    patched, applied = apply_config(source_path.read_text(encoding="utf-8"), config)
    if upstream_commit is None:
        completed = subprocess.run(["git", "-C", str(root), "rev-parse", "HEAD"],
                                   capture_output=True, text=True, timeout=60)
        upstream_commit = completed.stdout.strip() or None
    identity = compiler_identity(compiler, flags)
    target = target_platform()
    key = cache_key(upstream_commit=upstream_commit, patch_sha256=_digest(applied),
                    config=config, compiler=identity, target=target)
    entry = cache_root/key
    manifest = {"key": key, "upstream_commit": upstream_commit, "config": config,
                "applied": applied, "compiler": identity, "target": target,
                "derived_by_engine": dict(DERIVED_FIELDS),
                "conditional_reassignments": {field: body["detail"]
                                              for field, body in CONDITIONAL_FIELDS.items()}}
    if (entry/BINARY_RELPATH.name).is_file():
        return dict(manifest, binary=str(entry/BINARY_RELPATH.name), cached=True,
                    effective=json.loads((entry/"effective.json").read_text(encoding="utf-8")))

    cache_root.mkdir(parents=True, exist_ok=True)
    lock = cache_root/(key+".lock")
    _acquire(lock)
    try:
        if (entry/BINARY_RELPATH.name).is_file():
            return dict(manifest, binary=str(entry/BINARY_RELPATH.name), cached=True,
                        effective=json.loads((entry/"effective.json").read_text(encoding="utf-8")))
        staging = cache_root/("building-"+uuid.uuid4().hex)
        try:
            shutil.copytree(root, staging/"src", symlinks=True)
            (staging/"src"/PARAM_RELPATH).write_text(patched, encoding="utf-8")
            # Read back from the file that will be compiled, not from what we
            # intended to write, so a failed substitution cannot pass unnoticed.
            effective = read_effective((staging/"src"/PARAM_RELPATH).read_text(encoding="utf-8"))
            mismatched = {k: (config[k], effective.get(k)) for k in config
                          if k in PARAM_FIELDS and effective.get(k) != config[k]}
            if mismatched:
                raise ValueError("Effective Param.cpp differs from the request: "+repr(mismatched))
            environment = dict(os.environ)
            if identity["compiler"]:
                environment["CXX"] = identity["compiler"]
            if flags:
                environment["CXXFLAGS"] = " ".join(flags)
            completed = subprocess.run(list(build_command or BUILD_COMMAND), cwd=str(staging/"src"),
                                       capture_output=True, text=True, timeout=timeout,
                                       env=environment)
            if completed.returncode != 0:
                raise RuntimeError("NeuroSim build failed (%d):\n%s"
                                   % (completed.returncode, completed.stderr[-4000:]))
            binary = staging/"src"/BINARY_RELPATH
            if not binary.is_file():
                raise RuntimeError("Build reported success but produced no binary at "+str(binary))
            shutil.move(str(binary), str(staging/BINARY_RELPATH.name))
            (staging/"effective.json").write_text(json.dumps(effective, indent=2, sort_keys=True),
                                                  encoding="utf-8")
            (staging/"manifest.json").write_text(json.dumps(manifest, indent=2, sort_keys=True),
                                                 encoding="utf-8")
            shutil.rmtree(staging/"src", ignore_errors=True)
            try:
                os.replace(staging, entry)
            except OSError:
                # Another builder registered this key first; theirs is equivalent.
                if not (entry/BINARY_RELPATH.name).is_file():
                    raise
                shutil.rmtree(staging, ignore_errors=True)
            return dict(manifest, binary=str(entry/BINARY_RELPATH.name), cached=False,
                        effective=effective)
        except BaseException:
            shutil.rmtree(staging, ignore_errors=True)
            raise
    finally:
        shutil.rmtree(lock, ignore_errors=True)
