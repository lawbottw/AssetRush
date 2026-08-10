"""Config effect handler 註冊與分派。"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from typing import Protocol

from assetrush.engine.errors import FormulaError, UnknownEffectError
from assetrush.engine.events import Event
from assetrush.engine.formula import FormulaContext
from assetrush.engine.state import GameState

EffectSpec = Mapping[str, object]


@dataclass(frozen=True, slots=True)
class EffectContext:
    player_id: str
    variables: FormulaContext = field(default_factory=dict)
    total_tiles: int | None = None
    reason: str | None = None


class EffectHandler(Protocol):
    def __call__(
        self, state: GameState, spec: EffectSpec, ctx: EffectContext
    ) -> tuple[GameState, list[Event]]: ...


EFFECT_HANDLERS: dict[str, EffectHandler] = {}


def effect(name: str) -> Callable[[EffectHandler], EffectHandler]:
    def decorator(handler: EffectHandler) -> EffectHandler:
        EFFECT_HANDLERS[name] = handler
        return handler

    return decorator


def apply_effect(
    state: GameState, spec: EffectSpec, ctx: EffectContext
) -> tuple[GameState, list[Event]]:
    effect_type = spec.get("type")
    if not isinstance(effect_type, str):
        raise FormulaError("effect spec must contain string type")

    handler = EFFECT_HANDLERS.get(effect_type)
    if handler is None:
        raise UnknownEffectError(effect_type)
    return handler(state, spec, ctx)
