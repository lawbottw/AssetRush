from __future__ import annotations

from collections import Counter
from copy import deepcopy
from itertools import pairwise
from pathlib import Path
from typing import Any

import pytest

from assetrush.config_bundle import load_raw_config
from assetrush.engine import (
    BoardSamplingError,
    GameStartSpec,
    resolve_board_size,
    start_game,
    state_digest,
)

CONFIG_DIR = Path(__file__).resolve().parents[3] / "config"


def test_resolve_board_size_supports_daily_player_bands() -> None:
    config = load_raw_config(CONFIG_DIR)

    assert resolve_board_size(config, "daily", 2) == resolve_board_size(config, "daily", 6)
    assert resolve_board_size(config, "daily", 2).total_tiles == 28
    assert resolve_board_size(config, "daily", 7).total_tiles == 36
    assert resolve_board_size(config, "daily", 15).total_tiles == 48
    assert resolve_board_size(config, "daily", 30).property_tiles == 35
    assert resolve_board_size(config, "daily", 30).rolls_per_day == 14


def test_start_game_supports_all_blitz_target_player_pairs() -> None:
    config = load_raw_config(CONFIG_DIR)
    towns = synthetic_towns(config)

    for target_minutes in (20, 30, 45):
        for player_count in range(2, 9):
            spec = GameStartSpec(
                game_id=f"blitz-{target_minutes}-{player_count}",
                mode="blitz",
                player_ids=tuple(f"p{index}" for index in range(player_count)),
                server_seed="server-seed",
                game_seed=target_minutes * 100 + player_count,
                target_minutes=target_minutes,
            )

            state = start_game(spec=spec, config=config, towns=towns)

            assert state.board is not None
            assert len(state.board.tiles) == state.board.total_tiles
            assert state.board.property_tiles == sum(
                1 for tile in state.board.tiles if tile.kind == "property"
            )


def test_start_game_is_deterministic_for_same_seed_and_inputs() -> None:
    config = load_raw_config(CONFIG_DIR)
    towns = synthetic_towns(config)
    spec = GameStartSpec(
        game_id="daily-deterministic",
        mode="daily",
        player_ids=("p1", "p2", "p3", "p4"),
        server_seed="server-seed",
        game_seed=42,
    )

    first = start_game(spec=spec, config=config, towns=towns)
    second = start_game(spec=spec, config=config, towns=towns)

    assert state_digest(first) == state_digest(second)
    assert first.base_turn_order == second.base_turn_order
    assert [tile.town_code for tile in first.board.tiles if tile.kind == "property"] == [
        tile.town_code for tile in second.board.tiles if tile.kind == "property"
    ]


def test_daily_large_board_satisfies_sampling_constraints_and_layout_rules() -> None:
    config = load_raw_config(CONFIG_DIR)
    towns = synthetic_towns(config)
    spec = GameStartSpec(
        game_id="daily-large",
        mode="daily",
        player_ids=tuple(f"p{index}" for index in range(30)),
        server_seed="server-seed",
        game_seed=99,
    )

    state = start_game(spec=spec, config=config, towns=towns)

    assert state.phase == "active"
    assert state.day == 1
    assert state.lap_limit == 21
    assert state.day_limit == 21
    assert state.net_worth_threshold > 0
    assert state.board is not None
    tiles = state.board.tiles
    property_tiles = [tile for tile in tiles if tile.kind == "property"]
    assert len(tiles) == 48
    assert len(property_tiles) == 35
    assert tiles[0].kind == "start"
    assert tiles[1].kind == "property"
    assert all(
        left.kind == "property" or right.kind == "property" for left, right in pairwise(tiles)
    )

    assert len({tile.town_code for tile in property_tiles}) == len(property_tiles)
    region_counts = Counter(tile.region for tile in property_tiles)
    assert len(region_counts) == 6
    assert min(region_counts.values()) >= 2
    tier_counts = Counter(tile.price_tier for tile in property_tiles)
    assert 2 <= tier_counts[5] <= 3
    assert tier_counts[1] + tier_counts[2] >= 12
    county_counts = Counter(tile.county for tile in property_tiles)
    assert max(county_counts.values()) <= 8
    assert sum(1 for count in county_counts.values() if 2 <= count <= 3) >= 7


def test_crowded_daily_net_worth_threshold_uses_configured_multiplier() -> None:
    config = load_raw_config(CONFIG_DIR)
    baseline_config = deepcopy(config)
    baseline_config["endgame"]["net_worth_threshold"]["crowded_game_multiplier"]["multiplier"] = 1.0
    towns = synthetic_towns(config)
    spec = GameStartSpec(
        game_id="daily-crowded-threshold",
        mode="daily",
        player_ids=tuple(f"p{index}" for index in range(30)),
        server_seed="server-seed",
        game_seed=101,
    )

    adjusted = start_game(spec=spec, config=config, towns=towns)
    baseline = start_game(spec=spec, config=baseline_config, towns=towns)

    assert adjusted.net_worth_threshold == round(baseline.net_worth_threshold * 1.35)


def test_starting_assets_are_drawn_from_config_and_board() -> None:
    config = force_background(load_raw_config(CONFIG_DIR), "wealthy")
    towns = synthetic_towns(config)
    spec = GameStartSpec(
        game_id="wealthy-start",
        mode="daily",
        player_ids=("p1", "p2"),
        server_seed="server-seed",
        game_seed=7,
    )

    state = start_game(spec=spec, config=config, towns=towns)

    assert all(player.background_key == "wealthy" for player in state.players)
    assert all(player.cash == 650_000 for player in state.players)
    assert all(player.stock_holdings[0].value == 180_000 for player in state.players)
    assert all(not player.property_tile_indices for player in state.players)


def test_student_loan_starting_debt_is_recorded() -> None:
    config = force_background(load_raw_config(CONFIG_DIR), "indebted")
    towns = synthetic_towns(config)
    spec = GameStartSpec(
        game_id="indebted-start",
        mode="daily",
        player_ids=("p1", "p2"),
        server_seed="server-seed",
        game_seed=8,
    )

    state = start_game(spec=spec, config=config, towns=towns)

    assert all(player.background_key == "indebted" for player in state.players)
    assert all(player.loans[0].product_key == "student_loan" for player in state.players)
    assert all(player.loans[0].principal == 220_000 for player in state.players)
    assert all(player.cash == 120_000 for player in state.players)


def test_unsatisfied_board_constraints_raise_explicit_error() -> None:
    config = load_raw_config(CONFIG_DIR)
    towns = [
        {
            "code": "only",
            "name": "Only Town",
            "county": "台北市",
            "avg_price_per_ping": 100_000,
            "price_tier": 3,
            "population": 100_000,
        }
    ]
    spec = GameStartSpec(
        game_id="bad-board",
        mode="daily",
        player_ids=("p1", "p2"),
        server_seed="server-seed",
        game_seed=1,
    )

    with pytest.raises(BoardSamplingError):
        start_game(spec=spec, config=config, towns=towns)


def synthetic_towns(config: dict[str, Any]) -> list[dict[str, object]]:
    towns: list[dict[str, object]] = []
    board = config["board"]
    regions = board["regions"]
    code = 1
    for region in regions:
        for county in region["counties"]:
            for offset in range(6):
                tier = offset % 5 + 1
                towns.append(
                    {
                        "code": f"T{code:04d}",
                        "name": f"{county}-{offset}",
                        "county": county,
                        "avg_price_per_ping": 50_000 + tier * 100_000 + code,
                        "price_tier": tier,
                        "population": 30_000 + code * 100,
                    }
                )
                code += 1
    return towns


def force_background(config: dict[str, Any], background_key: str) -> dict[str, Any]:
    updated = deepcopy(config)
    backgrounds = updated["identities"]["backgrounds"]
    for background in backgrounds:
        background["weight"] = 100 if background["key"] == background_key else 0
    return updated
