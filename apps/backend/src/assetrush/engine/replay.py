"""事件 replay 與 state digest。"""

from __future__ import annotations

import json
from dataclasses import asdict, is_dataclass, replace
from typing import assert_never

from assetrush.engine.errors import InvalidEventError
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
    CashAdjustedEvent,
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
    PendingEffectAddedEvent,
    PhaseAdvancedEvent,
    PlayerBankruptedEvent,
    PlayerBlacklistedEvent,
    PlayerConfinedEvent,
    PlayerModifierAddedEvent,
    PlayerMovedEvent,
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
    TreasuryAdjustedEvent,
    TurnSkippedEvent,
    VehicleLiquidatedEvent,
    VehiclePurchasedEvent,
    VehicleUpkeepPaidEvent,
)
from assetrush.engine.state import (
    AllianceMemberState,
    AllianceProposalState,
    AllianceState,
    BankruptcyRecord,
    ConfinementState,
    GameState,
    PendingEffect,
    PlayerLoan,
    PlayerModifier,
    PropertyBidState,
    PropertyState,
    StockHolding,
    StockPrice,
    TradeOfferState,
)


def apply_event(state: GameState, event: Event) -> GameState:
    """套用單一事件。

    事件必須接在目前 `event_seq` 後面；replay 時若跳號、倒退或重複套用會失敗。
    """

    _validate_next_seq(state, event.seq)

    if isinstance(event, CashAdjustedEvent):
        player = state.player(event.player_id)
        balance_after = player.cash + event.delta
        if balance_after != event.balance_after:
            raise InvalidEventError(
                f"cash balance mismatch for {event.player_id}: "
                f"expected {balance_after}, got {event.balance_after}"
            )
        return replace(
            state,
            event_seq=event.seq,
            players=tuple(
                replace(existing, cash=balance_after)
                if existing.id == event.player_id
                else existing
                for existing in state.players
            ),
        )

    if isinstance(event, TreasuryAdjustedEvent):
        balance_after = state.treasury + event.delta
        if balance_after != event.balance_after:
            raise InvalidEventError(
                f"treasury balance mismatch: expected {balance_after}, got {event.balance_after}"
            )
        return replace(state, event_seq=event.seq, treasury=balance_after)

    if isinstance(event, PlayerMovedEvent):
        player = state.player(event.player_id)
        if player.position != event.position_before or player.lap != event.lap_before:
            raise InvalidEventError(
                f"player move mismatch for {event.player_id}: "
                f"expected position/lap {player.position}/{player.lap}, "
                f"got {event.position_before}/{event.lap_before}"
            )
        updated = replace(player, position=event.position_after, lap=event.lap_after)
        return replace(state.replace_player(updated), event_seq=event.seq)

    if isinstance(event, PlayerModifierAddedEvent):
        player = state.player(event.player_id)
        modifier = PlayerModifier(key=event.key, value=event.value, laps=event.laps)
        updated = replace(player, modifiers=(*player.modifiers, modifier))
        return replace(state.replace_player(updated), event_seq=event.seq)

    if isinstance(event, PendingEffectAddedEvent):
        state.player(event.player_id)
        pending_effect = PendingEffect(
            effect_type=event.effect_type,
            player_id=event.player_id,
            reason=event.reason,
        )
        return replace(
            state,
            event_seq=event.seq,
            pending_effects=(*state.pending_effects, pending_effect),
        )

    if isinstance(event, PhaseAdvancedEvent):
        if state.phase != event.phase_before:
            raise InvalidEventError(
                f"phase mismatch: expected {state.phase}, got {event.phase_before}"
            )
        return replace(state, event_seq=event.seq, phase=event.phase_after)

    if isinstance(event, DiceRolledEvent):
        state.player(event.player_id)
        if not 1 <= event.result <= 6:
            raise InvalidEventError(f"dice result must be 1..6, got {event.result}")
        if event.turn_seq != state.turn_seq + 1:
            raise InvalidEventError(
                f"turn seq mismatch: expected {state.turn_seq + 1}, got {event.turn_seq}"
            )
        return replace(
            state,
            event_seq=event.seq,
            rng_seq=state.rng_seq + 1,
            turn_seq=event.turn_seq,
        )

    if isinstance(event, TurnSkippedEvent):
        state.player(event.player_id)
        if event.turn_seq != state.turn_seq + 1:
            raise InvalidEventError(
                f"turn seq mismatch: expected {state.turn_seq + 1}, got {event.turn_seq}"
            )
        return replace(state, event_seq=event.seq, turn_seq=event.turn_seq)

    if isinstance(event, DailyRollUsedEvent):
        player = state.player(event.player_id)
        if state.mode != "daily":
            raise InvalidEventError("daily_roll_used can only apply to daily games")
        if event.day != state.day:
            raise InvalidEventError(
                f"daily roll day mismatch: expected {state.day}, got {event.day}"
            )
        if event.used != player.rolls_used_today + 1:
            raise InvalidEventError(
                f"daily roll used mismatch: expected {player.rolls_used_today + 1}, "
                f"got {event.used}"
            )
        if event.used > event.limit:
            raise InvalidEventError(f"daily roll limit exceeded: {event.used}/{event.limit}")
        updated = replace(player, rolls_used_today=event.used)
        return replace(state.replace_player(updated), event_seq=event.seq)

    if isinstance(event, LandingDispatchedEvent):
        state.player(event.player_id)
        if state.board is None or not 0 <= event.tile_index < len(state.board.tiles):
            raise InvalidEventError(f"landing tile out of range: {event.tile_index}")
        tile = state.board.tiles[event.tile_index]
        if tile.kind != event.tile_kind:
            raise InvalidEventError(
                f"landing tile kind mismatch: expected {tile.kind}, got {event.tile_kind}"
            )
        return replace(state, event_seq=event.seq)

    if isinstance(event, CardDrawnEvent):
        state.player(event.player_id)
        if event.rng_seq != state.rng_seq + 1:
            raise InvalidEventError(
                f"card rng seq mismatch: expected {state.rng_seq + 1}, got {event.rng_seq}"
            )
        return replace(state, event_seq=event.seq, rng_seq=event.rng_seq)

    if isinstance(event, HealthCheckTriggeredEvent):
        player = state.player(event.player_id)
        if player.lap != event.lap:
            raise InvalidEventError(
                f"health check lap mismatch: expected {player.lap}, got {event.lap}"
            )
        return replace(state, event_seq=event.seq)

    if isinstance(event, QuarterlyAffairsTriggeredEvent):
        player = state.player(event.player_id)
        if player.lap != event.lap:
            raise InvalidEventError(
                f"quarterly affairs lap mismatch: expected {player.lap}, got {event.lap}"
            )
        return replace(state, event_seq=event.seq)

    if isinstance(event, PropertyPurchasedEvent):
        if state.property_at(event.tile_index) is not None:
            raise InvalidEventError(f"property already owned: tile {event.tile_index}")
        player = state.player(event.player_id)
        if player.cash < event.price:
            raise InvalidEventError(f"insufficient cash to purchase tile {event.tile_index}")
        updated_player = replace(
            player,
            cash=player.cash - event.price,
            property_tile_indices=(*player.property_tile_indices, event.tile_index),
        )
        purchased_property = PropertyState(
            tile_index=event.tile_index,
            owner_id=event.player_id,
            level=event.level,
            invested=event.invested,
        )
        return replace(
            state.replace_player(updated_player).replace_property(purchased_property),
            event_seq=event.seq,
        )

    if isinstance(event, PropertyUpgradedEvent):
        upgraded_property = state.property_at(event.tile_index)
        if upgraded_property is None:
            raise InvalidEventError(f"property is unowned: tile {event.tile_index}")
        if upgraded_property.owner_id != event.player_id:
            raise InvalidEventError(f"property owner mismatch: tile {event.tile_index}")
        if upgraded_property.mortgaged:
            raise InvalidEventError(f"mortgaged property cannot upgrade: tile {event.tile_index}")
        if upgraded_property.level != event.level_before:
            raise InvalidEventError(
                f"property level mismatch: expected {upgraded_property.level}, "
                f"got {event.level_before}"
            )
        player = state.player(event.player_id)
        if player.cash < event.cost:
            raise InvalidEventError(f"insufficient cash to upgrade tile {event.tile_index}")
        updated_player = replace(player, cash=player.cash - event.cost)
        updated_property = replace(
            upgraded_property,
            level=event.level_after,
            invested=event.invested_after,
        )
        return replace(
            state.replace_player(updated_player).replace_property(updated_property),
            event_seq=event.seq,
        )

    if isinstance(event, RentPaidEvent):
        payer = state.player(event.payer_id)
        owner = state.player(event.owner_id)
        updated_payer = replace(payer, cash=payer.cash - event.amount)
        updated_owner = replace(owner, cash=owner.cash + event.amount)
        return replace(
            state.replace_player(updated_payer).replace_player(updated_owner),
            event_seq=event.seq,
        )

    if isinstance(event, PropertyMortgagedEvent):
        mortgaged_property = state.property_at(event.tile_index)
        if mortgaged_property is None:
            raise InvalidEventError(f"property is unowned: tile {event.tile_index}")
        if mortgaged_property.owner_id != event.player_id:
            raise InvalidEventError(f"property owner mismatch: tile {event.tile_index}")
        if mortgaged_property.mortgaged:
            raise InvalidEventError(f"property already mortgaged: tile {event.tile_index}")
        player = state.player(event.player_id)
        updated_player = replace(player, cash=player.cash + event.amount)
        updated_property = replace(mortgaged_property, mortgaged=True)
        return replace(
            state.replace_player(updated_player).replace_property(updated_property),
            event_seq=event.seq,
        )

    if isinstance(event, PropertyRedeemedEvent):
        redeemed_property = state.property_at(event.tile_index)
        if redeemed_property is None:
            raise InvalidEventError(f"property is unowned: tile {event.tile_index}")
        if redeemed_property.owner_id != event.player_id:
            raise InvalidEventError(f"property owner mismatch: tile {event.tile_index}")
        if not redeemed_property.mortgaged:
            raise InvalidEventError(f"property is not mortgaged: tile {event.tile_index}")
        player = state.player(event.player_id)
        if player.cash < event.cost:
            raise InvalidEventError(f"insufficient cash to redeem tile {event.tile_index}")
        updated_player = replace(player, cash=player.cash - event.cost)
        updated_property = replace(redeemed_property, mortgaged=False)
        return replace(
            state.replace_player(updated_player).replace_property(updated_property),
            event_seq=event.seq,
        )

    if isinstance(event, SalaryPaidEvent):
        player = state.player(event.player_id)
        if event.amount < 0:
            raise InvalidEventError(f"salary cannot be negative: {event.amount}")
        updated = replace(player, cash=player.cash + event.amount)
        return replace(state.replace_player(updated), event_seq=event.seq)

    if isinstance(event, StockPriceAdvancedEvent):
        if event.price <= 0:
            raise InvalidEventError(f"stock price must be positive: {event.price}")
        return replace(
            state,
            event_seq=event.seq,
            stock_prices=_upsert_stock_price(state.stock_prices, event.code, event.price),
        )

    if isinstance(event, StockBoughtEvent):
        player = state.player(event.player_id)
        if event.value <= 0:
            raise InvalidEventError(f"stock buy value must be positive: {event.value}")
        if player.cash < event.value:
            raise InvalidEventError(f"insufficient cash to buy stock {event.code}")
        updated = replace(
            player,
            cash=player.cash - event.value,
            stock_holdings=_add_stock_holding(player.stock_holdings, event.code, event.value),
        )
        return replace(state.replace_player(updated), event_seq=event.seq)

    if isinstance(event, StockSoldEvent):
        player = state.player(event.player_id)
        if event.value <= 0:
            raise InvalidEventError(f"stock sell value must be positive: {event.value}")
        updated_holdings = _subtract_stock_holding(player.stock_holdings, event.code, event.value)
        updated = replace(
            player,
            cash=player.cash + event.value,
            stock_holdings=updated_holdings,
        )
        return replace(state.replace_player(updated), event_seq=event.seq)

    if isinstance(event, LoanOpenedEvent):
        player = state.player(event.player_id)
        if event.principal <= 0:
            raise InvalidEventError(f"loan principal must be positive: {event.principal}")
        updated = replace(
            player,
            cash=player.cash + event.principal,
            loans=(
                *player.loans,
                PlayerLoan(
                    product_key=event.product_key,
                    principal=event.principal,
                    rate_per_lap=event.rate_per_lap,
                ),
            ),
        )
        return replace(state.replace_player(updated), event_seq=event.seq)

    if isinstance(event, LoanPaymentMadeEvent):
        player = state.player(event.player_id)
        if not 0 <= event.loan_index < len(player.loans):
            raise InvalidEventError(f"loan index out of range: {event.loan_index}")
        loan = player.loans[event.loan_index]
        if loan.product_key != event.product_key:
            raise InvalidEventError(
                f"loan product mismatch: expected {loan.product_key}, got {event.product_key}"
            )
        if loan.principal != event.principal_before:
            raise InvalidEventError(
                f"loan principal mismatch: expected {loan.principal}, got {event.principal_before}"
            )
        if event.principal_after != event.principal_before - event.principal_payment:
            raise InvalidEventError("loan principal after does not match principal payment")
        if event.total_payment != event.interest + event.principal_payment:
            raise InvalidEventError("loan total payment does not match interest plus principal")
        if player.cash < event.total_payment:
            raise InvalidEventError(f"insufficient cash to make loan payment {event.product_key}")
        loans = list(player.loans)
        loans[event.loan_index] = replace(loan, principal=event.principal_after)
        updated = replace(player, cash=player.cash - event.total_payment, loans=tuple(loans))
        return replace(state.replace_player(updated), event_seq=event.seq)

    if isinstance(event, VehiclePurchasedEvent):
        player = state.player(event.player_id)
        if event.vehicle_key in player.vehicles:
            raise InvalidEventError(f"vehicle already owned: {event.vehicle_key}")
        if player.cash < event.price:
            raise InvalidEventError(f"insufficient cash to buy vehicle {event.vehicle_key}")
        updated = replace(
            player,
            cash=player.cash - event.price,
            vehicles=(*player.vehicles, event.vehicle_key),
        )
        return replace(state.replace_player(updated), event_seq=event.seq)

    if isinstance(event, VehicleUpkeepPaidEvent):
        player = state.player(event.player_id)
        if event.vehicle_key not in player.vehicles:
            raise InvalidEventError(f"vehicle not owned: {event.vehicle_key}")
        if player.cash < event.amount:
            raise InvalidEventError(f"insufficient cash for vehicle upkeep {event.vehicle_key}")
        updated = replace(player, cash=player.cash - event.amount)
        return replace(state.replace_player(updated), event_seq=event.seq)

    if isinstance(event, InsurancePurchasedEvent):
        player = state.player(event.player_id)
        if event.policy_key in player.insurance_policies:
            raise InvalidEventError(f"insurance already owned: {event.policy_key}")
        if player.cash < event.premium:
            raise InvalidEventError(f"insufficient cash to buy insurance {event.policy_key}")
        updated = replace(
            player,
            cash=player.cash - event.premium,
            insurance_policies=(*player.insurance_policies, event.policy_key),
        )
        return replace(state.replace_player(updated), event_seq=event.seq)

    if isinstance(event, InsurancePremiumPaidEvent):
        player = state.player(event.player_id)
        if event.policy_key not in player.insurance_policies:
            raise InvalidEventError(f"insurance not owned: {event.policy_key}")
        if player.cash < event.premium:
            raise InvalidEventError(f"insufficient cash for insurance premium {event.policy_key}")
        updated = replace(player, cash=player.cash - event.premium)
        return replace(state.replace_player(updated), event_seq=event.seq)

    if isinstance(event, EducationStartedEvent):
        player = state.player(event.player_id)
        if player.education_course_key is not None:
            raise InvalidEventError(f"education already active: {player.education_course_key}")
        if player.cash < event.tuition:
            raise InvalidEventError(f"insufficient cash for education {event.course_key}")
        updated = replace(
            player,
            cash=player.cash - event.tuition,
            education_course_key=event.course_key,
            education_remaining_laps=event.remaining_laps,
        )
        return replace(state.replace_player(updated), event_seq=event.seq)

    if isinstance(event, EducationProgressedEvent):
        player = state.player(event.player_id)
        if player.education_course_key != event.course_key:
            raise InvalidEventError(
                f"education course mismatch: expected {player.education_course_key}, "
                f"got {event.course_key}"
            )
        if player.education_remaining_laps != event.remaining_laps_before:
            raise InvalidEventError(
                f"education laps mismatch: expected {player.education_remaining_laps}, "
                f"got {event.remaining_laps_before}"
            )
        modifiers = player.modifiers
        if event.completed and event.effective and event.salary_multiplier is not None:
            modifiers = (
                *modifiers,
                PlayerModifier(key="salary_multiplier", value=event.salary_multiplier),
            )
        updated = replace(
            player,
            education_course_key=None if event.completed else event.course_key,
            education_remaining_laps=event.remaining_laps_after,
            education_unlocked_tier=(
                event.unlocked_tier
                if event.completed and event.effective and event.unlocked_tier is not None
                else player.education_unlocked_tier
            ),
            modifiers=modifiers,
        )
        return replace(state.replace_player(updated), event_seq=event.seq)

    if isinstance(event, CareerChangedEvent):
        player = state.player(event.player_id)
        if player.occupation_key != event.occupation_key_before:
            raise InvalidEventError(
                f"occupation mismatch: expected {player.occupation_key}, "
                f"got {event.occupation_key_before}"
            )
        updated = replace(
            player,
            occupation_key=event.occupation_key_after,
            monthly_salary=event.monthly_salary_after,
        )
        return replace(state.replace_player(updated), event_seq=event.seq)

    if isinstance(event, HealthCheckResolvedEvent):
        player = state.player(event.player_id)
        if not 1 <= event.risk_roll <= 100:
            raise InvalidEventError(f"health risk roll must be 1..100, got {event.risk_roll}")
        health_after = min(100, max(0, player.health + event.health_delta))
        if health_after != event.health_after:
            raise InvalidEventError(
                f"health mismatch: expected {health_after}, got {event.health_after}"
            )
        updated = replace(player, health=health_after)
        return replace(state.replace_player(updated), event_seq=event.seq)

    if isinstance(event, BidPlacedEvent):
        player = state.player(event.player_id)
        if state.mode != "daily":
            raise InvalidEventError("bid_placed can only apply to daily games")
        if event.day != state.day:
            raise InvalidEventError(f"bid day mismatch: expected {state.day}, got {event.day}")
        if event.bid_amount <= 0:
            raise InvalidEventError(f"bid amount must be positive: {event.bid_amount}")
        if player.cash < event.bid_amount:
            raise InvalidEventError(f"insufficient cash to place bid on tile {event.tile_index}")
        if _property_bid(state, event.player_id, event.tile_index, event.day) is not None:
            raise InvalidEventError(f"bid already exists on tile {event.tile_index}")
        updated_player = replace(
            player,
            cash=player.cash - event.bid_amount,
            frozen_cash=player.frozen_cash + event.bid_amount,
        )
        placed_bid = PropertyBidState(
            tile_index=event.tile_index,
            player_id=event.player_id,
            bid_amount=event.bid_amount,
            day=event.day,
        )
        return replace(
            state.replace_player(updated_player),
            event_seq=event.seq,
            property_bids=(*state.property_bids, placed_bid),
        )

    if isinstance(event, BidRaisedEvent):
        player = state.player(event.player_id)
        raised_bid = _property_bid(state, event.player_id, event.tile_index, event.day)
        if raised_bid is None:
            raise InvalidEventError(f"bid not found on tile {event.tile_index}")
        if raised_bid.bid_amount != event.bid_before:
            raise InvalidEventError(
                f"bid amount mismatch: expected {raised_bid.bid_amount}, got {event.bid_before}"
            )
        if event.bid_after <= event.bid_before:
            raise InvalidEventError("bid_after must be greater than bid_before")
        delta = event.bid_after - event.bid_before
        if player.cash < delta:
            raise InvalidEventError(f"insufficient cash to raise bid on tile {event.tile_index}")
        updated_player = replace(
            player,
            cash=player.cash - delta,
            frozen_cash=player.frozen_cash + delta,
        )
        return replace(
            state.replace_player(updated_player),
            event_seq=event.seq,
            property_bids=_replace_property_bid(
                state.property_bids,
                replace(raised_bid, bid_amount=event.bid_after),
            ),
        )

    if isinstance(event, BidCancelledEvent):
        player = state.player(event.player_id)
        cancelled_bid = _property_bid(state, event.player_id, event.tile_index, event.day)
        if cancelled_bid is None:
            raise InvalidEventError(f"bid not found on tile {event.tile_index}")
        if cancelled_bid.bid_amount != event.bid_amount:
            raise InvalidEventError(
                f"bid amount mismatch: expected {cancelled_bid.bid_amount}, got {event.bid_amount}"
            )
        if player.frozen_cash < event.bid_amount:
            raise InvalidEventError(f"frozen cash underflow for {event.player_id}")
        updated_player = replace(
            player,
            cash=player.cash + event.bid_amount,
            frozen_cash=player.frozen_cash - event.bid_amount,
        )
        return replace(
            state.replace_player(updated_player),
            event_seq=event.seq,
            property_bids=_remove_property_bid(
                state.property_bids,
                event.player_id,
                event.tile_index,
                event.day,
            ),
        )

    if isinstance(event, BidWonEvent):
        player = state.player(event.player_id)
        winning_bid = _property_bid(state, event.player_id, event.tile_index, event.day)
        if winning_bid is None:
            raise InvalidEventError(f"winning bid not found on tile {event.tile_index}")
        if winning_bid.bid_amount != event.bid_amount:
            raise InvalidEventError(
                f"bid amount mismatch: expected {winning_bid.bid_amount}, got {event.bid_amount}"
            )
        if state.property_at(event.tile_index) is not None:
            raise InvalidEventError(f"property already owned: tile {event.tile_index}")
        if player.frozen_cash < event.bid_amount:
            raise InvalidEventError(f"frozen cash underflow for {event.player_id}")
        updated_player = replace(
            player,
            frozen_cash=player.frozen_cash - event.bid_amount,
            property_tile_indices=(*player.property_tile_indices, event.tile_index),
        )
        property_state = PropertyState(
            tile_index=event.tile_index,
            owner_id=event.player_id,
        )
        return replace(
            state.replace_player(updated_player).replace_property(property_state),
            event_seq=event.seq,
            property_bids=_remove_property_bid(
                state.property_bids,
                event.player_id,
                event.tile_index,
                event.day,
            ),
        )

    if isinstance(event, BidLostEvent):
        player = state.player(event.player_id)
        state.player(event.winner_id)
        losing_bid = _property_bid(state, event.player_id, event.tile_index, event.day)
        if losing_bid is None:
            raise InvalidEventError(f"losing bid not found on tile {event.tile_index}")
        if losing_bid.bid_amount != event.bid_amount:
            raise InvalidEventError(
                f"bid amount mismatch: expected {losing_bid.bid_amount}, got {event.bid_amount}"
            )
        if player.frozen_cash < event.bid_amount:
            raise InvalidEventError(f"frozen cash underflow for {event.player_id}")
        updated_player = replace(
            player,
            cash=player.cash + event.bid_amount,
            frozen_cash=player.frozen_cash - event.bid_amount,
        )
        return replace(
            state.replace_player(updated_player),
            event_seq=event.seq,
            property_bids=_remove_property_bid(
                state.property_bids,
                event.player_id,
                event.tile_index,
                event.day,
            ),
        )

    if isinstance(event, StandingOrdersExecutedEvent):
        state.player(event.player_id)
        if state.mode != "daily":
            raise InvalidEventError("standing_orders_executed can only apply to daily games")
        if event.day != state.day:
            raise InvalidEventError(
                f"standing order day mismatch: expected {state.day}, got {event.day}"
            )
        if event.rolls_executed < 0:
            raise InvalidEventError("standing order rolls cannot be negative")
        return replace(state, event_seq=event.seq)

    if isinstance(event, DailySettlementCompletedEvent):
        if state.mode != "daily":
            raise InvalidEventError("daily_settlement_completed can only apply to daily games")
        if event.day_before != state.day:
            raise InvalidEventError(
                f"daily settlement day mismatch: expected {state.day}, got {event.day_before}"
            )
        if event.day_after != event.day_before + 1:
            raise InvalidEventError("daily settlement must advance exactly one day")
        players = tuple(replace(player, rolls_used_today=0) for player in state.players)
        return replace(state, event_seq=event.seq, day=event.day_after, players=players)

    if isinstance(event, TradeOfferInvalidatedEvent):
        offer = _trade_offer(state, event.offer_id)
        if offer is None:
            raise InvalidEventError(f"trade offer not found: {event.offer_id}")
        if event.player_id not in {offer.from_player_id, offer.to_player_id}:
            raise InvalidEventError(
                f"player {event.player_id} is not a participant in offer {event.offer_id}"
            )
        working = state
        if event.cash_refund_player_id is not None:
            player = working.player(event.cash_refund_player_id)
            if player.frozen_cash < event.cash_refund:
                raise InvalidEventError(f"frozen cash underflow for {event.cash_refund_player_id}")
            updated_player = replace(
                player,
                cash=player.cash + event.cash_refund,
                frozen_cash=player.frozen_cash - event.cash_refund,
            )
            working = working.replace_player(updated_player)
        return replace(
            working,
            event_seq=event.seq,
            trade_offers=tuple(
                existing for existing in working.trade_offers if existing.offer_id != event.offer_id
            ),
        )

    if isinstance(event, LoanDefaultedEvent):
        player = state.player(event.player_id)
        if not 0 <= event.loan_index < len(player.loans):
            raise InvalidEventError(f"loan index out of range: {event.loan_index}")
        loan = player.loans[event.loan_index]
        if loan.product_key != event.product_key:
            raise InvalidEventError(
                f"loan product mismatch: expected {loan.product_key}, got {event.product_key}"
            )
        if loan.rate_per_lap != event.rate_before:
            raise InvalidEventError(
                f"loan rate mismatch: expected {loan.rate_per_lap}, got {event.rate_before}"
            )
        if event.default_count_after != player.default_count + 1:
            raise InvalidEventError(
                f"default count mismatch: expected {player.default_count + 1}, "
                f"got {event.default_count_after}"
            )
        loans = list(player.loans)
        loans[event.loan_index] = replace(loan, rate_per_lap=event.rate_after)
        updated = replace(
            player,
            default_count=event.default_count_after,
            loans=tuple(loans),
        )
        return replace(state.replace_player(updated), event_seq=event.seq)

    if isinstance(event, PlayerBlacklistedEvent):
        player = state.player(event.player_id)
        updated = replace(player, is_blacklisted=True)
        return replace(state.replace_player(updated), event_seq=event.seq)

    if isinstance(event, StockLiquidatedEvent):
        player = state.player(event.player_id)
        holdings = _subtract_stock_holding(player.stock_holdings, event.code, event.value)
        updated = replace(player, cash=player.cash + event.value, stock_holdings=holdings)
        return replace(state.replace_player(updated), event_seq=event.seq)

    if isinstance(event, VehicleLiquidatedEvent):
        player = state.player(event.player_id)
        if event.vehicle_key not in player.vehicles:
            raise InvalidEventError(f"vehicle not owned: {event.vehicle_key}")
        vehicles = list(player.vehicles)
        vehicles.remove(event.vehicle_key)
        updated = replace(
            player,
            cash=player.cash + event.amount,
            vehicles=tuple(vehicles),
        )
        return replace(state.replace_player(updated), event_seq=event.seq)

    if isinstance(event, PropertySoldToBankEvent):
        sold_property = state.property_at(event.tile_index)
        if sold_property is None:
            raise InvalidEventError(f"property is unowned: tile {event.tile_index}")
        if sold_property.owner_id != event.player_id:
            raise InvalidEventError(f"property owner mismatch: tile {event.tile_index}")
        player = state.player(event.player_id)
        updated_player = replace(
            player,
            cash=player.cash + event.amount,
            property_tile_indices=tuple(
                tile for tile in player.property_tile_indices if tile != event.tile_index
            ),
        )
        return replace(
            state.replace_player(updated_player),
            event_seq=event.seq,
            properties=tuple(
                property_state
                for property_state in state.properties
                if property_state.tile_index != event.tile_index
            ),
        )

    if isinstance(event, FamilyBailoutAppliedEvent):
        player = state.player(event.player_id)
        if event.amount <= 0:
            raise InvalidEventError("family bailout amount must be positive")
        updated = replace(player, cash=player.cash + event.amount)
        return replace(state.replace_player(updated), event_seq=event.seq)

    if isinstance(event, PrivateLoanRescueEvent):
        borrower = state.player(event.borrower_id)
        lender = state.player(event.lender_id)
        if event.amount <= 0:
            raise InvalidEventError("private loan rescue amount must be positive")
        if lender.cash < event.amount:
            raise InvalidEventError(f"insufficient lender cash: {event.lender_id}")
        updated_borrower = replace(
            borrower,
            cash=borrower.cash + event.amount,
            loans=(
                *borrower.loans,
                PlayerLoan(
                    product_key="finance_private_loan",
                    principal=event.amount,
                    rate_per_lap=event.rate_per_lap,
                ),
            ),
        )
        updated_lender = replace(lender, cash=lender.cash - event.amount)
        return replace(
            state.replace_player(updated_borrower).replace_player(updated_lender),
            event_seq=event.seq,
        )

    if isinstance(event, PlayerBankruptedEvent):
        player = state.player(event.player_id)
        record = BankruptcyRecord(
            player_id=event.player_id,
            day=event.day,
            net_worth_before=event.net_worth_before,
            counts_for_end_condition=event.counts_for_end_condition,
            reason=event.reason,
        )
        updated_player = replace(
            player,
            cash=0,
            frozen_cash=0,
            is_bankrupt=event.counts_for_end_condition,
            has_quit=not event.counts_for_end_condition,
            stock_holdings=(),
            property_tile_indices=(),
            loans=(),
            vehicles=(),
            confinement=None,
            alliance_id=None,
        )
        return replace(
            state.replace_player(updated_player),
            event_seq=event.seq,
            properties=tuple(
                property_state
                for property_state in state.properties
                if property_state.owner_id != event.player_id
            ),
            property_bids=tuple(
                bid for bid in state.property_bids if bid.player_id != event.player_id
            ),
            trade_offers=tuple(
                offer
                for offer in state.trade_offers
                if event.player_id not in {offer.from_player_id, offer.to_player_id}
            ),
            bankruptcy_records=(*state.bankruptcy_records, record),
        )

    if isinstance(event, BankruptcyThresholdReachedEvent):
        count = sum(1 for record in state.bankruptcy_records if record.counts_for_end_condition)
        if count != event.bankrupt_count:
            raise InvalidEventError(
                f"bankrupt count mismatch: expected {count}, got {event.bankrupt_count}"
            )
        if count < event.threshold:
            raise InvalidEventError("bankruptcy threshold event emitted before threshold reached")
        return replace(state, event_seq=event.seq, phase="finished")

    if isinstance(event, PlayerConfinedEvent):
        player = state.player(event.player_id)
        if event.remaining_turns <= 0:
            raise InvalidEventError("confinement remaining turns must be positive")
        updated = replace(
            player,
            confinement=ConfinementState(
                kind=event.kind,
                remaining_turns=event.remaining_turns,
                reason=event.reason,
            ),
        )
        return replace(state.replace_player(updated), event_seq=event.seq)

    if isinstance(event, ConfinementAdvancedEvent):
        player = state.player(event.player_id)
        if player.confinement is None:
            raise InvalidEventError(f"player is not confined: {event.player_id}")
        if player.confinement.kind != event.kind:
            raise InvalidEventError(
                f"confinement kind mismatch: expected {player.confinement.kind}, got {event.kind}"
            )
        if player.confinement.remaining_turns != event.remaining_before:
            raise InvalidEventError(
                f"confinement turns mismatch: expected {player.confinement.remaining_turns}, "
                f"got {event.remaining_before}"
            )
        if event.remaining_after < 0:
            raise InvalidEventError("confinement remaining turns cannot be negative")
        confinement = replace(player.confinement, remaining_turns=event.remaining_after)
        updated = replace(player, confinement=confinement)
        return replace(state.replace_player(updated), event_seq=event.seq)

    if isinstance(event, ConfinementReleasedEvent):
        player = state.player(event.player_id)
        if player.confinement is None:
            raise InvalidEventError(f"player is not confined: {event.player_id}")
        if player.confinement.kind != event.kind:
            raise InvalidEventError(
                f"confinement kind mismatch: expected {player.confinement.kind}, got {event.kind}"
            )
        updated = replace(player, confinement=None)
        return replace(state.replace_player(updated), event_seq=event.seq)

    if isinstance(event, ConfinementReleasePaidEvent):
        player = state.player(event.player_id)
        if player.confinement is None:
            raise InvalidEventError(f"player is not confined: {event.player_id}")
        if player.confinement.kind != event.kind:
            raise InvalidEventError(
                f"confinement kind mismatch: expected {player.confinement.kind}, got {event.kind}"
            )
        if player.cash < event.amount:
            raise InvalidEventError(f"insufficient cash for confinement release {event.kind}")
        updated = replace(player, cash=player.cash - event.amount, confinement=None)
        return replace(state.replace_player(updated), event_seq=event.seq)

    if isinstance(event, AllianceProposedEvent):
        state.player(event.from_player_id)
        state.player(event.to_player_id)
        if _alliance_proposal(state, event.proposal_id) is not None:
            raise InvalidEventError(f"alliance proposal already exists: {event.proposal_id}")
        proposal = AllianceProposalState(
            id=event.proposal_id,
            from_player_id=event.from_player_id,
            to_player_id=event.to_player_id,
            tier=event.tier,
            day=event.day,
            target_alliance_id=event.target_alliance_id,
            formation_style=event.formation_style,
        )
        return replace(
            state,
            event_seq=event.seq,
            alliance_proposals=(*state.alliance_proposals, proposal),
        )

    if isinstance(event, AllianceFormedEvent):
        if _alliance(state, event.alliance_id) is not None:
            raise InvalidEventError(f"alliance already exists: {event.alliance_id}")
        working = state
        member_states: list[AllianceMemberState] = []
        for player_id in event.member_ids:
            player = working.player(player_id)
            if player.alliance_id is not None:
                raise InvalidEventError(f"player already in alliance: {player_id}")
            if player.cash < event.formation_cost_per_member:
                raise InvalidEventError(f"insufficient cash to form alliance: {player_id}")
            contribution = event.pool_contribution_per_member
            updated = replace(
                player,
                cash=player.cash - event.formation_cost_per_member,
                alliance_id=event.alliance_id,
                relationship_changes=player.relationship_changes + 1,
            )
            working = working.replace_player(updated)
            member_states.append(AllianceMemberState(player_id=player_id, contributed=contribution))
        alliance = AllianceState(
            id=event.alliance_id,
            tier=event.tier,
            member_ids=event.member_ids,
            pool_balance=event.pool_contribution_per_member * len(event.member_ids),
            member_states=tuple(member_states),
            core_partner_ids=event.core_partner_ids,
            name=event.name,
        )
        return replace(
            working,
            event_seq=event.seq,
            alliances=(*working.alliances, alliance),
        )

    if isinstance(event, AllianceProposalResolvedEvent):
        existing_proposal = _alliance_proposal(state, event.proposal_id)
        if existing_proposal is None:
            raise InvalidEventError(f"alliance proposal not found: {event.proposal_id}")
        return replace(
            state,
            event_seq=event.seq,
            alliance_proposals=tuple(
                existing
                for existing in state.alliance_proposals
                if existing.id != event.proposal_id
            ),
        )

    if isinstance(event, AllianceMemberJoinedEvent):
        alliance = _active_alliance(state, event.alliance_id)
        player = state.player(event.player_id)
        if event.player_id in alliance.member_ids:
            raise InvalidEventError(f"player already in alliance: {event.player_id}")
        if player.alliance_id is not None:
            raise InvalidEventError(f"player already in alliance: {event.player_id}")
        if player.cash < event.formation_cost:
            raise InvalidEventError(f"insufficient cash to join alliance: {event.player_id}")
        updated_player = replace(
            player,
            cash=player.cash - event.formation_cost,
            alliance_id=event.alliance_id,
            relationship_changes=player.relationship_changes + 1,
        )
        updated_alliance = replace(
            alliance,
            member_ids=(*alliance.member_ids, event.player_id),
            pool_balance=alliance.pool_balance + event.pool_contribution,
            member_states=(
                *alliance.member_states,
                AllianceMemberState(
                    player_id=event.player_id,
                    contributed=event.pool_contribution,
                ),
            ),
        )
        return replace(
            state.replace_player(updated_player),
            event_seq=event.seq,
            alliances=_replace_alliance(state.alliances, updated_alliance),
        )

    if isinstance(event, AllianceMemberLeftEvent):
        alliance = _active_alliance(state, event.alliance_id)
        if event.player_id not in alliance.member_ids:
            raise InvalidEventError(f"player is not in alliance: {event.player_id}")
        player = state.player(event.player_id)
        updated_player = replace(
            player,
            alliance_id=None,
            relationship_changes=player.relationship_changes + 1,
        )
        updated_alliance = replace(
            alliance,
            member_ids=tuple(member for member in alliance.member_ids if member != event.player_id),
            member_states=tuple(
                member for member in alliance.member_states if member.player_id != event.player_id
            ),
        )
        return replace(
            state.replace_player(updated_player),
            event_seq=event.seq,
            alliances=_replace_alliance(state.alliances, updated_alliance),
        )

    if isinstance(event, AllianceTierChangedEvent):
        alliance = _active_alliance(state, event.alliance_id)
        if alliance.tier != event.tier_before:
            raise InvalidEventError(
                f"alliance tier mismatch: expected {alliance.tier}, got {event.tier_before}"
            )
        updated_alliance = replace(alliance, tier=event.tier_after)
        return replace(
            state,
            event_seq=event.seq,
            alliances=_replace_alliance(state.alliances, updated_alliance),
        )

    if isinstance(event, AllianceDissolvedEvent):
        alliance = _active_alliance(state, event.alliance_id)
        working = state
        for player_id in alliance.member_ids:
            player = working.player(player_id)
            working = working.replace_player(replace(player, alliance_id=None))
        updated_alliance = replace(alliance, active=False, member_ids=())
        return replace(
            working,
            event_seq=event.seq,
            alliances=_replace_alliance(working.alliances, updated_alliance),
        )

    if isinstance(event, AlliancePoolContributedEvent):
        alliance = _active_alliance(state, event.alliance_id)
        player = state.player(event.player_id)
        if event.player_id not in alliance.member_ids:
            raise InvalidEventError(f"player is not in alliance: {event.player_id}")
        if player.cash < event.amount:
            raise InvalidEventError(
                f"insufficient cash for alliance contribution: {event.player_id}"
            )
        updated_player = replace(player, cash=player.cash - event.amount)
        updated_alliance = replace(
            alliance,
            pool_balance=alliance.pool_balance + event.amount,
            member_states=_add_member_contribution(
                alliance.member_states,
                event.player_id,
                event.amount,
            ),
        )
        return replace(
            state.replace_player(updated_player),
            event_seq=event.seq,
            alliances=_replace_alliance(state.alliances, updated_alliance),
        )

    if isinstance(event, AlliancePoolPaidEvent):
        alliance = _active_alliance(state, event.alliance_id)
        if alliance.pool_balance < event.amount:
            raise InvalidEventError(f"insufficient alliance pool: {event.alliance_id}")
        updated_alliance = replace(
            alliance,
            pool_balance=alliance.pool_balance - event.amount,
        )
        return replace(
            state,
            event_seq=event.seq,
            alliances=_replace_alliance(state.alliances, updated_alliance),
        )

    if isinstance(event, AlliancePoolDistributedEvent):
        alliance = _active_alliance(state, event.alliance_id)
        payout_total = sum(amount for _, amount in event.payouts)
        if payout_total != alliance.pool_balance:
            raise InvalidEventError(
                f"alliance payout total mismatch: expected {alliance.pool_balance}, "
                f"got {payout_total}"
            )
        working = state
        for player_id, amount in event.payouts:
            player = working.player(player_id)
            if player_id not in alliance.member_ids:
                raise InvalidEventError(f"player is not in alliance: {player_id}")
            working = working.replace_player(replace(player, cash=player.cash + amount))
        updated_alliance = replace(alliance, pool_balance=0)
        return replace(
            working,
            event_seq=event.seq,
            alliances=_replace_alliance(working.alliances, updated_alliance),
        )

    if isinstance(event, AllianceBailoutAttemptedEvent):
        alliance = _active_alliance(state, event.alliance_id)
        if event.player_id not in alliance.member_ids:
            raise InvalidEventError(f"player is not in alliance: {event.player_id}")
        return replace(state, event_seq=event.seq)

    if isinstance(event, AllianceBailoutSucceededEvent):
        alliance = _active_alliance(state, event.alliance_id)
        player = state.player(event.player_id)
        if event.player_id not in alliance.member_ids:
            raise InvalidEventError(f"player is not in alliance: {event.player_id}")
        if alliance.pool_balance < event.pool_paid:
            raise InvalidEventError(f"insufficient alliance pool: {event.alliance_id}")
        working = state
        total_paid = event.pool_paid
        for payer_id, amount in event.member_charges:
            payer = working.player(payer_id)
            if payer_id not in alliance.member_ids or payer_id == event.player_id:
                raise InvalidEventError(f"invalid bailout payer: {payer_id}")
            if payer.cash < amount:
                raise InvalidEventError(f"insufficient cash for bailout payer: {payer_id}")
            working = working.replace_player(replace(payer, cash=payer.cash - amount))
            total_paid += amount
        updated_player = replace(player, cash=player.cash + total_paid)
        updated_alliance = replace(alliance, pool_balance=alliance.pool_balance - event.pool_paid)
        return replace(
            working.replace_player(updated_player),
            event_seq=event.seq,
            alliances=_replace_alliance(working.alliances, updated_alliance),
        )

    if isinstance(event, AllianceRuinedEvent):
        alliance = _active_alliance(state, event.alliance_id)
        working = state
        for player_id in alliance.member_ids:
            player = working.player(player_id)
            penalty = round(max(0, player.cash) * event.penalty_ratio)
            working = working.replace_player(replace(player, cash=player.cash - penalty))
        return replace(working, event_seq=event.seq)

    assert_never(event)


def apply_events(state: GameState, events: list[Event] | tuple[Event, ...]) -> GameState:
    next_state = state
    for event in events:
        next_state = apply_event(next_state, event)
    return next_state


def replay_events(initial_state: GameState, events: list[Event] | tuple[Event, ...]) -> GameState:
    return apply_events(initial_state, events)


def state_digest(state: GameState) -> str:
    payload = _canonical_data(state)
    return json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _validate_next_seq(state: GameState, seq: int) -> None:
    expected = state.event_seq + 1
    if seq != expected:
        raise InvalidEventError(f"event seq must be {expected}, got {seq}")


def _canonical_data(value: object) -> object:
    if is_dataclass(value) and not isinstance(value, type):
        return _canonical_data(asdict(value))
    if isinstance(value, dict):
        return {key: _canonical_data(item) for key, item in sorted(value.items())}
    if isinstance(value, tuple | list):
        return [_canonical_data(item) for item in value]
    return value


def _upsert_stock_price(
    prices: tuple[StockPrice, ...],
    code: str,
    price: float,
) -> tuple[StockPrice, ...]:
    updated = StockPrice(code=code, price=price)
    found = False
    result: list[StockPrice] = []
    for existing in prices:
        if existing.code == code:
            result.append(updated)
            found = True
        else:
            result.append(existing)
    if not found:
        result.append(updated)
    return tuple(result)


def _add_stock_holding(
    holdings: tuple[StockHolding, ...],
    code: str,
    value: int,
) -> tuple[StockHolding, ...]:
    result: list[StockHolding] = []
    found = False
    for holding in holdings:
        if holding.code == code:
            result.append(replace(holding, value=holding.value + value))
            found = True
        else:
            result.append(holding)
    if not found:
        result.append(StockHolding(code=code, value=value))
    return tuple(result)


def _subtract_stock_holding(
    holdings: tuple[StockHolding, ...],
    code: str,
    value: int,
) -> tuple[StockHolding, ...]:
    result: list[StockHolding] = []
    found = False
    for holding in holdings:
        if holding.code == code:
            found = True
            if holding.value < value:
                raise InvalidEventError(f"cannot sell more stock than held: {code}")
            remaining = holding.value - value
            if remaining > 0:
                result.append(replace(holding, value=remaining))
        else:
            result.append(holding)
    if not found:
        raise InvalidEventError(f"stock holding not found: {code}")
    return tuple(result)


def _property_bid(
    state: GameState,
    player_id: str,
    tile_index: int,
    day: int,
) -> PropertyBidState | None:
    for bid in state.property_bids:
        if bid.player_id == player_id and bid.tile_index == tile_index and bid.day == day:
            return bid
    return None


def _replace_property_bid(
    bids: tuple[PropertyBidState, ...],
    updated_bid: PropertyBidState,
) -> tuple[PropertyBidState, ...]:
    return tuple(
        updated_bid
        if bid.player_id == updated_bid.player_id
        and bid.tile_index == updated_bid.tile_index
        and bid.day == updated_bid.day
        else bid
        for bid in bids
    )


def _remove_property_bid(
    bids: tuple[PropertyBidState, ...],
    player_id: str,
    tile_index: int,
    day: int,
) -> tuple[PropertyBidState, ...]:
    return tuple(
        bid
        for bid in bids
        if not (bid.player_id == player_id and bid.tile_index == tile_index and bid.day == day)
    )


def _trade_offer(state: GameState, offer_id: str) -> TradeOfferState | None:
    for offer in state.trade_offers:
        if offer.offer_id == offer_id:
            return offer
    return None


def _alliance(state: GameState, alliance_id: str) -> AllianceState | None:
    for alliance in state.alliances:
        if alliance.id == alliance_id:
            return alliance
    return None


def _active_alliance(state: GameState, alliance_id: str) -> AllianceState:
    alliance = _alliance(state, alliance_id)
    if alliance is None or not alliance.active:
        raise InvalidEventError(f"active alliance not found: {alliance_id}")
    return alliance


def _replace_alliance(
    alliances: tuple[AllianceState, ...],
    updated_alliance: AllianceState,
) -> tuple[AllianceState, ...]:
    return tuple(
        updated_alliance if alliance.id == updated_alliance.id else alliance
        for alliance in alliances
    )


def _alliance_proposal(state: GameState, proposal_id: str) -> AllianceProposalState | None:
    for proposal in state.alliance_proposals:
        if proposal.id == proposal_id:
            return proposal
    return None


def _add_member_contribution(
    members: tuple[AllianceMemberState, ...],
    player_id: str,
    amount: int,
) -> tuple[AllianceMemberState, ...]:
    found = False
    updated_members: list[AllianceMemberState] = []
    for member in members:
        if member.player_id == player_id:
            updated_members.append(replace(member, contributed=member.contributed + amount))
            found = True
        else:
            updated_members.append(member)
    if not found:
        raise InvalidEventError(f"alliance member not found: {player_id}")
    return tuple(updated_members)
