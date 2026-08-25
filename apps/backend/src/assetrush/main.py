import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from assetrush import __version__
from assetrush.config import get_settings
from assetrush.console import force_utf8_output, setup_app_logging
from assetrush.db import DatabaseNotConfiguredError, dispose_engine, ping
from assetrush.routers import health

# 必須在 uvicorn 建立 logging handler 之前——handler 會綁定當下的 sys.stderr。
force_utf8_output()

logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    """啟動時驗證一次 Supabase 連線。

    M4 起 API 的所有遊戲寫入都依賴持久層，因此設定缺漏或連線失敗必須 fail-fast；
    只有純 engine 測試與模擬可以在沒有 DB 的情況下執行。
    """
    # 在這裡而非 import 期間：要等 uvicorn 先設定好 logging 才借得到它的 handler
    setup_app_logging()
    settings = get_settings()

    try:
        latency = await ping()
    except DatabaseNotConfiguredError as exc:
        logger.critical("Supabase 未設定：%s", exc)
        await dispose_engine()
        raise
    except Exception as exc:
        logger.critical(
            "Supabase 連線失敗（%s）：%s: %s｜檢查 .env 的 DATABASE_URL 與網路連線",
            settings.supabase_ref,
            type(exc).__name__,
            exc,
        )
        await dispose_engine()
        raise
    else:
        logger.info("Supabase 連線正常（%s，%.0f ms）", settings.supabase_ref, latency)

    try:
        yield
    finally:
        await dispose_engine()


app = FastAPI(
    title="AssetRush API",
    version=__version__,
    description="遊戲狀態的唯一擁有者。所有規則判定都在 engine/（鐵律 1）。",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=get_settings().frontend_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(health.router)
