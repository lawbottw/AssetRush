"""純函式規則引擎。

鐵律 2：本套件零 I/O——不得 import supabase / sqlalchemy / httpx / requests /
fastapi / asyncpg。理由是規則引擎必須能離線跑蒙地卡羅模擬（`make simulate`），
那是平衡工作的前提。CI 會檢查（見 tests/test_engine_purity.py）。
"""

from assetrush.engine.actions import (
    Action,
    AddPendingEffectAction,
    AddPlayerModifierAction,
    AdjustPlayerCashAction,
    AdjustTreasuryAction,
    MovePlayerAction,
    apply_action,
)
from assetrush.engine.effects import (
    EFFECT_HANDLERS,
    EffectContext,
    EffectHandler,
    apply_effect,
    effect,
)
from assetrush.engine.errors import (
    EngineError,
    FormulaError,
    InvalidActionError,
    UnknownEffectError,
    UnknownPlayerError,
)
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
    PlayerState,
)

__all__ = [
    "EFFECT_HANDLERS",
    "Action",
    "AddPendingEffectAction",
    "AddPlayerModifierAction",
    "AdjustPlayerCashAction",
    "AdjustTreasuryAction",
    "CashAdjustedEvent",
    "EffectContext",
    "EffectHandler",
    "EngineError",
    "Event",
    "FormulaError",
    "GameState",
    "InvalidActionError",
    "ModifierValue",
    "Money",
    "MovePlayerAction",
    "PendingEffect",
    "PendingEffectAddedEvent",
    "PlayerModifier",
    "PlayerModifierAddedEvent",
    "PlayerMovedEvent",
    "PlayerState",
    "TreasuryAdjustedEvent",
    "UnknownEffectError",
    "UnknownPlayerError",
    "apply_action",
    "apply_effect",
    "effect",
]
