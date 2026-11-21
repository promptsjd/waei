from __future__ import annotations

import argparse
from pathlib import Path

from pyscenedetect_demo.report import generate_html_report_from_json


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="scene-report",
        description="Generate a printable HTML storyboard report from scenes.json.",
    )
    parser.add_argument("json_path", help="Path to the generated scenes.json file.")
    parser.add_argument(
        "--output",
        default=None,
        help="Optional output HTML path. Default: report.html next to scenes.json",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        output_path = generate_html_report_from_json(
            json_path=Path(args.json_path),
            output_path=Path(args.output) if args.output else None,
        )
    except Exception as exc:
        parser.exit(status=1, message=f"Error: {exc}\n")
    print(f"HTML report: {output_path.resolve()}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
