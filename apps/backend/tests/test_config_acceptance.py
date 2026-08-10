from __future__ import annotations

import json
import shutil
from pathlib import Path

from assetrush.config_bundle import load_raw_config
from assetrush.engine import GameState, PlayerState
from assetrush.engine.config_models import GameConfig, validate_config_bundle
from assetrush.engine.effects import EffectContext, apply_effect

CONFIG_DIR = Path(__file__).resolve().parents[3] / "config"


def test_acceptance_rent_ratios_can_increase_by_20_percent(tmp_path: Path) -> None:
    config_dir = _copy_config(tmp_path)
    properties_path = config_dir / "properties.json"
    properties = _read_json(properties_path)
    before = [level["rent_ratio"] for level in properties["levels"]]
    for level in properties["levels"]:
        level["rent_ratio"] = round(level["rent_ratio"] * 1.2, 6)
    _write_json(properties_path, properties)

    config = _load(config_dir)

    after = [level.rent_ratio for level in config.properties.levels]
    assert after == [round(value * 1.2, 6) for value in before]


def test_acceptance_new_invoice_jackpot_card_uses_existing_gain_handler(
    tmp_path: Path,
) -> None:
    config_dir = _copy_config(tmp_path)
    events_path = config_dir / "events.json"
    events = _read_json(events_path)
    events["opportunity"][0]["weight"] -= 1
    events["opportunity"].append(
        {
            "id": "O99",
            "name": "發票中千萬",
            "weight": 1,
            "effect": {"type": "gain", "amount": 10000000},
        }
    )
    _write_json(events_path, events)

    config = _load(config_dir)
    added = next(card for card in config.events.opportunity if card.id == "O99")
    state = GameState(players=(PlayerState(id="p1", cash=0),))
    ctx = EffectContext(player_id="p1", variables={}, reason=added.id)

    next_state, events_out = apply_effect(state, added.effect.model_dump(exclude_none=True), ctx)

    assert next_state.player("p1").cash == 10000000
    assert events_out[0].reason == "O99"


def test_acceptance_loan_product_can_be_removed_without_hardcoded_count(tmp_path: Path) -> None:
    config_dir = _copy_config(tmp_path)
    loans_path = config_dir / "loans.json"
    loans = _read_json(loans_path)
    loans["products"] = [
        product for product in loans["products"] if product["key"] != "finance_private_loan"
    ]
    _write_json(loans_path, loans)

    config = _load(config_dir)

    assert "finance_private_loan" not in {product.key for product in config.loans.products}


def test_acceptance_property_levels_can_change_from_five_to_four(tmp_path: Path) -> None:
    config_dir = _copy_config(tmp_path)
    properties_path = config_dir / "properties.json"
    properties = _read_json(properties_path)
    properties["levels"] = properties["levels"][:4]
    _write_json(properties_path, properties)

    config = _load(config_dir)

    assert [level.level for level in config.properties.levels] == [0, 1, 2, 3]


def test_acceptance_county_can_be_added_to_region_grouping(tmp_path: Path) -> None:
    config_dir = _copy_config(tmp_path)
    board_path = config_dir / "board.json"
    board = _read_json(board_path)
    board["regions"][0]["counties"].append("測試縣")
    _write_json(board_path, board)

    config = _load(config_dir)

    assert "測試縣" in config.board.regions[0].counties


def _copy_config(tmp_path: Path) -> Path:
    target = tmp_path / "config"
    shutil.copytree(CONFIG_DIR, target)
    return target


def _load(config_dir: Path) -> GameConfig:
    return validate_config_bundle(load_raw_config(config_dir))


def _read_json(path: Path) -> dict[str, object]:
    return json.loads(path.read_text(encoding="utf-8"))


def _write_json(path: Path, value: dict[str, object]) -> None:
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding="utf-8")
