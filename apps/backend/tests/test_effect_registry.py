from __future__ import annotations

import json
from pathlib import Path

from assetrush.engine import GameState, PlayerState
from assetrush.engine.effects import EFFECT_HANDLERS, EffectContext, apply_effect

CONFIG_DIR = Path(__file__).resolve().parents[3] / "config"

VARIABLES = {
    "M": 38000,
    "NW": 500000,
    "Q": 114000,
    "avg_NW": 450000,
    "available_loan_capacity": 300000,
    "base_amount": 250000,
    "used_vehicle_extra_step": 1,
}


def test_events_json_effect_types_are_registered() -> None:
    events = json.loads((CONFIG_DIR / "events.json").read_text(encoding="utf-8"))
    effect_types = {
        card["effect"]["type"]
        for deck_name in ("opportunity", "fate")
        for card in events[deck_name]
    }

    assert effect_types <= set(EFFECT_HANDLERS)


def test_gain_effect_adjusts_player_cash_from_formula() -> None:
    state = GameState(players=(PlayerState(id="p1", cash=100),))
    ctx = EffectContext(player_id="p1", variables=VARIABLES, reason="O01")

    next_state, events = apply_effect(state, {"type": "gain", "formula": "Q * 0.5"}, ctx)

    assert next_state.player("p1").cash == 57100
    assert events[0].type == "cash_adjusted"
    assert events[0].reason == "O01"


def test_pay_effect_adjusts_player_cash_downward() -> None:
    state = GameState(players=(PlayerState(id="p1", cash=100000),))
    ctx = EffectContext(player_id="p1", variables=VARIABLES)

    next_state, events = apply_effect(state, {"type": "pay", "amount": 8000}, ctx)

    assert next_state.player("p1").cash == 92000
    assert events[0].delta == -8000


def test_pay_to_treasury_updates_player_and_treasury() -> None:
    state = GameState(players=(PlayerState(id="p1", cash=100000),), treasury=500)
    ctx = EffectContext(player_id="p1", variables=VARIABLES)

    next_state, events = apply_effect(
        state, {"type": "pay_to_treasury", "formula": "NW * 0.04"}, ctx
    )

    assert next_state.player("p1").cash == 80000
    assert next_state.treasury == 20500
    assert [event.type for event in events] == ["cash_adjusted", "treasury_adjusted"]


def test_gain_from_treasury_is_capped_by_available_pool() -> None:
    state = GameState(players=(PlayerState(id="p1", cash=100),), treasury=1000)
    ctx = EffectContext(player_id="p1", variables=VARIABLES)

    next_state, events = apply_effect(state, {"type": "gain_from_treasury", "amount": 30000}, ctx)

    assert next_state.player("p1").cash == 1100
    assert next_state.treasury == 0
    assert [event.type for event in events] == ["treasury_adjusted", "cash_adjusted"]


def test_new_card_using_existing_gain_effect_needs_no_new_handler() -> None:
    state = GameState(players=(PlayerState(id="p1", cash=0),))
    ctx = EffectContext(player_id="p1", variables=VARIABLES, reason="invoice_jackpot")

    next_state, events = apply_effect(state, {"type": "gain", "amount": 10000000}, ctx)

    assert next_state.player("p1").cash == 10000000
    assert events[0].reason == "invoice_jackpot"


def test_complex_effect_becomes_pending_effect_without_mutating_player() -> None:
    state = GameState(players=(PlayerState(id="p1", cash=100),))
    ctx = EffectContext(player_id="p1", variables=VARIABLES, reason="free_upgrade_card")

    next_state, events = apply_effect(state, {"type": "free_upgrade", "count": 1}, ctx)

    assert state.pending_effects == ()
    assert state.player("p1").cash == 100
    assert next_state.pending_effects[0].effect_type == "free_upgrade"
    assert next_state.player("p1").cash == 100
    assert events[0].type == "pending_effect_added"
