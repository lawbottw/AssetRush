"""health 端點。

測試一律不打真實 Supabase——CI 打外部服務會變成不穩定的紅燈來源。
DB 行為用 monkeypatch 換掉 `ping`。
"""

import logging
from collections.abc import Iterator

import pytest
from fastapi.testclient import TestClient

from assetrush.console import APP_LOGGER
from assetrush.db import DatabaseNotConfiguredError
from assetrush.main import app


@pytest.fixture
def client(monkeypatch: pytest.MonkeyPatch) -> Iterator[TestClient]:
    """預設讓 ping 成功，避免 lifespan 在測試環境真的去連線。"""

    async def _ok() -> float:
        return 1.23

    monkeypatch.setattr("assetrush.main.ping", _ok)
    monkeypatch.setattr("assetrush.routers.health.ping", _ok)
    monkeypatch.setattr("assetrush.main.dispose_engine", _noop)
    with TestClient(app) as c:
        yield c


async def _noop() -> None:
    return None


def test_health_returns_200(client: TestClient) -> None:
    res = client.get("/health")
    assert res.status_code == 200
    assert res.json()["status"] == "ok"


def test_health_does_no_io(monkeypatch: pytest.MonkeyPatch, client: TestClient) -> None:
    """liveness 不該碰 DB——碰了就會在 Supabase 掛掉時觸發不必要的重啟。"""

    async def _boom() -> float:
        raise AssertionError("/health 不該呼叫 ping()")

    monkeypatch.setattr("assetrush.routers.health.ping", _boom)
    assert client.get("/health").status_code == 200


def test_health_db_ok(client: TestClient) -> None:
    res = client.get("/health/db")
    assert res.status_code == 200
    body = res.json()
    assert body["status"] == "ok"
    assert body["latency_ms"] == 1.2


def test_health_db_not_configured(monkeypatch: pytest.MonkeyPatch, client: TestClient) -> None:
    async def _unset() -> float:
        raise DatabaseNotConfiguredError("DATABASE_URL 未設定")

    monkeypatch.setattr("assetrush.routers.health.ping", _unset)
    res = client.get("/health/db")
    assert res.status_code == 503
    assert res.json()["status"] == "not_configured"


def test_health_db_connection_error(monkeypatch: pytest.MonkeyPatch, client: TestClient) -> None:
    async def _down() -> float:
        raise OSError("connection refused")

    monkeypatch.setattr("assetrush.routers.health.ping", _down)
    res = client.get("/health/db")
    assert res.status_code == 503
    body = res.json()
    assert body["status"] == "error"
    assert "connection refused" in body["detail"]


def test_startup_fails_fast_on_db_outage(monkeypatch: pytest.MonkeyPatch) -> None:
    """M4 寫入全部依賴 DB；啟動時不能留下半可用 API。"""

    async def _down() -> float:
        raise OSError("connection refused")

    monkeypatch.setattr("assetrush.main.ping", _down)
    monkeypatch.setattr("assetrush.main.dispose_engine", _noop)
    with pytest.raises(OSError, match="connection refused"), TestClient(app):
        pass


def test_startup_fails_fast_without_database_url(monkeypatch: pytest.MonkeyPatch) -> None:
    async def _unset() -> float:
        raise DatabaseNotConfiguredError("DATABASE_URL 未設定")

    monkeypatch.setattr("assetrush.main.ping", _unset)
    monkeypatch.setattr("assetrush.main.dispose_engine", _noop)
    with pytest.raises(DatabaseNotConfiguredError, match="DATABASE_URL"), TestClient(app):
        pass


def test_startup_configures_app_logging(monkeypatch: pytest.MonkeyPatch) -> None:
    """lifespan 必須真的呼叫 setup_app_logging()。

    test_console.py 驗證那個函式本身是對的，但驗證不到「有沒有被呼叫」——
    少了這個測試，把 lifespan 裡那一行刪掉，整套測試仍然全綠，而實際跑
    `make dev` 時成功訊息又會消失。
    """

    async def _ok() -> float:
        return 1.0

    monkeypatch.setattr("assetrush.main.ping", _ok)
    monkeypatch.setattr("assetrush.main.dispose_engine", _noop)

    logger = logging.getLogger(APP_LOGGER)
    saved_handlers, saved_level = logger.handlers[:], logger.level
    logger.handlers.clear()
    logger.setLevel(logging.NOTSET)
    try:
        with TestClient(app):
            assert logger.handlers, "lifespan 沒有設定 assetrush 的 log handler"
            assert logger.isEnabledFor(logging.INFO)
    finally:
        logger.handlers[:] = saved_handlers
        logger.setLevel(saved_level)


def test_startup_logs_success(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    """成功連線必須留下 INFO 訊息。

    這則訊息就是 issue #5 的完成判準（「起動時能成功連上」）本身。少了它，
    連線成功與「啟動檢查根本沒跑」在畫面上完全一樣——而失敗時反而有紅字，
    這種不對稱會讓人以為沒問題。
    """

    async def _ok() -> float:
        return 42.0

    monkeypatch.setattr("assetrush.main.ping", _ok)
    monkeypatch.setattr("assetrush.main.dispose_engine", _noop)

    with caplog.at_level(logging.INFO, logger="assetrush.main"), TestClient(app):
        pass

    assert any("Supabase 連線正常" in r.message for r in caplog.records)


def test_startup_logs_failure(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    async def _down() -> float:
        raise OSError("connection refused")

    monkeypatch.setattr("assetrush.main.ping", _down)
    monkeypatch.setattr("assetrush.main.dispose_engine", _noop)

    with (
        caplog.at_level(logging.CRITICAL, logger="assetrush.main"),
        pytest.raises(OSError, match="connection refused"),
        TestClient(app),
    ):
        pass

    assert any("Supabase 連線失敗" in r.message for r in caplog.records)
