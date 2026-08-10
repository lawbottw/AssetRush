"""事件溯源事件型別。"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from assetrush.engine.state import ModifierValue, Money


@dataclass(frozen=True, slots=True)
class CashAdjustedEvent:
    type: Literal["cash_adjusted"]
    player_id: str
    delta: Money
    balance_after: Money
    reason: str | None = None


@dataclass(frozen=True, slots=True)
class TreasuryAdjustedEvent:
    type: Literal["treasury_adjusted"]
    delta: Money
    balance_after: Money
    reason: str | None = None


@dataclass(frozen=True, slots=True)
class PlayerMovedEvent:
    type: Literal["player_moved"]
    player_id: str
    position_before: int
    position_after: int
    lap_before: int
    lap_after: int
    reason: str | None = None


@dataclass(frozen=True, slots=True)
class PlayerModifierAddedEvent:
    type: Literal["player_modifier_added"]
    player_id: str
    key: str
    value: ModifierValue
    laps: int | None = None
    reason: str | None = None


@dataclass(frozen=True, slots=True)
class PendingEffectAddedEvent:
    type: Literal["pending_effect_added"]
    player_id: str
    effect_type: str
    reason: str | None = None


Event = (
    CashAdjustedEvent
    | TreasuryAdjustedEvent
    | PlayerMovedEvent
    | PlayerModifierAddedEvent
    | PendingEffectAddedEvent
)
