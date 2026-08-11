"""玩家 command 執行入口。"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Literal, assert_never

from assetrush.engine.actions import (
    Action,
    AdjustPlayerCashAction,
    AdjustTreasuryAction,
    MovePlayerAction,
    apply_action,
)
from assetrush.engine.effects import EffectContext, apply_effect
from assetrush.engine.errors import InvalidCommandError
from assetrush.engine.events import (
    AllianceBailoutAttemptedEvent,
    AllianceBailoutSucceededEvent,
    AllianceDissolvedEvent,
    AllianceFormedEvent,
    AllianceMemberJoinedEvent,
    AllianceMemberLeftEvent,
    AlliancePoolContributedEvent,
    AlliancePoolDistributedEvent,
    AlliancePoolPaidEvent,
    AllianceProposalResolvedEvent,
    AllianceProposedEvent,
    AllianceRuinedEvent,
    AllianceTierChangedEvent,
    BankruptcyThresholdReachedEvent,
    BidCancelledEvent,
    BidLostEvent,
    BidPlacedEvent,
    BidRaisedEvent,
    BidWonEvent,
    CardDrawnEvent,
    CareerChangedEvent,
    ConfinementAdvancedEvent,
    ConfinementReleasedEvent,
    ConfinementReleasePaidEvent,
    DailyRollUsedEvent,
    DailySettlementCompletedEvent,
    DiceRolledEvent,
    EducationProgressedEvent,
    EducationStartedEvent,
    Event,
    FamilyBailoutAppliedEvent,
    HealthCheckResolvedEvent,
    HealthCheckTriggeredEvent,
    InsurancePremiumPaidEvent,
    InsurancePurchasedEvent,
    LandingDispatchedEvent,
    LoanDefaultedEvent,
    LoanOpenedEvent,
    LoanPaymentMadeEvent,
    PhaseAdvancedEvent,
    PlayerBankruptedEvent,
    PlayerBlacklistedEvent,
    PlayerConfinedEvent,
    PrivateLoanRescueEvent,
    PropertyMortgagedEvent,
    PropertyPurchasedEvent,
    PropertyRedeemedEvent,
    PropertySoldToBankEvent,
    PropertyUpgradedEvent,
    QuarterlyAffairsTriggeredEvent,
    RentPaidEvent,
    SalaryPaidEvent,
    StandingOrdersExecutedEvent,
    StockBoughtEvent,
    StockLiquidatedEvent,
    StockPriceAdvancedEvent,
    StockSoldEvent,
    TradeOfferInvalidatedEvent,
    TurnSkippedEvent,
    VehicleLiquidatedEvent,
    VehiclePurchasedEvent,
    VehicleUpkeepPaidEvent,
)
from assetrush.engine.formula import FormulaValue
from assetrush.engine.replay import apply_events
from assetrush.engine.rng import derive_u64, proof_input, roll_d6
from assetrush.engine.state import (
    AllianceProposalState,
    AllianceState,
    AllianceTier,
    BoardTile,
    ConfinementKind,
    GamePhase,
    GameState,
    Money,
    PlayerState,
    PropertyBidState,
    PropertyState,
    StandingOrderState,
)

ConfigSnapshot = Mapping[str, object]

PHASE_SEQUENCE: tuple[GamePhase, ...] = (
    "lobby",
    "recruiting",
    "starting",
    "active",
    "settling",
    "finished",
)


@dataclass(frozen=True, slots=True)
class AdvancePhaseCommand:
    type: Literal["advance_phase"]
    phase: GamePhase
    reason: str | None = None


@dataclass(frozen=True, slots=True)
class RollDiceCommand:
    type: Literal["roll_dice"]
    player_id: str


@dataclass(frozen=True, slots=True)
class ApplyActionCommand:
    type: Literal["apply_action"]
    action: Action


@dataclass(frozen=True, slots=True)
class TakeTurnCommand:
    type: Literal["take_turn"]
    player_id: str


@dataclass(frozen=True, slots=True)
class PurchasePropertyCommand:
    type: Literal["purchase_property"]
    player_id: str
    tile_index: int


@dataclass(frozen=True, slots=True)
class UpgradePropertyCommand:
    type: Literal["upgrade_property"]
    player_id: str
    tile_index: int


@dataclass(frozen=True, slots=True)
class MortgagePropertyCommand:
    type: Literal["mortgage_property"]
    player_id: str
    tile_index: int


@dataclass(frozen=True, slots=True)
class RedeemPropertyCommand:
    type: Literal["redeem_property"]
    player_id: str
    tile_index: int


@dataclass(frozen=True, slots=True)
class PlacePropertyBidCommand:
    type: Literal["place_property_bid"]
    player_id: str
    tile_index: int
    bid_amount: Money


@dataclass(frozen=True, slots=True)
class CancelPropertyBidCommand:
    type: Literal["cancel_property_bid"]
    player_id: str
    tile_index: int
    reason: str | None = None


@dataclass(frozen=True, slots=True)
class CancelPlayerBidsCommand:
    type: Literal["cancel_player_bids"]
    player_id: str
    reason: str | None = None


@dataclass(frozen=True, slots=True)
class RunDailySettlementCommand:
    type: Literal["run_daily_settlement"]
    execute_standing_orders: bool = True


@dataclass(frozen=True, slots=True)
class InvalidatePlayerTradeOffersCommand:
    type: Literal["invalidate_player_trade_offers"]
    player_id: str
    reason: str | None = None


@dataclass(frozen=True, slots=True)
class LoanDefaultCommand:
    type: Literal["loan_default"]
    player_id: str
    loan_index: int


@dataclass(frozen=True, slots=True)
class ResolveCashShortfallCommand:
    type: Literal["resolve_cash_shortfall"]
    player_id: str
    family_bailout_amount: Money = 0
    finance_lender_id: str | None = None
    finance_loan_amount: Money = 0
    reason: str = "cash_shortfall"


@dataclass(frozen=True, slots=True)
class ResolveCashShortfallsCommand:
    type: Literal["resolve_cash_shortfalls"]
    player_ids: tuple[str, ...]
    reason: str = "cash_shortfall_batch"


@dataclass(frozen=True, slots=True)
class VoluntaryQuitCommand:
    type: Literal["voluntary_quit"]
    player_id: str


@dataclass(frozen=True, slots=True)
class ConfinePlayerCommand:
    type: Literal["confine_player"]
    player_id: str
    kind: ConfinementKind
    turns: int
    reason: str | None = None


@dataclass(frozen=True, slots=True)
class PayConfinementReleaseCommand:
    type: Literal["pay_confinement_release"]
    player_id: str


@dataclass(frozen=True, slots=True)
class ProposeAllianceCommand:
    type: Literal["propose_alliance"]
    from_player_id: str
    to_player_id: str
    tier: AllianceTier
    proposal_id: str
    target_alliance_id: str | None = None
    formation_style: Literal["standard", "budget"] = "standard"


@dataclass(frozen=True, slots=True)
class RespondAllianceProposalCommand:
    type: Literal["respond_alliance_proposal"]
    proposal_id: str
    accepted: bool
    alliance_id: str | None = None
    name: str | None = None


@dataclass(frozen=True, slots=True)
class LeaveAllianceCommand:
    type: Literal["leave_alliance"]
    player_id: str
    reason: str = "left"


@dataclass(frozen=True, slots=True)
class PayHouseholdFeesCommand:
    type: Literal["pay_household_fees"]
    alliance_id: str


@dataclass(frozen=True, slots=True)
class ShareAllianceRentIncomeCommand:
    type: Literal["share_alliance_rent_income"]
    alliance_id: str
    player_id: str
    rent_amount: Money


@dataclass(frozen=True, slots=True)
class PayAllianceExpenseCommand:
    type: Literal["pay_alliance_expense"]
    alliance_id: str
    amount: Money
    reason: str = "common_activity"


@dataclass(frozen=True, slots=True)
class DistributeAlliancePoolCommand:
    type: Literal["distribute_alliance_pool"]
    alliance_id: str


@dataclass(frozen=True, slots=True)
class QuarterlyChoices:
    buy_stock_code: str | None = None
    buy_stock_value: Money = 0
    sell_stock_code: str | None = None
    sell_stock_value: Money = 0
    open_loan_product_key: str | None = None
    open_loan_amount: Money = 0
    education_course_key: str | None = None
    career_change_to: str | None = None
    vehicle_key: str | None = None
    insurance_policy_key: str | None = None


@dataclass(frozen=True, slots=True)
class RunQuarterlyAffairsCommand:
    type: Literal["run_quarterly_affairs"]
    player_id: str
    choices: QuarterlyChoices = QuarterlyChoices()


Command = (
    AdvancePhaseCommand
    | RollDiceCommand
    | ApplyActionCommand
    | TakeTurnCommand
    | PurchasePropertyCommand
    | UpgradePropertyCommand
    | MortgagePropertyCommand
    | RedeemPropertyCommand
    | PlacePropertyBidCommand
    | CancelPropertyBidCommand
    | CancelPlayerBidsCommand
    | RunDailySettlementCommand
    | InvalidatePlayerTradeOffersCommand
    | LoanDefaultCommand
    | ResolveCashShortfallCommand
    | ResolveCashShortfallsCommand
    | VoluntaryQuitCommand
    | ConfinePlayerCommand
    | PayConfinementReleaseCommand
    | ProposeAllianceCommand
    | RespondAllianceProposalCommand
    | LeaveAllianceCommand
    | PayHouseholdFeesCommand
    | ShareAllianceRentIncomeCommand
    | PayAllianceExpenseCommand
    | DistributeAlliancePoolCommand
    | RunQuarterlyAffairsCommand
)


@dataclass(frozen=True, slots=True)
class Transition:
    state: GameState
    events: list[Event]


def execute_command(state: GameState, command: Command, config: ConfigSnapshot) -> Transition:
    """執行 command，回傳新 state 與事件。"""

    if isinstance(command, AdvancePhaseCommand):
        return _advance_phase(state, command)
    if isinstance(command, RollDiceCommand):
        return _roll_dice(state, command)
    if isinstance(command, ApplyActionCommand):
        next_state, events = apply_action(state, command.action, config)
        return Transition(state=next_state, events=events)
    if isinstance(command, TakeTurnCommand):
        return _take_turn(state, command, config)
    if isinstance(command, PurchasePropertyCommand):
        return _purchase_property(state, command, config)
    if isinstance(command, UpgradePropertyCommand):
        return _upgrade_property(state, command, config)
    if isinstance(command, MortgagePropertyCommand):
        return _mortgage_property(state, command, config)
    if isinstance(command, RedeemPropertyCommand):
        return _redeem_property(state, command, config)
    if isinstance(command, PlacePropertyBidCommand):
        return _place_property_bid(state, command, config)
    if isinstance(command, CancelPropertyBidCommand):
        return _cancel_property_bid(state, command)
    if isinstance(command, CancelPlayerBidsCommand):
        return _cancel_player_bids(state, command)
    if isinstance(command, RunDailySettlementCommand):
        return _run_daily_settlement(state, command, config)
    if isinstance(command, InvalidatePlayerTradeOffersCommand):
        return _invalidate_player_trade_offers(state, command)
    if isinstance(command, LoanDefaultCommand):
        return _loan_default(state, command)
    if isinstance(command, ResolveCashShortfallCommand):
        return _resolve_cash_shortfall(state, command, config, check_threshold=True)
    if isinstance(command, ResolveCashShortfallsCommand):
        return _resolve_cash_shortfalls(state, command, config)
    if isinstance(command, VoluntaryQuitCommand):
        return _voluntary_quit(state, command, config)
    if isinstance(command, ConfinePlayerCommand):
        return _confine_player(state, command, config)
    if isinstance(command, PayConfinementReleaseCommand):
        return _pay_confinement_release(state, command, config)
    if isinstance(command, ProposeAllianceCommand):
        return _propose_alliance(state, command, config)
    if isinstance(command, RespondAllianceProposalCommand):
        return _respond_alliance_proposal(state, command, config)
    if isinstance(command, LeaveAllianceCommand):
        return _leave_alliance(state, command, config)
    if isinstance(command, PayHouseholdFeesCommand):
        return _pay_household_fees(state, command, config)
    if isinstance(command, ShareAllianceRentIncomeCommand):
        return _share_alliance_rent_income(state, command, config)
    if isinstance(command, PayAllianceExpenseCommand):
        return _pay_alliance_expense(state, command)
    if isinstance(command, DistributeAlliancePoolCommand):
        return _distribute_alliance_pool(state, command)
    if isinstance(command, RunQuarterlyAffairsCommand):
        return _run_quarterly_affairs(state, command, config)

    assert_never(command)


def _advance_phase(state: GameState, command: AdvancePhaseCommand) -> Transition:
    expected = _next_phase(state.phase)
    if command.phase != expected:
        raise InvalidCommandError(
            f"cannot advance phase from {state.phase!r} to {command.phase!r}; expected {expected!r}"
        )

    event = PhaseAdvancedEvent(
        type="phase_advanced",
        phase_before=state.phase,
        phase_after=command.phase,
        reason=command.reason,
        seq=state.event_seq + 1,
    )
    return Transition(state=apply_events(state, [event]), events=[event])


def _roll_dice(state: GameState, command: RollDiceCommand) -> Transition:
    if state.phase != "active":
        raise InvalidCommandError(f"roll_dice is only allowed in active phase, got {state.phase}")
    if not state.server_seed:
        raise InvalidCommandError("roll_dice requires server_seed")

    player = state.player(command.player_id)
    _require_player_not_bankrupt(player)
    if player.confinement is not None:
        raise InvalidCommandError(f"confined player cannot roll dice: {command.player_id}")
    turn_seq = state.turn_seq + 1
    result = roll_d6(state.server_seed, state.id, turn_seq, command.player_id)
    event = DiceRolledEvent(
        type="dice_rolled",
        player_id=command.player_id,
        result=result,
        turn_seq=turn_seq,
        proof_input=proof_input(state.id, turn_seq, command.player_id),
        seq=state.event_seq + 1,
    )
    return Transition(state=apply_events(state, [event]), events=[event])


def _take_turn(state: GameState, command: TakeTurnCommand, config: ConfigSnapshot) -> Transition:
    if state.phase != "active":
        raise InvalidCommandError(f"take_turn is only allowed in active phase, got {state.phase}")
    if state.board is None:
        raise InvalidCommandError("take_turn requires board")
    if not state.server_seed:
        raise InvalidCommandError("take_turn requires server_seed")

    player = state.player(command.player_id)
    _require_player_not_bankrupt(player)
    if state.mode == "blitz":
        _validate_blitz_turn(state, command.player_id)
    else:
        _validate_daily_roll_budget(state, player)

    if player.confinement is not None:
        return _skip_confined_turn(state, command.player_id)

    events: list[Event] = []
    working = state
    turn_seq = working.turn_seq + 1
    dice = roll_d6(working.server_seed, working.id, turn_seq, command.player_id)
    dice_event = DiceRolledEvent(
        type="dice_rolled",
        player_id=command.player_id,
        result=dice,
        turn_seq=turn_seq,
        proof_input=proof_input(working.id, turn_seq, command.player_id),
        seq=working.event_seq + 1,
    )
    working = apply_events(working, [dice_event])
    events.append(dice_event)

    if working.mode == "daily":
        daily_event = DailyRollUsedEvent(
            type="daily_roll_used",
            player_id=command.player_id,
            day=working.day,
            used=working.player(command.player_id).rolls_used_today + 1,
            limit=_daily_roll_limit(working),
            seq=working.event_seq + 1,
        )
        working = apply_events(working, [daily_event])
        events.append(daily_event)

    board = working.board
    if board is None:
        raise InvalidCommandError("take_turn requires board")

    working, move_events = apply_action(
        working,
        MovePlayerAction(
            type="move_player",
            player_id=command.player_id,
            steps=dice,
            total_tiles=board.total_tiles,
            reason="turn_roll",
        ),
        config,
    )
    events.extend(move_events)

    moved = move_events[0]
    if moved.type != "player_moved":
        raise InvalidCommandError("turn movement did not emit player_moved")
    if moved.lap_after > moved.lap_before:
        working, pass_start_events = _trigger_pass_start(working, command.player_id)
        events.extend(pass_start_events)

    working, landing_events = _dispatch_landing(working, command.player_id, config)
    events.extend(landing_events)
    return Transition(state=working, events=events)


def _skip_confined_turn(state: GameState, player_id: str) -> Transition:
    player = state.player(player_id)
    confinement = player.confinement
    if confinement is None:
        raise InvalidCommandError(f"player is not confined: {player_id}")

    working = state
    events: list[Event] = []
    skipped = TurnSkippedEvent(
        type="turn_skipped",
        player_id=player_id,
        turn_seq=working.turn_seq + 1,
        reason=confinement.kind,
        seq=working.event_seq + 1,
    )
    working = _apply_quarterly_event(working, events, skipped)

    if working.mode == "daily":
        daily_event = DailyRollUsedEvent(
            type="daily_roll_used",
            player_id=player_id,
            day=working.day,
            used=working.player(player_id).rolls_used_today + 1,
            limit=_daily_roll_limit(working),
            seq=working.event_seq + 1,
        )
        working = _apply_quarterly_event(working, events, daily_event)

    remaining_after = max(0, confinement.remaining_turns - 1)
    advanced = ConfinementAdvancedEvent(
        type="confinement_advanced",
        player_id=player_id,
        kind=confinement.kind,
        remaining_before=confinement.remaining_turns,
        remaining_after=remaining_after,
        seq=working.event_seq + 1,
    )
    working = _apply_quarterly_event(working, events, advanced)
    if remaining_after == 0:
        released = ConfinementReleasedEvent(
            type="confinement_released",
            player_id=player_id,
            kind=confinement.kind,
            reason="served",
            seq=working.event_seq + 1,
        )
        working = _apply_quarterly_event(working, events, released)
    return Transition(state=working, events=events)


def _validate_blitz_turn(state: GameState, player_id: str) -> None:
    order = _alive_player_order(state)
    expected_player = order[state.turn_seq % len(order)]
    if player_id != expected_player:
        raise InvalidCommandError(f"expected blitz turn for {expected_player}, got {player_id}")


def _validate_daily_roll_budget(state: GameState, player: PlayerState) -> None:
    limit = _daily_roll_limit(state)
    if player.rolls_used_today >= limit:
        raise InvalidCommandError(
            f"daily roll budget exhausted for {player.id}: {player.rolls_used_today}/{limit}"
        )


def _daily_roll_limit(state: GameState) -> int:
    if state.rolls_per_day is None:
        raise InvalidCommandError("daily game requires rolls_per_day")
    return state.rolls_per_day


def _trigger_pass_start(state: GameState, player_id: str) -> tuple[GameState, list[Event]]:
    player = state.player(player_id)
    events: list[Event] = []
    working = state
    health = HealthCheckTriggeredEvent(
        type="health_check_triggered",
        player_id=player_id,
        lap=player.lap,
        seq=working.event_seq + 1,
    )
    working = apply_events(working, [health])
    events.append(health)

    quarterly = QuarterlyAffairsTriggeredEvent(
        type="quarterly_affairs_triggered",
        player_id=player_id,
        lap=player.lap,
        seq=working.event_seq + 1,
    )
    working = apply_events(working, [quarterly])
    events.append(quarterly)
    return working, events


def _dispatch_landing(
    state: GameState,
    player_id: str,
    config: ConfigSnapshot,
) -> tuple[GameState, list[Event]]:
    if state.board is None:
        raise InvalidCommandError("landing dispatch requires board")

    player = state.player(player_id)
    tile = state.board.tiles[player.position]
    event = LandingDispatchedEvent(
        type="landing_dispatched",
        player_id=player_id,
        tile_index=tile.index,
        tile_kind=tile.kind,
        seq=state.event_seq + 1,
    )
    working = apply_events(state, [event])
    events: list[Event] = [event]

    if tile.kind in {"opportunity", "fate"}:
        working, card_events = _draw_and_apply_card(working, player_id, tile.kind, config)
        events.extend(card_events)
    elif tile.kind == "property":
        working, property_events = _dispatch_property_landing(
            working,
            player_id,
            tile.index,
            config,
        )
        events.extend(property_events)
    elif tile.kind == "tax":
        working, tax_events = _apply_tax_office(working, player_id, config)
        events.extend(tax_events)

    return working, events


def _dispatch_property_landing(
    state: GameState,
    player_id: str,
    tile_index: int,
    config: ConfigSnapshot,
) -> tuple[GameState, list[Event]]:
    property_state = state.property_at(tile_index)
    if property_state is None or property_state.owner_id == player_id or property_state.mortgaged:
        return state, []
    event = _rent_event(state, player_id, tile_index, config)
    return apply_events(state, [event]), [event]


def _purchase_property(
    state: GameState,
    command: PurchasePropertyCommand,
    config: ConfigSnapshot,
) -> Transition:
    _require_active(state)
    player = state.player(command.player_id)
    _require_property_operation_allowed(player, "purchase property")
    if state.mode != "blitz":
        raise InvalidCommandError("daily property acquisition uses claim auction")
    tile = _property_tile(state, command.tile_index)
    if state.property_at(tile.index) is not None:
        raise InvalidCommandError(f"property is already owned: tile {tile.index}")
    price = _base_price(tile)
    if player.cash < price:
        raise InvalidCommandError(f"insufficient cash to purchase tile {tile.index}")
    event = PropertyPurchasedEvent(
        type="property_purchased",
        player_id=command.player_id,
        tile_index=tile.index,
        price=price,
        seq=state.event_seq + 1,
    )
    return Transition(state=apply_events(state, [event]), events=[event])


def _upgrade_property(
    state: GameState,
    command: UpgradePropertyCommand,
    config: ConfigSnapshot,
) -> Transition:
    _require_active(state)
    _require_property_operation_allowed(state.player(command.player_id), "upgrade property")
    property_state = _owned_property(state, command.player_id, command.tile_index)
    if property_state.mortgaged:
        raise InvalidCommandError(f"mortgaged property cannot upgrade: tile {command.tile_index}")
    max_level = _max_property_level(config)
    if property_state.level >= max_level:
        raise InvalidCommandError(f"property is already max level: tile {command.tile_index}")
    tile = _property_tile(state, command.tile_index)
    cost = _upgrade_cost(tile, property_state.level + 1, config)
    player = state.player(command.player_id)
    if player.cash < cost:
        raise InvalidCommandError(f"insufficient cash to upgrade tile {command.tile_index}")
    event = PropertyUpgradedEvent(
        type="property_upgraded",
        player_id=command.player_id,
        tile_index=command.tile_index,
        level_before=property_state.level,
        level_after=property_state.level + 1,
        cost=cost,
        invested_after=property_state.invested + cost,
        seq=state.event_seq + 1,
    )
    return Transition(state=apply_events(state, [event]), events=[event])


def _mortgage_property(
    state: GameState,
    command: MortgagePropertyCommand,
    config: ConfigSnapshot,
) -> Transition:
    _require_active(state)
    _require_property_operation_allowed(state.player(command.player_id), "mortgage property")
    property_state = _owned_property(state, command.player_id, command.tile_index)
    if property_state.mortgaged:
        raise InvalidCommandError(f"property already mortgaged: tile {command.tile_index}")
    amount = round(
        _base_price(_property_tile(state, command.tile_index)) * _mortgage_receive_ratio(config)
    )
    event = PropertyMortgagedEvent(
        type="property_mortgaged",
        player_id=command.player_id,
        tile_index=command.tile_index,
        amount=amount,
        seq=state.event_seq + 1,
    )
    return Transition(state=apply_events(state, [event]), events=[event])


def _redeem_property(
    state: GameState,
    command: RedeemPropertyCommand,
    config: ConfigSnapshot,
) -> Transition:
    _require_active(state)
    _require_property_operation_allowed(state.player(command.player_id), "redeem property")
    property_state = _owned_property(state, command.player_id, command.tile_index)
    if not property_state.mortgaged:
        raise InvalidCommandError(f"property is not mortgaged: tile {command.tile_index}")
    cost = round(
        _base_price(_property_tile(state, command.tile_index)) * _mortgage_redeem_ratio(config)
    )
    if state.player(command.player_id).cash < cost:
        raise InvalidCommandError(f"insufficient cash to redeem tile {command.tile_index}")
    event = PropertyRedeemedEvent(
        type="property_redeemed",
        player_id=command.player_id,
        tile_index=command.tile_index,
        cost=cost,
        seq=state.event_seq + 1,
    )
    return Transition(state=apply_events(state, [event]), events=[event])


def _place_property_bid(
    state: GameState,
    command: PlacePropertyBidCommand,
    config: ConfigSnapshot,
) -> Transition:
    _require_daily_claim(state)
    player = state.player(command.player_id)
    _require_property_operation_allowed(player, "place property bid")
    tile = _property_tile(state, command.tile_index)
    if state.property_at(tile.index) is not None:
        raise InvalidCommandError(f"property is already owned: tile {tile.index}")
    minimum_bid = _base_price(tile)
    if command.bid_amount < minimum_bid:
        raise InvalidCommandError(
            f"bid must be at least base price {minimum_bid}, got {command.bid_amount}"
        )

    existing_bid = _player_bid_for_tile(state, command.player_id, tile.index, state.day)
    if existing_bid is None:
        if player.cash < command.bid_amount:
            raise InvalidCommandError(f"insufficient cash to bid on tile {tile.index}")
        event: Event = BidPlacedEvent(
            type="bid_placed",
            player_id=command.player_id,
            tile_index=tile.index,
            bid_amount=command.bid_amount,
            day=state.day,
            seq=state.event_seq + 1,
        )
    else:
        if command.bid_amount <= existing_bid.bid_amount:
            raise InvalidCommandError(
                f"bid raise must exceed current bid {existing_bid.bid_amount}"
            )
        delta = command.bid_amount - existing_bid.bid_amount
        if player.cash < delta:
            raise InvalidCommandError(f"insufficient cash to raise bid on tile {tile.index}")
        event = BidRaisedEvent(
            type="bid_raised",
            player_id=command.player_id,
            tile_index=tile.index,
            bid_before=existing_bid.bid_amount,
            bid_after=command.bid_amount,
            day=state.day,
            seq=state.event_seq + 1,
        )
    return Transition(state=apply_events(state, [event]), events=[event])


def _cancel_property_bid(
    state: GameState,
    command: CancelPropertyBidCommand,
) -> Transition:
    _require_daily_claim(state)
    bid = _player_bid_for_tile(state, command.player_id, command.tile_index, state.day)
    if bid is None:
        raise InvalidCommandError(f"bid not found on tile {command.tile_index}")
    event = BidCancelledEvent(
        type="bid_cancelled",
        player_id=command.player_id,
        tile_index=command.tile_index,
        bid_amount=bid.bid_amount,
        day=bid.day,
        reason=command.reason,
        seq=state.event_seq + 1,
    )
    return Transition(state=apply_events(state, [event]), events=[event])


def _cancel_player_bids(state: GameState, command: CancelPlayerBidsCommand) -> Transition:
    _require_daily_claim(state)
    state.player(command.player_id)
    working = state
    events: list[Event] = []
    for bid in sorted(
        [bid for bid in state.property_bids if bid.player_id == command.player_id],
        key=lambda item: (item.day, item.tile_index),
    ):
        event = BidCancelledEvent(
            type="bid_cancelled",
            player_id=command.player_id,
            tile_index=bid.tile_index,
            bid_amount=bid.bid_amount,
            day=bid.day,
            reason=command.reason,
            seq=working.event_seq + 1,
        )
        working = _apply_quarterly_event(working, events, event)
    return Transition(state=working, events=events)


def _run_daily_settlement(
    state: GameState,
    command: RunDailySettlementCommand,
    config: ConfigSnapshot,
) -> Transition:
    _require_daily_claim(state)
    working = state
    events: list[Event] = []

    if command.execute_standing_orders:
        working = _execute_standing_orders(working, config, events)

    working = _settle_property_bids(working, events)
    event = DailySettlementCompletedEvent(
        type="daily_settlement_completed",
        day_before=working.day,
        day_after=working.day + 1,
        seq=working.event_seq + 1,
    )
    working = _apply_quarterly_event(working, events, event)
    return Transition(state=working, events=events)


def _invalidate_player_trade_offers(
    state: GameState,
    command: InvalidatePlayerTradeOffersCommand,
) -> Transition:
    state.player(command.player_id)
    working = state
    events: list[Event] = []
    impacted = [
        offer
        for offer in state.trade_offers
        if command.player_id in {offer.from_player_id, offer.to_player_id}
    ]
    for offer in sorted(impacted, key=lambda item: item.offer_id):
        event = TradeOfferInvalidatedEvent(
            type="trade_offer_invalidated",
            offer_id=offer.offer_id,
            player_id=command.player_id,
            cash_refund_player_id=offer.from_player_id if offer.cash_frozen > 0 else None,
            cash_refund=offer.cash_frozen,
            reason=command.reason,
            seq=working.event_seq + 1,
        )
        working = _apply_quarterly_event(working, events, event)
    return Transition(state=working, events=events)


def _loan_default(state: GameState, command: LoanDefaultCommand) -> Transition:
    player = state.player(command.player_id)
    if not 0 <= command.loan_index < len(player.loans):
        raise InvalidCommandError(f"loan index out of range: {command.loan_index}")
    loan = player.loans[command.loan_index]
    working = state
    events: list[Event] = []
    default_event = LoanDefaultedEvent(
        type="loan_defaulted",
        player_id=command.player_id,
        loan_index=command.loan_index,
        product_key=loan.product_key,
        default_count_after=player.default_count + 1,
        rate_before=loan.rate_per_lap,
        rate_after=loan.rate_per_lap + 0.01,
        seq=working.event_seq + 1,
    )
    working = _apply_quarterly_event(working, events, default_event)
    if working.player(command.player_id).default_count >= 3 and not player.is_blacklisted:
        blacklist_event = PlayerBlacklistedEvent(
            type="player_blacklisted",
            player_id=command.player_id,
            seq=working.event_seq + 1,
        )
        working = _apply_quarterly_event(working, events, blacklist_event)
    return Transition(state=working, events=events)


def _resolve_cash_shortfalls(
    state: GameState,
    command: ResolveCashShortfallsCommand,
    config: ConfigSnapshot,
) -> Transition:
    working = state
    events: list[Event] = []
    for player_id in command.player_ids:
        transition = _resolve_cash_shortfall(
            working,
            ResolveCashShortfallCommand(
                type="resolve_cash_shortfall",
                player_id=player_id,
                reason=command.reason,
            ),
            config,
            check_threshold=False,
        )
        working = transition.state
        events.extend(transition.events)
    working = _emit_bankruptcy_threshold_if_reached(working, config, events)
    return Transition(state=working, events=events)


def _resolve_cash_shortfall(
    state: GameState,
    command: ResolveCashShortfallCommand,
    config: ConfigSnapshot,
    *,
    check_threshold: bool,
) -> Transition:
    state.player(command.player_id)
    working = state
    events: list[Event] = []
    if working.player(command.player_id).cash >= 0:
        return Transition(state=working, events=events)

    working = _invalidate_trade_offers_for_player(
        working,
        command.player_id,
        command.reason,
        events,
    )
    working = _cancel_bids_for_player(working, command.player_id, command.reason, events)
    working = _liquidate_stocks(working, command.player_id, events)
    working = _liquidate_mortgages(working, command.player_id, config, events)
    working = _liquidate_vehicles(working, command.player_id, config, events)
    working = _liquidate_properties_to_bank(working, command.player_id, config, events)

    if working.player(command.player_id).cash < 0:
        working = _attempt_alliance_bailout(working, command.player_id, config, events)

    if working.player(command.player_id).cash < 0 and command.family_bailout_amount > 0:
        bailout = FamilyBailoutAppliedEvent(
            type="family_bailout_applied",
            player_id=command.player_id,
            amount=command.family_bailout_amount,
            seq=working.event_seq + 1,
        )
        working = _apply_quarterly_event(working, events, bailout)

    if working.player(command.player_id).cash < 0 and command.finance_lender_id is not None:
        rescue_amount = command.finance_loan_amount
        if rescue_amount <= 0:
            raise InvalidCommandError("finance_loan_amount must be positive")
        _require_finance_lender(working, command.finance_lender_id)
        rescue = PrivateLoanRescueEvent(
            type="private_loan_rescue",
            borrower_id=command.player_id,
            lender_id=command.finance_lender_id,
            amount=rescue_amount,
            rate_per_lap=_finance_private_loan_rate(config),
            seq=working.event_seq + 1,
        )
        working = _apply_quarterly_event(working, events, rescue)

    if working.player(command.player_id).cash < 0:
        working = _remove_bankrupt_from_alliance(working, command.player_id, config, events)
        bankrupt = PlayerBankruptedEvent(
            type="player_bankrupted",
            player_id=command.player_id,
            day=working.day,
            net_worth_before=_player_net_worth(working, working.player(command.player_id)),
            counts_for_end_condition=True,
            reason=command.reason,
            seq=working.event_seq + 1,
        )
        working = _apply_quarterly_event(working, events, bankrupt)

    if check_threshold:
        working = _emit_bankruptcy_threshold_if_reached(working, config, events)
    return Transition(state=working, events=events)


def _voluntary_quit(
    state: GameState,
    command: VoluntaryQuitCommand,
    config: ConfigSnapshot,
) -> Transition:
    player = state.player(command.player_id)
    if player.is_bankrupt or player.has_quit:
        raise InvalidCommandError(f"player already exited: {command.player_id}")
    working = state
    events: list[Event] = []
    working = _invalidate_trade_offers_for_player(
        working,
        command.player_id,
        "voluntary_quit",
        events,
    )
    working = _cancel_bids_for_player(working, command.player_id, "voluntary_quit", events)
    quit_event = PlayerBankruptedEvent(
        type="player_bankrupted",
        player_id=command.player_id,
        day=working.day,
        net_worth_before=_player_net_worth(working, working.player(command.player_id)),
        counts_for_end_condition=False,
        reason="voluntary_quit",
        seq=working.event_seq + 1,
    )
    working = _apply_quarterly_event(working, events, quit_event)
    working = _emit_bankruptcy_threshold_if_reached(working, config, events)
    return Transition(state=working, events=events)


def _confine_player(
    state: GameState,
    command: ConfinePlayerCommand,
    config: ConfigSnapshot,
) -> Transition:
    player = state.player(command.player_id)
    _require_player_not_bankrupt(player)
    turns = _confinement_turns(state, player, command.kind, command.turns, config)
    event = PlayerConfinedEvent(
        type="player_confined",
        player_id=command.player_id,
        kind=command.kind,
        remaining_turns=turns,
        reason=command.reason,
        seq=state.event_seq + 1,
    )
    return Transition(state=apply_events(state, [event]), events=[event])


def _pay_confinement_release(
    state: GameState,
    command: PayConfinementReleaseCommand,
    config: ConfigSnapshot,
) -> Transition:
    player = state.player(command.player_id)
    if player.confinement is None:
        raise InvalidCommandError(f"player is not confined: {command.player_id}")
    amount = _confinement_release_cost(
        player.confinement.kind,
        player.confinement.remaining_turns,
        config,
    )
    event = ConfinementReleasePaidEvent(
        type="confinement_release_paid",
        player_id=command.player_id,
        kind=player.confinement.kind,
        amount=amount,
        reason="paid_release",
        seq=state.event_seq + 1,
    )
    return Transition(state=apply_events(state, [event]), events=[event])


def _propose_alliance(
    state: GameState,
    command: ProposeAllianceCommand,
    config: ConfigSnapshot,
) -> Transition:
    if command.from_player_id == command.to_player_id:
        raise InvalidCommandError("cannot propose alliance to self")
    proposer = state.player(command.from_player_id)
    invitee = state.player(command.to_player_id)
    _require_player_not_bankrupt(proposer)
    _require_player_not_bankrupt(invitee)
    _alliance_tier_config(config, command.tier)

    if any(proposal.id == command.proposal_id for proposal in state.alliance_proposals):
        raise InvalidCommandError(f"alliance proposal already exists: {command.proposal_id}")

    if command.target_alliance_id is None:
        _require_relationship_change_available(proposer, config)
        _require_relationship_change_available(invitee, config)
        if proposer.alliance_id is not None or invitee.alliance_id is not None:
            raise InvalidCommandError("new alliance requires both players to be single")
        if command.tier not in {"couple", "married"}:
            raise InvalidCommandError("new family alliance requires joining an existing core pair")
    else:
        _require_relationship_change_available(invitee, config)
        alliance = _require_active_alliance(state, command.target_alliance_id)
        if command.from_player_id not in alliance.member_ids:
            raise InvalidCommandError("alliance join proposal must come from an existing member")
        if invitee.alliance_id is not None:
            raise InvalidCommandError(f"player already in alliance: {invitee.id}")
        if command.tier not in {"family_small", "family_large"}:
            raise InvalidCommandError("joining an existing alliance requires a family tier")
        _require_alliance_size(command.tier, len(alliance.member_ids) + 1, config)

    event = AllianceProposedEvent(
        type="alliance_proposed",
        proposal_id=command.proposal_id,
        from_player_id=command.from_player_id,
        to_player_id=command.to_player_id,
        tier=command.tier,
        day=state.day,
        target_alliance_id=command.target_alliance_id,
        formation_style=command.formation_style,
        seq=state.event_seq + 1,
    )
    return Transition(state=apply_events(state, [event]), events=[event])


def _respond_alliance_proposal(
    state: GameState,
    command: RespondAllianceProposalCommand,
    config: ConfigSnapshot,
) -> Transition:
    proposal = _alliance_proposal_state(state, command.proposal_id)
    if not command.accepted:
        resolved = AllianceProposalResolvedEvent(
            type="alliance_proposal_resolved",
            proposal_id=command.proposal_id,
            accepted=False,
            seq=state.event_seq + 1,
        )
        return Transition(state=apply_events(state, [resolved]), events=[resolved])

    working = state
    events: list[Event] = []
    proposer = working.player(proposal.from_player_id)
    invitee = working.player(proposal.to_player_id)
    _require_player_not_bankrupt(proposer)
    _require_player_not_bankrupt(invitee)

    if proposal.target_alliance_id is None:
        _require_relationship_change_available(proposer, config)
        _require_relationship_change_available(invitee, config)
        alliance_id = command.alliance_id or f"alliance:{proposal.id}"
        if proposer.alliance_id is not None or invitee.alliance_id is not None:
            raise InvalidCommandError("new alliance requires both players to be single")
        _require_alliance_size(proposal.tier, 2, config)
        cost = _formation_cost_per_member(proposal.tier, proposal.formation_style, config)
        formed = AllianceFormedEvent(
            type="alliance_formed",
            alliance_id=alliance_id,
            tier=proposal.tier,
            member_ids=(proposal.from_player_id, proposal.to_player_id),
            formation_cost_per_member=cost,
            pool_contribution_per_member=_formation_pool_contribution(proposal.tier, cost),
            core_partner_ids=(proposal.from_player_id, proposal.to_player_id),
            name=command.name,
            seq=working.event_seq + 1,
        )
        working = _apply_quarterly_event(working, events, formed)
    else:
        _require_relationship_change_available(invitee, config)
        alliance = _require_active_alliance(working, proposal.target_alliance_id)
        if proposal.from_player_id not in alliance.member_ids:
            raise InvalidCommandError("alliance join proposal must come from an existing member")
        if invitee.alliance_id is not None:
            raise InvalidCommandError(f"player already in alliance: {invitee.id}")
        next_size = len(alliance.member_ids) + 1
        target_tier = _target_family_tier(next_size, config)
        if proposal.tier != target_tier:
            raise InvalidCommandError(
                f"joining would require tier {target_tier}, got {proposal.tier}"
            )
        cost = _formation_cost_per_member(target_tier, proposal.formation_style, config)
        joined = AllianceMemberJoinedEvent(
            type="alliance_member_joined",
            alliance_id=alliance.id,
            player_id=proposal.to_player_id,
            formation_cost=cost,
            pool_contribution=_formation_pool_contribution(target_tier, cost),
            seq=working.event_seq + 1,
        )
        working = _apply_quarterly_event(working, events, joined)
        if alliance.tier != target_tier:
            changed = AllianceTierChangedEvent(
                type="alliance_tier_changed",
                alliance_id=alliance.id,
                tier_before=alliance.tier,
                tier_after=target_tier,
                seq=working.event_seq + 1,
            )
            working = _apply_quarterly_event(working, events, changed)

    resolved = AllianceProposalResolvedEvent(
        type="alliance_proposal_resolved",
        proposal_id=command.proposal_id,
        accepted=True,
        seq=working.event_seq + 1,
    )
    working = _apply_quarterly_event(working, events, resolved)
    return Transition(state=working, events=events)


def _leave_alliance(
    state: GameState,
    command: LeaveAllianceCommand,
    config: ConfigSnapshot,
) -> Transition:
    player = state.player(command.player_id)
    if player.alliance_id is None:
        raise InvalidCommandError(f"player is not in alliance: {command.player_id}")
    _require_relationship_change_available(player, config)

    working = state
    events: list[Event] = []
    left = AllianceMemberLeftEvent(
        type="alliance_member_left",
        alliance_id=player.alliance_id,
        player_id=command.player_id,
        reason=command.reason,
        seq=working.event_seq + 1,
    )
    working = _apply_quarterly_event(working, events, left)
    working = _normalize_alliance_after_departure(
        working,
        player.alliance_id,
        command.reason,
        config,
        events,
    )
    return Transition(state=working, events=events)


def _pay_household_fees(
    state: GameState,
    command: PayHouseholdFeesCommand,
    config: ConfigSnapshot,
) -> Transition:
    alliance = _require_active_alliance(state, command.alliance_id)
    ratio = _tier_float(config, alliance.tier, "household_fee_ratio")
    working = state
    events: list[Event] = []
    for player_id in alliance.member_ids:
        player = working.player(player_id)
        amount = round(player.monthly_salary * 3 * ratio)
        if amount <= 0:
            continue
        contribution = AlliancePoolContributedEvent(
            type="alliance_pool_contributed",
            alliance_id=alliance.id,
            player_id=player_id,
            amount=amount,
            reason="household_fee",
            seq=working.event_seq + 1,
        )
        working = _apply_quarterly_event(working, events, contribution)
    return Transition(state=working, events=events)


def _share_alliance_rent_income(
    state: GameState,
    command: ShareAllianceRentIncomeCommand,
    config: ConfigSnapshot,
) -> Transition:
    alliance = _require_active_alliance(state, command.alliance_id)
    if command.player_id not in alliance.member_ids:
        raise InvalidCommandError(f"player is not in alliance: {command.player_id}")
    amount = round(command.rent_amount * _tier_float(config, alliance.tier, "profit_share_ratio"))
    if amount <= 0:
        return Transition(state=state, events=[])
    event = AlliancePoolContributedEvent(
        type="alliance_pool_contributed",
        alliance_id=command.alliance_id,
        player_id=command.player_id,
        amount=amount,
        reason="rent_share",
        seq=state.event_seq + 1,
    )
    return Transition(state=apply_events(state, [event]), events=[event])


def _pay_alliance_expense(
    state: GameState,
    command: PayAllianceExpenseCommand,
) -> Transition:
    _require_active_alliance(state, command.alliance_id)
    if command.amount <= 0:
        raise InvalidCommandError("alliance expense amount must be positive")
    event = AlliancePoolPaidEvent(
        type="alliance_pool_paid",
        alliance_id=command.alliance_id,
        amount=command.amount,
        reason=command.reason,
        seq=state.event_seq + 1,
    )
    return Transition(state=apply_events(state, [event]), events=[event])


def _distribute_alliance_pool(
    state: GameState,
    command: DistributeAlliancePoolCommand,
) -> Transition:
    alliance = _require_active_alliance(state, command.alliance_id)
    if alliance.pool_balance <= 0:
        return Transition(state=state, events=[])
    payouts = _pool_distribution(alliance)
    event = AlliancePoolDistributedEvent(
        type="alliance_pool_distributed",
        alliance_id=command.alliance_id,
        payouts=payouts,
        seq=state.event_seq + 1,
    )
    return Transition(state=apply_events(state, [event]), events=[event])


def _attempt_alliance_bailout(
    state: GameState,
    player_id: str,
    config: ConfigSnapshot,
    events: list[Event],
) -> GameState:
    player = state.player(player_id)
    if player.alliance_id is None:
        return state

    alliance = _require_active_alliance(state, player.alliance_id)
    shortfall = -player.cash
    if shortfall <= 0:
        return state

    working = state
    attempted = AllianceBailoutAttemptedEvent(
        type="alliance_bailout_attempted",
        alliance_id=alliance.id,
        player_id=player_id,
        shortfall=shortfall,
        seq=working.event_seq + 1,
    )
    working = _apply_quarterly_event(working, events, attempted)

    alliance = _require_active_alliance(working, alliance.id)
    pool_paid = min(alliance.pool_balance, shortfall)
    remaining = shortfall - pool_paid
    member_charges = _bailout_member_charges(
        working,
        alliance,
        player_id,
        remaining,
        _bailout_member_cash_cap(config),
    )
    total_paid = pool_paid + sum(amount for _, amount in member_charges)
    if total_paid >= shortfall:
        succeeded = AllianceBailoutSucceededEvent(
            type="alliance_bailout_succeeded",
            alliance_id=alliance.id,
            player_id=player_id,
            pool_paid=pool_paid,
            member_charges=member_charges,
            seq=working.event_seq + 1,
        )
        return _apply_quarterly_event(working, events, succeeded)

    ruined = AllianceRuinedEvent(
        type="alliance_ruined",
        alliance_id=alliance.id,
        failed_player_id=player_id,
        penalty_ratio=_alliance_ruin_penalty_ratio(config),
        seq=working.event_seq + 1,
    )
    return _apply_quarterly_event(working, events, ruined)


def _remove_bankrupt_from_alliance(
    state: GameState,
    player_id: str,
    config: ConfigSnapshot,
    events: list[Event],
) -> GameState:
    player = state.player(player_id)
    if player.alliance_id is None:
        return state
    alliance_id = player.alliance_id
    left = AllianceMemberLeftEvent(
        type="alliance_member_left",
        alliance_id=alliance_id,
        player_id=player_id,
        reason="bankruptcy",
        seq=state.event_seq + 1,
    )
    working = _apply_quarterly_event(state, events, left)
    return _normalize_alliance_after_departure(
        working,
        alliance_id,
        "bankruptcy",
        config,
        events,
    )


def _normalize_alliance_after_departure(
    state: GameState,
    alliance_id: str,
    reason: str,
    config: ConfigSnapshot,
    events: list[Event],
) -> GameState:
    alliance = _find_alliance(state, alliance_id)
    if alliance is None or not alliance.active:
        return state
    if len(alliance.member_ids) < 2:
        dissolved = AllianceDissolvedEvent(
            type="alliance_dissolved",
            alliance_id=alliance_id,
            reason=reason,
            seq=state.event_seq + 1,
        )
        return _apply_quarterly_event(state, events, dissolved)

    target_tier = _target_tier_after_departure(alliance, config)
    if alliance.tier == target_tier:
        return state
    changed = AllianceTierChangedEvent(
        type="alliance_tier_changed",
        alliance_id=alliance_id,
        tier_before=alliance.tier,
        tier_after=target_tier,
        seq=state.event_seq + 1,
    )
    return _apply_quarterly_event(state, events, changed)


def _bailout_member_charges(
    state: GameState,
    alliance: AllianceState,
    failed_player_id: str,
    amount: Money,
    cap_ratio: float,
) -> tuple[tuple[str, Money], ...]:
    if amount <= 0:
        return ()
    eligible: list[tuple[str, Money, Money]] = []
    for member_id in alliance.member_ids:
        if member_id == failed_player_id:
            continue
        cash = state.player(member_id).cash
        cap = max(0, round(cash * cap_ratio))
        if cap <= 0:
            continue
        member_state = alliance.member_state(member_id)
        contributed = member_state.contributed if member_state is not None else 0
        eligible.append((member_id, contributed, cap))
    if not eligible:
        return ()

    total_weight = sum(max(0, contributed) for _, contributed, _ in eligible)
    if total_weight <= 0:
        total_weight = len(eligible)
        weighted = [(member_id, 1, cap) for member_id, _, cap in eligible]
    else:
        weighted = [
            (member_id, max(0, contributed), cap) for member_id, contributed, cap in eligible
        ]

    charges: dict[str, Money] = {}
    for member_id, weight, cap in weighted:
        share = min(cap, (amount * weight) // total_weight)
        if share > 0:
            charges[member_id] = share

    remaining = amount - sum(charges.values())
    while remaining > 0:
        candidates = [
            (member_id, weight, cap - charges.get(member_id, 0))
            for member_id, weight, cap in weighted
            if cap - charges.get(member_id, 0) > 0
        ]
        if not candidates:
            break
        member_id, _, capacity = max(candidates, key=lambda item: (item[2], item[1], item[0]))
        extra = min(remaining, capacity)
        charges[member_id] = charges.get(member_id, 0) + extra
        remaining -= extra

    return tuple(
        (member_id, charges[member_id]) for member_id in alliance.member_ids if member_id in charges
    )


def _pool_distribution(alliance: AllianceState) -> tuple[tuple[str, Money], ...]:
    if alliance.pool_balance <= 0:
        return ()
    weights: list[Money] = []
    for member_id in alliance.member_ids:
        member_state = alliance.member_state(member_id)
        weights.append(member_state.contributed if member_state is not None else 0)
    total_weight = sum(max(0, weight) for weight in weights)
    if total_weight <= 0:
        weights = [1 for _ in alliance.member_ids]
        total_weight = len(weights)
    payouts: list[tuple[str, Money]] = []
    remaining = alliance.pool_balance
    remaining_weight = total_weight
    for member_id, weight in zip(alliance.member_ids, weights, strict=True):
        if remaining_weight <= 0:
            amount = 0
        elif len(payouts) == len(alliance.member_ids) - 1:
            amount = remaining
        else:
            amount = (alliance.pool_balance * max(0, weight)) // total_weight
        payouts.append((member_id, amount))
        remaining -= amount
        remaining_weight -= max(0, weight)
    return tuple((member_id, amount) for member_id, amount in payouts if amount > 0)


def _alliance_proposal_state(state: GameState, proposal_id: str) -> AllianceProposalState:
    for proposal in state.alliance_proposals:
        if proposal.id == proposal_id:
            return proposal
    raise InvalidCommandError(f"alliance proposal not found: {proposal_id}")


def _find_alliance(state: GameState, alliance_id: str) -> AllianceState | None:
    for alliance in state.alliances:
        if alliance.id == alliance_id:
            return alliance
    return None


def _require_active_alliance(state: GameState, alliance_id: str) -> AllianceState:
    alliance = _find_alliance(state, alliance_id)
    if alliance is None or not alliance.active:
        raise InvalidCommandError(f"active alliance not found: {alliance_id}")
    return alliance


def _require_relationship_change_available(player: PlayerState, config: ConfigSnapshot) -> None:
    limit = _max_relationship_changes(config)
    if player.relationship_changes >= limit:
        raise InvalidCommandError(
            f"relationship change limit reached for {player.id}: "
            f"{player.relationship_changes}/{limit}"
        )


def _max_relationship_changes(config: ConfigSnapshot) -> int:
    formation = _mapping(_alliances_config(config).get("formation"), "alliances.formation")
    return _int(formation.get("max_switches_per_game"), "alliances.formation.max_switches_per_game")


def _alliance_tier_config(config: ConfigSnapshot, tier: AllianceTier) -> ConfigSnapshot:
    for raw_tier in _list(_alliances_config(config).get("tiers"), "alliances.tiers"):
        row = _mapping(raw_tier, "alliance tier")
        if row.get("key") == tier:
            return row
    raise InvalidCommandError(f"unknown alliance tier: {tier}")


def _require_alliance_size(tier: AllianceTier, size: int, config: ConfigSnapshot) -> None:
    row = _alliance_tier_config(config, tier)
    exact_size = row.get("size")
    if exact_size is not None:
        if size != _int(exact_size, f"alliance tier {tier}.size"):
            raise InvalidCommandError(f"alliance tier {tier} requires size {exact_size}")
        return
    size_range = _list(row.get("size_range"), f"alliance tier {tier}.size_range")
    minimum = _int(size_range[0], f"alliance tier {tier}.size_range[0]")
    maximum = _int(size_range[1], f"alliance tier {tier}.size_range[1]")
    if not minimum <= size <= maximum:
        raise InvalidCommandError(f"alliance tier {tier} requires size {minimum}-{maximum}")


def _target_family_tier(size: int, config: ConfigSnapshot) -> AllianceTier:
    if 3 <= size <= 4:
        return "family_small"
    if 5 <= size <= _max_alliance_size(config):
        return "family_large"
    raise InvalidCommandError(f"family alliance requires size 3-{_max_alliance_size(config)}")


def _target_tier_after_departure(alliance: AllianceState, config: ConfigSnapshot) -> AllianceTier:
    size = len(alliance.member_ids)
    if size == 2:
        return "couple" if alliance.tier == "couple" else "married"
    return _target_family_tier(size, config)


def _max_alliance_size(config: ConfigSnapshot) -> int:
    return _int(_alliances_config(config).get("max_size"), "alliances.max_size")


def _formation_cost_per_member(
    tier: AllianceTier,
    formation_style: str | None,
    config: ConfigSnapshot,
) -> Money:
    row = _alliance_tier_config(config, tier)
    if tier == "married" and formation_style == "budget":
        return _int(row.get("formation_cost_budget"), f"alliance tier {tier}.formation_cost_budget")
    value = row.get("formation_cost_per_member", row.get("formation_cost"))
    return _int(value, f"alliance tier {tier}.formation_cost")


def _formation_pool_contribution(tier: AllianceTier, formation_cost: Money) -> Money:
    return formation_cost if tier in {"family_small", "family_large"} else 0


def _tier_float(config: ConfigSnapshot, tier: AllianceTier, field: str) -> float:
    return _float(_alliance_tier_config(config, tier).get(field), f"alliance tier {tier}.{field}")


def _alliance_tax_surcharge(
    state: GameState,
    player_id: str,
    config: ConfigSnapshot,
) -> float:
    player = state.player(player_id)
    if player.alliance_id is None:
        return 0.0
    alliance = _find_alliance(state, player.alliance_id)
    if alliance is None or not alliance.active:
        return 0.0
    return _tier_float(config, alliance.tier, "tax_surcharge")


def _internal_rent_multiplier(
    state: GameState,
    payer_id: str,
    owner_id: str,
    config: ConfigSnapshot,
) -> float:
    payer = state.player(payer_id)
    owner = state.player(owner_id)
    if payer.alliance_id is None or payer.alliance_id != owner.alliance_id:
        return 1.0
    alliance = _find_alliance(state, payer.alliance_id)
    if alliance is None or not alliance.active:
        return 1.0
    return _tier_float(config, alliance.tier, "internal_rent_multiplier")


def _bailout_member_cash_cap(config: ConfigSnapshot) -> float:
    bailout = _alliance_bailout_config(config)
    return _float(bailout.get("member_cash_cap"), "alliances.mechanics.bailout.member_cash_cap")


def _alliance_ruin_penalty_ratio(config: ConfigSnapshot) -> float:
    bailout = _alliance_bailout_config(config)
    failure = _mapping(bailout.get("on_failure"), "alliances.mechanics.bailout.on_failure")
    return _float(
        failure.get("family_penalty_cash_ratio"),
        "alliances.mechanics.bailout.on_failure.family_penalty_cash_ratio",
    )


def _alliance_bailout_config(config: ConfigSnapshot) -> ConfigSnapshot:
    mechanics = _mapping(_alliances_config(config).get("mechanics"), "alliances.mechanics")
    return _mapping(mechanics.get("bailout"), "alliances.mechanics.bailout")


def _alliances_config(config: ConfigSnapshot) -> ConfigSnapshot:
    return _mapping(config.get("alliances"), "config.alliances")


def _invalidate_trade_offers_for_player(
    state: GameState,
    player_id: str,
    reason: str,
    events: list[Event],
) -> GameState:
    working = state
    for offer in sorted(
        [
            offer
            for offer in working.trade_offers
            if player_id in {offer.from_player_id, offer.to_player_id}
        ],
        key=lambda item: item.offer_id,
    ):
        event = TradeOfferInvalidatedEvent(
            type="trade_offer_invalidated",
            offer_id=offer.offer_id,
            player_id=player_id,
            cash_refund_player_id=offer.from_player_id if offer.cash_frozen > 0 else None,
            cash_refund=offer.cash_frozen,
            reason=reason,
            seq=working.event_seq + 1,
        )
        working = _apply_quarterly_event(working, events, event)
    return working


def _cancel_bids_for_player(
    state: GameState,
    player_id: str,
    reason: str,
    events: list[Event],
) -> GameState:
    working = state
    for bid in sorted(
        [bid for bid in working.property_bids if bid.player_id == player_id],
        key=lambda item: (item.day, item.tile_index),
    ):
        event = BidCancelledEvent(
            type="bid_cancelled",
            player_id=player_id,
            tile_index=bid.tile_index,
            bid_amount=bid.bid_amount,
            day=bid.day,
            reason=reason,
            seq=working.event_seq + 1,
        )
        working = _apply_quarterly_event(working, events, event)
    return working


def _liquidate_stocks(
    state: GameState,
    player_id: str,
    events: list[Event],
) -> GameState:
    working = state
    while working.player(player_id).cash < 0 and working.player(player_id).stock_holdings:
        holding = min(
            working.player(player_id).stock_holdings,
            key=lambda item: (item.value, item.code),
        )
        event = StockLiquidatedEvent(
            type="stock_liquidated",
            player_id=player_id,
            code=holding.code,
            value=holding.value,
            seq=working.event_seq + 1,
        )
        working = _apply_quarterly_event(working, events, event)
    return working


def _liquidate_mortgages(
    state: GameState,
    player_id: str,
    config: ConfigSnapshot,
    events: list[Event],
) -> GameState:
    working = state
    while working.player(player_id).cash < 0:
        candidates = [
            property_state
            for property_state in working.properties
            if property_state.owner_id == player_id and not property_state.mortgaged
        ]
        if not candidates:
            return working
        property_state = min(
            candidates,
            key=lambda item: (
                _base_price(_property_tile(working, item.tile_index)),
                item.tile_index,
            ),
        )
        amount = round(
            _base_price(_property_tile(working, property_state.tile_index))
            * _mortgage_receive_ratio(config)
        )
        event = PropertyMortgagedEvent(
            type="property_mortgaged",
            player_id=player_id,
            tile_index=property_state.tile_index,
            amount=amount,
            seq=working.event_seq + 1,
        )
        working = _apply_quarterly_event(working, events, event)
    return working


def _liquidate_vehicles(
    state: GameState,
    player_id: str,
    config: ConfigSnapshot,
    events: list[Event],
) -> GameState:
    working = state
    while working.player(player_id).cash < 0 and working.player(player_id).vehicles:
        vehicle_key = min(
            working.player(player_id).vehicles,
            key=lambda key: (_vehicle_liquidation_amount(key, config), key),
        )
        event = VehicleLiquidatedEvent(
            type="vehicle_liquidated",
            player_id=player_id,
            vehicle_key=vehicle_key,
            amount=_vehicle_liquidation_amount(vehicle_key, config),
            seq=working.event_seq + 1,
        )
        working = _apply_quarterly_event(working, events, event)
    return working


def _liquidate_properties_to_bank(
    state: GameState,
    player_id: str,
    config: ConfigSnapshot,
    events: list[Event],
) -> GameState:
    working = state
    while working.player(player_id).cash < 0:
        candidates = [
            property_state
            for property_state in working.properties
            if property_state.owner_id == player_id
        ]
        if not candidates:
            return working
        property_state = min(
            candidates,
            key=lambda item: (
                _base_price(_property_tile(working, item.tile_index)),
                item.tile_index,
            ),
        )
        amount = round(_property_market_value(working, property_state) * _bank_sale_ratio(config))
        event = PropertySoldToBankEvent(
            type="property_sold_to_bank",
            player_id=player_id,
            tile_index=property_state.tile_index,
            amount=amount,
            seq=working.event_seq + 1,
        )
        working = _apply_quarterly_event(working, events, event)
    return working


def _execute_standing_orders(
    state: GameState,
    config: ConfigSnapshot,
    events: list[Event],
) -> GameState:
    working = state
    for player_id in _daily_player_order(working):
        executed = 0
        while working.player(player_id).rolls_used_today < _daily_roll_limit(working):
            transition = _take_turn(
                working,
                TakeTurnCommand(type="take_turn", player_id=player_id),
                config,
            )
            working = transition.state
            events.extend(transition.events)
            executed += 1
            working = _apply_standing_order_bid(working, player_id, config, events)
        if executed > 0:
            event = StandingOrdersExecutedEvent(
                type="standing_orders_executed",
                player_id=player_id,
                day=working.day,
                rolls_executed=executed,
                seq=working.event_seq + 1,
            )
            working = _apply_quarterly_event(working, events, event)
    return working


def _apply_standing_order_bid(
    state: GameState,
    player_id: str,
    config: ConfigSnapshot,
    events: list[Event],
) -> GameState:
    order = _standing_order(state, player_id)
    if order is None or not order.enabled or order.bid_policy == "none":
        return state
    if state.board is None:
        return state
    player = state.player(player_id)
    tile = state.board.tiles[player.position]
    if tile.kind != "property" or state.property_at(tile.index) is not None:
        return state
    if _player_bid_for_tile(state, player_id, tile.index, state.day) is not None:
        return state
    bid_amount = _standing_order_bid_amount(tile, order)
    if bid_amount > round(_base_price(tile) * order.max_bid_ratio):
        return state
    if player.cash - bid_amount < order.cash_floor:
        return state
    transition = _place_property_bid(
        state,
        PlacePropertyBidCommand(
            type="place_property_bid",
            player_id=player_id,
            tile_index=tile.index,
            bid_amount=bid_amount,
        ),
        config,
    )
    events.extend(transition.events)
    return transition.state


def _settle_property_bids(state: GameState, events: list[Event]) -> GameState:
    working = state
    settlement_day = working.day
    pending = [bid for bid in working.property_bids if bid.day == settlement_day]
    for tile_index in sorted({bid.tile_index for bid in pending}):
        tile_bids = [
            bid
            for bid in working.property_bids
            if bid.tile_index == tile_index and bid.day == settlement_day
        ]
        if not tile_bids:
            continue
        if working.property_at(tile_index) is not None:
            for bid in sorted(tile_bids, key=lambda item: item.player_id):
                event = BidCancelledEvent(
                    type="bid_cancelled",
                    player_id=bid.player_id,
                    tile_index=bid.tile_index,
                    bid_amount=bid.bid_amount,
                    day=bid.day,
                    reason="property_already_owned",
                    seq=working.event_seq + 1,
                )
                working = _apply_quarterly_event(working, events, event)
            continue
        winner = _winning_bid(working, tile_bids, settlement_day)
        win_event = BidWonEvent(
            type="bid_won",
            player_id=winner.player_id,
            tile_index=winner.tile_index,
            bid_amount=winner.bid_amount,
            base_price=_base_price(_property_tile(working, winner.tile_index)),
            day=winner.day,
            seq=working.event_seq + 1,
        )
        working = _apply_quarterly_event(working, events, win_event)
        for bid in sorted(tile_bids, key=lambda item: item.player_id):
            if bid.player_id == winner.player_id:
                continue
            lose_event = BidLostEvent(
                type="bid_lost",
                player_id=bid.player_id,
                tile_index=bid.tile_index,
                bid_amount=bid.bid_amount,
                winner_id=winner.player_id,
                day=bid.day,
                seq=working.event_seq + 1,
            )
            working = _apply_quarterly_event(working, events, lose_event)
    return working


def _run_quarterly_affairs(
    state: GameState,
    command: RunQuarterlyAffairsCommand,
    config: ConfigSnapshot,
) -> Transition:
    _require_quarterly_active(state)
    _require_quarterly_allowed(state.player(command.player_id))

    working = state
    events: list[Event] = []
    lap = working.player(command.player_id).lap

    for stock in _stock_rows(config):
        code = _string(stock.get("code"), "stock.code")
        price_event = StockPriceAdvancedEvent(
            type="stock_price_advanced",
            code=code,
            price=_simulated_stock_price(working, code, lap, stock, config),
            lap=lap,
            seq=working.event_seq + 1,
        )
        working = _apply_quarterly_event(working, events, price_event)

    salary = _quarterly_salary(working.player(command.player_id), config)
    if salary > 0:
        salary_event = SalaryPaidEvent(
            type="salary_paid",
            player_id=command.player_id,
            amount=salary,
            seq=working.event_seq + 1,
        )
        working = _apply_quarterly_event(working, events, salary_event)

    working = _apply_loan_minimum_payments(working, command.player_id, events)
    working = _apply_vehicle_upkeep(working, command.player_id, config, events)
    working = _apply_insurance_premiums(working, command.player_id, config, events)
    working = _resolve_health_check(working, command.player_id, config, events)
    working = _progress_education(working, command.player_id, config, events)
    working = _apply_quarterly_choices(working, command.player_id, command.choices, config, events)

    return Transition(state=working, events=events)


def available_quarterly_actions(
    state: GameState,
    player_id: str,
    config: ConfigSnapshot,
) -> tuple[str, ...]:
    player = state.player(player_id)
    actions = ["buy_stock"]
    if player.stock_holdings:
        actions.append("sell_stock")
    for product in _quarterly_loan_products(config):
        key = _string(product.get("key"), "loan.key")
        if _is_enabled(product):
            actions.append(f"open_loan:{key}")
    if player.education_course_key is None:
        for course in _education_courses(config):
            actions.append(f"start_education:{_string(course.get('key'), 'course.key')}")
    for occupation in _occupation_rows(config):
        actions.append(f"career_change:{_string(occupation.get('key'), 'occupation.key')}")
    for vehicle in _vehicle_rows(config):
        key = _string(vehicle.get("key"), "vehicle.key")
        if key != "none" and key not in player.vehicles:
            actions.append(f"buy_vehicle:{key}")
    for policy in _insurance_rows(config):
        key = _string(policy.get("key"), "insurance.key")
        if key not in player.insurance_policies:
            actions.append(f"buy_insurance:{key}")
    for side_job in _side_job_rows(config):
        if _is_enabled(side_job):
            actions.append(f"side_job:{_string(side_job.get('key'), 'side_job.key')}")
    return tuple(actions)


def _apply_quarterly_choices(
    state: GameState,
    player_id: str,
    choices: QuarterlyChoices,
    config: ConfigSnapshot,
    events: list[Event],
) -> GameState:
    working = state
    if choices.sell_stock_code is not None:
        working = _sell_stock(
            working,
            player_id,
            choices.sell_stock_code,
            choices.sell_stock_value,
            events,
        )
    if choices.open_loan_product_key is not None:
        working = _open_loan(
            working,
            player_id,
            choices.open_loan_product_key,
            choices.open_loan_amount,
            config,
            events,
        )
    if choices.buy_stock_code is not None:
        working = _buy_stock(
            working,
            player_id,
            choices.buy_stock_code,
            choices.buy_stock_value,
            events,
        )
    if choices.education_course_key is not None:
        working = _start_education(working, player_id, choices.education_course_key, config, events)
    if choices.career_change_to is not None:
        working = _change_career(working, player_id, choices.career_change_to, config, events)
    if choices.vehicle_key is not None:
        working = _buy_vehicle(working, player_id, choices.vehicle_key, config, events)
    if choices.insurance_policy_key is not None:
        working = _buy_insurance(
            working,
            player_id,
            choices.insurance_policy_key,
            config,
            events,
        )
    return working


def _apply_loan_minimum_payments(
    state: GameState,
    player_id: str,
    events: list[Event],
) -> GameState:
    working = state
    for loan_index, loan in enumerate(tuple(working.player(player_id).loans)):
        if loan.principal <= 0:
            continue
        interest = round(loan.principal * loan.rate_per_lap)
        principal_payment = min(loan.principal, round(loan.principal * 0.05))
        total_payment = interest + principal_payment
        if working.player(player_id).cash < total_payment:
            raise InvalidCommandError(
                f"insufficient cash for minimum loan payment {loan.product_key}"
            )
        event = LoanPaymentMadeEvent(
            type="loan_payment_made",
            player_id=player_id,
            loan_index=loan_index,
            product_key=loan.product_key,
            principal_before=loan.principal,
            interest=interest,
            principal_payment=principal_payment,
            total_payment=total_payment,
            principal_after=loan.principal - principal_payment,
            seq=working.event_seq + 1,
        )
        working = _apply_quarterly_event(working, events, event)
    return working


def _apply_vehicle_upkeep(
    state: GameState,
    player_id: str,
    config: ConfigSnapshot,
    events: list[Event],
) -> GameState:
    working = state
    for vehicle_key in working.player(player_id).vehicles:
        if vehicle_key == "none":
            continue
        amount = _vehicle_upkeep(vehicle_key, config)
        if amount <= 0:
            continue
        if working.player(player_id).cash < amount:
            raise InvalidCommandError(f"insufficient cash for vehicle upkeep {vehicle_key}")
        event = VehicleUpkeepPaidEvent(
            type="vehicle_upkeep_paid",
            player_id=player_id,
            vehicle_key=vehicle_key,
            amount=amount,
            seq=working.event_seq + 1,
        )
        working = _apply_quarterly_event(working, events, event)
    return working


def _apply_insurance_premiums(
    state: GameState,
    player_id: str,
    config: ConfigSnapshot,
    events: list[Event],
) -> GameState:
    working = state
    if not _insurance_premium_due(working.player(player_id).lap):
        return working
    for policy_key in working.player(player_id).insurance_policies:
        premium = _insurance_premium(policy_key, config)
        if working.player(player_id).cash < premium:
            raise InvalidCommandError(f"insufficient cash for insurance premium {policy_key}")
        event = InsurancePremiumPaidEvent(
            type="insurance_premium_paid",
            player_id=player_id,
            policy_key=policy_key,
            premium=premium,
            seq=working.event_seq + 1,
        )
        working = _apply_quarterly_event(working, events, event)
    return working


def _resolve_health_check(
    state: GameState,
    player_id: str,
    config: ConfigSnapshot,
    events: list[Event],
) -> GameState:
    player = state.player(player_id)
    multiplier = _health_risk_multiplier(player.health, config)
    threshold = max(1, min(100, round(10 * multiplier)))
    risk_roll = (
        int(derive_u64(state.server_seed, state.id, "health_check", player.lap, player_id) % 100)
        + 1
    )
    health_delta = -10 if risk_roll <= threshold else 0
    health_after = min(100, max(0, player.health + health_delta))
    event = HealthCheckResolvedEvent(
        type="health_check_resolved",
        player_id=player_id,
        risk_roll=risk_roll,
        risk_threshold=threshold,
        health_delta=health_delta,
        health_after=health_after,
        seq=state.event_seq + 1,
    )
    return _apply_quarterly_event(state, events, event)


def _progress_education(
    state: GameState,
    player_id: str,
    config: ConfigSnapshot,
    events: list[Event],
) -> GameState:
    player = state.player(player_id)
    if player.education_course_key is None or player.education_remaining_laps <= 0:
        return state
    course = _education_course(player.education_course_key, config)
    remaining_after = max(0, player.education_remaining_laps - 1)
    completed = remaining_after == 0
    effective = False
    unlocked_tier: int | None = None
    salary_multiplier: float | None = None
    if completed:
        chance = _education_success_chance(config)
        marker = derive_u64(
            state.server_seed,
            state.id,
            "education_outcome",
            player.lap,
            f"{player_id}:{player.education_course_key}",
        )
        effective = marker % 10_000 < round(chance * 10_000)
        if effective:
            unlocked_tier = _int(course.get("unlocks_tier"), "course.unlocks_tier")
            multiplier = course.get("permanent_salary_multiplier")
            if multiplier is not None:
                salary_multiplier = _float(multiplier, "course.permanent_salary_multiplier")
    event = EducationProgressedEvent(
        type="education_progressed",
        player_id=player_id,
        course_key=player.education_course_key,
        remaining_laps_before=player.education_remaining_laps,
        remaining_laps_after=remaining_after,
        completed=completed,
        effective=effective,
        unlocked_tier=unlocked_tier,
        salary_multiplier=salary_multiplier,
        seq=state.event_seq + 1,
    )
    return _apply_quarterly_event(state, events, event)


def _sell_stock(
    state: GameState,
    player_id: str,
    code: str,
    value: Money,
    events: list[Event],
) -> GameState:
    if value <= 0:
        raise InvalidCommandError("sell_stock_value must be positive")
    if _stock_holding_value(state.player(player_id), code) < value:
        raise InvalidCommandError(f"cannot sell more stock than held: {code}")
    event = StockSoldEvent(
        type="stock_sold",
        player_id=player_id,
        code=code,
        value=value,
        price=_current_stock_price(state, code),
        seq=state.event_seq + 1,
    )
    return _apply_quarterly_event(state, events, event)


def _open_loan(
    state: GameState,
    player_id: str,
    product_key: str,
    amount: Money,
    config: ConfigSnapshot,
    events: list[Event],
) -> GameState:
    if amount <= 0:
        raise InvalidCommandError("open_loan_amount must be positive")
    product = _loan_product(product_key, config)
    player = state.player(player_id)
    if player.is_blacklisted and product_key != "finance_private_loan":
        raise InvalidCommandError("blacklisted player can only use finance private loan")
    if not _is_enabled(product):
        raise InvalidCommandError(f"loan product is disabled: {product_key}")
    event = LoanOpenedEvent(
        type="loan_opened",
        player_id=player_id,
        product_key=product_key,
        principal=amount,
        rate_per_lap=_loan_rate(product, player, config),
        seq=state.event_seq + 1,
    )
    return _apply_quarterly_event(state, events, event)


def _buy_stock(
    state: GameState,
    player_id: str,
    code: str,
    value: Money,
    events: list[Event],
) -> GameState:
    if value <= 0:
        raise InvalidCommandError("buy_stock_value must be positive")
    if state.player(player_id).cash < value:
        raise InvalidCommandError(f"insufficient cash to buy stock {code}")
    event = StockBoughtEvent(
        type="stock_bought",
        player_id=player_id,
        code=code,
        value=value,
        price=_current_stock_price(state, code),
        seq=state.event_seq + 1,
    )
    return _apply_quarterly_event(state, events, event)


def _start_education(
    state: GameState,
    player_id: str,
    course_key: str,
    config: ConfigSnapshot,
    events: list[Event],
) -> GameState:
    player = state.player(player_id)
    if player.education_course_key is not None:
        raise InvalidCommandError(f"education already active: {player.education_course_key}")
    course = _education_course(course_key, config)
    tuition = _int(course.get("tuition"), "course.tuition")
    if player.cash < tuition:
        raise InvalidCommandError(f"insufficient cash for education {course_key}")
    event = EducationStartedEvent(
        type="education_started",
        player_id=player_id,
        course_key=course_key,
        tuition=tuition,
        remaining_laps=_int(course.get("turns"), "course.turns"),
        seq=state.event_seq + 1,
    )
    return _apply_quarterly_event(state, events, event)


def _change_career(
    state: GameState,
    player_id: str,
    occupation_key: str,
    config: ConfigSnapshot,
    events: list[Event],
) -> GameState:
    player = state.player(player_id)
    occupation = _occupation_row(occupation_key, config)
    target_tier = _int(occupation.get("tier"), "occupation.tier")
    current_tier = _current_occupation_tier(player, config)
    if target_tier > current_tier and (
        player.education_unlocked_tier is None or player.education_unlocked_tier < target_tier
    ):
        raise InvalidCommandError(f"career change to tier {target_tier} requires education")
    event = CareerChangedEvent(
        type="career_changed",
        player_id=player_id,
        occupation_key_before=player.occupation_key,
        occupation_key_after=occupation_key,
        monthly_salary_after=_int(occupation.get("monthly_salary"), "occupation.monthly_salary"),
        seq=state.event_seq + 1,
    )
    return _apply_quarterly_event(state, events, event)


def _buy_vehicle(
    state: GameState,
    player_id: str,
    vehicle_key: str,
    config: ConfigSnapshot,
    events: list[Event],
) -> GameState:
    if vehicle_key == "none":
        raise InvalidCommandError("cannot purchase vehicle 'none'")
    player = state.player(player_id)
    if vehicle_key in player.vehicles:
        raise InvalidCommandError(f"vehicle already owned: {vehicle_key}")
    vehicle = _vehicle_row(vehicle_key, config)
    price = _int(vehicle.get("price"), "vehicle.price")
    if player.cash < price:
        raise InvalidCommandError(f"insufficient cash to buy vehicle {vehicle_key}")
    event = VehiclePurchasedEvent(
        type="vehicle_purchased",
        player_id=player_id,
        vehicle_key=vehicle_key,
        price=price,
        seq=state.event_seq + 1,
    )
    return _apply_quarterly_event(state, events, event)


def _buy_insurance(
    state: GameState,
    player_id: str,
    policy_key: str,
    config: ConfigSnapshot,
    events: list[Event],
) -> GameState:
    player = state.player(player_id)
    if policy_key in player.insurance_policies:
        raise InvalidCommandError(f"insurance already owned: {policy_key}")
    premium = _insurance_premium(policy_key, config)
    if player.cash < premium:
        raise InvalidCommandError(f"insufficient cash to buy insurance {policy_key}")
    event = InsurancePurchasedEvent(
        type="insurance_purchased",
        player_id=player_id,
        policy_key=policy_key,
        premium=premium,
        seq=state.event_seq + 1,
    )
    return _apply_quarterly_event(state, events, event)


def _draw_and_apply_card(
    state: GameState,
    player_id: str,
    deck: Literal["opportunity", "fate"],
    config: ConfigSnapshot,
) -> tuple[GameState, list[Event]]:
    events_config = _mapping(config.get("events"), "config.events")
    cards = _list(events_config.get(deck), f"events.{deck}")
    card = _draw_card(state, player_id, deck, cards)
    rng_seq = state.rng_seq + 1
    event = CardDrawnEvent(
        type="card_drawn",
        player_id=player_id,
        deck=deck,
        card_id=_string(card.get("id"), "card.id"),
        card_name=_string(card.get("name"), "card.name"),
        rng_seq=rng_seq,
        seq=state.event_seq + 1,
    )
    working = apply_events(state, [event])
    events: list[Event] = [event]
    effect = _mapping(card.get("effect"), "card.effect")
    working, effect_events = apply_effect(
        working,
        effect,
        EffectContext(
            player_id=player_id,
            variables=_effect_variables(working, player_id),
            total_tiles=working.board.total_tiles if working.board is not None else None,
            reason=event.card_id,
        ),
    )
    events.extend(effect_events)
    return working, events


def _draw_card(
    state: GameState,
    player_id: str,
    deck: Literal["opportunity", "fate"],
    cards: list[object],
) -> ConfigSnapshot:
    if not cards:
        raise InvalidCommandError(f"{deck} deck is empty")
    total = sum(_int(_mapping(card, "card").get("weight"), "card.weight") for card in cards)
    marker = derive_u64(state.server_seed, state.id, f"card:{deck}", state.rng_seq + 1, player_id)
    marker = marker % total
    running = 0
    for raw_card in cards:
        card = _mapping(raw_card, "card")
        running += _int(card.get("weight"), "card.weight")
        if marker < running:
            return card
    return _mapping(cards[-1], "card")


def _apply_tax_office(
    state: GameState,
    player_id: str,
    config: ConfigSnapshot,
) -> tuple[GameState, list[Event]]:
    amount = _tax_amount(state, player_id, config)
    if amount <= 0:
        return state, []
    working, cash_events = apply_action(
        state,
        AdjustPlayerCashAction(
            type="adjust_player_cash",
            player_id=player_id,
            delta=-amount,
            reason="tax_office",
        ),
        config,
    )
    working, treasury_events = apply_action(
        working,
        AdjustTreasuryAction(type="adjust_treasury", delta=amount, reason="tax_office"),
        config,
    )
    return working, [*cash_events, *treasury_events]


def _tax_amount(state: GameState, player_id: str, config: ConfigSnapshot) -> Money:
    events_config = _mapping(config.get("events"), "config.events")
    tax_office = _mapping(events_config.get("tax_office"), "events.tax_office")
    brackets = _list(tax_office.get("brackets"), "events.tax_office.brackets")
    net_worth = _player_net_worth(state, state.player(player_id))
    for bracket in brackets:
        row = _mapping(bracket, "tax bracket")
        up_to = row.get("up_to")
        if up_to is None or net_worth <= _int(up_to, "tax bracket up_to"):
            surcharge = _alliance_tax_surcharge(state, player_id, config)
            rate = _float(row.get("rate"), "tax bracket rate")
            return round(net_worth * rate * (1 + surcharge))
    return 0


def _effect_variables(state: GameState, player_id: str) -> dict[str, FormulaValue]:
    player = state.player(player_id)
    net_worth = _player_net_worth(state, player)
    all_net_worths = [_player_net_worth(state, other) for other in state.players]
    avg_net_worth = sum(all_net_worths) / len(all_net_worths)
    return {
        "M": player.monthly_salary,
        "NW": net_worth,
        "Q": player.monthly_salary * 3,
        "avg_NW": avg_net_worth,
        "available_loan_capacity": 0,
        "base_amount": 250000,
        "used_vehicle_extra_step": 1 if player.vehicles else 0,
    }


def _player_net_worth(state: GameState, player: PlayerState) -> Money:
    board = state.board
    property_value = 0
    if board is not None:
        property_value = sum(
            (board.tiles[property_state.tile_index].base_price or 0) + property_state.invested
            for property_state in state.properties
            if property_state.owner_id == player.id
            and 0 <= property_state.tile_index < len(board.tiles)
        )
    stock_value = sum(holding.value for holding in player.stock_holdings)
    debt = sum(loan.principal for loan in player.loans)
    return player.cash + player.frozen_cash + property_value + stock_value - debt


def player_net_worth(state: GameState, player_id: str) -> Money:
    return _player_net_worth(state, state.player(player_id))


def alliance_net_worth(state: GameState, alliance_id: str) -> Money:
    alliance = _require_active_alliance(state, alliance_id)
    return sum(
        _player_net_worth(state, state.player(player_id)) for player_id in alliance.member_ids
    )


def _require_active(state: GameState) -> None:
    if state.phase != "active":
        raise InvalidCommandError(
            f"property command is only allowed in active phase, got {state.phase}"
        )
    if state.board is None:
        raise InvalidCommandError("property command requires board")


def _require_daily_claim(state: GameState) -> None:
    if state.phase != "active":
        raise InvalidCommandError(f"daily claim is only allowed in active phase, got {state.phase}")
    if state.mode != "daily":
        raise InvalidCommandError(f"daily claim requires daily mode, got {state.mode}")
    if state.board is None:
        raise InvalidCommandError("daily claim requires board")
    if not state.server_seed:
        raise InvalidCommandError("daily claim requires server_seed")


def _property_tile(state: GameState, tile_index: int) -> BoardTile:
    if state.board is None:
        raise InvalidCommandError("property command requires board")
    if not 0 <= tile_index < len(state.board.tiles):
        raise InvalidCommandError(f"property tile out of range: {tile_index}")
    tile = state.board.tiles[tile_index]
    if tile.kind != "property":
        raise InvalidCommandError(f"tile is not property: {tile_index}")
    return tile


def _owned_property(state: GameState, player_id: str, tile_index: int) -> PropertyState:
    state.player(player_id)
    property_state = state.property_at(tile_index)
    if property_state is None:
        raise InvalidCommandError(f"property is unowned: tile {tile_index}")
    if property_state.owner_id != player_id:
        raise InvalidCommandError(
            f"property is owned by {property_state.owner_id}: tile {tile_index}"
        )
    return property_state


def _base_price(tile: BoardTile) -> Money:
    if tile.base_price is None:
        raise InvalidCommandError(f"property tile missing base price: {tile.index}")
    return tile.base_price


def _player_bid_for_tile(
    state: GameState,
    player_id: str,
    tile_index: int,
    day: int,
) -> PropertyBidState | None:
    for bid in state.property_bids:
        if bid.player_id == player_id and bid.tile_index == tile_index and bid.day == day:
            return bid
    return None


def _standing_order(state: GameState, player_id: str) -> StandingOrderState | None:
    for order in state.standing_orders:
        if order.player_id == player_id:
            return order
    return None


def _standing_order_bid_amount(tile: BoardTile, order: StandingOrderState) -> Money:
    if order.bid_policy == "base_price":
        return _base_price(tile)
    return 0


def _daily_player_order(state: GameState) -> tuple[str, ...]:
    order = _alive_player_order(state)
    if not order:
        return ()
    offset = state.day % len(order)
    return (*order[offset:], *order[:offset])


def _alive_player_order(state: GameState) -> tuple[str, ...]:
    base_order = state.base_turn_order or tuple(player.id for player in state.players)
    exited = {player.id for player in state.players if player.is_bankrupt or player.has_quit}
    order = tuple(player_id for player_id in base_order if player_id not in exited)
    if not order:
        raise InvalidCommandError("no active players remain")
    return order


def _daily_order_rank(state: GameState, player_id: str, day: int) -> int:
    order = state.base_turn_order or tuple(player.id for player in state.players)
    if player_id not in order:
        return len(order)
    offset = day % len(order)
    rotated = (*order[offset:], *order[:offset])
    return rotated.index(player_id)


def _winning_bid(
    state: GameState,
    bids: list[PropertyBidState],
    day: int,
) -> PropertyBidState:
    return min(
        bids,
        key=lambda bid: (
            -bid.bid_amount,
            _daily_order_rank(state, bid.player_id, day),
            bid.player_id,
        ),
    )


def _rent_event(
    state: GameState,
    payer_id: str,
    tile_index: int,
    config: ConfigSnapshot,
) -> RentPaidEvent:
    property_state = state.property_at(tile_index)
    if property_state is None:
        raise InvalidCommandError(f"property is unowned: tile {tile_index}")
    if _has_rent_free_modifier(state.player(payer_id), property_state.owner_id):
        amount = 0
        monopoly_applied = False
    else:
        amount, monopoly_applied = _rent_amount(state, property_state, config)
        multiplier = _internal_rent_multiplier(
            state,
            payer_id,
            property_state.owner_id,
            config,
        )
        amount = round(amount * multiplier)
    return RentPaidEvent(
        type="rent_paid",
        payer_id=payer_id,
        owner_id=property_state.owner_id,
        tile_index=tile_index,
        amount=amount,
        monopoly_applied=monopoly_applied,
        seq=state.event_seq + 1,
    )


def _has_rent_free_modifier(player: PlayerState, owner_id: str) -> bool:
    keys = {modifier.key for modifier in player.modifiers}
    return "rent_free_all" in keys or f"rent_free:{owner_id}" in keys


def _rent_amount(
    state: GameState,
    property_state: PropertyState,
    config: ConfigSnapshot,
) -> tuple[Money, bool]:
    tile = _property_tile(state, property_state.tile_index)
    level_config = _property_level(config, property_state.level)
    amount = round(_base_price(tile) * _float(level_config.get("rent_ratio"), "rent_ratio"))
    monopoly_applied = _has_monopoly(state, property_state.owner_id, tile.county)
    if monopoly_applied:
        amount = round(amount * _monopoly_multiplier(config))
    return amount, monopoly_applied


def _has_monopoly(state: GameState, owner_id: str, county: str | None) -> bool:
    if county is None or state.board is None:
        return False
    county_property_tiles = [
        tile for tile in state.board.tiles if tile.kind == "property" and tile.county == county
    ]
    if not county_property_tiles:
        return False
    for tile in county_property_tiles:
        property_state = state.property_at(tile.index)
        if (
            property_state is None
            or property_state.owner_id != owner_id
            or property_state.mortgaged
        ):
            return False
    return True


def _upgrade_cost(tile: BoardTile, level: int, config: ConfigSnapshot) -> Money:
    level_config = _property_level(config, level)
    ratio = level_config.get("upgrade_cost_ratio")
    if ratio is None:
        raise InvalidCommandError(f"level {level} has no upgrade cost")
    return round(_base_price(tile) * _float(ratio, "upgrade_cost_ratio"))


def _max_property_level(config: ConfigSnapshot) -> int:
    levels = _property_levels(config)
    return max(
        _int(_mapping(level, "property level").get("level"), "property level") for level in levels
    )


def _property_level(config: ConfigSnapshot, level: int) -> ConfigSnapshot:
    for raw_level in _property_levels(config):
        row = _mapping(raw_level, "property level")
        if row.get("level") == level:
            return row
    raise InvalidCommandError(f"unknown property level: {level}")


def _property_levels(config: ConfigSnapshot) -> list[object]:
    properties = _mapping(config.get("properties"), "config.properties")
    return _list(properties.get("levels"), "properties.levels")


def _monopoly_multiplier(config: ConfigSnapshot) -> float:
    properties = _mapping(config.get("properties"), "config.properties")
    monopoly = _mapping(properties.get("monopoly"), "properties.monopoly")
    return _float(monopoly.get("rent_multiplier"), "monopoly.rent_multiplier")


def _mortgage_receive_ratio(config: ConfigSnapshot) -> float:
    properties = _mapping(config.get("properties"), "config.properties")
    mortgage = _mapping(properties.get("mortgage"), "properties.mortgage")
    return _float(mortgage.get("receive_ratio"), "mortgage.receive_ratio")


def _mortgage_redeem_ratio(config: ConfigSnapshot) -> float:
    properties = _mapping(config.get("properties"), "config.properties")
    mortgage = _mapping(properties.get("mortgage"), "properties.mortgage")
    return _float(mortgage.get("redeem_ratio"), "mortgage.redeem_ratio")


def _require_quarterly_active(state: GameState) -> None:
    if state.phase != "active":
        raise InvalidCommandError(
            f"quarterly affairs are only allowed in active phase, got {state.phase}"
        )
    if not state.server_seed:
        raise InvalidCommandError("quarterly affairs require server_seed")


def _apply_quarterly_event(state: GameState, events: list[Event], event: Event) -> GameState:
    next_state = apply_events(state, [event])
    events.append(event)
    return next_state


def _quarterly_salary(player: PlayerState, config: ConfigSnapshot) -> Money:
    if any(modifier.key == "no_salary" for modifier in player.modifiers):
        return 0
    amount = float(player.monthly_salary * 3)
    if player.education_course_key is not None:
        amount *= _education_salary_multiplier(config)
    for modifier in player.modifiers:
        if modifier.key in {"salary_multiplier", "salary_modifier"} and isinstance(
            modifier.value, int | float
        ):
            amount *= float(modifier.value)
    return max(0, round(amount))


def _simulated_stock_price(
    state: GameState,
    code: str,
    lap: int,
    stock: ConfigSnapshot,
    config: ConfigSnapshot,
) -> float:
    seed_price = _float(stock.get("seed_price"), "stock.seed_price")
    clamp = _stock_return_clamp(config)
    marker = derive_u64(state.server_seed, state.id, "stock_price", lap, code)
    unit = (marker % 20_001) / 10_000 - 1
    price = seed_price * (1 + unit * clamp)
    return round(max(0.01, price), 2)


def _stock_return_clamp(config: ConfigSnapshot) -> float:
    stocks = _mapping(config.get("stocks"), "config.stocks")
    trading = _mapping(stocks.get("trading"), "stocks.trading")
    return _float(trading.get("daily_return_clamp"), "stocks.trading.daily_return_clamp")


def _stock_rows(config: ConfigSnapshot) -> list[ConfigSnapshot]:
    stocks = _mapping(config.get("stocks"), "config.stocks")
    rows: list[ConfigSnapshot] = []
    for raw_value in stocks.values():
        if isinstance(raw_value, list):
            for raw_row in raw_value:
                row = _mapping(raw_row, "stock")
                if "code" in row and "seed_price" in row:
                    rows.append(row)
    return rows


def _current_stock_price(state: GameState, code: str) -> float:
    for price in state.stock_prices:
        if price.code == code:
            return price.price
    raise InvalidCommandError(f"stock price not available: {code}")


def _stock_holding_value(player: PlayerState, code: str) -> Money:
    for holding in player.stock_holdings:
        if holding.code == code:
            return holding.value
    return 0


def _loan_product(product_key: str, config: ConfigSnapshot) -> ConfigSnapshot:
    for product in _loan_products(config):
        if product.get("key") == product_key:
            return product
    raise InvalidCommandError(f"unknown loan product: {product_key}")


def _loan_products(config: ConfigSnapshot) -> list[ConfigSnapshot]:
    loans = _mapping(config.get("loans"), "config.loans")
    return [
        _mapping(product, "loan product")
        for product in _list(loans.get("products"), "loans.products")
    ]


def _quarterly_loan_products(config: ConfigSnapshot) -> list[ConfigSnapshot]:
    loans = _mapping(config.get("loans"), "config.loans")
    origination = _mapping(loans.get("origination_points"), "loans.origination_points")
    quarterly = _mapping(
        origination.get("quarterly_affairs"),
        "loans.origination_points.quarterly_affairs",
    )
    allowed = {
        _string(product_key, "quarterly loan product")
        for product_key in _list(quarterly.get("products"), "quarterly_affairs.products")
    }
    return [
        product
        for product in _loan_products(config)
        if _string(product.get("key"), "loan.key") in allowed
    ]


def _loan_rate(product: ConfigSnapshot, player: PlayerState, config: ConfigSnapshot) -> float:
    rate = _float(product.get("rate_per_lap"), "loan.rate_per_lap")
    if player.occupation_key is None:
        return rate
    loans = _mapping(config.get("loans"), "config.loans")
    modifiers = loans.get("occupation_credit_modifiers")
    if not isinstance(modifiers, Mapping):
        return rate
    modifier = modifiers.get(player.occupation_key)
    if not isinstance(modifier, Mapping):
        return rate
    discount = modifier.get("rate_discount", 0)
    if isinstance(discount, int | float) and not isinstance(discount, bool):
        rate -= float(discount)
    return max(0, rate)


def _vehicle_rows(config: ConfigSnapshot) -> list[ConfigSnapshot]:
    vehicles = _mapping(config.get("vehicles"), "config.vehicles")
    return [
        _mapping(vehicle, "vehicle")
        for vehicle in _list(vehicles.get("vehicles"), "vehicles.vehicles")
    ]


def _vehicle_row(vehicle_key: str, config: ConfigSnapshot) -> ConfigSnapshot:
    for vehicle in _vehicle_rows(config):
        if vehicle.get("key") == vehicle_key:
            return vehicle
    raise InvalidCommandError(f"unknown vehicle: {vehicle_key}")


def _vehicle_upkeep(vehicle_key: str, config: ConfigSnapshot) -> Money:
    vehicle = _vehicle_row(vehicle_key, config)
    return _int(vehicle.get("upkeep_per_turn"), "vehicle.upkeep_per_turn")


def _insurance_rows(config: ConfigSnapshot) -> list[ConfigSnapshot]:
    insurance = _mapping(config.get("insurance"), "config.insurance")
    return [
        _mapping(policy, "insurance")
        for policy in _list(insurance.get("policies"), "insurance.policies")
    ]


def _insurance_policy(policy_key: str, config: ConfigSnapshot) -> ConfigSnapshot:
    for policy in _insurance_rows(config):
        if policy.get("key") == policy_key:
            return policy
    raise InvalidCommandError(f"unknown insurance policy: {policy_key}")


def _insurance_premium(policy_key: str, config: ConfigSnapshot) -> Money:
    policy = _insurance_policy(policy_key, config)
    return _int(policy.get("premium_per_year"), "insurance.premium_per_year")


def _insurance_premium_due(lap: int) -> bool:
    return lap > 0 and lap % 4 == 0


def _health_risk_multiplier(health: int, config: ConfigSnapshot) -> float:
    wellbeing = _mapping(config.get("wellbeing"), "config.wellbeing")
    health_config = _mapping(wellbeing.get("health"), "wellbeing.health")
    for raw_band in _list(health_config.get("bands"), "wellbeing.health.bands"):
        band = _mapping(raw_band, "health band")
        if health <= _int(band.get("max"), "health band max"):
            return _float(band.get("disease_risk_multiplier"), "health band multiplier")
    return 1.0


def _education_config(config: ConfigSnapshot) -> ConfigSnapshot:
    occupations = _mapping(config.get("occupations"), "config.occupations")
    return _mapping(occupations.get("education"), "occupations.education")


def _education_courses(config: ConfigSnapshot) -> list[ConfigSnapshot]:
    education = _education_config(config)
    return [
        _mapping(course, "course")
        for course in _list(education.get("courses"), "education.courses")
    ]


def _education_course(course_key: str, config: ConfigSnapshot) -> ConfigSnapshot:
    for course in _education_courses(config):
        if course.get("key") == course_key:
            return course
    raise InvalidCommandError(f"unknown education course: {course_key}")


def _education_salary_multiplier(config: ConfigSnapshot) -> float:
    education = _education_config(config)
    return _float(
        education.get("salary_multiplier_while_studying"),
        "education.salary_multiplier_while_studying",
    )


def _education_success_chance(config: ConfigSnapshot) -> float:
    education = _education_config(config)
    outcome = _mapping(education.get("outcome"), "education.outcome")
    return _float(outcome.get("success_chance"), "education.outcome.success_chance")


def _occupation_rows(config: ConfigSnapshot) -> list[ConfigSnapshot]:
    occupations = _mapping(config.get("occupations"), "config.occupations")
    return [
        _mapping(occupation, "occupation")
        for occupation in _list(occupations.get("occupations"), "occupations.occupations")
    ]


def _occupation_row(occupation_key: str, config: ConfigSnapshot) -> ConfigSnapshot:
    for occupation in _occupation_rows(config):
        if occupation.get("key") == occupation_key:
            return occupation
    raise InvalidCommandError(f"unknown occupation: {occupation_key}")


def _current_occupation_tier(player: PlayerState, config: ConfigSnapshot) -> int:
    if player.occupation_key is None:
        return 1
    return _int(_occupation_row(player.occupation_key, config).get("tier"), "occupation.tier")


def _side_job_rows(config: ConfigSnapshot) -> list[ConfigSnapshot]:
    occupations = _mapping(config.get("occupations"), "config.occupations")
    side_jobs = _mapping(occupations.get("side_jobs"), "occupations.side_jobs")
    return [
        _mapping(side_job, "side_job")
        for side_job in _list(side_jobs.get("jobs"), "side_jobs.jobs")
    ]


def _is_enabled(row: ConfigSnapshot) -> bool:
    enabled = row.get("enabled", True)
    return isinstance(enabled, bool) and enabled


def _property_market_value(state: GameState, property_state: PropertyState) -> Money:
    return _base_price(_property_tile(state, property_state.tile_index)) + property_state.invested


def _bank_sale_ratio(config: ConfigSnapshot) -> float:
    properties = _mapping(config.get("properties"), "config.properties")
    sale = _mapping(properties.get("sale"), "properties.sale")
    return _float(sale.get("to_bank_ratio"), "properties.sale.to_bank_ratio")


def _vehicle_liquidation_amount(vehicle_key: str, config: ConfigSnapshot) -> Money:
    vehicle = _vehicle_row(vehicle_key, config)
    return round(_int(vehicle.get("price"), "vehicle.price") * _vehicle_bankruptcy_ratio(config))


def _vehicle_bankruptcy_ratio(config: ConfigSnapshot) -> float:
    vehicles = _mapping(config.get("vehicles"), "config.vehicles")
    ratio = vehicles.get("on_bankruptcy_ratio")
    if ratio is None:
        return 0.70
    return _float(ratio, "vehicles.on_bankruptcy_ratio")


def _finance_private_loan_rate(config: ConfigSnapshot) -> float:
    product = _loan_product("finance_private_loan", config)
    return _float(product.get("rate_per_lap"), "finance_private_loan.rate_per_lap")


def _require_finance_lender(state: GameState, lender_id: str) -> None:
    lender = state.player(lender_id)
    _require_player_not_bankrupt(lender)
    if lender.occupation_key != "finance":
        raise InvalidCommandError("pre-bankruptcy rescue requires finance occupation lender")


def _emit_bankruptcy_threshold_if_reached(
    state: GameState,
    config: ConfigSnapshot,
    events: list[Event],
) -> GameState:
    if state.phase == "finished":
        return state
    threshold = _bankruptcy_threshold(state, config)
    bankrupt_count = sum(
        1 for record in state.bankruptcy_records if record.counts_for_end_condition
    )
    if bankrupt_count < threshold:
        return state
    event = BankruptcyThresholdReachedEvent(
        type="bankruptcy_threshold_reached",
        bankrupt_count=bankrupt_count,
        threshold=threshold,
        seq=state.event_seq + 1,
    )
    return _apply_quarterly_event(state, events, event)


def _bankruptcy_threshold(state: GameState, config: ConfigSnapshot) -> int:
    endgame = _mapping(config.get("endgame"), "config.endgame")
    threshold = _mapping(endgame.get("bankruptcy_threshold"), "endgame.bankruptcy_threshold")
    ratio = _float(threshold.get("default_ratio"), "bankruptcy_threshold.default_ratio")
    crowded = threshold.get("crowded_override")
    if isinstance(crowded, Mapping):
        min_players = _int(crowded.get("min_players"), "crowded_override.min_players")
        if len(state.players) >= min_players:
            ratio = _float(crowded.get("ratio"), "crowded_override.ratio")
    return max(1, _ceil_int(len(state.players) * ratio))


def _confinement_turns(
    state: GameState,
    player: PlayerState,
    kind: ConfinementKind,
    turns: int,
    config: ConfigSnapshot,
) -> int:
    if turns <= 0:
        raise InvalidCommandError("confinement turns must be positive")
    capped = min(turns, _confinement_mode_cap(state, config))
    if kind == "hospital" and "health" in player.insurance_policies:
        return max(1, capped // 2)
    return capped


def _confinement_mode_cap(state: GameState, config: ConfigSnapshot) -> int:
    confinement = _mapping(config.get("confinement"), "config.confinement")
    caps = _mapping(confinement.get("mode_caps"), "confinement.mode_caps")
    if state.mode == "daily":
        return _int(caps.get("daily_max_turns"), "confinement.mode_caps.daily_max_turns")
    return _int(caps.get("blitz_max_turns"), "confinement.mode_caps.blitz_max_turns")


def _confinement_release_cost(
    kind: ConfinementKind,
    remaining_turns: int,
    config: ConfigSnapshot,
) -> Money:
    confinement = _mapping(config.get("confinement"), "config.confinement")
    if kind == "jail":
        jail = _mapping(confinement.get("jail"), "confinement.jail")
        release = _mapping(jail.get("release"), "confinement.jail.release")
        formula = release.get("bail_formula")
        if formula == "20000 * remaining_turns":
            return 20_000 * remaining_turns
        return 20_000 * remaining_turns
    hospital = _mapping(confinement.get("hospital"), "confinement.hospital")
    early = _mapping(hospital.get("early_discharge"), "confinement.hospital.early_discharge")
    formula = early.get("cost_formula")
    if formula == "50000 * remaining_turns":
        return 50_000 * remaining_turns
    return 50_000 * remaining_turns


def _require_player_not_bankrupt(player: PlayerState) -> None:
    if player.is_bankrupt or player.has_quit:
        raise InvalidCommandError(f"player has exited: {player.id}")


def _require_property_operation_allowed(player: PlayerState, operation: str) -> None:
    _require_player_not_bankrupt(player)
    if player.confinement is not None and player.confinement.kind == "hospital":
        raise InvalidCommandError(f"hospitalized player cannot {operation}: {player.id}")


def _require_quarterly_allowed(player: PlayerState) -> None:
    _require_player_not_bankrupt(player)
    if player.confinement is not None:
        raise InvalidCommandError(f"confined player cannot open quarterly affairs: {player.id}")


def _ceil_int(value: float) -> int:
    integer = int(value)
    return integer if value == integer else integer + 1


def _next_phase(phase: GamePhase) -> GamePhase:
    try:
        index = PHASE_SEQUENCE.index(phase)
    except ValueError as exc:
        raise InvalidCommandError(f"unknown phase: {phase}") from exc
    if index == len(PHASE_SEQUENCE) - 1:
        raise InvalidCommandError("finished phase cannot advance")
    return PHASE_SEQUENCE[index + 1]


def _mapping(value: object, path: str) -> ConfigSnapshot:
    if not isinstance(value, Mapping):
        raise InvalidCommandError(f"{path} must be an object")
    return value


def _list(value: object, path: str) -> list[object]:
    if not isinstance(value, list):
        raise InvalidCommandError(f"{path} must be a list")
    return value


def _string(value: object, path: str) -> str:
    if not isinstance(value, str) or not value:
        raise InvalidCommandError(f"{path} must be a non-empty string")
    return value


def _int(value: object, path: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise InvalidCommandError(f"{path} must be an integer")
    return value


def _float(value: object, path: str) -> float:
    if isinstance(value, bool) or not isinstance(value, int | float):
        raise InvalidCommandError(f"{path} must be a number")
    return float(value)
