from __future__ import annotations

import pytest

from assetrush.engine import (
    AllianceMemberState,
    AllianceState,
    BoardReference,
    BoardTile,
    DistributeAlliancePoolCommand,
    GameState,
    InvalidCommandError,
    PayHouseholdFeesCommand,
    PlayerState,
    PropertyState,
    ProposeAllianceCommand,
    ResolveCashShortfallCommand,
    RespondAllianceProposalCommand,
    TakeTurnCommand,
    execute_command,
    replay_events,
    roll_d6,
    state_digest,
)


def test_married_alliance_forms_through_proposal_and_replays() -> None:
    state = _state(players=(PlayerState(id="p1", cash=500_000), PlayerState(id="p2", cash=500_000)))

    proposed = execute_command(
        state,
        ProposeAllianceCommand(
            type="propose_alliance",
            from_player_id="p1",
            to_player_id="p2",
            tier="married",
            proposal_id="proposal-1",
            formation_style="budget",
        ),
        _config(),
    )
    accepted = execute_command(
        proposed.state,
        RespondAllianceProposalCommand(
            type="respond_alliance_proposal",
            proposal_id="proposal-1",
            accepted=True,
            alliance_id="family-1",
        ),
        _config(),
    )

    assert [event.type for event in [*proposed.events, *accepted.events]] == [
        "alliance_proposed",
        "alliance_formed",
        "alliance_proposal_resolved",
    ]
    assert accepted.state.player("p1").cash == 450_000
    assert accepted.state.player("p2").cash == 450_000
    assert accepted.state.player("p1").alliance_id == "family-1"
    assert accepted.state.alliances[0].tier == "married"
    assert accepted.state.alliance_proposals == ()

    replayed = replay_events(state, [*proposed.events, *accepted.events])
    assert state_digest(replayed) == state_digest(accepted.state)


def test_joining_core_pair_upgrades_to_small_family() -> None:
    married = _married_state(
        players=(
            PlayerState(id="p1", cash=450_000, alliance_id="family-1", relationship_changes=1),
            PlayerState(id="p2", cash=450_000, alliance_id="family-1", relationship_changes=1),
            PlayerState(id="p3", cash=500_000),
        )
    )

    proposed = execute_command(
        married,
        ProposeAllianceCommand(
            type="propose_alliance",
            from_player_id="p1",
            to_player_id="p3",
            tier="family_small",
            proposal_id="proposal-join",
            target_alliance_id="family-1",
        ),
        _config(),
    )
    accepted = execute_command(
        proposed.state,
        RespondAllianceProposalCommand(
            type="respond_alliance_proposal",
            proposal_id="proposal-join",
            accepted=True,
        ),
        _config(),
    )

    assert [event.type for event in accepted.events] == [
        "alliance_member_joined",
        "alliance_tier_changed",
        "alliance_proposal_resolved",
    ]
    alliance = accepted.state.alliances[0]
    assert alliance.tier == "family_small"
    assert alliance.member_ids == ("p1", "p2", "p3")
    assert alliance.pool_balance == 100_000
    assert accepted.state.player("p3").cash == 400_000
    assert accepted.state.player("p3").relationship_changes == 1


def test_household_fees_enter_pool_and_distribute_by_contribution() -> None:
    state = _married_state(
        players=(
            PlayerState(
                id="p1",
                cash=450_000,
                monthly_salary=100_000,
                alliance_id="family-1",
                relationship_changes=1,
            ),
            PlayerState(
                id="p2",
                cash=450_000,
                monthly_salary=200_000,
                alliance_id="family-1",
                relationship_changes=1,
            ),
        )
    )

    paid = execute_command(
        state,
        PayHouseholdFeesCommand(type="pay_household_fees", alliance_id="family-1"),
        _config(),
    )
    distributed = execute_command(
        paid.state,
        DistributeAlliancePoolCommand(type="distribute_alliance_pool", alliance_id="family-1"),
        _config(),
    )

    assert [event.amount for event in paid.events if event.type == "alliance_pool_contributed"] == [
        30_000,
        60_000,
    ]
    assert distributed.events[0].type == "alliance_pool_distributed"
    assert distributed.events[0].payouts == (("p1", 30_000), ("p2", 60_000))
    assert distributed.state.alliances[0].pool_balance == 0
    assert distributed.state.player("p1").cash == 450_000
    assert distributed.state.player("p2").cash == 450_000


def test_alliance_bailout_success_prevents_bankruptcy() -> None:
    state = _state(
        players=(
            PlayerState(id="p1", cash=-70_000, alliance_id="family-1", relationship_changes=1),
            PlayerState(id="p2", cash=100_000, alliance_id="family-1", relationship_changes=1),
        ),
        alliances=(
            AllianceState(
                id="family-1",
                tier="married",
                member_ids=("p1", "p2"),
                pool_balance=30_000,
                member_states=(
                    AllianceMemberState(player_id="p1"),
                    AllianceMemberState(player_id="p2", contributed=30_000),
                ),
                core_partner_ids=("p1", "p2"),
            ),
        ),
    )

    transition = execute_command(
        state,
        ResolveCashShortfallCommand(type="resolve_cash_shortfall", player_id="p1"),
        _config(),
    )

    assert [event.type for event in transition.events] == [
        "alliance_bailout_attempted",
        "alliance_bailout_succeeded",
    ]
    assert transition.state.player("p1").cash == 0
    assert transition.state.player("p1").is_bankrupt is False
    assert transition.state.player("p2").cash == 60_000
    assert transition.state.alliances[0].pool_balance == 0


def test_failed_alliance_bailout_ruins_family_then_exits_bankrupt_member() -> None:
    state = _state(
        players=(
            PlayerState(id="p1", cash=-120_000, alliance_id="family-1", relationship_changes=1),
            PlayerState(id="p2", cash=100_000, alliance_id="family-1", relationship_changes=1),
        ),
        alliances=(
            AllianceState(
                id="family-1",
                tier="married",
                member_ids=("p1", "p2"),
                pool_balance=10_000,
                member_states=(
                    AllianceMemberState(player_id="p1"),
                    AllianceMemberState(player_id="p2", contributed=10_000),
                ),
                core_partner_ids=("p1", "p2"),
            ),
        ),
    )

    transition = execute_command(
        state,
        ResolveCashShortfallCommand(type="resolve_cash_shortfall", player_id="p1"),
        _config(bankruptcy_ratio=0.5),
    )

    assert [event.type for event in transition.events] == [
        "alliance_bailout_attempted",
        "alliance_ruined",
        "alliance_member_left",
        "alliance_dissolved",
        "player_bankrupted",
        "bankruptcy_threshold_reached",
    ]
    assert transition.state.player("p1").is_bankrupt is True
    assert transition.state.player("p1").alliance_id is None
    assert transition.state.player("p2").cash == 90_000
    assert transition.state.player("p2").alliance_id is None
    assert transition.state.alliances[0].active is False


def test_relationship_change_limit_is_enforced() -> None:
    state = _state(
        players=(
            PlayerState(id="p1", cash=500_000, relationship_changes=2),
            PlayerState(id="p2", cash=500_000),
        )
    )

    with pytest.raises(InvalidCommandError, match="relationship change limit"):
        execute_command(
            state,
            ProposeAllianceCommand(
                type="propose_alliance",
                from_player_id="p1",
                to_player_id="p2",
                tier="couple",
                proposal_id="proposal-limit",
            ),
            _config(),
        )


def test_internal_couple_rent_uses_tier_multiplier() -> None:
    board = _board()
    dice = roll_d6("seed", "alliance-game", 1, "payer")
    state = _state(
        players=(
            PlayerState(
                id="payer",
                cash=10_000,
                position=(1 - dice) % board.total_tiles,
                alliance_id="family-1",
            ),
            PlayerState(
                id="owner",
                cash=1_000,
                property_tile_indices=(1,),
                alliance_id="family-1",
            ),
        ),
        properties=(PropertyState(tile_index=1, owner_id="owner"),),
        alliances=(
            AllianceState(
                id="family-1",
                tier="couple",
                member_ids=("payer", "owner"),
                core_partner_ids=("payer", "owner"),
            ),
        ),
        board=board,
    )

    transition = execute_command(
        state,
        TakeTurnCommand(type="take_turn", player_id="payer"),
        _config(),
    )

    rent = next(event for event in transition.events if event.type == "rent_paid")
    assert rent.amount == 30
    assert transition.state.player("payer").cash == 9_970
    assert transition.state.player("owner").cash == 1_030


def _married_state(*, players: tuple[PlayerState, ...]) -> GameState:
    return _state(
        players=players,
        alliances=(
            AllianceState(
                id="family-1",
                tier="married",
                member_ids=("p1", "p2"),
                member_states=(
                    AllianceMemberState(player_id="p1"),
                    AllianceMemberState(player_id="p2"),
                ),
                core_partner_ids=("p1", "p2"),
            ),
        ),
    )


def _state(
    *,
    players: tuple[PlayerState, ...],
    properties: tuple[PropertyState, ...] = (),
    alliances: tuple[AllianceState, ...] = (),
    board: BoardReference | None = None,
) -> GameState:
    return GameState(
        id="alliance-game",
        phase="active",
        server_seed="seed",
        board=board or _board(),
        players=players,
        properties=properties,
        alliances=alliances,
        base_turn_order=tuple(player.id for player in players),
    )


def _board() -> BoardReference:
    return BoardReference(
        seed=1,
        total_tiles=4,
        property_tiles=1,
        config_version="test",
        tiles=(
            BoardTile(index=0, kind="start", name="Start"),
            BoardTile(index=1, kind="property", name="A", base_price=1_000),
            BoardTile(index=2, kind="opportunity", name="Opportunity"),
            BoardTile(index=3, kind="fate", name="Fate"),
        ),
    )


def _config(*, bankruptcy_ratio: float = 0.20) -> dict[str, object]:
    return {
        "alliances": {
            "tiers": [
                {
                    "key": "couple",
                    "size": 2,
                    "formation_cost": 0,
                    "internal_rent_multiplier": 0.5,
                    "household_fee_ratio": 0.05,
                    "profit_share_ratio": 0.10,
                    "tax_surcharge": 0.0,
                },
                {
                    "key": "married",
                    "size": 2,
                    "formation_cost": 300_000,
                    "formation_cost_budget": 50_000,
                    "internal_rent_multiplier": 0.0,
                    "household_fee_ratio": 0.10,
                    "profit_share_ratio": 0.25,
                    "tax_surcharge": 0.10,
                },
                {
                    "key": "family_small",
                    "size_range": [3, 4],
                    "formation_cost_per_member": 100_000,
                    "internal_rent_multiplier": 0.0,
                    "household_fee_ratio": 0.15,
                    "profit_share_ratio": 0.30,
                    "tax_surcharge": 0.20,
                },
                {
                    "key": "family_large",
                    "size_range": [5, 8],
                    "formation_cost_per_member": 100_000,
                    "internal_rent_multiplier": 0.0,
                    "household_fee_ratio": 0.20,
                    "profit_share_ratio": 0.35,
                    "tax_surcharge": 0.40,
                },
            ],
            "max_size": 8,
            "mechanics": {
                "bailout": {
                    "member_cash_cap": 0.5,
                    "on_failure": {"family_penalty_cash_ratio": 0.10},
                }
            },
            "formation": {"max_switches_per_game": 2},
        },
        "properties": {
            "levels": [{"level": 0, "rent_ratio": 0.06}],
            "monopoly": {"rent_multiplier": 2.0},
            "mortgage": {"receive_ratio": 0.5, "redeem_ratio": 0.55},
            "sale": {"to_bank_ratio": 0.70},
        },
        "events": {
            "opportunity": [],
            "fate": [],
            "tax_office": {"brackets": [{"up_to": None, "rate": 0.02}]},
            "start": {"salary_multiplier": 3},
        },
        "endgame": {
            "bankruptcy_threshold": {
                "default_ratio": bankruptcy_ratio,
                "crowded_override": {"min_players": 21, "ratio": 0.30},
            }
        },
        "vehicles": {"on_bankruptcy_ratio": 0.70, "vehicles": []},
        "loans": {
            "products": [{"key": "finance_private_loan", "rate_per_lap": 0.03}],
            "origination_points": {"quarterly_affairs": {"products": []}},
        },
    }
