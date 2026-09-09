"""CLI entry point."""

import argparse
import os
from pathlib import Path

from dotenv import load_dotenv

from forgery_audit.client import ResembleClient
from forgery_audit.pipeline import process


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Analyze a media folder and produce Latvian PDFs with raw API evidence."
    )
    parser.add_argument("folder", type=Path)
    parser.add_argument("--output", type=Path, default=Path("results/audit"))
    parser.add_argument("--env-file", type=Path, default=Path(".env"))
    parser.add_argument("--timeout", type=float, default=900, help="Polling deadline per artifact, in seconds")
    parser.add_argument(
        "--offline", action="store_true", help="Generate reports from cached payloads; never submit files"
    )
    parser.add_argument(
        "--analyst",
        default=os.environ.get("FORGERY_AUDIT_ANALYST", ""),
        help="Person who performed the analysis, printed as Sagatavoja; remembered per output folder",
    )
    args = parser.parse_args()
    if args.timeout <= 0:
        parser.error("--timeout must be positive")
    load_dotenv(args.env_file)
    key = os.environ.get("RESEMBLE_AI_API_KEY") or os.environ.get("RESEMBLE_API_TOKEN")
    client = ResembleClient(key) if key and not args.offline else None
    try:
        results = process(args.folder, args.output, client, args.timeout, args.offline, args.analyst)
    except ValueError as exc:
        parser.error(str(exc))
    finally:
        if client:
            client.close()
    for result in results:
        print(f"{result['file']}: {result['assessment']} -> {args.output / result['directory']}")
        if result.get("error"):
            print(f"  {result['error']}")
    return int(any(r.get("error") or not r.get("supported", True) for r in results))


if __name__ == "__main__":
    raise SystemExit(main())
