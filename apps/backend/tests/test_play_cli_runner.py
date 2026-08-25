from __future__ import annotations

import json
import random
from dataclasses import replace
from pathlib import Path

from assetrush.config_bundle import load_raw_config
from assetrush.engine.event_codec import event_from_dict, event_to_dict
from assetrush.sim.runner import (
    RunnerSpec,
    _run_daily_day,
    apply_command_payload,
    available_cli_commands,
    create_initial_state,
    replay_event_stream,
    run_auto_game,
)

CONFIG_DIR = Path(__file__).resolve().parents[3] / "config"


def test_runner_completes_blitz_and_replay_digest_matches() -> None:
    config = load_raw_config(CONFIG_DIR)
    result = run_auto_game(
        RunnerSpec(
            mode="blitz",
            player_count=2,
            seed="runner-test",
            game_id="runner-blitz",
            strategy="conservative",
            max_turns=300,
        ),
        config,
    )

    assert result.completed is True
    assert result.final_state.phase == "finished"
    assert result.final_digest == result.replay_digest
    assert result.turns_executed > 0


def test_runner_completes_daily_and_jsonl_round_trip_replays() -> None:
    config = load_raw_config(CONFIG_DIR)
    result = run_auto_game(
        RunnerSpec(
            mode="daily",
            player_count=2,
            seed="runner-test",
            game_id="runner-daily",
            strategy="aggressive",
            max_turns=600,
        ),
        config,
    )

    encoded = [event_to_dict(event) for event in result.events]
    decoded = tuple(event_from_dict(json.loads(json.dumps(row))) for row in encoded)
    replayed_state, replayed_digest = replay_event_stream(result.initial_state, decoded)

    assert result.completed is True
    assert replayed_state.phase == "finished"
    assert replayed_digest == result.final_digest


def test_runner_lists_and_applies_manual_command_payload() -> None:
    config = load_raw_config(CONFIG_DIR)
    state = create_initial_state(
        RunnerSpec(mode="blitz", player_count=2, seed="runner-test", game_id="manual"),
        config,
    )

    command_types = {command["type"] for command in available_cli_commands()}
    transition = apply_command_payload(
        state,
        {"type": "take_turn", "player_id": state.base_turn_order[0]},
        config,
    )

    assert "take_turn" in command_types
    assert transition.events[0].type == "dice_rolled"
    assert transition.state.turn_seq == 1


def test_stock_education_strategy_executes_quarterly_choices_after_passing_start() -> None:
    config = load_raw_config(CONFIG_DIR)
    result = run_auto_game(
        RunnerSpec(
            mode="blitz",
            player_count=2,
            seed="quarterly-strategy",
            game_id="quarterly-strategy",
            strategy="stock_education",
            max_turns=80,
        ),
        config,
    )
    event_types = [event.type for event in result.events]

    assert "quarterly_affairs_triggered" in event_types
    assert "salary_paid" in event_types
    assert "stock_bought" in event_types
    assert "education_started" in event_types


def test_runner_can_skip_replay_digest_for_large_simulation_batches() -> None:
    config = load_raw_config(CONFIG_DIR)
    result = run_auto_game(
        RunnerSpec(
            mode="blitz",
            player_count=2,
            seed="skip-replay",
            game_id="skip-replay",
            strategy="mixed",
            max_turns=300,
            verify_replay=False,
        ),
        config,
    )

    assert result.completed is True
    assert result.replay_checked is False
    assert result.replay_verified is False
    assert result.final_digest == ""
    assert result.replay_digest == ""


def test_daily_runner_skips_bankrupt_players_instead_of_looping_forever() -> None:
    config = load_raw_config(CONFIG_DIR)
    state = create_initial_state(
        RunnerSpec(
            mode="daily",
            player_count=2,
            seed="bankrupt-skip",
            game_id="bankrupt-skip",
        ),
        config,
    )
    bankrupt_player = replace(state.player("p1"), is_bankrupt=True)
    state = replace(state, players=(bankrupt_player, state.player("p2")))
    events = []

    next_state = _run_daily_day(state, "mixed", 0, config, random.Random(0), events)

    assert next_state.day == state.day + 1
    assert next_state.player("p1").rolls_used_today == 0
    assert any(event.type == "daily_settlement_completed" for event in events)
