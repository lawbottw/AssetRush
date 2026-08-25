"""M2 開局初始化。"""

from __future__ import annotations

import random
from collections.abc import Mapping, Sequence
from dataclasses import dataclass

from assetrush.engine.board import TownInput, build_board
from assetrush.engine.errors import GameSetupError
from assetrush.engine.rng import derive_u64, seed_hash
from assetrush.engine.state import (
    BoardReference,
    BoardTile,
    GameMode,
    GamePhase,
    GameState,
    Money,
    PlayerLoan,
    PlayerState,
    PropertyState,
    StockHolding,
)

ConfigSnapshot = Mapping[str, object]


@dataclass(frozen=True, slots=True)
class GameStartSpec:
    game_id: str
    mode: GameMode
    player_ids: tuple[str, ...]
    server_seed: str
    game_seed: int
    target_minutes: int | None = None


@dataclass(frozen=True, slots=True)
class BoardSize:
    total_tiles: int
    property_tiles: int
    lap_limit: int
    day_limit: int | None = None
    rolls_per_day: int | None = None


def start_game(
    *,
    spec: GameStartSpec,
    config: ConfigSnapshot,
    towns: Sequence[TownInput],
) -> GameState:
    """從 config 與 towns fixture 建立可 replay 的初始局狀態。"""

    _validate_player_ids(spec.player_ids)
    size = resolve_board_size(config, spec.mode, len(spec.player_ids), spec.target_minutes)
    board = build_board(
        config=config,
        towns=towns,
        seed=spec.game_seed,
        total_tiles=size.total_tiles,
        property_tiles=size.property_tiles,
    )
    players = _draw_players(
        spec=spec,
        config=config,
        board=board,
    )
    threshold = _net_worth_threshold(config, players, board, size.lap_limit, spec.mode)
    reached_threshold = any(_net_worth(player, board) >= threshold for player in players)
    phase: GamePhase = "settling" if reached_threshold else "active"

    return GameState(
        players=players,
        id=spec.game_id,
        mode=spec.mode,
        phase=phase,
        server_seed=spec.server_seed,
        server_seed_hash=seed_hash(spec.server_seed),
        day=1 if spec.mode == "daily" else 0,
        lap_limit=size.lap_limit,
        day_limit=size.day_limit,
        rolls_per_day=size.rolls_per_day,
        net_worth_threshold=threshold,
        base_turn_order=_turn_order(spec),
        board=board,
        properties=_starting_property_states(players),
    )


def resolve_board_size(
    config: ConfigSnapshot,
    mode: GameMode,
    player_count: int,
    target_minutes: int | None = None,
) -> BoardSize:
    endgame = _mapping(config.get("endgame"), "config.endgame")
    modes = _mapping(endgame.get("modes"), "endgame.modes")
    mode_config = _mapping(modes.get(mode), f"endgame.modes.{mode}")
    _validate_player_count(mode_config, mode, player_count)

    if mode == "daily":
        return _daily_board_size(mode_config, player_count)
    return _blitz_board_size(config, mode_config, player_count, target_minutes)


def _daily_board_size(mode_config: ConfigSnapshot, player_count: int) -> BoardSize:
    rows = _list(mode_config.get("board_size_by_players"), "daily.board_size_by_players")
    for index, raw in enumerate(rows):
        row = _mapping(raw, f"daily.board_size_by_players[{index}]")
        if _int(row.get("min"), "min") <= player_count <= _int(row.get("max"), "max"):
            return BoardSize(
                total_tiles=_int(row.get("total_tiles"), "total_tiles"),
                property_tiles=_int(row.get("property_tiles"), "property_tiles"),
                lap_limit=_int(mode_config.get("lap_limit"), "daily.lap_limit"),
                day_limit=_int(mode_config.get("day_limit"), "daily.day_limit"),
                rolls_per_day=_int(row.get("avg_rolls_per_day"), "avg_rolls_per_day"),
            )
    raise GameSetupError(f"daily board size not configured for {player_count} players")


def _blitz_board_size(
    config: ConfigSnapshot,
    mode_config: ConfigSnapshot,
    player_count: int,
    target_minutes: int | None,
) -> BoardSize:
    auto = _mapping(mode_config.get("auto_config"), "blitz.auto_config")
    minutes = target_minutes or _int(auto.get("default_target_minutes"), "default_target_minutes")
    allowed_minutes = {
        _int(value, "target_minutes")
        for value in _list(auto.get("target_minutes_options"), "target_minutes_options")
    }
    if minutes not in allowed_minutes:
        raise GameSetupError(f"target_minutes must be one of {sorted(allowed_minutes)}")

    turns_per_player = minutes * 60 / _float(auto.get("sec_per_turn"), "sec_per_turn")
    turns_per_player = turns_per_player / player_count
    base_laps = _int(auto.get("base_laps"), "base_laps")
    avg_dice = _float(auto.get("avg_dice"), "avg_dice")
    tiles = round(turns_per_player / base_laps * avg_dice)

    tiles_min = _int(auto.get("tiles_min"), "tiles_min")
    tiles_max = _int(auto.get("tiles_max"), "tiles_max")
    if tiles < tiles_min:
        tiles = tiles_min
        laps = round(turns_per_player / (tiles_min / avg_dice))
    elif tiles > tiles_max:
        tiles = tiles_max
        laps = round(turns_per_player / (tiles_max / avg_dice))
    else:
        laps = base_laps

    laps = max(
        _int(auto.get("laps_min"), "laps_min"),
        min(_int(auto.get("laps_max"), "laps_max"), laps),
    )
    property_tiles = tiles - _function_tile_count(config, tiles)
    return BoardSize(total_tiles=tiles, property_tiles=property_tiles, lap_limit=laps)


def _function_tile_count(config: ConfigSnapshot, total_tiles: int) -> int:
    board = _mapping(config.get("board"), "config.board")
    function_tiles = _mapping(board.get("function_tiles"), "board.function_tiles")
    layouts = _mapping(function_tiles.get("layouts"), "board.function_tiles.layouts")
    layout = _list(
        layouts.get(_nearest_layout_key(layouts, total_tiles)),
        f"board layout {total_tiles}",
    )
    return sum(_int(_mapping(row, "layout row").get("count"), "count") for row in layout)


def _nearest_layout_key(layouts: Mapping[str, object], total_tiles: int) -> str:
    available: list[int] = []
    for key in layouts:
        try:
            available.append(int(key))
        except ValueError as exc:
            raise GameSetupError(f"board layout key must be an integer: {key}") from exc
    if not available:
        raise GameSetupError("board.function_tiles.layouts must not be empty")
    return str(min(available, key=lambda value: (abs(value - total_tiles), value)))


def _draw_players(
    *,
    spec: GameStartSpec,
    config: ConfigSnapshot,
    board: BoardReference,
) -> tuple[PlayerState, ...]:
    identities = _mapping(config.get("identities"), "config.identities")
    occupations_config = _mapping(config.get("occupations"), "config.occupations")
    wellbeing = _mapping(config.get("wellbeing"), "config.wellbeing")
    stocks_config = _mapping(config.get("stocks"), "config.stocks")
    loans_config = _mapping(config.get("loans"), "config.loans")
    vehicles_config = _mapping(config.get("vehicles"), "config.vehicles")
    backgrounds = _list(identities.get("backgrounds"), "identities.backgrounds")
    occupations = _list(occupations_config.get("occupations"), "occupations.occupations")

    assigned_properties: set[int] = set()
    players: list[PlayerState] = []
    for index, player_id in enumerate(spec.player_ids):
        rng = random.Random(
            derive_u64(spec.server_seed, spec.game_id, "starting_identity", index, player_id)
        )
        background = _weighted_row(backgrounds, rng, "background")
        occupation = _weighted_row(occupations, rng, "occupation")
        cash = _starting_cash(background, identities, len(spec.player_ids))
        stock_holdings = _starting_stocks(background, stocks_config, rng)
        property_indices = _starting_properties(background, board, assigned_properties, rng)
        loans = _starting_loans(background, loans_config)
        players.append(
            PlayerState(
                id=player_id,
                cash=cash,
                background_key=_string(background.get("key"), "background.key"),
                occupation_key=_string(occupation.get("key"), "occupation.key"),
                monthly_salary=_int(occupation.get("monthly_salary"), "occupation.monthly_salary"),
                health=_starting_health(wellbeing, rng),
                luck=_starting_luck(wellbeing, rng),
                stock_holdings=stock_holdings,
                property_tile_indices=property_indices,
                loans=loans,
                vehicles=_starting_vehicles(background, vehicles_config, rng),
            )
        )
    return tuple(players)


def _starting_cash(
    background: ConfigSnapshot,
    identities: ConfigSnapshot,
    player_count: int,
) -> Money:
    cash = _int(background.get("starting_cash"), "background.starting_cash")
    adjustment = _mapping(
        identities.get("crowded_game_adjustment", {}),
        "identities.crowded_game_adjustment",
    )
    min_players = adjustment.get("min_players")
    multiplier = adjustment.get("starting_cash_multiplier")
    if (
        isinstance(min_players, int)
        and isinstance(multiplier, int | float)
        and player_count >= min_players
    ):
        cash = round(cash * float(multiplier))
    return cash


def _starting_stocks(
    background: ConfigSnapshot,
    stocks_config: ConfigSnapshot,
    rng: random.Random,
) -> tuple[StockHolding, ...]:
    grants = _list(background.get("grants", []), "background.grants")
    stock_rows = _stock_rows(stocks_config)
    holdings: list[StockHolding] = []
    for grant in grants:
        row = _mapping(grant, "grant")
        if row.get("type") != "stock":
            continue
        stock = _mapping(rng.choice(stock_rows), "stock")
        holdings.append(
            StockHolding(
                code=_string(stock.get("code"), "stock.code"),
                value=_int(row.get("value"), "stock grant value"),
            )
        )
    return tuple(holdings)


def _starting_properties(
    background: ConfigSnapshot,
    board: BoardReference,
    assigned_properties: set[int],
    rng: random.Random,
) -> tuple[int, ...]:
    grants = _list(background.get("grants", []), "background.grants")
    indices: list[int] = []
    for grant in grants:
        row = _mapping(grant, "grant")
        if row.get("type") != "property":
            continue
        tile = _pick_property_tile(
            board,
            _string(row.get("pick"), "property grant pick"),
            assigned_properties,
            rng,
        )
        assigned_properties.add(tile.index)
        indices.append(tile.index)
    return tuple(indices)


def _starting_loans(
    background: ConfigSnapshot,
    loans_config: ConfigSnapshot,
) -> tuple[PlayerLoan, ...]:
    amount = background.get("student_loan")
    if amount is None:
        return ()
    product = _loan_product(loans_config, "student_loan")
    return (
        PlayerLoan(
            product_key="student_loan",
            principal=_int(amount, "background.student_loan"),
            rate_per_lap=_float(
                background.get("student_loan_rate_per_lap", product.get("rate_per_lap")),
                "student_loan_rate_per_lap",
            ),
        ),
    )


def _starting_vehicles(
    background: ConfigSnapshot,
    vehicles_config: ConfigSnapshot,
    rng: random.Random,
) -> tuple[str, ...]:
    vehicles: list[str] = []
    for grant in _list(background.get("grants", []), "background.grants"):
        row = _mapping(grant, "grant")
        if row.get("type") != "vehicle":
            continue
        chance = _float(row.get("chance", 1.0), "vehicle chance")
        if rng.random() <= chance:
            vehicles.append(
                _resolve_vehicle_grant(
                    _string(row.get("pick"), "vehicle pick"), vehicles_config, rng
                )
            )
    return tuple(vehicles)


def _resolve_vehicle_grant(
    pick: str,
    vehicles_config: ConfigSnapshot,
    rng: random.Random,
) -> str:
    if pick == "scooter_or_domestic":
        pick = ("scooter", "domestic")[rng.randrange(2)]
    vehicle_keys = {
        _string(_mapping(row, "vehicle").get("key"), "vehicle.key")
        for row in _list(vehicles_config.get("vehicles"), "vehicles.vehicles")
    }
    if pick not in vehicle_keys:
        raise GameSetupError(f"unknown vehicle grant: {pick}")
    return pick


def _pick_property_tile(
    board: BoardReference,
    pick: str,
    assigned_properties: set[int],
    rng: random.Random,
) -> BoardTile:
    property_tiles = [
        tile
        for tile in board.tiles
        if tile.kind == "property" and tile.index not in assigned_properties
    ]
    if not property_tiles:
        raise GameSetupError("no property tiles available for starting grant")
    sorted_tiles = sorted(property_tiles, key=lambda tile: (tile.base_price or 0, tile.index))
    if pick == "median_tier":
        tier3 = [tile for tile in sorted_tiles if tile.price_tier == 3]
        lower = len(sorted_tiles) // 3
        upper = max(lower + 1, len(sorted_tiles) * 2 // 3)
        candidates = tier3 or sorted_tiles[lower:upper]
    elif pick == "top_quartile":
        start = max(0, len(sorted_tiles) * 3 // 4)
        candidates = sorted_tiles[start:] or sorted_tiles[-1:]
    else:
        candidates = sorted_tiles
    return rng.choice(candidates)


def _starting_health(wellbeing: ConfigSnapshot, rng: random.Random) -> int:
    health = _mapping(wellbeing.get("health"), "wellbeing.health")
    start_range = _list(health.get("starting_range"), "health.starting_range")
    low = _int(start_range[0], "health.starting_range[0]")
    high = _int(start_range[1], "health.starting_range[1]")
    return rng.randint(low, high)


def _starting_luck(wellbeing: ConfigSnapshot, rng: random.Random) -> int:
    luck = _mapping(wellbeing.get("luck"), "wellbeing.luck")
    row = _weighted_row(_list(luck.get("starting_weights"), "luck.starting_weights"), rng, "luck")
    return _int(row.get("value"), "luck.value")


def _turn_order(spec: GameStartSpec) -> tuple[str, ...]:
    rolls = [
        (
            derive_u64(spec.server_seed, spec.game_id, "turn_order", 0, player_id) % 100 + 1,
            -index,
            player_id,
        )
        for index, player_id in enumerate(spec.player_ids)
    ]
    return tuple(player_id for _roll, _join_order, player_id in sorted(rolls, reverse=True))


def _net_worth_threshold(
    config: ConfigSnapshot,
    players: Sequence[PlayerState],
    board: BoardReference,
    lap_limit: int,
    mode: GameMode,
) -> Money:
    endgame = _mapping(config.get("endgame"), "config.endgame")
    threshold = _mapping(endgame.get("net_worth_threshold"), "endgame.net_worth_threshold")
    net_worths = [_net_worth(player, board) for player in players]
    avg_starting = sum(net_worths) / len(net_worths)
    max_starting = max(net_worths)
    avg_quarterly_salary = sum(player.monthly_salary * 3 for player in players) / len(players)
    first = (avg_starting + lap_limit * avg_quarterly_salary) * _float(
        threshold.get("income_multiplier"),
        "income_multiplier",
    )
    second = max_starting * _float(
        threshold.get("max_starting_multiplier"),
        "max_starting_multiplier",
    )
    mode_multipliers = _mapping(
        threshold.get("mode_multiplier", {}), "net_worth_threshold.mode_multiplier"
    )
    multiplier = _float(
        mode_multipliers.get(mode, 1.0), f"net_worth_threshold.mode_multiplier.{mode}"
    )
    crowded_multiplier = threshold.get("crowded_game_multiplier")
    if isinstance(crowded_multiplier, Mapping):
        min_players = _int(
            crowded_multiplier.get("min_players"),
            "net_worth_threshold.crowded_game_multiplier.min_players",
        )
        if len(players) >= min_players:
            multiplier *= _float(
                crowded_multiplier.get("multiplier"),
                "net_worth_threshold.crowded_game_multiplier.multiplier",
            )
    return round(max(first, second) * multiplier)


def _net_worth(player: PlayerState, board: BoardReference) -> Money:
    property_values = sum(
        (board.tiles[index].base_price or 0)
        for index in player.property_tile_indices
        if 0 <= index < len(board.tiles)
    )
    stock_values = sum(holding.value for holding in player.stock_holdings)
    debt = sum(loan.principal for loan in player.loans)
    return player.cash + property_values + stock_values - debt


def _starting_property_states(players: Sequence[PlayerState]) -> tuple[PropertyState, ...]:
    return tuple(
        PropertyState(tile_index=tile_index, owner_id=player.id)
        for player in players
        for tile_index in player.property_tile_indices
    )


def _validate_player_ids(player_ids: Sequence[str]) -> None:
    if len(player_ids) < 2:
        raise GameSetupError("at least two players are required")
    if len(set(player_ids)) != len(player_ids):
        raise GameSetupError("player ids must be unique")
    if any(not player_id for player_id in player_ids):
        raise GameSetupError("player ids must be non-empty")


def _validate_player_count(mode_config: ConfigSnapshot, mode: GameMode, player_count: int) -> None:
    min_players = _int(mode_config.get("min_players"), f"{mode}.min_players")
    max_players = _int(mode_config.get("max_players"), f"{mode}.max_players")
    if not min_players <= player_count <= max_players:
        raise GameSetupError(
            f"{mode} supports {min_players}-{max_players} players, got {player_count}"
        )


def _weighted_row(rows: Sequence[object], rng: random.Random, path: str) -> ConfigSnapshot:
    weighted = [_mapping(row, f"{path} row") for row in rows]
    total = sum(_int(row.get("weight"), f"{path}.weight") for row in weighted)
    marker = rng.random() * total
    running = 0.0
    for row in weighted:
        running += _int(row.get("weight"), f"{path}.weight")
        if running >= marker:
            return row
    return weighted[-1]


def _stock_rows(stocks_config: ConfigSnapshot) -> list[object]:
    rows: list[object] = []
    for key in ("equities", "etfs_passive", "etfs_active"):
        rows.extend(_list(stocks_config.get(key), f"stocks.{key}"))
    if not rows:
        raise GameSetupError("stocks config has no instruments")
    return rows


def _loan_product(loans_config: ConfigSnapshot, product_key: str) -> ConfigSnapshot:
    for product in _list(loans_config.get("products"), "loans.products"):
        row = _mapping(product, "loan product")
        if row.get("key") == product_key:
            return row
    raise GameSetupError(f"loan product not found: {product_key}")


def _mapping(value: object, path: str) -> ConfigSnapshot:
    if not isinstance(value, Mapping):
        raise GameSetupError(f"{path} must be an object")
    return value


def _list(value: object, path: str) -> list[object]:
    if not isinstance(value, list):
        raise GameSetupError(f"{path} must be a list")
    return value


def _string(value: object, path: str) -> str:
    if not isinstance(value, str) or not value:
        raise GameSetupError(f"{path} must be a non-empty string")
    return value


def _int(value: object, path: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise GameSetupError(f"{path} must be an integer")
    return value


def _float(value: object, path: str) -> float:
    if isinstance(value, bool) or not isinstance(value, int | float):
        raise GameSetupError(f"{path} must be a number")
    return float(value)
