"""同步 docs/02 的 config 摘要區塊。"""

from __future__ import annotations

import argparse
import sys
from collections.abc import Iterable, Mapping, Sequence
from pathlib import Path
from typing import Any

from assetrush.config_bundle import ConfigBundle, load_config_bundle
from assetrush.engine.config_models import ConfigValidationError

BEGIN_MARKER = "<!-- BEGIN GENERATED CONFIG SUMMARY -->"
END_MARKER = "<!-- END GENERATED CONFIG SUMMARY -->"


def generate_summary(bundle: ConfigBundle) -> str:
    raw = bundle.raw
    events = _mapping(raw["events"])
    properties = _mapping(raw["properties"])
    loans = _mapping(raw["loans"])
    occupations = _mapping(raw["occupations"])
    insurance = _mapping(raw["insurance"])
    board = _mapping(raw["board"])

    lines = [
        BEGIN_MARKER,
        "",
        "### 12.1 Config 自動同步摘要",
        "",
        "> 本區塊由 `make sync-balance-doc` 產生；不要手動編輯。",
        "",
        "| 項目 | 摘要 |",
        "|---|---|",
        f"| Config version | `{bundle.config.version}` |",
        (
            "| 事件卡 | "
            f"機會 {len(_sequence(events['opportunity']))} 張 / 權重 "
            f"{_weight_total(events['opportunity'])}；命運 "
            f"{len(_sequence(events['fate']))} 張 / 權重 {_weight_total(events['fate'])} |"
        ),
        f"| Effect types | `{_join_effect_types(events)}` |",
        f"| 地產等級 | {_property_levels(properties)} |",
        f"| 貸款產品 | {_loan_products(loans)} |",
        f"| 進修結果 | {_education_outcome(occupations)} |",
        f"| 進修課程 | {_education_courses(occupations)} |",
        f"| 保險 | {_insurance_policies(insurance)} |",
        f"| 棋盤 layout | {_board_layouts(board)} |",
        f"| 六大區域 | {_board_regions(board)} |",
        "",
        END_MARKER,
    ]
    return "\n".join(lines)


def replace_generated_block(document: str, generated: str) -> str:
    begin = document.find(BEGIN_MARKER)
    end = document.find(END_MARKER)
    if begin == -1 or end == -1 or end < begin:
        stripped = document.rstrip()
        return f"{stripped}\n\n{generated}\n"

    end += len(END_MARKER)
    return f"{document[:begin]}{generated}{document[end:]}"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--config-dir",
        type=Path,
        default=Path(__file__).resolve().parents[3] / "config",
        help="config/*.json 目錄",
    )
    parser.add_argument(
        "--doc",
        type=Path,
        default=Path(__file__).resolve().parents[3] / "docs" / "02-game-balance.md",
        help="要同步的 docs/02 markdown",
    )
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--write", action="store_true", help="寫回 docs/02")
    mode.add_argument("--check", action="store_true", help="只檢查 docs/02 是否已同步")
    args = parser.parse_args(argv)

    try:
        bundle = load_config_bundle(args.config_dir)
    except ConfigValidationError as exc:
        print(f"FAIL: config validation failed: {exc}", file=sys.stderr)
        return 1

    original = args.doc.read_text(encoding="utf-8")
    updated = replace_generated_block(original, generate_summary(bundle))

    if args.check:
        if updated != original:
            print(
                "FAIL: docs/02-game-balance.md config summary is stale; "
                "run `make sync-balance-doc`.",
                file=sys.stderr,
            )
            return 1
        print("OK: docs/02 config summary is up to date")
        return 0

    args.doc.write_text(updated, encoding="utf-8")
    print(f"OK: synced {args.doc}")
    return 0


def _mapping(value: object) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise TypeError("expected mapping")
    return value


def _sequence(value: object) -> Sequence[object]:
    if not isinstance(value, Sequence) or isinstance(value, str):
        raise TypeError("expected sequence")
    return value


def _weight_total(cards: object) -> int:
    total = 0
    for card in _sequence(cards):
        item = _mapping(card)
        weight = item.get("weight")
        if isinstance(weight, int):
            total += weight
    return total


def _join_effect_types(events: Mapping[str, Any]) -> str:
    effect_types: set[str] = set()
    for deck_name in ("opportunity", "fate"):
        for card in _sequence(events[deck_name]):
            effect = _mapping(_mapping(card)["effect"])
            effect_type = effect.get("type")
            if isinstance(effect_type, str):
                effect_types.add(effect_type)
    return "`, `".join(sorted(effect_types))


def _property_levels(properties: Mapping[str, Any]) -> str:
    parts: list[str] = []
    for level in _sequence(properties["levels"]):
        item = _mapping(level)
        parts.append(f"L{item['level']} {item['name']} 租金 {float(item['rent_ratio']) * 100:.1f}%")
    return "；".join(parts)


def _loan_products(loans: Mapping[str, Any]) -> str:
    parts: list[str] = []
    for product in _sequence(loans["products"]):
        item = _mapping(product)
        status = "啟用" if item.get("enabled", True) is True else "停用"
        parts.append(f"{item['name']}({status})")
    return "；".join(parts)


def _education_outcome(occupations: Mapping[str, Any]) -> str:
    outcome = _mapping(_mapping(occupations["education"])["outcome"])
    success = float(outcome["success_chance"]) * 100
    failure = float(outcome["failure_chance"]) * 100
    refund = "退費" if outcome.get("refund_on_failure") is True else "不退費"
    return f"完成時擲結果：有效進修 {success:.0f}% / 打水飄 {failure:.0f}%；失敗{refund}"


def _education_courses(occupations: Mapping[str, Any]) -> str:
    courses = _sequence(_mapping(occupations["education"])["courses"])
    return "；".join(
        f"{_mapping(course)['name']} ${int(_mapping(course)['tuition']):,}" for course in courses
    )


def _insurance_policies(insurance: Mapping[str, Any]) -> str:
    return "；".join(str(_mapping(policy)["name"]) for policy in _sequence(insurance["policies"]))


def _board_layouts(board: Mapping[str, Any]) -> str:
    layouts = _mapping(_mapping(board["function_tiles"])["layouts"])
    parts: list[str] = []
    for size, layout in sorted(layouts.items(), key=lambda item: int(item[0])):
        function_tiles = sum(int(_mapping(tile)["count"]) for tile in _sequence(layout))
        parts.append(f"{size}格:{function_tiles}功能格")
    return "；".join(parts)


def _board_regions(board: Mapping[str, Any]) -> str:
    regions: Iterable[object] = _sequence(board["regions"])
    return "；".join(
        f"{_mapping(region)['name']}({len(_sequence(_mapping(region)['counties']))})"
        for region in regions
    )


if __name__ == "__main__":
    raise SystemExit(main())
