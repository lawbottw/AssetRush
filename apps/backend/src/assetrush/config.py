from functools import lru_cache
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

# repo 根目錄：config.py → assetrush → src → backend → apps → <root>
REPO_ROOT = Path(__file__).resolve().parents[4]


class Settings(BaseSettings):
    """環境設定。Supabase 相關的鍵在 M0 尚未接上（見 issue #5）。"""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    env: str = "development"
    api_port: int = 8000

    # config/*.json 的位置。版本化遊戲數值的真實來源。
    config_dir: Path = REPO_ROOT / "config"


@lru_cache
def get_settings() -> Settings:
    return Settings()
