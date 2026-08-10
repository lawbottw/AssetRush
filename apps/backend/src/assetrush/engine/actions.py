"""玩家 action 與 reducer。"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, replace
from typing import Literal, assert_never

from assetrush.engine.errors import InvalidActionError
from assetrush.engine.events import (
    CashAdjustedEvent,
    Event,
    PendingEffectAddedEvent,
    PlayerModifierAddedEvent,
    PlayerMovedEvent,
    TreasuryAdjustedEvent,
)
from assetrush.engine.state import (
    GameState,
    ModifierValue,
    Money,
    PendingEffect,
    PlayerModifier,
)

ConfigSnapshot = Mapping[str, object]


@dataclass(frozen=True, slots=True)
class AdjustPlayerCashAction:
    type: Literal["adjust_player_cash"]
    player_id: str
    delta: Money
    reason: str | None = None


@dataclass(frozen=True, slots=True)
class AdjustTreasuryAction:
    type: Literal["adjust_treasury"]
    delta: Money
    reason: str | None = None


@dataclass(frozen=True, slots=True)
class MovePlayerAction:
    type: Literal["move_player"]
    player_id: str
    steps: int = 0
    position: int | None = None
    lap_delta: int = 0
    total_tiles: int | None = None
    reason: str | None = None


@dataclass(frozen=True, slots=True)
class AddPlayerModifierAction:
    type: Literal["add_player_modifier"]
    player_id: str
    key: str
    value: ModifierValue = True
    laps: int | None = None
    reason: str | None = None


@dataclass(frozen=True, slots=True)
class AddPendingEffectAction:
    type: Literal["add_pending_effect"]
    player_id: str
    effect_type: str
    reason: str | None = None


Action = (
    AdjustPlayerCashAction
    | AdjustTreasuryAction
    | MovePlayerAction
    | AddPlayerModifierAction
    | AddPendingEffectAction
)


def apply_action(
    state: GameState, action: Action, config: ConfigSnapshot
) -> tuple[GameState, list[Event]]:
    """套用 action 並回傳新 state 與事件。

    `config` 在 #9 僅保留簽名；正式 schema 會在後續 M1 issue 補上。
    """
    _ = config

    if isinstance(action, AdjustPlayerCashAction):
        return _adjust_player_cash(state, action)
    if isinstance(action, AdjustTreasuryAction):
        return _adjust_treasury(state, action)
    if isinstance(action, MovePlayerAction):
        return _move_player(state, action)
    if isinstance(action, AddPlayerModifierAction):
        return _add_player_modifier(state, action)
    if isinstance(action, AddPendingEffectAction):
        return _add_pending_effect(state, action)

    assert_never(action)


def _adjust_player_cash(
    state: GameState, action: AdjustPlayerCashAction
) -> tuple[GameState, list[Event]]:
    if action.delta == 0:
        raise InvalidActionError("cash delta must not be zero")

    player = state.player(action.player_id)
    updated_player = replace(player, cash=player.cash + action.delta)
    updated_state = state.replace_player(updated_player)
    event = CashAdjustedEvent(
        type="cash_adjusted",
        player_id=action.player_id,
        delta=action.delta,
        balance_after=updated_player.cash,
        reason=action.reason,
    )
    return updated_state, [event]


def _adjust_treasury(
    state: GameState, action: AdjustTreasuryAction
) -> tuple[GameState, list[Event]]:
    if action.delta == 0:
        raise InvalidActionError("treasury delta must not be zero")

    updated_state = replace(state, treasury=state.treasury + action.delta)
    event = TreasuryAdjustedEvent(
        type="treasury_adjusted",
        delta=action.delta,
        balance_after=updated_state.treasury,
        reason=action.reason,
    )
    return updated_state, [event]


def _move_player(state: GameState, action: MovePlayerAction) -> tuple[GameState, list[Event]]:
    if action.position is None and action.steps == 0 and action.lap_delta == 0:
        raise InvalidActionError("move action must change position or lap")
    if action.total_tiles is not None and action.total_tiles <= 0:
        raise InvalidActionError("total_tiles must be positive")

    player = state.player(action.player_id)
    position_before = player.position
    lap_before = player.lap

    if action.position is not None:
        position_after = action.position
        lap_from_steps = 0
    elif action.total_tiles is None:
        position_after = player.position + action.steps
        lap_from_steps = 0
    else:
        raw_position = player.position + action.steps
        position_after = raw_position % action.total_tiles
        lap_from_steps = raw_position // action.total_tiles

    lap_after = player.lap + action.lap_delta + lap_from_steps
    updated_player = replace(player, position=position_after, lap=lap_after)
    updated_state = state.replace_player(updated_player)
    event = PlayerMovedEvent(
        type="player_moved",
        player_id=action.player_id,
        position_before=position_before,
        position_after=position_after,
        lap_before=lap_before,
        lap_after=lap_after,
        reason=action.reason,
    )
    return updated_state, [event]


def _add_player_modifier(
    state: GameState, action: AddPlayerModifierAction
) -> tuple[GameState, list[Event]]:
    if not action.key:
        raise InvalidActionError("modifier key must not be empty")
    if action.laps is not None and action.laps <= 0:
        raise InvalidActionError("modifier laps must be positive")

    player = state.player(action.player_id)
    modifier = PlayerModifier(key=action.key, value=action.value, laps=action.laps)
    updated_player = replace(player, modifiers=(*player.modifiers, modifier))
    updated_state = state.replace_player(updated_player)
    event = PlayerModifierAddedEvent(
        type="player_modifier_added",
        player_id=action.player_id,
        key=action.key,
        value=action.value,
        laps=action.laps,
        reason=action.reason,
    )
    return updated_state, [event]


def _add_pending_effect(
    state: GameState, action: AddPendingEffectAction
) -> tuple[GameState, list[Event]]:
    if not action.effect_type:
        raise InvalidActionError("pending effect type must not be empty")

    state.player(action.player_id)
    pending_effect = PendingEffect(
        effect_type=action.effect_type,
        player_id=action.player_id,
        reason=action.reason,
    )
    updated_state = replace(state, pending_effects=(*state.pending_effects, pending_effect))
    event = PendingEffectAddedEvent(
        type="pending_effect_added",
        player_id=action.player_id,
        effect_type=action.effect_type,
        reason=action.reason,
    )
    return updated_state, [event]
