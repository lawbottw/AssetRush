"""驗證 config/*.json 的 schema 與跨檔不變式。"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from assetrush.config_bundle import load_config_bundle
from assetrush.engine.config_models import ConfigValidationError


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--config-dir",
        type=Path,
        default=Path(__file__).resolve().parents[3] / "config",
        help="config/*.json 目錄",
    )
    args = parser.parse_args(argv)

    try:
        bundle = load_config_bundle(args.config_dir)
    except ConfigValidationError as exc:
        print(f"FAIL: config validation failed: {exc}", file=sys.stderr)
        return 1

    print(f"OK: config validation passed (version {bundle.config.version})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
