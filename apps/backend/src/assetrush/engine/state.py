"""不可變遊戲狀態。"""

from __future__ import annotations

from dataclasses import dataclass, replace
from typing import Literal

from assetrush.engine.errors import UnknownPlayerError

Money = int
ModifierValue = str | int | float | bool | None
GameMode = Literal["blitz", "daily"]
GamePhase = Literal["lobby", "recruiting", "starting", "active", "settling", "finished"]
ConfinementKind = Literal["jail", "hospital"]
AllianceTier = Literal["couple", "married", "family_small", "family_large"]
TileKind = Literal[
    "start",
    "property",
    "opportunity",
    "fate",
    "leisure",
    "tax",
    "jail",
    "hospital",
]


@dataclass(frozen=True, slots=True)
class Town:
    """棋盤抽樣使用的鄉鎮資料列；M2/M3 可用合成 fixture。"""

    code: str
    name: str
    county: str
    region: str
    avg_price_per_ping: int
    price_tier: int
    population: int
    is_active: bool = True


@dataclass(frozen=True, slots=True)
class BoardTile:
    """物化後的棋盤格。"""

    index: int
    kind: TileKind
    town_code: str | None = None
    name: str | None = None
    county: str | None = None
    region: str | None = None
    price_tier: int | None = None
    base_price: Money | None = None


@dataclass(frozen=True, slots=True)
class BoardReference:
    """局內棋盤引用與 #20 物化格資料。"""

    seed: int
    total_tiles: int
    property_tiles: int
    config_version: str
    tiles: tuple[BoardTile, ...] = ()


@dataclass(frozen=True, slots=True)
class StockHolding:
    code: str
    value: Money


@dataclass(frozen=True, slots=True)
class StockPrice:
    code: str
    price: float


@dataclass(frozen=True, slots=True)
class PlayerLoan:
    product_key: str
    principal: Money
    rate_per_lap: float


@dataclass(frozen=True, slots=True)
class ConfinementState:
    kind: ConfinementKind
    remaining_turns: int
    reason: str | None = None


@dataclass(frozen=True, slots=True)
class PropertyState:
    tile_index: int
    owner_id: str
    level: int = 0
    invested: Money = 0
    mortgaged: bool = False


@dataclass(frozen=True, slots=True)
class PropertyBidState:
    tile_index: int
    player_id: str
    bid_amount: Money
    day: int


StandingBidPolicy = Literal["none", "base_price"]


@dataclass(frozen=True, slots=True)
class StandingOrderState:
    player_id: str
    bid_policy: StandingBidPolicy = "none"
    cash_floor: Money = 0
    max_bid_ratio: float = 1.0
    enabled: bool = True


@dataclass(frozen=True, slots=True)
class TradeOfferState:
    offer_id: str
    from_player_id: str
    to_player_id: str
    cash_frozen: Money = 0
    property_tile_indices: tuple[int, ...] = ()


@dataclass(frozen=True, slots=True)
class BankruptcyRecord:
    player_id: str
    day: int
    net_worth_before: Money
    counts_for_end_condition: bool
    reason: str


@dataclass(frozen=True, slots=True)
class AllianceMemberState:
    player_id: str
    contributed: Money = 0
    relationship_changes: int = 0


@dataclass(frozen=True, slots=True)
class AllianceState:
    id: str
    tier: AllianceTier
    member_ids: tuple[str, ...]
    pool_balance: Money = 0
    member_states: tuple[AllianceMemberState, ...] = ()
    core_partner_ids: tuple[str, str] | None = None
    active: bool = True
    name: str | None = None

    def member_state(self, player_id: str) -> AllianceMemberState | None:
        for member in self.member_states:
            if member.player_id == player_id:
                return member
        return None


@dataclass(frozen=True, slots=True)
class AllianceProposalState:
    id: str
    from_player_id: str
    to_player_id: str
    tier: AllianceTier
    day: int
    target_alliance_id: str | None = None
    formation_style: str | None = None


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
    """不可變玩家狀態；M2 #20 補足開局身分與起始資產。"""

    id: str
    cash: Money
    frozen_cash: Money = 0
    position: int = 0
    lap: int = 0
    background_key: str | None = None
    occupation_key: str | None = None
    monthly_salary: Money = 0
    health: int = 70
    luck: int = 0
    rolls_used_today: int = 0
    default_count: int = 0
    is_blacklisted: bool = False
    is_bankrupt: bool = False
    has_quit: bool = False
    alliance_id: str | None = None
    relationship_changes: int = 0
    confinement: ConfinementState | None = None
    stock_holdings: tuple[StockHolding, ...] = ()
    property_tile_indices: tuple[int, ...] = ()
    loans: tuple[PlayerLoan, ...] = ()
    vehicles: tuple[str, ...] = ()
    insurance_policies: tuple[str, ...] = ()
    education_course_key: str | None = None
    education_remaining_laps: int = 0
    education_unlocked_tier: int | None = None
    modifiers: tuple[PlayerModifier, ...] = ()


@dataclass(frozen=True, slots=True)
class GameState:
    """不可變局狀態。

    M2 #19 先補足共用骨架；完整棋盤、地產與債務規則會由後續 issue 接上。
    """

    players: tuple[PlayerState, ...]
    id: str = "game"
    mode: GameMode = "blitz"
    phase: GamePhase = "lobby"
    server_seed: str = ""
    server_seed_hash: str = ""
    turn_seq: int = 0
    event_seq: int = 0
    rng_seq: int = 0
    day: int = 0
    lap_limit: int = 0
    day_limit: int | None = None
    rolls_per_day: int | None = None
    net_worth_threshold: Money = 0
    base_turn_order: tuple[str, ...] = ()
    board: BoardReference | None = None
    properties: tuple[PropertyState, ...] = ()
    property_bids: tuple[PropertyBidState, ...] = ()
    standing_orders: tuple[StandingOrderState, ...] = ()
    trade_offers: tuple[TradeOfferState, ...] = ()
    bankruptcy_records: tuple[BankruptcyRecord, ...] = ()
    alliances: tuple[AllianceState, ...] = ()
    alliance_proposals: tuple[AllianceProposalState, ...] = ()
    stock_prices: tuple[StockPrice, ...] = ()
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

    def property_at(self, tile_index: int) -> PropertyState | None:
        for property_state in self.properties:
            if property_state.tile_index == tile_index:
                return property_state
        return None

    def replace_property(self, updated_property: PropertyState) -> GameState:
        replaced = False
        properties: list[PropertyState] = []
        for property_state in self.properties:
            if property_state.tile_index == updated_property.tile_index:
                properties.append(updated_property)
                replaced = True
            else:
                properties.append(property_state)
        if not replaced:
            properties.append(updated_property)
        return replace(self, properties=tuple(properties))
