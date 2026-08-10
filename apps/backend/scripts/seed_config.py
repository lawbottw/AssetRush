"""將 repo 的 config bundle 寫入 `game_configs`。"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
from dataclasses import dataclass
from pathlib import Path

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from assetrush.config_bundle import ConfigBundle, load_config_bundle
from assetrush.console import force_utf8_output
from assetrush.db import DatabaseNotConfiguredError, dispose_engine, get_sessionmaker
from assetrush.engine.config_models import ConfigValidationError


@dataclass(frozen=True, slots=True)
class SeedConfigCommand:
    version: str
    payload_json: str
    activate: bool
    notes: str | None


def build_seed_command(
    bundle: ConfigBundle,
    *,
    activate: bool,
    notes: str | None,
) -> SeedConfigCommand:
    return SeedConfigCommand(
        version=bundle.config.version,
        payload_json=json.dumps(bundle.raw, ensure_ascii=False, sort_keys=True),
        activate=activate,
        notes=notes,
    )


async def seed_config(session: AsyncSession, command: SeedConfigCommand) -> None:
    if command.activate:
        await session.execute(text("update game_configs set is_active = false where is_active"))

    await session.execute(
        text(
            """
            insert into game_configs (version, payload, is_active, notes)
            values (:version, cast(:payload as jsonb), :activate, :notes)
            on conflict (version) do update set
              payload = excluded.payload,
              is_active = case
                when :activate then excluded.is_active
                else game_configs.is_active
              end,
              notes = excluded.notes
            """
        ),
        {
            "version": command.version,
            "payload": command.payload_json,
            "activate": command.activate,
            "notes": command.notes,
        },
    )


async def _run(args: argparse.Namespace) -> int:
    try:
        bundle = load_config_bundle(args.config_dir)
    except ConfigValidationError as exc:
        print(f"FAIL: config validation failed: {exc}", file=sys.stderr)
        return 1

    command = build_seed_command(bundle, activate=args.activate, notes=args.notes)

    try:
        async with get_sessionmaker()() as session, session.begin():
            await seed_config(session, command)
    except DatabaseNotConfiguredError as exc:
        print(f"FAIL: {exc}", file=sys.stderr)
        return 1
    except Exception as exc:  # noqa: BLE001 — DB driver 會丟多種連線/SQL 例外
        print(f"FAIL: seed-config failed: {type(exc).__name__}: {exc}", file=sys.stderr)
        return 1
    finally:
        await dispose_engine()

    active = "active" if command.activate else "inactive"
    print(f"OK: seeded config {command.version} ({active})")
    return 0


def main(argv: list[str] | None = None) -> int:
    force_utf8_output()
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--config-dir",
        type=Path,
        default=Path(__file__).resolve().parents[3] / "config",
        help="config/*.json 目錄",
    )
    parser.add_argument(
        "--activate",
        action="store_true",
        help="將本版本設為新局使用的 active config",
    )
    parser.add_argument("--notes", help="寫入 game_configs.notes")
    return asyncio.run(_run(parser.parse_args(argv)))


if __name__ == "__main__":
    raise SystemExit(main())
