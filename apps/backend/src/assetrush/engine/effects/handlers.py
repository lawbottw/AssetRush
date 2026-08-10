"""M1 effect handlers。"""

from __future__ import annotations

from collections.abc import Sequence

from assetrush.engine.actions import (
    Action,
    AddPendingEffectAction,
    AddPlayerModifierAction,
    AdjustPlayerCashAction,
    AdjustTreasuryAction,
    MovePlayerAction,
    apply_action,
)
from assetrush.engine.effects.registry import EffectContext, EffectSpec, effect
from assetrush.engine.events import Event
from assetrush.engine.formula import resolve_amount
from assetrush.engine.state import GameState, ModifierValue

PENDING_EFFECT_TYPES = frozenset(
    {
        "confiscate_stock_gains",
        "downgrade_property",
        "free_alliance_proposal",
        "free_upgrade",
        "legal_case",
        "risky_investment_offer",
        "vehicle_sell_offer",
    }
)


@effect("none")
def handle_none(
    state: GameState, spec: EffectSpec, ctx: EffectContext
) -> tuple[GameState, list[Event]]:
    _ = spec
    _ = ctx
    return state, []


@effect("gain")
def handle_gain(
    state: GameState, spec: EffectSpec, ctx: EffectContext
) -> tuple[GameState, list[Event]]:
    amount = resolve_amount(spec, ctx.variables)
    if amount == 0:
        return state, []
    return apply_action(
        state,
        AdjustPlayerCashAction(
            type="adjust_player_cash",
            player_id=ctx.player_id,
            delta=amount,
            reason=_reason(ctx, "gain"),
        ),
        {},
    )


@effect("pay")
def handle_pay(
    state: GameState, spec: EffectSpec, ctx: EffectContext
) -> tuple[GameState, list[Event]]:
    amount = resolve_amount(spec, ctx.variables)
    if amount == 0:
        return state, []
    return apply_action(
        state,
        AdjustPlayerCashAction(
            type="adjust_player_cash",
            player_id=ctx.player_id,
            delta=-amount,
            reason=_reason(ctx, "pay"),
        ),
        {},
    )


@effect("pay_to_treasury")
def handle_pay_to_treasury(
    state: GameState, spec: EffectSpec, ctx: EffectContext
) -> tuple[GameState, list[Event]]:
    amount = resolve_amount(spec, ctx.variables)
    if amount == 0:
        return state, []
    return _apply_many(
        state,
        (
            AdjustPlayerCashAction(
                type="adjust_player_cash",
                player_id=ctx.player_id,
                delta=-amount,
                reason=_reason(ctx, "pay_to_treasury"),
            ),
            AdjustTreasuryAction(
                type="adjust_treasury",
                delta=amount,
                reason=_reason(ctx, "pay_to_treasury"),
            ),
        ),
    )


@effect("gain_from_treasury")
def handle_gain_from_treasury(
    state: GameState, spec: EffectSpec, ctx: EffectContext
) -> tuple[GameState, list[Event]]:
    requested = resolve_amount(spec, ctx.variables)
    amount = min(requested, state.treasury)
    if amount <= 0:
        return state, []
    return _apply_many(
        state,
        (
            AdjustTreasuryAction(
                type="adjust_treasury",
                delta=-amount,
                reason=_reason(ctx, "gain_from_treasury"),
            ),
            AdjustPlayerCashAction(
                type="adjust_player_cash",
                player_id=ctx.player_id,
                delta=amount,
                reason=_reason(ctx, "gain_from_treasury"),
            ),
        ),
    )


@effect("move")
def handle_move(
    state: GameState, spec: EffectSpec, ctx: EffectContext
) -> tuple[GameState, list[Event]]:
    steps = _int_value(spec.get("steps"), "steps")
    return apply_action(
        state,
        MovePlayerAction(
            type="move_player",
            player_id=ctx.player_id,
            steps=steps,
            total_tiles=ctx.total_tiles,
            reason=_reason(ctx, "move"),
        ),
        {},
    )


@effect("move_to_tile")
def handle_move_to_tile(
    state: GameState, spec: EffectSpec, ctx: EffectContext
) -> tuple[GameState, list[Event]]:
    if spec.get("kind") == "start":
        return apply_action(
            state,
            MovePlayerAction(
                type="move_player",
                player_id=ctx.player_id,
                position=0,
                reason=_reason(ctx, "move_to_tile"),
            ),
            {},
        )
    return _add_pending(state, "move_to_tile", ctx)


@effect("buff")
def handle_buff(
    state: GameState, spec: EffectSpec, ctx: EffectContext
) -> tuple[GameState, list[Event]]:
    key = _string_value(spec.get("key"), "key")
    return _add_modifier(
        state,
        ctx,
        key=key,
        value=_modifier_value(spec.get("value", True)),
        laps=_optional_positive_int(spec.get("laps"), "laps"),
        default_reason="buff",
    )


@effect("salary_modifier")
def handle_salary_modifier(
    state: GameState, spec: EffectSpec, ctx: EffectContext
) -> tuple[GameState, list[Event]]:
    return _add_modifier(
        state,
        ctx,
        key="salary_modifier",
        value=_modifier_value(spec.get("value", True)),
        laps=_optional_positive_int(spec.get("laps"), "laps"),
        default_reason="salary_modifier",
    )


@effect("no_salary")
def handle_no_salary(
    state: GameState, spec: EffectSpec, ctx: EffectContext
) -> tuple[GameState, list[Event]]:
    return _add_modifier(
        state,
        ctx,
        key="no_salary",
        value=_modifier_value(spec.get("buyout", True)),
        laps=_optional_positive_int(spec.get("laps"), "laps"),
        default_reason="no_salary",
    )


@effect("rent_modifier")
def handle_rent_modifier(
    state: GameState, spec: EffectSpec, ctx: EffectContext
) -> tuple[GameState, list[Event]]:
    return _add_modifier(
        state,
        ctx,
        key="rent_modifier",
        value=_modifier_value(spec.get("value", True)),
        laps=_optional_positive_int(spec.get("laps"), "laps"),
        default_reason="rent_modifier",
    )


@effect("stock_shock")
def handle_stock_shock(
    state: GameState, spec: EffectSpec, ctx: EffectContext
) -> tuple[GameState, list[Event]]:
    return _add_modifier(
        state,
        ctx,
        key="stock_shock",
        value=_modifier_value(spec.get("value", True)),
        laps=_optional_positive_int(spec.get("laps"), "laps"),
        default_reason="stock_shock",
    )


for _effect_type in PENDING_EFFECT_TYPES:

    @effect(_effect_type)
    def handle_pending(
        state: GameState,
        spec: EffectSpec,
        ctx: EffectContext,
        effect_type: str = _effect_type,
    ) -> tuple[GameState, list[Event]]:
        _ = spec
        return _add_pending(state, effect_type, ctx)


def _apply_many(state: GameState, actions: Sequence[Action]) -> tuple[GameState, list[Event]]:
    events: list[Event] = []
    next_state = state
    for action in actions:
        next_state, new_events = apply_action(next_state, action, {})
        events.extend(new_events)
    return next_state, events


def _add_modifier(
    state: GameState,
    ctx: EffectContext,
    *,
    key: str,
    value: ModifierValue,
    laps: int | None,
    default_reason: str,
) -> tuple[GameState, list[Event]]:
    return apply_action(
        state,
        AddPlayerModifierAction(
            type="add_player_modifier",
            player_id=ctx.player_id,
            key=key,
            value=value,
            laps=laps,
            reason=_reason(ctx, default_reason),
        ),
        {},
    )


def _add_pending(
    state: GameState, effect_type: str, ctx: EffectContext
) -> tuple[GameState, list[Event]]:
    return apply_action(
        state,
        AddPendingEffectAction(
            type="add_pending_effect",
            player_id=ctx.player_id,
            effect_type=effect_type,
            reason=_reason(ctx, effect_type),
        ),
        {},
    )


def _reason(ctx: EffectContext, default: str) -> str:
    return ctx.reason or default


def _int_value(value: object, field_name: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise ValueError(f"{field_name} must be an integer")
    return value


def _string_value(value: object, field_name: str) -> str:
    if not isinstance(value, str) or not value:
        raise ValueError(f"{field_name} must be a non-empty string")
    return value


def _optional_positive_int(value: object, field_name: str) -> int | None:
    if value is None:
        return None
    result = _int_value(value, field_name)
    if result <= 0:
        raise ValueError(f"{field_name} must be positive")
    return result


def _modifier_value(value: object) -> ModifierValue:
    if isinstance(value, str | int | float | bool) or value is None:
        return value
    return str(value)
