"""Write the immutable deployment baseline or independently refreshed Luna drift status."""
import argparse
import datetime
import json
from pathlib import Path


def build_status(mode, luna_sha, tester_sha, compatible=True, error=""):
    if mode not in {"build", "live"}:
        raise ValueError("Status mode must be build or live")
    if not (len(luna_sha) == 40 and len(tester_sha) == 40 and
            all(c in "0123456789abcdef" for c in (luna_sha + tester_sha).lower())):
        raise ValueError("Expected full Git SHA-1 revisions")
    return {
        "schema_version": 1,
        "mode": mode,
        "luna_sha": luna_sha,
        "tester_sha": tester_sha,
        "compatible": bool(compatible),
        "checked_at": datetime.datetime.now(datetime.timezone.utc).isoformat(),
        "error": error[:1200] if not compatible else "",
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--mode", choices=("build", "live"), required=True)
    parser.add_argument("--luna-sha", required=True)
    parser.add_argument("--tester-sha", required=True)
    parser.add_argument("--compatible", choices=("true", "false"), default="true")
    parser.add_argument("--error-file", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    error = args.error_file.read_text() if args.error_file and args.error_file.exists() else ""
    payload = build_status(args.mode, args.luna_sha, args.tester_sha,
                           args.compatible == "true", error)
    args.output.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n")


if __name__ == "__main__":
    main()
