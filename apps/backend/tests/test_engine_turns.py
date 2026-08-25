from __future__ import annotations

from dataclasses import replace

import pytest

from assetrush.engine import (
    BoardReference,
    BoardTile,
    GameState,
    InvalidCommandError,
    PlayerState,
    TakeTurnCommand,
    UnknownEffectError,
    execute_command,
    replay_events,
    roll_d6,
    state_digest,
)


def test_blitz_take_turn_enforces_base_turn_order() -> None:
    state = turn_state(mode="blitz", player_ids=("p1", "p2"), base_turn_order=("p1", "p2"))

    with pytest.raises(InvalidCommandError, match="expected blitz turn"):
        execute_command(state, TakeTurnCommand(type="take_turn", player_id="p2"), game_config())

    transition = execute_command(
        state,
        TakeTurnCommand(type="take_turn", player_id="p1"),
        game_config(),
    )

    assert transition.state.turn_seq == 1
    assert transition.events[0].type == "dice_rolled"
    assert transition.events[1].type == "player_moved"
    assert transition.events[-1].type == "landing_dispatched"


def test_daily_take_turn_consumes_fixed_roll_budget() -> None:
    state = turn_state(mode="daily", player_ids=("p1",), rolls_per_day=1)

    transition = execute_command(
        state,
        TakeTurnCommand(type="take_turn", player_id="p1"),
        game_config(),
    )

    assert transition.state.player("p1").rolls_used_today == 1
    assert [event.type for event in transition.events][1] == "daily_roll_used"

    with pytest.raises(InvalidCommandError, match="daily roll budget exhausted"):
        execute_command(
            transition.state,
            TakeTurnCommand(type="take_turn", player_id="p1"),
            game_config(),
        )


def test_vehicle_owner_can_spend_configured_extra_movement_step() -> None:
    state = turn_state(player_ids=("p1",))
    state = replace(state, players=(replace(state.player("p1"), vehicles=("scooter",)),))

    transition = execute_command(
        state,
        TakeTurnCommand(type="take_turn", player_id="p1", extra_move_steps=1),
        game_config(),
    )

    moved = transition.events[1]
    assert moved.type == "player_moved"
    assert moved.position_after == (roll_d6("seed", "game", 1, "p1") + 1) % 8
    assert moved.reason == "turn_roll_vehicle"
    assert state_digest(replay_events(state, transition.events)) == state_digest(transition.state)


def test_extra_vehicle_movement_requires_an_owned_vehicle() -> None:
    state = turn_state(player_ids=("p1",))

    with pytest.raises(InvalidCommandError, match="vehicle allowance"):
        execute_command(
            state,
            TakeTurnCommand(type="take_turn", player_id="p1", extra_move_steps=1),
            game_config(),
        )


def test_passing_start_emits_health_then_quarterly_before_landing() -> None:
    board = simple_board()
    result = roll_d6("seed", "game", 1, "p1")
    start_position = board.total_tiles - result
    state = turn_state(player_ids=("p1",), board=board, positions={"p1": start_position})

    transition = execute_command(
        state,
        TakeTurnCommand(type="take_turn", player_id="p1"),
        game_config(),
    )

    assert transition.state.player("p1").lap == 1
    assert [event.type for event in transition.events] == [
        "dice_rolled",
        "player_moved",
        "health_check_triggered",
        "quarterly_affairs_triggered",
        "landing_dispatched",
    ]
    assert transition.events[2].lap == 1
    assert transition.events[3].lap == 1


def test_opportunity_landing_draws_card_applies_effect_and_replays() -> None:
    board = simple_board()
    result = roll_d6("seed", "game", 1, "p1")
    state = turn_state(player_ids=("p1",), board=board, positions={"p1": (2 - result) % 8})

    transition = execute_command(
        state,
        TakeTurnCommand(type="take_turn", player_id="p1"),
        game_config(),
    )

    assert "card_drawn" in [event.type for event in transition.events]
    assert transition.state.player("p1").cash == 1_123
    assert state_digest(replay_events(state, transition.events)) == state_digest(transition.state)


def test_unknown_card_effect_raises_instead_of_silently_corrupting_state() -> None:
    board = simple_board()
    result = roll_d6("seed", "game", 1, "p1")
    state = turn_state(player_ids=("p1",), board=board, positions={"p1": (2 - result) % 8})
    config = game_config()
    config["events"]["opportunity"][0]["effect"] = {"type": "not_registered"}

    with pytest.raises(UnknownEffectError, match="not_registered"):
        execute_command(state, TakeTurnCommand(type="take_turn", player_id="p1"), config)


def test_jail_and_hospital_tiles_are_harmless_landings() -> None:
    for target_index in (6, 7):
        board = simple_board()
        result = roll_d6("seed", "game", 1, "p1")
        state = turn_state(
            player_ids=("p1",),
            board=board,
            positions={"p1": (target_index - result) % 8},
        )

        transition = execute_command(
            state,
            TakeTurnCommand(type="take_turn", player_id="p1"),
            game_config(),
        )

        assert transition.events[-1].type == "landing_dispatched"
        assert transition.events[-1].tile_index == target_index
        assert transition.state.pending_effects == ()
        assert transition.state.player("p1").cash == 1_000


def test_tax_landing_pays_treasury_from_net_worth_bracket() -> None:
    board = simple_board()
    result = roll_d6("seed", "game", 1, "p1")
    state = turn_state(player_ids=("p1",), board=board, positions={"p1": (5 - result) % 8})

    transition = execute_command(
        state,
        TakeTurnCommand(type="take_turn", player_id="p1"),
        game_config(),
    )

    assert transition.state.player("p1").cash == 900
    assert transition.state.treasury == 100
    assert [event.type for event in transition.events][-3:] == [
        "landing_dispatched",
        "cash_adjusted",
        "treasury_adjusted",
    ]


def turn_state(
    *,
    mode: str = "blitz",
    player_ids: tuple[str, ...],
    board: BoardReference | None = None,
    positions: dict[str, int] | None = None,
    base_turn_order: tuple[str, ...] = (),
    rolls_per_day: int | None = None,
) -> GameState:
    positions = positions or {}
    return GameState(
        players=tuple(
            PlayerState(
                id=player_id,
                cash=1_000,
                position=positions.get(player_id, 0),
                monthly_salary=10_000,
            )
            for player_id in player_ids
        ),
        id="game",
        mode=mode,  # type: ignore[arg-type]
        phase="active",
        server_seed="seed",
        base_turn_order=base_turn_order,
        board=board or simple_board(),
        day=1 if mode == "daily" else 0,
        rolls_per_day=rolls_per_day,
    )


def simple_board() -> BoardReference:
    return BoardReference(
        seed=1,
        total_tiles=8,
        property_tiles=3,
        config_version="test",
        tiles=(
            BoardTile(index=0, kind="start"),
            BoardTile(index=1, kind="property", town_code="T1", base_price=100_000),
            BoardTile(index=2, kind="opportunity"),
            BoardTile(index=3, kind="fate"),
            BoardTile(index=4, kind="leisure"),
            BoardTile(index=5, kind="tax"),
            BoardTile(index=6, kind="jail"),
            BoardTile(index=7, kind="hospital"),
        ),
    )


def game_config() -> dict[str, object]:
    return {
        "events": {
            "opportunity": [
                {
                    "id": "OTEST",
                    "name": "測試機會",
                    "weight": 100,
                    "effect": {"type": "gain", "amount": 123},
                }
            ],
            "fate": [
                {
                    "id": "FTEST",
                    "name": "測試命運",
                    "weight": 100,
                    "effect": {"type": "pay", "amount": 10},
                }
            ],
            "tax_office": {"brackets": [{"up_to": None, "rate": 0.10}]},
        },
        "vehicles": {
            "vehicles": [
                {
                    "key": "scooter",
                    "price": 80_000,
                    "move_choice_extra": 1,
                    "upkeep_per_turn": 1_000,
                }
            ]
        },
    }
