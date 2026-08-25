"""Create Supabase-compatible primitives in a disposable local PostgreSQL database."""

from __future__ import annotations

import asyncio
import sys
from urllib.parse import urlparse

import asyncpg  # type: ignore[import-untyped]
from migrate import asyncpg_dsn

from assetrush.config import get_settings
from assetrush.console import force_utf8_output

LOCAL_HOSTS = {"127.0.0.1", "localhost", "::1"}


def require_local_database(database_url: str) -> str:
    dsn = asyncpg_dsn(database_url)
    host = urlparse(dsn).hostname
    if host not in LOCAL_HOSTS:
        raise ValueError(
            f"bootstrap-test-db refuses non-local database host {host!r}; use disposable PostgreSQL"
        )
    return dsn


async def _run() -> int:
    database_url = get_settings().database_url.get_secret_value()
    connection = await asyncpg.connect(require_local_database(database_url))
    try:
        await connection.execute(
            """
            do $$
            begin
              if not exists (select 1 from pg_roles where rolname = 'anon') then
                create role anon nologin;
              end if;
              if not exists (select 1 from pg_roles where rolname = 'authenticated') then
                create role authenticated nologin;
              end if;
              if not exists (select 1 from pg_roles where rolname = 'service_role') then
                create role service_role nologin bypassrls;
              end if;
            end
            $$;
            create schema if not exists auth;
            create table if not exists auth.users (id uuid primary key);
            create or replace function auth.uid()
            returns uuid
            language sql
            stable
            as $$
              select nullif(current_setting('request.jwt.claim.sub', true), '')::uuid;
            $$;
            """
        )
    finally:
        await connection.close()
    print("OK: local Supabase-compatible test primitives are ready")
    return 0


def main() -> int:
    force_utf8_output()
    try:
        return asyncio.run(_run())
    except Exception as exc:  # noqa: BLE001 - command must return a stable non-zero result
        print(f"FAIL: bootstrap-test-db: {type(exc).__name__}: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
