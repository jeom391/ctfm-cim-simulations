"""Export the implemented API only; --check detects drift without writing files."""
import argparse
import json
from pathlib import Path

from ctfm_api.app import app


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=Path(__file__).resolve().parent / "openapi/openapi.json")
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()
    expected = (json.dumps(app.openapi(), ensure_ascii=False, indent=2, sort_keys=True, allow_nan=False) + "\n").encode("utf-8")
    if args.check:
        if not args.output.is_file() or args.output.read_bytes() != expected:
            print("OpenAPI snapshot is missing or stale; regenerate with export_openapi.py.")
            return 1
        print("OpenAPI snapshot is current.")
        return 0
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_bytes(expected)
    print("OpenAPI snapshot written.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
