"""不可變遊戲狀態。"""

from __future__ import annotations

from dataclasses import dataclass, replace

from assetrush.engine.errors import UnknownPlayerError

Money = int
ModifierValue = str | int | float | bool | None


@dataclass(frozen=True, slots=True)
class PlayerModifier:
    """尚未建完整規則前，用來承接 buff / modifier 類效果。"""

    key: str
    value: ModifierValue = True
    laps: int | None = None


@dataclass(frozen=True, slots=True)
class PendingEffect:
    """尚未建模的複雜效果，留給 M2 規則模組消化。"""

    effect_type: str
    player_id: str
    reason: str | None = None


@dataclass(frozen=True, slots=True)
class PlayerState:
    """M1 最小玩家狀態；完整欄位會在 M2 隨規則補齊。"""

    id: str
    cash: Money
    position: int = 0
    lap: int = 0
    modifiers: tuple[PlayerModifier, ...] = ()


@dataclass(frozen=True, slots=True)
class GameState:
    """M1 最小局狀態。"""

    players: tuple[PlayerState, ...]
    treasury: Money = 0
    pending_effects: tuple[PendingEffect, ...] = ()

    def player(self, player_id: str) -> PlayerState:
        for player in self.players:
            if player.id == player_id:
                return player
        raise UnknownPlayerError(player_id)

    def replace_player(self, updated_player: PlayerState) -> GameState:
        replaced = False
        players: list[PlayerState] = []
        for player in self.players:
            if player.id == updated_player.id:
                players.append(updated_player)
                replaced = True
            else:
                players.append(player)

        if not replaced:
            raise UnknownPlayerError(updated_player.id)

        return replace(self, players=tuple(players))
