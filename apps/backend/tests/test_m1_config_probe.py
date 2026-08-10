from __future__ import annotations

from pathlib import Path

from assetrush.config_bundle import load_config_bundle
from assetrush.engine import GameState, PlayerState
from assetrush.engine.effects import EffectContext, apply_effect

CONFIG_DIR = Path(__file__).resolve().parents[3] / "config"


def test_m1_config_formula_effect_reaches_reducer() -> None:
    bundle = load_config_bundle(CONFIG_DIR)
    card = next(card for card in bundle.config.events.opportunity if card.id == "O01")
    state = GameState(players=(PlayerState(id="p1", cash=100),))
    ctx = EffectContext(
        player_id="p1",
        variables={"Q": 114000},
        reason=card.id,
    )

    next_state, events = apply_effect(state, card.effect.model_dump(exclude_none=True), ctx)

    assert next_state.player("p1").cash == 57100
    assert events[0].type == "cash_adjusted"
    assert events[0].reason == "O01"
