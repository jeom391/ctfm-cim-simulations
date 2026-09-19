"""Generate schemas from the same models used by API/core; --check never writes."""
import argparse
import json
from pathlib import Path
from ctfm.profiles import ProfileManifest
from ctfm_api.contracts import AnalysisRequest
from ctfm_api.results import AnalysisResult,ExperimentResult

MODELS={"device-profile":ProfileManifest,"analysis-request":AnalysisRequest,"analysis-result":AnalysisResult,"experiment-result":ExperimentResult}
def main():
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument("--check",action="store_true")
    args=parser.parse_args();root=Path(__file__).parent/"schemas";stale=[]
    for name,model in MODELS.items():
        schema=model.model_json_schema();schema["$schema"]="https://json-schema.org/draft/2020-12/schema"
        expected=(json.dumps(schema,ensure_ascii=False,indent=2,sort_keys=True,allow_nan=False)+"\n").encode()
        path=root/(name+".schema.json")
        if args.check:
            if not path.is_file() or path.read_bytes()!=expected:stale.append(str(path.name))
        else:path.write_bytes(expected)
    if stale:print("Stale schemas: "+", ".join(stale));return 1
    print("Shared schemas are current." if args.check else "Shared schemas written.");return 0
if __name__=="__main__":raise SystemExit(main())
