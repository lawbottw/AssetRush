"""Apply repository SQL migrations to the configured PostgreSQL database."""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import re
import sys
from dataclasses import dataclass
from pathlib import Path

import asyncpg  # type: ignore[import-untyped]

from assetrush.config import get_settings
from assetrush.console import force_utf8_output
from assetrush.db import DatabaseNotConfiguredError

MIGRATION_NAME = re.compile(r"^(?P<version>[0-9]{14})_[a-z0-9_]+\.sql$")
MIGRATION_LOCK = "assetrush:schema-migrations"


@dataclass(frozen=True, slots=True)
class Migration:
    version: str
    path: Path
    checksum: str
    sql: str


def discover_migrations(directory: Path) -> tuple[Migration, ...]:
    migrations: list[Migration] = []
    for path in sorted(directory.glob("*.sql")):
        match = MIGRATION_NAME.fullmatch(path.name)
        if match is None:
            raise ValueError(f"invalid migration filename: {path.name}")
        sql = path.read_text(encoding="utf-8")
        migrations.append(
            Migration(
                version=match.group("version"),
                path=path,
                checksum=hashlib.sha256(sql.encode()).hexdigest(),
                sql=sql,
            )
        )

    versions = [migration.version for migration in migrations]
    if len(versions) != len(set(versions)):
        raise ValueError("migration versions must be unique")
    return tuple(migrations)


def asyncpg_dsn(database_url: str) -> str:
    if database_url.startswith("postgresql+asyncpg://"):
        return database_url.replace("postgresql+asyncpg://", "postgresql://", 1)
    if database_url.startswith("postgres://") or database_url.startswith("postgresql://"):
        return database_url
    raise ValueError("DATABASE_URL must use a PostgreSQL scheme")


async def apply_migrations(
    connection: asyncpg.Connection, migrations: tuple[Migration, ...]
) -> int:
    await connection.execute(
        """
        create table if not exists public.assetrush_schema_migrations (
          version text primary key,
          checksum text not null,
          applied_at timestamptz not null default now()
        )
        """
    )
    await connection.execute("select pg_advisory_lock(hashtext($1))", MIGRATION_LOCK)
    applied = 0
    try:
        for migration in migrations:
            existing = await connection.fetchrow(
                "select checksum from public.assetrush_schema_migrations where version = $1",
                migration.version,
            )
            if existing is not None:
                if existing["checksum"] != migration.checksum:
                    raise RuntimeError(
                        f"applied migration {migration.version} checksum changed: "
                        f"{migration.path.name}"
                    )
                continue

            async with connection.transaction():
                await connection.execute(migration.sql)
                await connection.execute(
                    """
                    insert into public.assetrush_schema_migrations (version, checksum)
                    values ($1, $2)
                    """,
                    migration.version,
                    migration.checksum,
                )
            applied += 1
            print(f"APPLIED {migration.path.name}")
    finally:
        await connection.execute("select pg_advisory_unlock(hashtext($1))", MIGRATION_LOCK)
    return applied


async def _run(args: argparse.Namespace) -> int:
    try:
        migrations = discover_migrations(args.migrations_dir)
    except ValueError as exc:
        print(f"FAIL: {exc}", file=sys.stderr)
        return 1

    if args.dry_run:
        for migration in migrations:
            print(f"{migration.version} {migration.checksum[:12]} {migration.path.name}")
        return 0

    database_url = get_settings().database_url.get_secret_value()
    if not database_url:
        raise DatabaseNotConfiguredError("DATABASE_URL 未設定")

    connection = await asyncpg.connect(asyncpg_dsn(database_url))
    try:
        applied = await apply_migrations(connection, migrations)
    finally:
        await connection.close()

    print(f"OK: {applied} migration(s) applied; {len(migrations) - applied} already current")
    return 0


def main(argv: list[str] | None = None) -> int:
    force_utf8_output()
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--migrations-dir",
        type=Path,
        default=Path(__file__).resolve().parents[3] / "supabase" / "migrations",
    )
    parser.add_argument("--dry-run", action="store_true")
    try:
        return asyncio.run(_run(parser.parse_args(argv)))
    except DatabaseNotConfiguredError as exc:
        print(f"FAIL: {exc}", file=sys.stderr)
        return 1
    except Exception as exc:  # noqa: BLE001 - database drivers expose many subclasses
        print(f"FAIL: migrate failed: {type(exc).__name__}: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
