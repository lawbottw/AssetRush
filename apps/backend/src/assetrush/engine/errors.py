"""Engine 自有例外型別。"""

from __future__ import annotations


class EngineError(Exception):
    """規則引擎錯誤的基底類別。"""


class UnknownPlayerError(EngineError):
    """Action 指向不存在的玩家。"""

    def __init__(self, player_id: str) -> None:
        self.player_id = player_id
        super().__init__(f"unknown player: {player_id}")


class InvalidActionError(EngineError):
    """Action 本身不符合規則引擎的基本前置條件。"""


class FormulaError(EngineError):
    """公式無法安全解析或求值。"""


class UnknownEffectError(EngineError):
    """Config effect type 沒有對應 handler。"""

    def __init__(self, effect_type: str) -> None:
        self.effect_type = effect_type
        super().__init__(f"unknown effect: {effect_type}")
