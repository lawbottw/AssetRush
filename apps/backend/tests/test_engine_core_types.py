from __future__ import annotations

import pytest

from assetrush.engine import (
    AddPendingEffectAction,
    AddPlayerModifierAction,
    AdjustPlayerCashAction,
    AdjustTreasuryAction,
    GameState,
    InvalidActionError,
    MovePlayerAction,
    PlayerState,
    UnknownPlayerError,
    apply_action,
)


def test_adjust_player_cash_increases_cash_and_emits_event() -> None:
    state = GameState(players=(PlayerState(id="p1", cash=100),))
    action = AdjustPlayerCashAction(
        type="adjust_player_cash",
        player_id="p1",
        delta=50,
        reason="test_gain",
    )

    next_state, events = apply_action(state, action, {})

    assert next_state.player("p1").cash == 150
    assert len(events) == 1
    event = events[0]
    assert event.type == "cash_adjusted"
    assert event.player_id == "p1"
    assert event.delta == 50
    assert event.balance_after == 150
    assert event.reason == "test_gain"


def test_adjust_player_cash_returns_new_state_without_mutating_original() -> None:
    original_player = PlayerState(id="p1", cash=100)
    state = GameState(players=(original_player,))
    action = AdjustPlayerCashAction(type="adjust_player_cash", player_id="p1", delta=50)

    next_state, _events = apply_action(state, action, {})

    assert state.player("p1") is original_player
    assert state.player("p1").cash == 100
    assert next_state is not state
    assert next_state.player("p1") is not original_player
    assert next_state.player("p1").cash == 150


def test_adjust_player_cash_allows_negative_cash_delta() -> None:
    state = GameState(players=(PlayerState(id="p1", cash=100),))
    action = AdjustPlayerCashAction(
        type="adjust_player_cash",
        player_id="p1",
        delta=-125,
        reason="forced_payment",
    )

    next_state, events = apply_action(state, action, {})

    assert next_state.player("p1").cash == -25
    assert events[0].delta == -125
    assert events[0].balance_after == -25


def test_adjust_player_cash_rejects_zero_delta() -> None:
    state = GameState(players=(PlayerState(id="p1", cash=100),))
    action = AdjustPlayerCashAction(type="adjust_player_cash", player_id="p1", delta=0)

    with pytest.raises(InvalidActionError, match="cash delta"):
        apply_action(state, action, {})


def test_adjust_player_cash_rejects_unknown_player() -> None:
    state = GameState(players=(PlayerState(id="p1", cash=100),))
    action = AdjustPlayerCashAction(type="adjust_player_cash", player_id="missing", delta=50)

    with pytest.raises(UnknownPlayerError, match="missing"):
        apply_action(state, action, {})


def test_adjust_treasury_updates_treasury_and_emits_event() -> None:
    state = GameState(players=(PlayerState(id="p1", cash=100),), treasury=500)
    action = AdjustTreasuryAction(type="adjust_treasury", delta=-125, reason="payout")

    next_state, events = apply_action(state, action, {})

    assert state.treasury == 500
    assert next_state.treasury == 375
    assert events[0].type == "treasury_adjusted"
    assert events[0].delta == -125
    assert events[0].balance_after == 375


def test_move_player_wraps_position_and_increments_lap() -> None:
    state = GameState(players=(PlayerState(id="p1", cash=100, position=8, lap=2),))
    action = MovePlayerAction(
        type="move_player",
        player_id="p1",
        steps=5,
        total_tiles=10,
        reason="move",
    )

    next_state, events = apply_action(state, action, {})

    player = next_state.player("p1")
    assert player.position == 3
    assert player.lap == 3
    assert events[0].type == "player_moved"
    assert events[0].position_before == 8
    assert events[0].position_after == 3


def test_add_player_modifier_appends_modifier() -> None:
    state = GameState(players=(PlayerState(id="p1", cash=100),))
    action = AddPlayerModifierAction(
        type="add_player_modifier",
        player_id="p1",
        key="next_purchase_discount",
        value=0.2,
        laps=1,
    )

    next_state, events = apply_action(state, action, {})

    assert len(state.player("p1").modifiers) == 0
    assert next_state.player("p1").modifiers[0].key == "next_purchase_discount"
    assert next_state.player("p1").modifiers[0].value == 0.2
    assert events[0].type == "player_modifier_added"


def test_add_pending_effect_records_unmodeled_effect() -> None:
    state = GameState(players=(PlayerState(id="p1", cash=100),))
    action = AddPendingEffectAction(
        type="add_pending_effect",
        player_id="p1",
        effect_type="free_upgrade",
        reason="card",
    )

    next_state, events = apply_action(state, action, {})

    assert state.pending_effects == ()
    assert next_state.pending_effects[0].effect_type == "free_upgrade"
    assert next_state.pending_effects[0].player_id == "p1"
    assert events[0].type == "pending_effect_added"
