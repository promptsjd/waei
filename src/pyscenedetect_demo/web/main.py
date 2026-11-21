from __future__ import annotations

import argparse
from pyscenedetect_demo import __version__
from pyscenedetect_demo.settings import AppSettings


def build_parser() -> argparse.ArgumentParser:
    defaults = AppSettings.from_env()
    parser = argparse.ArgumentParser(
        prog="scene-web",
        description="Start the WAIE web UI.",
    )
    parser.add_argument("--version", action="version", version=f"WAIE {__version__}")
    parser.add_argument(
        "--host",
        default=defaults.host,
        help="Bind address. Default: %(default)s",
    )
    parser.add_argument(
        "--port",
        type=int,
        default=defaults.port,
        help="Listen port. Default: %(default)s",
    )
    parser.add_argument(
        "--output",
        default=str(defaults.output_root),
        help="Output root directory. Default: %(default)s",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)

    import uvicorn

    from pyscenedetect_demo.web import create_app

    app = create_app(output_root=args.output)

    uvicorn.run(app, host=args.host, port=args.port)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
