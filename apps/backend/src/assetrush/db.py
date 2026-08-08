"""Postgres 連線。

用 SQLAlchemy async + asyncpg 而非 `supabase-py`：鐵律 3 要求每個改變局狀態的
寫入都先取 advisory lock（`select pg_advisory_xact_lock(hashtext(:gid))`），
那是原生 SQL，PostgREST 表達不出來。`supabase-py` 之後只會用在 Auth Admin API（M5）。

engine 層不得 import 這個模組——依賴方向是 services → db，CI 會檢查
（見 scripts/check_engine_purity.py）。
"""

from __future__ import annotations

import time
from collections.abc import AsyncIterator
from functools import lru_cache

from sqlalchemy import text
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from assetrush.config import Settings, get_settings


class DatabaseNotConfiguredError(RuntimeError):
    """DATABASE_URL 未設定。M0 階段允許，M4 之後應視為啟動失敗。"""


@lru_cache
def get_engine() -> AsyncEngine:
    settings: Settings = get_settings()
    if not settings.has_database:
        raise DatabaseNotConfiguredError(
            "DATABASE_URL 未設定。在 apps/backend/.env 填入 Supabase dashboard → "
            "Settings → Database 的 Session pooler 連線字串（見 README 的環境變數表）。"
        )

    return create_async_engine(
        settings.database_url.get_secret_value(),
        # Supabase 的 pooler 會主動關閉閒置連線，回收前先驗證存活，
        # 否則第一個請求會拿到已斷線的 connection。
        pool_pre_ping=True,
        pool_size=5,
        max_overflow=5,
        echo=False,
    )


@lru_cache
def get_sessionmaker() -> async_sessionmaker[AsyncSession]:
    return async_sessionmaker(get_engine(), expire_on_commit=False)


async def get_session() -> AsyncIterator[AsyncSession]:
    """FastAPI 相依注入用。"""
    async with get_sessionmaker()() as session:
        yield session


async def ping() -> float:
    """對 DB 送一次 `select 1`，回傳往返毫秒數。

    連不上時讓底層例外往上拋——呼叫端要區分「沒設定」與「設定了但連不上」，
    把它們壓成同一個布林值會讓除錯變成猜謎。
    """
    started = time.perf_counter()
    async with get_engine().connect() as conn:
        await conn.execute(text("select 1"))
    return (time.perf_counter() - started) * 1000


async def dispose_engine() -> None:
    """關閉連線池。應用關閉時呼叫。"""
    if get_engine.cache_info().currsize:
        await get_engine().dispose()
