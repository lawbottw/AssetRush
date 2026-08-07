"""engine 零 I/O 邊界檢查（鐵律 2）。

`assetrush.engine` 不得（直接或間接）依賴任何 DB / HTTP / web framework。
理由：規則引擎必須能離線跑蒙地卡羅模擬，M3 的全部價值建立在這件事上。一旦
有人在 engine 裡塞了一個 DB 查詢，模擬就跑不動了——而且通常等到要跑模擬時
才會發現，那時已經要重構整個引擎。所以這條檢查要在寫第一行遊戲程式碼之前
就上 CI。

用 AST 靜態掃描而非 import 攔截：不必真的載入模組，因此相依未安裝也能跑，
而且連 `if TYPE_CHECKING:` 底下的偷渡也擋得住。

跨模組追蹤是必要的——`engine/rules.py` 只 import `assetrush.services` 看似乾淨，
但 services 拖進來的是整條 DB 依賴。掃描會沿著 assetrush 內部 import 遞迴。

這支腳本刻意放在 engine 外面（它自己要讀檔案，是 I/O）。

用法：
    uv run python scripts/check_engine_purity.py      # 違規時 exit 1
"""

from __future__ import annotations

import argparse
import ast
import sys
from collections.abc import Iterator
from dataclasses import dataclass
from pathlib import Path

#: 這些頂層套件（及其子模組）在 engine 內一律禁止。
BANNED_ROOTS: frozenset[str] = frozenset(
    {
        # DB
        "supabase",
        "sqlalchemy",
        "asyncpg",
        "psycopg",
        "psycopg2",
        "alembic",
        # HTTP
        "httpx",
        "requests",
        "aiohttp",
        "urllib",
        "urllib3",
        "http",
        "socket",
        # web framework / 排程
        "fastapi",
        "starlette",
        "uvicorn",
        "apscheduler",
        # 會讓純函式不再是純函式的東西
        "os",
        "pathlib",
        "subprocess",
        "threading",
        "multiprocessing",
    }
)

#: assetrush 內部唯一允許被 engine 依賴的子套件。依賴方向是
#: services / routers / jobs / sim → engine，反向即為違規。
ALLOWED_INTERNAL_PREFIX = "assetrush.engine"

ENGINE_PACKAGE = "assetrush.engine"


@dataclass(frozen=True)
class Violation:
    module: str
    path: Path
    lineno: int
    imported: str
    reason: str

    def __str__(self) -> str:
        return f"{self.path}:{self.lineno}: {self.module} → {self.imported}｜{self.reason}"


def module_file(module: str, src_root: Path) -> Path | None:
    base = src_root.joinpath(*module.split("."))
    pkg = base / "__init__.py"
    if pkg.is_file():
        return pkg
    mod = base.with_suffix(".py")
    return mod if mod.is_file() else None


def resolve_relative(package: str, target: str, level: int) -> str:
    """把相對 import 還原成絕對模組名。

    `package` 是發起 import 的模組所屬的套件（`__init__.py` 即為自身）。
    level == 0 表示本來就是絕對 import。
    """
    if level == 0:
        return target
    parts = package.split(".")
    base = parts[: len(parts) - (level - 1)] if level > 1 else parts
    return ".".join([*base, target]) if target else ".".join(base)


def classify(imported: str) -> str | None:
    """回傳違規理由；合法則回傳 None。"""
    root = imported.split(".")[0]
    if root == "assetrush":
        if imported == ALLOWED_INTERNAL_PREFIX or imported.startswith(
            f"{ALLOWED_INTERNAL_PREFIX}."
        ):
            return None
        return "engine 不得反向依賴其他 assetrush 子套件（方向是 X → engine）"
    if root in BANNED_ROOTS:
        return f"`{root}` 是 I/O 相依，engine 必須能離線執行"
    return None


def imports_of(package: str, tree: ast.AST) -> Iterator[tuple[str, int]]:
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                yield alias.name, node.lineno
        elif isinstance(node, ast.ImportFrom):
            target = resolve_relative(package, node.module or "", node.level)
            if node.level > 0 and not node.module:
                # `from . import x` — 逐一還原成完整模組名
                for alias in node.names:
                    yield f"{target}.{alias.name}", node.lineno
            elif target:
                yield target, node.lineno


def scan(src_root: Path) -> list[Violation]:
    """從 engine 套件出發遞迴掃描，回傳所有違規（依檔案、行號排序）。"""
    violations: list[Violation] = []
    seen: set[str] = set()
    queue: list[str] = [ENGINE_PACKAGE]

    while queue:
        module = queue.pop()
        if module in seen:
            continue
        seen.add(module)

        path = module_file(module, src_root)
        if path is None:
            continue

        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        # `__init__.py` 的相對 import 以自身為基準，一般模組以所屬 package 為基準
        package = module if path.name == "__init__.py" else module.rsplit(".", 1)[0]

        for imported, lineno in imports_of(package, tree):
            reason = classify(imported)
            if reason is not None:
                violations.append(Violation(module, path, lineno, imported, reason))
            elif imported.startswith("assetrush."):
                queue.append(imported)

    return sorted(violations, key=lambda v: (str(v.path), v.lineno))


def engine_modules(src_root: Path) -> list[Path]:
    return sorted((src_root.joinpath(*ENGINE_PACKAGE.split("."))).rglob("*.py"))


def default_src_root() -> Path:
    # scripts/check_engine_purity.py → apps/backend → apps/backend/src
    return Path(__file__).resolve().parents[1] / "src"


def _force_utf8_output() -> None:
    """Windows 主控台預設 cp950，訊息裡的中文會讓 print 直接拋 UnicodeEncodeError。

    那會把「檢查通過」變成 exit 1 的假失敗，比沒有檢查更糟。
    """
    for stream in (sys.stdout, sys.stderr):
        reconfigure = getattr(stream, "reconfigure", None)
        if reconfigure is not None:
            reconfigure(encoding="utf-8", errors="replace")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--src", type=Path, default=default_src_root(), help="src/ 目錄")
    args = parser.parse_args(argv)

    _force_utf8_output()
    src_root: Path = args.src
    violations = scan(src_root)

    if violations:
        print(f"FAIL: engine 零 I/O 邊界檢查失敗（{len(violations)} 項違規）", file=sys.stderr)
        for v in violations:
            print(f"    {v}", file=sys.stderr)
        print("\n見 CLAUDE.md 鐵律 2：engine/ 零 I/O。", file=sys.stderr)
        return 1

    print(f"OK: engine 零 I/O 邊界檢查通過（掃描 {len(engine_modules(src_root))} 個模組）")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
