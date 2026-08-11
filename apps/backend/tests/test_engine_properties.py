from __future__ import annotations

import pytest

from assetrush.engine import (
    BoardReference,
    BoardTile,
    GameState,
    InvalidCommandError,
    MortgagePropertyCommand,
    PlayerModifier,
    PlayerState,
    PropertyState,
    PurchasePropertyCommand,
    RedeemPropertyCommand,
    TakeTurnCommand,
    UpgradePropertyCommand,
    execute_command,
    replay_events,
    roll_d6,
    state_digest,
)


def test_blitz_purchase_unowned_property_uses_base_price_and_replays() -> None:
    state = property_state(players=(PlayerState(id="p1", cash=10_000),))

    transition = execute_command(
        state,
        PurchasePropertyCommand(type="purchase_property", player_id="p1", tile_index=1),
        property_config(),
    )

    assert transition.events[0].type == "property_purchased"
    assert transition.state.player("p1").cash == 9_000
    assert transition.state.property_at(1) == PropertyState(tile_index=1, owner_id="p1")
    assert transition.state.player("p1").property_tile_indices == (1,)
    assert state_digest(replay_events(state, transition.events)) == state_digest(transition.state)


def test_daily_purchase_is_left_for_claim_auction_issue() -> None:
    state = property_state(mode="daily", players=(PlayerState(id="p1", cash=10_000),))

    with pytest.raises(InvalidCommandError, match="claim auction"):
        execute_command(
            state,
            PurchasePropertyCommand(type="purchase_property", player_id="p1", tile_index=1),
            property_config(),
        )


def test_upgrade_is_sequential_and_uses_config_cost() -> None:
    state = property_state(
        players=(PlayerState(id="p1", cash=10_000, property_tile_indices=(1,)),),
        properties=(PropertyState(tile_index=1, owner_id="p1"),),
    )

    transition = execute_command(
        state,
        UpgradePropertyCommand(type="upgrade_property", player_id="p1", tile_index=1),
        property_config(),
    )

    assert transition.events[0].type == "property_upgraded"
    assert transition.events[0].level_before == 0
    assert transition.events[0].level_after == 1
    assert transition.events[0].cost == 500
    assert transition.state.player("p1").cash == 9_500
    assert transition.state.property_at(1).level == 1
    assert transition.state.property_at(1).invested == 500


def test_upgrade_rejects_mortgaged_property_and_insufficient_cash() -> None:
    mortgaged = property_state(
        players=(PlayerState(id="p1", cash=10_000, property_tile_indices=(1,)),),
        properties=(PropertyState(tile_index=1, owner_id="p1", mortgaged=True),),
    )

    with pytest.raises(InvalidCommandError, match="mortgaged property cannot upgrade"):
        execute_command(
            mortgaged,
            UpgradePropertyCommand(type="upgrade_property", player_id="p1", tile_index=1),
            property_config(),
        )

    poor = property_state(
        players=(PlayerState(id="p1", cash=100, property_tile_indices=(1,)),),
        properties=(PropertyState(tile_index=1, owner_id="p1"),),
    )

    with pytest.raises(InvalidCommandError, match="insufficient cash"):
        execute_command(
            poor,
            UpgradePropertyCommand(type="upgrade_property", player_id="p1", tile_index=1),
            property_config(),
        )


def test_landing_on_other_property_pays_rent_to_owner() -> None:
    state = state_landing_on(
        target_index=1,
        players=(
            PlayerState(id="payer", cash=10_000),
            PlayerState(id="owner", cash=1_000, property_tile_indices=(1,)),
        ),
        properties=(PropertyState(tile_index=1, owner_id="owner"),),
    )

    transition = execute_command(
        state,
        TakeTurnCommand(type="take_turn", player_id="payer"),
        property_config(),
    )

    rent = next(event for event in transition.events if event.type == "rent_paid")
    assert rent.amount == 60
    assert not rent.monopoly_applied
    assert transition.state.player("payer").cash == 9_940
    assert transition.state.player("owner").cash == 1_060


def test_rent_can_create_cash_shortfall_for_liquidation_pipeline() -> None:
    state = state_landing_on(
        target_index=1,
        players=(
            PlayerState(id="payer", cash=10),
            PlayerState(id="owner", cash=1_000, property_tile_indices=(1,)),
        ),
        properties=(PropertyState(tile_index=1, owner_id="owner"),),
    )

    transition = execute_command(
        state,
        TakeTurnCommand(type="take_turn", player_id="payer"),
        property_config(),
    )

    rent = next(event for event in transition.events if event.type == "rent_paid")
    assert rent.amount == 60
    assert transition.state.player("payer").cash == -50
    assert transition.state.player("owner").cash == 1_060
    assert state_digest(replay_events(state, transition.events)) == state_digest(transition.state)


def test_monopoly_doubles_rent_and_mortgage_breaks_monopoly() -> None:
    state = state_landing_on(
        target_index=1,
        players=(
            PlayerState(id="payer", cash=10_000),
            PlayerState(id="owner", cash=1_000, property_tile_indices=(1, 2)),
        ),
        properties=(
            PropertyState(tile_index=1, owner_id="owner"),
            PropertyState(tile_index=2, owner_id="owner"),
        ),
    )

    transition = execute_command(
        state,
        TakeTurnCommand(type="take_turn", player_id="payer"),
        property_config(),
    )
    rent = next(event for event in transition.events if event.type == "rent_paid")
    assert rent.amount == 120
    assert rent.monopoly_applied

    broken = property_state(
        players=state.players,
        properties=(
            PropertyState(tile_index=1, owner_id="owner"),
            PropertyState(tile_index=2, owner_id="owner", mortgaged=True),
        ),
    )
    broken = state_landing_on(
        target_index=1,
        players=broken.players,
        properties=broken.properties,
    )
    broken_transition = execute_command(
        broken,
        TakeTurnCommand(type="take_turn", player_id="payer"),
        property_config(),
    )
    broken_rent = next(event for event in broken_transition.events if event.type == "rent_paid")
    assert broken_rent.amount == 60
    assert not broken_rent.monopoly_applied


def test_mortgaged_property_blocks_rent() -> None:
    state = state_landing_on(
        target_index=1,
        players=(
            PlayerState(id="payer", cash=10_000),
            PlayerState(id="owner", cash=1_000, property_tile_indices=(1,)),
        ),
        properties=(PropertyState(tile_index=1, owner_id="owner", mortgaged=True),),
    )

    transition = execute_command(
        state,
        TakeTurnCommand(type="take_turn", player_id="payer"),
        property_config(),
    )

    assert "rent_paid" not in [event.type for event in transition.events]
    assert transition.state.player("payer").cash == 10_000
    assert transition.state.player("owner").cash == 1_000


def test_rent_free_modifier_overrides_monopoly_rent() -> None:
    state = state_landing_on(
        target_index=1,
        players=(
            PlayerState(id="payer", cash=10_000, modifiers=(PlayerModifier("rent_free:owner"),)),
            PlayerState(id="owner", cash=1_000, property_tile_indices=(1, 2)),
        ),
        properties=(
            PropertyState(tile_index=1, owner_id="owner"),
            PropertyState(tile_index=2, owner_id="owner"),
        ),
    )

    transition = execute_command(
        state,
        TakeTurnCommand(type="take_turn", player_id="payer"),
        property_config(),
    )

    rent = next(event for event in transition.events if event.type == "rent_paid")
    assert rent.amount == 0
    assert not rent.monopoly_applied
    assert transition.state.player("payer").cash == 10_000


def test_mortgage_and_redeem_use_config_ratios() -> None:
    state = property_state(
        players=(PlayerState(id="p1", cash=10_000, property_tile_indices=(1,)),),
        properties=(PropertyState(tile_index=1, owner_id="p1"),),
    )

    mortgaged = execute_command(
        state,
        MortgagePropertyCommand(type="mortgage_property", player_id="p1", tile_index=1),
        property_config(),
    )

    assert mortgaged.events[0].type == "property_mortgaged"
    assert mortgaged.events[0].amount == 500
    assert mortgaged.state.player("p1").cash == 10_500
    assert mortgaged.state.property_at(1).mortgaged

    redeemed = execute_command(
        mortgaged.state,
        RedeemPropertyCommand(type="redeem_property", player_id="p1", tile_index=1),
        property_config(),
    )

    assert redeemed.events[0].type == "property_redeemed"
    assert redeemed.events[0].cost == 550
    assert redeemed.state.player("p1").cash == 9_950
    assert not redeemed.state.property_at(1).mortgaged


def property_state(
    *,
    mode: str = "blitz",
    players: tuple[PlayerState, ...],
    properties: tuple[PropertyState, ...] = (),
) -> GameState:
    return GameState(
        players=players,
        id="game",
        mode=mode,  # type: ignore[arg-type]
        phase="active",
        server_seed="seed",
        board=property_board(),
        properties=properties,
        base_turn_order=tuple(player.id for player in players),
        rolls_per_day=4 if mode == "daily" else None,
        day=1 if mode == "daily" else 0,
    )


def state_landing_on(
    *,
    target_index: int,
    players: tuple[PlayerState, ...],
    properties: tuple[PropertyState, ...],
) -> GameState:
    result = roll_d6("seed", "game", 1, players[0].id)
    adjusted_players = (
        PlayerState(
            id=players[0].id,
            cash=players[0].cash,
            position=(target_index - result) % property_board().total_tiles,
            modifiers=players[0].modifiers,
        ),
        *players[1:],
    )
    return property_state(players=adjusted_players, properties=properties)


def property_board() -> BoardReference:
    return BoardReference(
        seed=1,
        total_tiles=4,
        property_tiles=3,
        config_version="test",
        tiles=(
            BoardTile(index=0, kind="start"),
            BoardTile(index=1, kind="property", county="A", base_price=1_000),
            BoardTile(index=2, kind="property", county="A", base_price=2_000),
            BoardTile(index=3, kind="property", county="B", base_price=3_000),
        ),
    )


def property_config() -> dict[str, object]:
    return {
        "properties": {
            "levels": [
                {"level": 0, "rent_ratio": 0.06, "upgrade_cost_ratio": None},
                {"level": 1, "rent_ratio": 0.15, "upgrade_cost_ratio": 0.50},
                {"level": 2, "rent_ratio": 0.30, "upgrade_cost_ratio": 0.70},
            ],
            "monopoly": {"rent_multiplier": 2.0},
            "mortgage": {"receive_ratio": 0.50, "redeem_ratio": 0.55},
        },
        "events": {"tax_office": {"brackets": [{"up_to": None, "rate": 0.10}]}},
    }
