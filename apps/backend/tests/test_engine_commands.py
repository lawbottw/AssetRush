from __future__ import annotations

import pytest

from assetrush.engine import (
    AdvancePhaseCommand,
    GameState,
    InvalidCommandError,
    PlayerState,
    RollDiceCommand,
    execute_command,
    roll_d6,
)


def test_advance_phase_follows_fixed_sequence() -> None:
    state = GameState(players=(PlayerState(id="p1", cash=100),), phase="lobby")

    transition = execute_command(
        state,
        AdvancePhaseCommand(type="advance_phase", phase="recruiting", reason="host_opened"),
        {},
    )

    assert transition.state.phase == "recruiting"
    assert transition.state.event_seq == 1
    assert transition.events[0].type == "phase_advanced"
    assert transition.events[0].phase_before == "lobby"
    assert transition.events[0].phase_after == "recruiting"


def test_advance_phase_rejects_skipped_phase() -> None:
    state = GameState(players=(PlayerState(id="p1", cash=100),), phase="lobby")

    with pytest.raises(InvalidCommandError, match="cannot advance phase"):
        execute_command(state, AdvancePhaseCommand(type="advance_phase", phase="active"), {})


@pytest.mark.parametrize("phase", ["lobby", "recruiting", "finished"])
def test_roll_dice_rejects_invalid_phase(phase: str) -> None:
    state = GameState(
        players=(PlayerState(id="p1", cash=100),),
        id="game-19",
        phase=phase,  # type: ignore[arg-type]
        server_seed="m2-seed",
    )

    with pytest.raises(InvalidCommandError, match="active phase"):
        execute_command(state, RollDiceCommand(type="roll_dice", player_id="p1"), {})


def test_roll_dice_in_active_phase_emits_deterministic_event() -> None:
    state = GameState(
        players=(PlayerState(id="p1", cash=100),),
        id="game-19",
        phase="active",
        server_seed="m2-seed",
    )

    transition = execute_command(state, RollDiceCommand(type="roll_dice", player_id="p1"), {})

    event = transition.events[0]
    assert event.type == "dice_rolled"
    assert event.player_id == "p1"
    assert event.turn_seq == 1
    assert event.result == roll_d6("m2-seed", "game-19", 1, "p1")
    assert event.proof_input == "game-19:1:p1"
    assert event.seq == 1
    assert transition.state.turn_seq == 1
    assert transition.state.rng_seq == 1
    assert transition.state.event_seq == 1
