"""The generated snapshot must be reproducible, and check mode must be read-only."""
import json
from pathlib import Path
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "packages/contracts/export_openapi.py"


def test_export_and_read_only_staleness_check(tmp_path):
    output = tmp_path / "openapi.json"

    def run(*args):
        return subprocess.run(
            [sys.executable, str(SCRIPT), "--output", str(output), *args],
            capture_output=True, text=True,
        )

    missing = run("--check")
    assert missing.returncode == 1
    assert not output.exists()
    created = run()
    assert created.returncode == 0, created.stderr
    data = json.loads(output.read_text(encoding="utf-8"))
    assert "/api/v1/experiments" in data["paths"]
    before = output.stat().st_mtime_ns
    assert run("--check").returncode == 0
    assert output.stat().st_mtime_ns == before
    output.write_text("{}\n", encoding="utf-8")
    stale = output.read_bytes()
    assert run("--check").returncode == 1
    assert output.read_bytes() == stale
