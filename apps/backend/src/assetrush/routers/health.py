"""健康檢查。

`/health`（liveness）與 `/health/db`（readiness）刻意分開：liveness 探針不該
因為 DB 短暫不可用就把整個 process 重啟掉——重啟解決不了 Supabase 那端的問題，
只會讓還能服務的請求也一起中斷。
"""

from typing import Literal

from fastapi import APIRouter, Response, status
from pydantic import BaseModel

from assetrush import __version__
from assetrush.config import get_settings
from assetrush.db import DatabaseNotConfiguredError, ping

router = APIRouter(tags=["meta"])


class HealthResponse(BaseModel):
    status: str
    version: str
    env: str


class DbHealthResponse(BaseModel):
    status: Literal["ok", "not_configured", "error"]
    latency_ms: float | None = None
    detail: str | None = None


@router.get("/health", response_model=HealthResponse)
async def health() -> HealthResponse:
    """Liveness：不做任何 I/O。"""
    settings = get_settings()
    return HealthResponse(status="ok", version=__version__, env=settings.env)


@router.get("/health/db", response_model=DbHealthResponse)
async def health_db(response: Response) -> DbHealthResponse:
    """Readiness：實際對 Supabase 送一次查詢。

    未設定與連不上回不同的 status，兩者都給 503——對呼叫端而言都是「還不能用」，
    但 `detail` 要能一眼看出該去設定變數還是該去查網路。
    """
    try:
        latency = await ping()
    except DatabaseNotConfiguredError as exc:
        response.status_code = status.HTTP_503_SERVICE_UNAVAILABLE
        return DbHealthResponse(status="not_configured", detail=str(exc))
    except Exception as exc:  # noqa: BLE001 — 連線失敗的型別依 driver 而異
        response.status_code = status.HTTP_503_SERVICE_UNAVAILABLE
        return DbHealthResponse(status="error", detail=f"{type(exc).__name__}: {exc}")

    return DbHealthResponse(status="ok", latency_ms=round(latency, 1))
