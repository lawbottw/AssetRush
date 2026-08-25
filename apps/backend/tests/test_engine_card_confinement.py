from __future__ import annotations

import pytest

from assetrush.engine import GameState, PlayerState
from assetrush.engine.commands import _draw_and_apply_card


@pytest.mark.parametrize(
    ("card_field", "kind"),
    (("jail", "jail"), ("hospitalize", "hospital")),
)
def test_fate_card_confinement_metadata_creates_replayable_confinement_event(
    card_field: str,
    kind: str,
) -> None:
    state = GameState(
        id="card-confinement",
        phase="active",
        server_seed="card-seed",
        players=(PlayerState(id="p1", cash=500_000),),
    )
    config: dict[str, object] = {
        "events": {
            "fate": [
                {
                    "id": "F99",
                    "name": "confinement card",
                    "weight": 1,
                    "effect": {"type": "none"},
                    card_field: 2,
                }
            ]
        },
        "confinement": {
            "mode_caps": {"blitz_max_turns": 1, "daily_max_turns": 3},
        },
    }

    next_state, events = _draw_and_apply_card(state, "p1", "fate", config)

    assert [event.type for event in events] == ["card_drawn", "player_confined"]
    assert next_state.player("p1").confinement is not None
    assert next_state.player("p1").confinement.kind == kind
    assert next_state.player("p1").confinement.remaining_turns == 1
    assert next_state.player("p1").confinement.reason == "F99"
