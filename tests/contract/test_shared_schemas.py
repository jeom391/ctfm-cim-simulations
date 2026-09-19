import json
from pathlib import Path
import subprocess
import sys
from jsonschema import Draft202012Validator
ROOT=Path(__file__).resolve().parents[2]
def test_generated_shared_schemas_are_valid_and_current():
    result=subprocess.run([sys.executable,str(ROOT/"packages/contracts/export_schemas.py"),"--check"],capture_output=True,text=True)
    assert result.returncode==0,result.stdout+result.stderr
    for path in (ROOT/"packages/contracts/schemas").glob("*.schema.json"):
        Draft202012Validator.check_schema(json.loads(path.read_text(encoding="utf-8")))
