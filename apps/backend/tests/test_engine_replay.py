from __future__ import annotations

import pytest

from assetrush.engine import (
    AdjustPlayerCashAction,
    ApplyActionCommand,
    CashAdjustedEvent,
    GameState,
    InvalidEventError,
    PlayerState,
    execute_command,
    replay_events,
    state_digest,
)


def test_same_initial_state_and_commands_produce_same_digest() -> None:
    initial = GameState(players=(PlayerState(id="p1", cash=100),), id="game-19")
    commands = (
        ApplyActionCommand(
            type="apply_action",
            action=AdjustPlayerCashAction(type="adjust_player_cash", player_id="p1", delta=50),
        ),
        ApplyActionCommand(
            type="apply_action",
            action=AdjustPlayerCashAction(type="adjust_player_cash", player_id="p1", delta=-25),
        ),
    )

    first_state = initial
    second_state = initial
    first_events = []
    for command in commands:
        first_transition = execute_command(first_state, command, {})
        second_transition = execute_command(second_state, command, {})
        first_state = first_transition.state
        second_state = second_transition.state
        first_events.extend(first_transition.events)

    assert state_digest(first_state) == state_digest(second_state)
    assert state_digest(replay_events(initial, first_events)) == state_digest(first_state)


def test_replay_rejects_non_contiguous_event_seq() -> None:
    initial = GameState(players=(PlayerState(id="p1", cash=100),))
    event = CashAdjustedEvent(
        type="cash_adjusted",
        player_id="p1",
        delta=50,
        balance_after=150,
        seq=2,
    )

    with pytest.raises(InvalidEventError, match="event seq"):
        replay_events(initial, [event])


def test_replay_rejects_stale_event_seq() -> None:
    initial = GameState(players=(PlayerState(id="p1", cash=100),))
    first = CashAdjustedEvent(
        type="cash_adjusted",
        player_id="p1",
        delta=50,
        balance_after=150,
        seq=1,
    )
    duplicate = CashAdjustedEvent(
        type="cash_adjusted",
        player_id="p1",
        delta=50,
        balance_after=200,
        seq=1,
    )

    with pytest.raises(InvalidEventError, match="event seq"):
        replay_events(initial, [first, duplicate])
