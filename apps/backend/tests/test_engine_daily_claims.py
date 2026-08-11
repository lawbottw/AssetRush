from __future__ import annotations

import pytest

from assetrush.engine import (
    BidWonEvent,
    BoardReference,
    BoardTile,
    CancelPlayerBidsCommand,
    CancelPropertyBidCommand,
    GameState,
    InvalidatePlayerTradeOffersCommand,
    InvalidCommandError,
    PlacePropertyBidCommand,
    PlayerState,
    PropertyState,
    RunDailySettlementCommand,
    StandingOrderState,
    TradeOfferState,
    execute_command,
    player_net_worth,
    replay_events,
    state_digest,
)


def test_same_bid_tiebreak_uses_rotating_daily_order_deterministically() -> None:
    state = _daily_state(day=0, base_turn_order=("p2", "p1"))
    first = _place_bid(state, "p1", 1, 100_000)
    first = _place_bid(first, "p2", 1, 100_000)

    settlement = execute_command(
        first,
        RunDailySettlementCommand(type="run_daily_settlement", execute_standing_orders=False),
        {},
    )
    repeat = execute_command(
        first,
        RunDailySettlementCommand(type="run_daily_settlement", execute_standing_orders=False),
        {},
    )

    assert state_digest(settlement.state) == state_digest(repeat.state)
    assert state_digest(replay_events(first, settlement.events)) == state_digest(settlement.state)
    assert settlement.state.property_at(1) == PropertyState(tile_index=1, owner_id="p2")

    rotated = _daily_state(day=1, base_turn_order=("p2", "p1"))
    rotated = _place_bid(rotated, "p1", 1, 100_000)
    rotated = _place_bid(rotated, "p2", 1, 100_000)
    rotated_settlement = execute_command(
        rotated,
        RunDailySettlementCommand(type="run_daily_settlement", execute_standing_orders=False),
        {},
    )

    assert rotated_settlement.state.property_at(1) == PropertyState(tile_index=1, owner_id="p1")


def test_bid_freezes_cash_counts_toward_net_worth_but_cannot_be_reused() -> None:
    state = _daily_state(player_cash=120_000)
    transition = execute_command(
        state,
        PlacePropertyBidCommand(
            type="place_property_bid",
            player_id="p1",
            tile_index=1,
            bid_amount=100_000,
        ),
        {},
    )

    player = transition.state.player("p1")
    assert player.cash == 20_000
    assert player.frozen_cash == 100_000
    assert player_net_worth(transition.state, "p1") == 120_000

    with pytest.raises(InvalidCommandError, match="insufficient cash"):
        execute_command(
            transition.state,
            PlacePropertyBidCommand(
                type="place_property_bid",
                player_id="p1",
                tile_index=2,
                bid_amount=100_000,
            ),
            {},
        )

    cancelled = execute_command(
        transition.state,
        CancelPropertyBidCommand(
            type="cancel_property_bid",
            player_id="p1",
            tile_index=1,
            reason="changed_mind",
        ),
        {},
    )
    assert cancelled.state.player("p1").cash == 120_000
    assert cancelled.state.player("p1").frozen_cash == 0
    assert cancelled.state.property_bids == ()


def test_bid_raise_settlement_refunds_losers_and_sinks_premium() -> None:
    state = _daily_state(player_cash=200_000, other_cash=200_000)
    state = _place_bid(state, "p1", 1, 100_000)
    state = _place_bid(state, "p2", 1, 100_000)
    state = _place_bid(state, "p1", 1, 130_000)

    settlement = execute_command(
        state,
        RunDailySettlementCommand(type="run_daily_settlement", execute_standing_orders=False),
        {},
    )

    assert settlement.state.property_at(1) == PropertyState(tile_index=1, owner_id="p1")
    assert settlement.state.player("p1").cash == 70_000
    assert settlement.state.player("p1").frozen_cash == 0
    assert settlement.state.player("p2").cash == 200_000
    assert settlement.state.player("p2").frozen_cash == 0
    assert settlement.state.property_bids == ()
    won = [event for event in settlement.events if isinstance(event, BidWonEvent)]
    assert won[0].bid_amount == 130_000
    assert won[0].base_price == 100_000


def test_pre_bankruptcy_cancels_pending_bids_but_post_win_keeps_property() -> None:
    state = _daily_state(player_cash=300_000)
    state = _place_bid(state, "p1", 1, 100_000)
    state = _place_bid(state, "p1", 2, 100_000)

    cancelled = execute_command(
        state,
        CancelPlayerBidsCommand(
            type="cancel_player_bids",
            player_id="p1",
            reason="pre_bankruptcy",
        ),
        {},
    )
    assert cancelled.state.player("p1").cash == 300_000
    assert cancelled.state.property_bids == ()

    won = _place_bid(_daily_state(player_cash=300_000), "p1", 1, 100_000)
    settled = execute_command(
        won,
        RunDailySettlementCommand(type="run_daily_settlement", execute_standing_orders=False),
        {},
    )
    after_win = execute_command(
        settled.state,
        CancelPlayerBidsCommand(
            type="cancel_player_bids",
            player_id="p1",
            reason="post_win_bankruptcy",
        ),
        {},
    )
    assert after_win.events == []
    assert after_win.state.property_at(1) == PropertyState(tile_index=1, owner_id="p1")


def test_standing_orders_execute_missing_daily_rolls_and_complete_day() -> None:
    state = _daily_state(
        player_cash=500_000,
        other_cash=500_000,
        rolls_per_day=2,
        standing_orders=(StandingOrderState(player_id="p1", bid_policy="base_price"),),
    )

    transition = execute_command(
        state,
        RunDailySettlementCommand(type="run_daily_settlement"),
        _turn_config(),
    )

    event_types = [event.type for event in transition.events]
    assert "standing_orders_executed" in event_types
    assert "daily_settlement_completed" in event_types
    assert transition.state.day == 1
    assert transition.state.turn_seq == 4
    assert transition.state.player("p1").rolls_used_today == 0
    assert transition.state.player("p2").rolls_used_today == 0


def test_invalidating_trade_offers_unfreezes_cash_for_liquidation_path() -> None:
    state = _daily_state(
        player_cash=20_000,
        frozen_cash=50_000,
        trade_offers=(
            TradeOfferState(
                offer_id="offer-1",
                from_player_id="p1",
                to_player_id="p2",
                cash_frozen=50_000,
            ),
        ),
    )

    transition = execute_command(
        state,
        InvalidatePlayerTradeOffersCommand(
            type="invalidate_player_trade_offers",
            player_id="p1",
            reason="pre_liquidation",
        ),
        {},
    )

    assert transition.state.player("p1").cash == 70_000
    assert transition.state.player("p1").frozen_cash == 0
    assert transition.state.trade_offers == ()


def _place_bid(
    state: GameState,
    player_id: str,
    tile_index: int,
    bid_amount: int,
) -> GameState:
    return execute_command(
        state,
        PlacePropertyBidCommand(
            type="place_property_bid",
            player_id=player_id,
            tile_index=tile_index,
            bid_amount=bid_amount,
        ),
        {},
    ).state


def _daily_state(
    *,
    day: int = 0,
    player_cash: int = 200_000,
    other_cash: int = 200_000,
    frozen_cash: int = 0,
    base_turn_order: tuple[str, ...] = ("p1", "p2"),
    rolls_per_day: int = 0,
    standing_orders: tuple[StandingOrderState, ...] = (),
    trade_offers: tuple[TradeOfferState, ...] = (),
) -> GameState:
    return GameState(
        id="daily-game",
        mode="daily",
        phase="active",
        server_seed="daily-seed",
        day=day,
        rolls_per_day=rolls_per_day,
        base_turn_order=base_turn_order,
        board=_board(),
        players=(
            PlayerState(id="p1", cash=player_cash, frozen_cash=frozen_cash),
            PlayerState(id="p2", cash=other_cash),
        ),
        standing_orders=standing_orders,
        trade_offers=trade_offers,
    )


def _board() -> BoardReference:
    return BoardReference(
        seed=1,
        total_tiles=8,
        property_tiles=7,
        config_version="test",
        tiles=(
            BoardTile(index=0, kind="start", name="Start"),
            BoardTile(index=1, kind="property", name="A", base_price=100_000, county="C1"),
            BoardTile(index=2, kind="property", name="B", base_price=100_000, county="C1"),
            BoardTile(index=3, kind="property", name="C", base_price=100_000, county="C2"),
            BoardTile(index=4, kind="property", name="D", base_price=100_000, county="C2"),
            BoardTile(index=5, kind="property", name="E", base_price=100_000, county="C3"),
            BoardTile(index=6, kind="property", name="F", base_price=100_000, county="C3"),
            BoardTile(index=7, kind="property", name="G", base_price=100_000, county="C4"),
        ),
    )


def _turn_config() -> dict[str, object]:
    return {
        "properties": {
            "levels": [{"level": 0, "rent_ratio": 0.06}],
            "monopoly": {"rent_multiplier": 2.0},
            "mortgage": {"receive_ratio": 0.5, "redeem_ratio": 0.55},
        }
    }
