"""鐵律 2 的守門測試。

真實檢查在 scripts/check_engine_purity.py；這裡除了跑真實 engine 之外，還用
合成的套件樹驗證「檢查本身抓得到違規」——一個永遠回傳 0 的檢查等於沒有檢查。
"""

from __future__ import annotations

from pathlib import Path

import pytest
from check_engine_purity import default_src_root, main, scan


def write_pkg(root: Path, module: str, source: str) -> None:
    path = root.joinpath(*module.split("."))
    path.mkdir(parents=True, exist_ok=True)
    (path / "__init__.py").write_text(source, encoding="utf-8")


def make_tree(tmp_path: Path, engine_source: str, **others: str) -> Path:
    src = tmp_path / "src"
    write_pkg(src, "assetrush", "")
    write_pkg(src, "assetrush.engine", engine_source)
    for module, source in others.items():
        write_pkg(src, f"assetrush.{module}", source)
    return src


def test_real_engine_is_pure() -> None:
    assert scan(default_src_root()) == []


def test_main_exits_zero_on_real_tree() -> None:
    assert main([]) == 0


@pytest.mark.parametrize(
    "source",
    [
        "import httpx",
        "import sqlalchemy.orm",
        "from httpx import AsyncClient",
        "from fastapi import Depends",
        "import supabase",
        "import asyncpg",
        "import requests",
        # TYPE_CHECKING 底下的偷渡也要擋
        "from typing import TYPE_CHECKING\nif TYPE_CHECKING:\n    import httpx\n",
        # 藏在函式內的延遲 import 一樣算
        "def load():\n    import httpx\n    return httpx\n",
    ],
    ids=[
        "httpx",
        "sqlalchemy-submodule",
        "httpx-from",
        "fastapi-from",
        "supabase",
        "asyncpg",
        "requests",
        "type-checking-block",
        "deferred-in-function",
    ],
)
def test_banned_import_is_caught(tmp_path: Path, source: str) -> None:
    src = make_tree(tmp_path, source)
    violations = scan(src)
    assert violations, f"應該要抓到違規，但沒有：{source!r}"


def test_transitive_violation_is_caught(tmp_path: Path) -> None:
    """engine 只 import services 看似乾淨，但 services 拖進來整條 DB 依賴。"""
    src = make_tree(
        tmp_path,
        "from assetrush.helpers import touch",
        helpers="import sqlalchemy\n\n\ndef touch() -> None: ...\n",
    )
    violations = scan(src)
    reasons = {v.imported for v in violations}
    # 反向依賴本身就違規（依賴方向是 X → engine）
    assert "assetrush.helpers" in reasons


def test_clean_engine_passes(tmp_path: Path) -> None:
    src = make_tree(
        tmp_path,
        "from dataclasses import dataclass\nfrom decimal import Decimal\nimport math\n",
    )
    assert scan(src) == []


def test_internal_engine_import_is_allowed(tmp_path: Path) -> None:
    src = tmp_path / "src"
    write_pkg(src, "assetrush", "")
    write_pkg(src, "assetrush.engine", "from assetrush.engine.rules import apply\n")
    (src / "assetrush" / "engine" / "rules.py").write_text(
        "def apply() -> None: ...\n", encoding="utf-8"
    )
    assert scan(src) == []


def test_relative_import_inside_engine_is_resolved(tmp_path: Path) -> None:
    """`from .rules import apply` 不該被誤判成外部套件。"""
    src = tmp_path / "src"
    write_pkg(src, "assetrush", "")
    write_pkg(src, "assetrush.engine", "from .rules import apply\n")
    (src / "assetrush" / "engine" / "rules.py").write_text(
        "import httpx\n\n\ndef apply() -> None: ...\n", encoding="utf-8"
    )
    violations = scan(src)
    # 相對 import 必須被解析並遞迴進去，才抓得到 rules.py 裡的 httpx
    assert [v.imported for v in violations] == ["httpx"]
