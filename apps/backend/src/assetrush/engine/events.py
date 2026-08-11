"""事件溯源事件型別。"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from assetrush.engine.state import (
    AllianceTier,
    ConfinementKind,
    GamePhase,
    ModifierValue,
    Money,
    TileKind,
)


@dataclass(frozen=True, slots=True)
class CashAdjustedEvent:
    type: Literal["cash_adjusted"]
    player_id: str
    delta: Money
    balance_after: Money
    reason: str | None = None
    seq: int = 0


@dataclass(frozen=True, slots=True)
class TreasuryAdjustedEvent:
    type: Literal["treasury_adjusted"]
    delta: Money
    balance_after: Money
    reason: str | None = None
    seq: int = 0


@dataclass(frozen=True, slots=True)
class PlayerMovedEvent:
    type: Literal["player_moved"]
    player_id: str
    position_before: int
    position_after: int
    lap_before: int
    lap_after: int
    reason: str | None = None
    seq: int = 0


@dataclass(frozen=True, slots=True)
class PlayerModifierAddedEvent:
    type: Literal["player_modifier_added"]
    player_id: str
    key: str
    value: ModifierValue
    laps: int | None = None
    reason: str | None = None
    seq: int = 0


@dataclass(frozen=True, slots=True)
class PendingEffectAddedEvent:
    type: Literal["pending_effect_added"]
    player_id: str
    effect_type: str
    reason: str | None = None
    seq: int = 0


@dataclass(frozen=True, slots=True)
class PhaseAdvancedEvent:
    type: Literal["phase_advanced"]
    phase_before: GamePhase
    phase_after: GamePhase
    reason: str | None = None
    seq: int = 0


@dataclass(frozen=True, slots=True)
class DiceRolledEvent:
    type: Literal["dice_rolled"]
    player_id: str
    result: int
    turn_seq: int
    proof_input: str
    seq: int = 0


@dataclass(frozen=True, slots=True)
class DailyRollUsedEvent:
    type: Literal["daily_roll_used"]
    player_id: str
    day: int
    used: int
    limit: int
    seq: int = 0


@dataclass(frozen=True, slots=True)
class LandingDispatchedEvent:
    type: Literal["landing_dispatched"]
    player_id: str
    tile_index: int
    tile_kind: TileKind
    seq: int = 0


@dataclass(frozen=True, slots=True)
class CardDrawnEvent:
    type: Literal["card_drawn"]
    player_id: str
    deck: Literal["opportunity", "fate"]
    card_id: str
    card_name: str
    rng_seq: int
    seq: int = 0


@dataclass(frozen=True, slots=True)
class HealthCheckTriggeredEvent:
    type: Literal["health_check_triggered"]
    player_id: str
    lap: int
    seq: int = 0


@dataclass(frozen=True, slots=True)
class QuarterlyAffairsTriggeredEvent:
    type: Literal["quarterly_affairs_triggered"]
    player_id: str
    lap: int
    seq: int = 0


@dataclass(frozen=True, slots=True)
class PropertyPurchasedEvent:
    type: Literal["property_purchased"]
    player_id: str
    tile_index: int
    price: Money
    level: int = 0
    invested: Money = 0
    seq: int = 0


@dataclass(frozen=True, slots=True)
class PropertyUpgradedEvent:
    type: Literal["property_upgraded"]
    player_id: str
    tile_index: int
    level_before: int
    level_after: int
    cost: Money
    invested_after: Money
    seq: int = 0


@dataclass(frozen=True, slots=True)
class RentPaidEvent:
    type: Literal["rent_paid"]
    payer_id: str
    owner_id: str
    tile_index: int
    amount: Money
    monopoly_applied: bool
    seq: int = 0


@dataclass(frozen=True, slots=True)
class PropertyMortgagedEvent:
    type: Literal["property_mortgaged"]
    player_id: str
    tile_index: int
    amount: Money
    seq: int = 0


@dataclass(frozen=True, slots=True)
class PropertyRedeemedEvent:
    type: Literal["property_redeemed"]
    player_id: str
    tile_index: int
    cost: Money
    seq: int = 0


@dataclass(frozen=True, slots=True)
class SalaryPaidEvent:
    type: Literal["salary_paid"]
    player_id: str
    amount: Money
    seq: int = 0


@dataclass(frozen=True, slots=True)
class StockPriceAdvancedEvent:
    type: Literal["stock_price_advanced"]
    code: str
    price: float
    lap: int
    seq: int = 0


@dataclass(frozen=True, slots=True)
class StockBoughtEvent:
    type: Literal["stock_bought"]
    player_id: str
    code: str
    value: Money
    price: float
    seq: int = 0


@dataclass(frozen=True, slots=True)
class StockSoldEvent:
    type: Literal["stock_sold"]
    player_id: str
    code: str
    value: Money
    price: float
    seq: int = 0


@dataclass(frozen=True, slots=True)
class LoanOpenedEvent:
    type: Literal["loan_opened"]
    player_id: str
    product_key: str
    principal: Money
    rate_per_lap: float
    seq: int = 0


@dataclass(frozen=True, slots=True)
class LoanPaymentMadeEvent:
    type: Literal["loan_payment_made"]
    player_id: str
    loan_index: int
    product_key: str
    principal_before: Money
    interest: Money
    principal_payment: Money
    total_payment: Money
    principal_after: Money
    seq: int = 0


@dataclass(frozen=True, slots=True)
class VehiclePurchasedEvent:
    type: Literal["vehicle_purchased"]
    player_id: str
    vehicle_key: str
    price: Money
    seq: int = 0


@dataclass(frozen=True, slots=True)
class VehicleUpkeepPaidEvent:
    type: Literal["vehicle_upkeep_paid"]
    player_id: str
    vehicle_key: str
    amount: Money
    seq: int = 0


@dataclass(frozen=True, slots=True)
class InsurancePurchasedEvent:
    type: Literal["insurance_purchased"]
    player_id: str
    policy_key: str
    premium: Money
    seq: int = 0


@dataclass(frozen=True, slots=True)
class InsurancePremiumPaidEvent:
    type: Literal["insurance_premium_paid"]
    player_id: str
    policy_key: str
    premium: Money
    seq: int = 0


@dataclass(frozen=True, slots=True)
class EducationStartedEvent:
    type: Literal["education_started"]
    player_id: str
    course_key: str
    tuition: Money
    remaining_laps: int
    seq: int = 0


@dataclass(frozen=True, slots=True)
class EducationProgressedEvent:
    type: Literal["education_progressed"]
    player_id: str
    course_key: str
    remaining_laps_before: int
    remaining_laps_after: int
    completed: bool
    effective: bool
    unlocked_tier: int | None = None
    salary_multiplier: float | None = None
    seq: int = 0


@dataclass(frozen=True, slots=True)
class CareerChangedEvent:
    type: Literal["career_changed"]
    player_id: str
    occupation_key_before: str | None
    occupation_key_after: str
    monthly_salary_after: Money
    seq: int = 0


@dataclass(frozen=True, slots=True)
class HealthCheckResolvedEvent:
    type: Literal["health_check_resolved"]
    player_id: str
    risk_roll: int
    risk_threshold: int
    health_delta: int
    health_after: int
    seq: int = 0


@dataclass(frozen=True, slots=True)
class BidPlacedEvent:
    type: Literal["bid_placed"]
    player_id: str
    tile_index: int
    bid_amount: Money
    day: int
    seq: int = 0


@dataclass(frozen=True, slots=True)
class BidRaisedEvent:
    type: Literal["bid_raised"]
    player_id: str
    tile_index: int
    bid_before: Money
    bid_after: Money
    day: int
    seq: int = 0


@dataclass(frozen=True, slots=True)
class BidCancelledEvent:
    type: Literal["bid_cancelled"]
    player_id: str
    tile_index: int
    bid_amount: Money
    day: int
    reason: str | None = None
    seq: int = 0


@dataclass(frozen=True, slots=True)
class BidWonEvent:
    type: Literal["bid_won"]
    player_id: str
    tile_index: int
    bid_amount: Money
    base_price: Money
    day: int
    seq: int = 0


@dataclass(frozen=True, slots=True)
class BidLostEvent:
    type: Literal["bid_lost"]
    player_id: str
    tile_index: int
    bid_amount: Money
    winner_id: str
    day: int
    seq: int = 0


@dataclass(frozen=True, slots=True)
class StandingOrdersExecutedEvent:
    type: Literal["standing_orders_executed"]
    player_id: str
    day: int
    rolls_executed: int
    seq: int = 0


@dataclass(frozen=True, slots=True)
class DailySettlementCompletedEvent:
    type: Literal["daily_settlement_completed"]
    day_before: int
    day_after: int
    seq: int = 0


@dataclass(frozen=True, slots=True)
class TradeOfferInvalidatedEvent:
    type: Literal["trade_offer_invalidated"]
    offer_id: str
    player_id: str
    cash_refund_player_id: str | None = None
    cash_refund: Money = 0
    reason: str | None = None
    seq: int = 0


@dataclass(frozen=True, slots=True)
class TurnSkippedEvent:
    type: Literal["turn_skipped"]
    player_id: str
    turn_seq: int
    reason: str
    seq: int = 0


@dataclass(frozen=True, slots=True)
class LoanDefaultedEvent:
    type: Literal["loan_defaulted"]
    player_id: str
    loan_index: int
    product_key: str
    default_count_after: int
    rate_before: float
    rate_after: float
    seq: int = 0


@dataclass(frozen=True, slots=True)
class PlayerBlacklistedEvent:
    type: Literal["player_blacklisted"]
    player_id: str
    seq: int = 0


@dataclass(frozen=True, slots=True)
class StockLiquidatedEvent:
    type: Literal["stock_liquidated"]
    player_id: str
    code: str
    value: Money
    seq: int = 0


@dataclass(frozen=True, slots=True)
class VehicleLiquidatedEvent:
    type: Literal["vehicle_liquidated"]
    player_id: str
    vehicle_key: str
    amount: Money
    seq: int = 0


@dataclass(frozen=True, slots=True)
class PropertySoldToBankEvent:
    type: Literal["property_sold_to_bank"]
    player_id: str
    tile_index: int
    amount: Money
    seq: int = 0


@dataclass(frozen=True, slots=True)
class FamilyBailoutAppliedEvent:
    type: Literal["family_bailout_applied"]
    player_id: str
    amount: Money
    seq: int = 0


@dataclass(frozen=True, slots=True)
class PrivateLoanRescueEvent:
    type: Literal["private_loan_rescue"]
    borrower_id: str
    lender_id: str
    amount: Money
    rate_per_lap: float
    seq: int = 0


@dataclass(frozen=True, slots=True)
class PlayerBankruptedEvent:
    type: Literal["player_bankrupted"]
    player_id: str
    day: int
    net_worth_before: Money
    counts_for_end_condition: bool
    reason: str
    seq: int = 0


@dataclass(frozen=True, slots=True)
class BankruptcyThresholdReachedEvent:
    type: Literal["bankruptcy_threshold_reached"]
    bankrupt_count: int
    threshold: int
    seq: int = 0


@dataclass(frozen=True, slots=True)
class PlayerConfinedEvent:
    type: Literal["player_confined"]
    player_id: str
    kind: ConfinementKind
    remaining_turns: int
    reason: str | None = None
    seq: int = 0


@dataclass(frozen=True, slots=True)
class ConfinementAdvancedEvent:
    type: Literal["confinement_advanced"]
    player_id: str
    kind: ConfinementKind
    remaining_before: int
    remaining_after: int
    seq: int = 0


@dataclass(frozen=True, slots=True)
class ConfinementReleasedEvent:
    type: Literal["confinement_released"]
    player_id: str
    kind: ConfinementKind
    reason: str
    seq: int = 0


@dataclass(frozen=True, slots=True)
class ConfinementReleasePaidEvent:
    type: Literal["confinement_release_paid"]
    player_id: str
    kind: ConfinementKind
    amount: Money
    reason: str
    seq: int = 0


@dataclass(frozen=True, slots=True)
class AllianceProposedEvent:
    type: Literal["alliance_proposed"]
    proposal_id: str
    from_player_id: str
    to_player_id: str
    tier: AllianceTier
    day: int
    target_alliance_id: str | None = None
    formation_style: str | None = None
    seq: int = 0


@dataclass(frozen=True, slots=True)
class AllianceFormedEvent:
    type: Literal["alliance_formed"]
    alliance_id: str
    tier: AllianceTier
    member_ids: tuple[str, ...]
    formation_cost_per_member: Money
    pool_contribution_per_member: Money
    core_partner_ids: tuple[str, str] | None = None
    name: str | None = None
    seq: int = 0


@dataclass(frozen=True, slots=True)
class AllianceProposalResolvedEvent:
    type: Literal["alliance_proposal_resolved"]
    proposal_id: str
    accepted: bool
    seq: int = 0


@dataclass(frozen=True, slots=True)
class AllianceMemberJoinedEvent:
    type: Literal["alliance_member_joined"]
    alliance_id: str
    player_id: str
    formation_cost: Money
    pool_contribution: Money
    seq: int = 0


@dataclass(frozen=True, slots=True)
class AllianceMemberLeftEvent:
    type: Literal["alliance_member_left"]
    alliance_id: str
    player_id: str
    reason: str
    seq: int = 0


@dataclass(frozen=True, slots=True)
class AllianceTierChangedEvent:
    type: Literal["alliance_tier_changed"]
    alliance_id: str
    tier_before: AllianceTier
    tier_after: AllianceTier
    seq: int = 0


@dataclass(frozen=True, slots=True)
class AllianceDissolvedEvent:
    type: Literal["alliance_dissolved"]
    alliance_id: str
    reason: str
    seq: int = 0


@dataclass(frozen=True, slots=True)
class AlliancePoolContributedEvent:
    type: Literal["alliance_pool_contributed"]
    alliance_id: str
    player_id: str
    amount: Money
    reason: str
    seq: int = 0


@dataclass(frozen=True, slots=True)
class AlliancePoolPaidEvent:
    type: Literal["alliance_pool_paid"]
    alliance_id: str
    amount: Money
    reason: str
    seq: int = 0


@dataclass(frozen=True, slots=True)
class AlliancePoolDistributedEvent:
    type: Literal["alliance_pool_distributed"]
    alliance_id: str
    payouts: tuple[tuple[str, Money], ...]
    seq: int = 0


@dataclass(frozen=True, slots=True)
class AllianceBailoutAttemptedEvent:
    type: Literal["alliance_bailout_attempted"]
    alliance_id: str
    player_id: str
    shortfall: Money
    seq: int = 0


@dataclass(frozen=True, slots=True)
class AllianceBailoutSucceededEvent:
    type: Literal["alliance_bailout_succeeded"]
    alliance_id: str
    player_id: str
    pool_paid: Money
    member_charges: tuple[tuple[str, Money], ...]
    seq: int = 0


@dataclass(frozen=True, slots=True)
class AllianceRuinedEvent:
    type: Literal["alliance_ruined"]
    alliance_id: str
    failed_player_id: str
    penalty_ratio: float
    seq: int = 0


Event = (
    CashAdjustedEvent
    | TreasuryAdjustedEvent
    | PlayerMovedEvent
    | PlayerModifierAddedEvent
    | PendingEffectAddedEvent
    | PhaseAdvancedEvent
    | DiceRolledEvent
    | DailyRollUsedEvent
    | LandingDispatchedEvent
    | CardDrawnEvent
    | HealthCheckTriggeredEvent
    | QuarterlyAffairsTriggeredEvent
    | PropertyPurchasedEvent
    | PropertyUpgradedEvent
    | RentPaidEvent
    | PropertyMortgagedEvent
    | PropertyRedeemedEvent
    | SalaryPaidEvent
    | StockPriceAdvancedEvent
    | StockBoughtEvent
    | StockSoldEvent
    | LoanOpenedEvent
    | LoanPaymentMadeEvent
    | VehiclePurchasedEvent
    | VehicleUpkeepPaidEvent
    | InsurancePurchasedEvent
    | InsurancePremiumPaidEvent
    | EducationStartedEvent
    | EducationProgressedEvent
    | CareerChangedEvent
    | HealthCheckResolvedEvent
    | BidPlacedEvent
    | BidRaisedEvent
    | BidCancelledEvent
    | BidWonEvent
    | BidLostEvent
    | StandingOrdersExecutedEvent
    | DailySettlementCompletedEvent
    | TradeOfferInvalidatedEvent
    | TurnSkippedEvent
    | LoanDefaultedEvent
    | PlayerBlacklistedEvent
    | StockLiquidatedEvent
    | VehicleLiquidatedEvent
    | PropertySoldToBankEvent
    | FamilyBailoutAppliedEvent
    | PrivateLoanRescueEvent
    | PlayerBankruptedEvent
    | BankruptcyThresholdReachedEvent
    | PlayerConfinedEvent
    | ConfinementAdvancedEvent
    | ConfinementReleasedEvent
    | ConfinementReleasePaidEvent
    | AllianceProposedEvent
    | AllianceFormedEvent
    | AllianceProposalResolvedEvent
    | AllianceMemberJoinedEvent
    | AllianceMemberLeftEvent
    | AllianceTierChangedEvent
    | AllianceDissolvedEvent
    | AlliancePoolContributedEvent
    | AlliancePoolPaidEvent
    | AlliancePoolDistributedEvent
    | AllianceBailoutAttemptedEvent
    | AllianceBailoutSucceededEvent
    | AllianceRuinedEvent
)
