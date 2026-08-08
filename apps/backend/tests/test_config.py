"""Settings 的解析行為。

`frontend_origins` 有一個不明顯的陷阱：pydantic-settings 對 list 型別預設會先
`json.loads()`，那發生在 `field_validator` **之前**。少了 `NoDecode` 標註的話，
`.env` 裡寫 `FRONTEND_ORIGINS=http://localhost:3000` 會在 Settings 初始化時就
炸成 JSONDecodeError——而且錯誤訊息完全看不出是這個原因。
"""

import pytest

from assetrush.config import Settings


def _settings(monkeypatch: pytest.MonkeyPatch, **env: str) -> Settings:
    """只從環境變數建立 Settings，忽略開發者本機的 .env。"""
    for key, value in env.items():
        monkeypatch.setenv(key, value)
    return Settings(_env_file=None)  # type: ignore[call-arg]


def test_frontend_origins_defaults(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("FRONTEND_ORIGINS", raising=False)
    assert _settings(monkeypatch).frontend_origins == ["http://localhost:3000"]


def test_frontend_origins_single_value(monkeypatch: pytest.MonkeyPatch) -> None:
    """裸的 URL 不是合法 JSON——這正是 NoDecode 要解決的情況。"""
    settings = _settings(monkeypatch, FRONTEND_ORIGINS="http://localhost:3000")
    assert settings.frontend_origins == ["http://localhost:3000"]


def test_frontend_origins_comma_separated(monkeypatch: pytest.MonkeyPatch) -> None:
    settings = _settings(monkeypatch, FRONTEND_ORIGINS="http://a.com,http://b.com")
    assert settings.frontend_origins == ["http://a.com", "http://b.com"]


def test_frontend_origins_strips_whitespace(monkeypatch: pytest.MonkeyPatch) -> None:
    settings = _settings(monkeypatch, FRONTEND_ORIGINS=" http://a.com , http://b.com ")
    assert settings.frontend_origins == ["http://a.com", "http://b.com"]


def test_secrets_are_masked_in_repr(monkeypatch: pytest.MonkeyPatch) -> None:
    """機密不得出現在 repr——FastAPI 的 500 頁面與 uvicorn 的 traceback 會印區域變數。"""
    settings = _settings(
        monkeypatch,
        SUPABASE_SERVICE_ROLE_KEY="sb_secret_should_never_appear",
        DATABASE_URL="postgresql+asyncpg://u:hunter2@host/db",
    )
    dumped = repr(settings)
    assert "should_never_appear" not in dumped
    assert "hunter2" not in dumped
    # 但取得原值仍然可行
    assert settings.database_url.get_secret_value().endswith("/db")


def test_supabase_ref_extracted_from_url(monkeypatch: pytest.MonkeyPatch) -> None:
    """ref 只用於 log，必須不含任何機密。"""
    settings = _settings(monkeypatch, SUPABASE_URL="https://abcdefgh.supabase.co")
    assert settings.supabase_ref == "abcdefgh"


def test_supabase_ref_without_url(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("SUPABASE_URL", raising=False)
    assert _settings(monkeypatch).supabase_ref == "unknown"


def test_has_database_reflects_database_url(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("DATABASE_URL", raising=False)
    assert _settings(monkeypatch).has_database is False
    assert _settings(monkeypatch, DATABASE_URL="postgresql+asyncpg://u:p@h/d").has_database is True
