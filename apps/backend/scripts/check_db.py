"""驗證 Supabase 連線（`make check-db`）。

刻意獨立於 `make lint` 之外——lint 不該需要網路。
"""

from __future__ import annotations

import asyncio
import sys

from assetrush.config import get_settings
from assetrush.console import force_utf8_output
from assetrush.db import DatabaseNotConfiguredError, dispose_engine, ping


async def _run() -> int:
    settings = get_settings()
    try:
        latency = await ping()
    except DatabaseNotConfiguredError as exc:
        print(f"SKIP: {exc}", file=sys.stderr)
        return 1
    except Exception as exc:  # noqa: BLE001 — 連線失敗的型別依 driver 而異
        print(
            f"FAIL: Supabase 連線失敗（{settings.supabase_ref}）\n"
            f"    {type(exc).__name__}: {exc}\n\n"
            "檢查 apps/backend/.env 的 DATABASE_URL。Supabase dashboard →\n"
            "Settings → Database → Connection string → **Session pooler**\n"
            "（direct connection 是 IPv6-only，家用網路不一定通）。\n"
            "字串開頭要改成 postgresql+asyncpg:// 才是 SQLAlchemy 的 async driver。",
            file=sys.stderr,
        )
        return 1
    finally:
        await dispose_engine()

    print(f"OK: Supabase 連線正常（{settings.supabase_ref}，{latency:.0f} ms）")
    return 0


def main() -> int:
    force_utf8_output()
    return asyncio.run(_run())


if __name__ == "__main__":
    raise SystemExit(main())
