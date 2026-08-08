from functools import lru_cache
from pathlib import Path
from typing import Annotated

from pydantic import Field, SecretStr, field_validator
from pydantic_settings import BaseSettings, NoDecode, SettingsConfigDict

# repo 根目錄：config.py → assetrush → src → backend → apps → <root>
REPO_ROOT = Path(__file__).resolve().parents[4]


class Settings(BaseSettings):
    """環境設定。

    機密值一律用 `SecretStr`——它在 `repr()`、log、以及例外 traceback 裡會顯示成
    `**********`。FastAPI 的 500 頁面與 uvicorn 的錯誤輸出都會印出區域變數，
    service_role key 用純 str 存就等於在等一次意外外洩。取值用 `.get_secret_value()`。
    """

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    env: str = "development"
    api_port: int = 8000

    # config/*.json 的位置。版本化遊戲數值的真實來源。
    config_dir: Path = REPO_ROOT / "config"

    # --- Supabase ---------------------------------------------------------
    # M0 階段全部可留空：還沒有任何依賴 DB 的端點，缺值不該擋住 `make dev`。
    # M4 接上持久層時改成必填。
    supabase_url: str = ""
    supabase_anon_key: str = ""
    supabase_service_role_key: SecretStr = SecretStr("")

    #: SQLAlchemy 連線字串。用 Supabase 的 **Session pooler**（port 5432）而非
    #: direct connection——後者現在是 IPv6-only，家用網路不一定通。
    database_url: SecretStr = SecretStr("")

    # --- CORS -------------------------------------------------------------
    #: `NoDecode` 不可省略。pydantic-settings 對 list 型別預設會先 json.loads()，
    #: 那發生在 field_validator 之前——逗號分隔的值會直接炸成 JSONDecodeError，
    #: 而不是交給下面的 validator 處理。
    frontend_origins: Annotated[list[str], NoDecode] = Field(
        default_factory=lambda: ["http://localhost:3000"]
    )

    # --- LINE（M5 / M10 才會用到，見 docs/09 §3.4）--------------------------
    line_channel_id: str | None = None
    line_channel_secret: SecretStr | None = None
    line_messaging_channel_token: SecretStr | None = None
    line_messaging_channel_secret: SecretStr | None = None

    @field_validator("frontend_origins", mode="before")
    @classmethod
    def _split_origins(cls, v: object) -> object:
        """允許 `.env` 用逗號分隔寫多個來源。

        pydantic-settings 對 `list[str]` 預設期待 JSON 陣列，但在 `.env` 裡寫
        `["a","b"]` 很容易打錯引號。逗號分隔是 env 檔的慣例。
        """
        if isinstance(v, str):
            return [origin.strip() for origin in v.split(",") if origin.strip()]
        return v

    @property
    def has_database(self) -> bool:
        """DATABASE_URL 是否已設定。M0 階段用來決定要不要嘗試連線。"""
        return bool(self.database_url.get_secret_value())

    @property
    def supabase_ref(self) -> str:
        """從 SUPABASE_URL 取出專案 ref，只用於 log（不含任何機密）。"""
        if not self.supabase_url:
            return "unknown"
        host = self.supabase_url.removeprefix("https://").removeprefix("http://")
        return host.split(".")[0]


@lru_cache
def get_settings() -> Settings:
    return Settings()
