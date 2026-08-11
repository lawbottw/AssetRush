from __future__ import annotations

import pytest

from assetrush.engine import (
    BoardReference,
    BoardTile,
    ConfinementState,
    ConfinePlayerCommand,
    InvalidCommandError,
    LoanDefaultCommand,
    PlayerLoan,
    PlayerState,
    PropertyState,
    ResolveCashShortfallCommand,
    ResolveCashShortfallsCommand,
    RunQuarterlyAffairsCommand,
    StockHolding,
    TakeTurnCommand,
    UpgradePropertyCommand,
    VoluntaryQuitCommand,
    execute_command,
    replay_events,
    state_digest,
)
from assetrush.engine.state import GameState


def test_cash_shortfall_liquidates_in_configured_order_until_cash_recovers() -> None:
    state = _state(
        players=(
            PlayerState(
                id="p1",
                cash=-300_000,
                stock_holdings=(
                    StockHolding(code="B", value=60_000),
                    StockHolding(code="A", value=50_000),
                ),
                property_tile_indices=(1, 2),
                vehicles=("scooter",),
            ),
            PlayerState(id="p2", cash=500_000),
        ),
        properties=(
            PropertyState(tile_index=1, owner_id="p1"),
            PropertyState(tile_index=2, owner_id="p1"),
        ),
    )

    transition = execute_command(
        state,
        ResolveCashShortfallCommand(type="resolve_cash_shortfall", player_id="p1"),
        _config(),
    )

    assert [event.type for event in transition.events] == [
        "stock_liquidated",
        "stock_liquidated",
        "property_mortgaged",
        "property_mortgaged",
        "vehicle_liquidated",
    ]
    player = transition.state.player("p1")
    assert player.cash == 16_000
    assert player.stock_holdings == ()
    assert player.vehicles == ()
    assert transition.state.property_at(1).mortgaged is True  # type: ignore[union-attr]
    assert transition.state.property_at(2).mortgaged is True  # type: ignore[union-attr]
    assert state_digest(replay_events(state, transition.events)) == state_digest(transition.state)


def test_bankruptcy_releases_assets_and_voluntary_quit_does_not_count() -> None:
    state = _state(
        players=(
            PlayerState(
                id="p1",
                cash=-1_000_000,
                property_tile_indices=(1,),
                vehicles=("scooter",),
            ),
            PlayerState(id="p2", cash=500_000),
        ),
        properties=(PropertyState(tile_index=1, owner_id="p1"),),
    )

    transition = execute_command(
        state,
        ResolveCashShortfallCommand(type="resolve_cash_shortfall", player_id="p1"),
        _config(),
    )

    assert transition.state.player("p1").is_bankrupt is True
    assert transition.state.player("p1").loans == ()
    assert transition.state.player("p1").vehicles == ()
    assert transition.state.property_at(1) is None
    assert transition.state.bankruptcy_records[0].counts_for_end_condition is True
    assert transition.state.phase == "finished"

    quit_state = _state(
        players=(PlayerState(id="p1", cash=100_000), PlayerState(id="p2", cash=100_000)),
    )
    quit_transition = execute_command(
        quit_state,
        VoluntaryQuitCommand(type="voluntary_quit", player_id="p1"),
        _config(),
    )
    assert quit_transition.state.player("p1").has_quit is True
    assert quit_transition.state.bankruptcy_records[0].counts_for_end_condition is False
    assert quit_transition.state.phase == "active"


def test_batch_bankruptcy_checks_threshold_after_all_players_are_resolved() -> None:
    state = _state(
        players=(
            PlayerState(id="p1", cash=-1_000_000),
            PlayerState(id="p2", cash=-1_000_000),
            PlayerState(id="p3", cash=500_000),
        )
    )

    transition = execute_command(
        state,
        ResolveCashShortfallsCommand(
            type="resolve_cash_shortfalls",
            player_ids=("p1", "p2"),
        ),
        _config(bankruptcy_ratio=0.5),
    )

    event_types = [event.type for event in transition.events]
    assert event_types[-1] == "bankruptcy_threshold_reached"
    assert event_types.count("player_bankrupted") == 2
    assert len(transition.state.bankruptcy_records) == 2
    assert transition.state.phase == "finished"


def test_blacklisted_player_can_only_use_finance_rescue_lender() -> None:
    state = _state(
        players=(
            PlayerState(
                id="p1",
                cash=-50_000,
                loans=(PlayerLoan(product_key="credit", principal=100_000, rate_per_lap=0.02),),
            ),
            PlayerState(id="p2", cash=500_000, occupation_key="service"),
            PlayerState(id="p3", cash=500_000, occupation_key="finance"),
        )
    )
    working = state
    for _ in range(3):
        working = execute_command(
            working,
            LoanDefaultCommand(type="loan_default", player_id="p1", loan_index=0),
            _config(),
        ).state

    assert working.player("p1").is_blacklisted is True
    with pytest.raises(InvalidCommandError, match="finance occupation"):
        execute_command(
            working,
            ResolveCashShortfallCommand(
                type="resolve_cash_shortfall",
                player_id="p1",
                finance_lender_id="p2",
                finance_loan_amount=50_000,
            ),
            _config(),
        )

    rescued = execute_command(
        working,
        ResolveCashShortfallCommand(
            type="resolve_cash_shortfall",
            player_id="p1",
            finance_lender_id="p3",
            finance_loan_amount=50_000,
        ),
        _config(),
    )
    assert rescued.state.player("p1").is_bankrupt is False
    assert rescued.state.player("p1").cash == 0
    assert rescued.state.player("p3").cash == 450_000


def test_confinement_blocks_forbidden_actions_and_releases_on_skipped_turn() -> None:
    jailed = execute_command(
        _state(
            mode="daily",
            rolls_per_day=1,
            players=(PlayerState(id="p1", cash=500_000), PlayerState(id="p2", cash=500_000)),
        ),
        ConfinePlayerCommand(type="confine_player", player_id="p1", kind="jail", turns=2),
        _config(),
    ).state

    with pytest.raises(InvalidCommandError, match="quarterly"):
        execute_command(
            jailed,
            RunQuarterlyAffairsCommand(type="run_quarterly_affairs", player_id="p1"),
            _config(),
        )

    skipped = execute_command(
        jailed,
        TakeTurnCommand(type="take_turn", player_id="p1"),
        _config(),
    )
    assert skipped.state.player("p1").confinement == ConfinementState(
        kind="jail",
        remaining_turns=1,
        reason=None,
    )
    assert "turn_skipped" in [event.type for event in skipped.events]

    hospitalized = execute_command(
        _state(
            players=(PlayerState(id="p1", cash=500_000, property_tile_indices=(1,)),),
            properties=(PropertyState(tile_index=1, owner_id="p1"),),
        ),
        ConfinePlayerCommand(type="confine_player", player_id="p1", kind="hospital", turns=2),
        _config(),
    ).state
    with pytest.raises(InvalidCommandError, match="hospitalized"):
        execute_command(
            hospitalized,
            UpgradePropertyCommand(type="upgrade_property", player_id="p1", tile_index=1),
            _config(),
        )


def test_family_bailout_is_allowed_while_confined() -> None:
    state = _state(
        players=(
            PlayerState(
                id="p1",
                cash=-50_000,
                confinement=ConfinementState(kind="jail", remaining_turns=2),
            ),
        )
    )

    transition = execute_command(
        state,
        ResolveCashShortfallCommand(
            type="resolve_cash_shortfall",
            player_id="p1",
            family_bailout_amount=50_000,
        ),
        _config(),
    )

    assert transition.state.player("p1").cash == 0
    assert transition.state.player("p1").is_bankrupt is False
    assert transition.state.player("p1").confinement == ConfinementState(
        kind="jail",
        remaining_turns=2,
    )


def _state(
    *,
    players: tuple[PlayerState, ...],
    properties: tuple[PropertyState, ...] = (),
    mode: str = "blitz",
    rolls_per_day: int | None = None,
) -> GameState:
    return GameState(
        id="liquidation-game",
        mode=mode,  # type: ignore[arg-type]
        phase="active",
        server_seed="liquidation-seed",
        board=_board(),
        players=players,
        properties=properties,
        base_turn_order=tuple(player.id for player in players),
        rolls_per_day=rolls_per_day,
    )


def _board() -> BoardReference:
    return BoardReference(
        seed=1,
        total_tiles=4,
        property_tiles=3,
        config_version="test",
        tiles=(
            BoardTile(index=0, kind="start", name="Start"),
            BoardTile(index=1, kind="property", name="A", base_price=100_000, county="C1"),
            BoardTile(index=2, kind="property", name="B", base_price=200_000, county="C2"),
            BoardTile(index=3, kind="property", name="C", base_price=300_000, county="C3"),
        ),
    )


def _config(*, bankruptcy_ratio: float = 0.20) -> dict[str, object]:
    return {
        "properties": {
            "levels": [
                {"level": 0, "rent_ratio": 0.06},
                {"level": 1, "rent_ratio": 0.15, "upgrade_cost_ratio": 0.5},
            ],
            "monopoly": {"rent_multiplier": 2.0},
            "mortgage": {"receive_ratio": 0.5, "redeem_ratio": 0.55},
            "sale": {"to_bank_ratio": 0.70},
        },
        "vehicles": {
            "on_bankruptcy_ratio": 0.70,
            "vehicles": [
                {"key": "scooter", "price": 80_000, "upkeep_per_turn": 1_000},
            ],
        },
        "loans": {
            "products": [
                {"key": "credit", "rate_per_lap": 0.02},
                {"key": "finance_private_loan", "rate_per_lap": 0.03},
            ],
            "origination_points": {"quarterly_affairs": {"products": ["credit"]}},
        },
        "endgame": {
            "bankruptcy_threshold": {
                "default_ratio": bankruptcy_ratio,
                "crowded_override": {"min_players": 21, "ratio": 0.30},
            }
        },
        "confinement": {
            "mode_caps": {"blitz_max_turns": 1, "daily_max_turns": 3},
            "jail": {"release": {"bail_formula": "20000 * remaining_turns"}},
            "hospital": {"early_discharge": {"cost_formula": "50000 * remaining_turns"}},
        },
    }
