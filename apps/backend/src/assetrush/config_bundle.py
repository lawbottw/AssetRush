"""讀取並驗證 repo 版控的 config bundle。

這個模組刻意放在 engine 外：讀檔是 I/O，不能讓 `assetrush.engine.*` 依賴它。
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from assetrush.engine.config_models import (
    REQUIRED_CONFIG_FILES,
    ConfigValidationError,
    GameConfig,
    validate_config_bundle,
)


@dataclass(frozen=True, slots=True)
class ConfigBundle:
    raw: dict[str, Any]
    config: GameConfig


def load_raw_config(config_dir: Path) -> dict[str, Any]:
    """讀取 `config/*.json`，並拒絕缺檔與未知檔。"""
    if not config_dir.is_dir():
        raise ConfigValidationError(f"config dir does not exist: {config_dir}")

    raw: dict[str, Any] = {}
    for path in sorted(config_dir.glob("*.json")):
        try:
            raw[path.stem] = json.loads(path.read_text(encoding="utf-8"))
        except json.JSONDecodeError as exc:
            raise ConfigValidationError(f"{path.name}: invalid JSON: {exc}") from exc

    missing = sorted(REQUIRED_CONFIG_FILES - set(raw))
    if missing:
        raise ConfigValidationError(f"missing config files: {', '.join(missing)}")

    unknown = sorted(set(raw) - REQUIRED_CONFIG_FILES)
    if unknown:
        raise ConfigValidationError(f"unknown config files: {', '.join(unknown)}")

    return raw


def load_config_bundle(config_dir: Path) -> ConfigBundle:
    raw = load_raw_config(config_dir)
    return ConfigBundle(raw=raw, config=validate_config_bundle(raw))
