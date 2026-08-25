"""Reusable text-game runner for M2 and future simulations."""

from __future__ import annotations

import random
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from typing import Any, Literal, cast

from assetrush.engine import (
    AdvancePhaseCommand,
    Command,
    GameMode,
    GameStartSpec,
    GameState,
    InvalidCommandError,
    PlacePropertyBidCommand,
    ProposeAllianceCommand,
    PurchasePropertyCommand,
    QuarterlyChoices,
    ResolveCashShortfallCommand,
    RespondAllianceProposalCommand,
    RunDailySettlementCommand,
    RunQuarterlyAffairsCommand,
    TakeTurnCommand,
    Transition,
    execute_command,
    player_net_worth,
    replay_events,
    start_game,
    state_digest,
)
from assetrush.engine.events import Event
from assetrush.engine.state import BoardTile, GamePhase, PlayerState

ConfigSnapshot = Mapping[str, object]
StrategyName = Literal[
    "conservative",
    "aggressive",
    "random",
    "stock_education",
    "vehicle",
    "alliance",
    "mixed",
]


@dataclass(frozen=True, slots=True)
class RunnerSpec:
    mode: GameMode
    player_count: int
    seed: str
    game_id: str = "cli-game"
    target_minutes: int | None = None
    strategy: StrategyName = "conservative"
    strategy_offset: int = 0
    max_turns: int = 1000
    verify_replay: bool = True


@dataclass(frozen=True, slots=True)
class GameRunResult:
    spec: RunnerSpec
    initial_state: GameState
    final_state: GameState
    events: tuple[Event, ...]
    replay_digest: str
    final_digest: str
    replay_checked: bool
    replay_verified: bool
    turns_executed: int
    completed: bool


def available_cli_commands() -> tuple[dict[str, object], ...]:
    return (
        {
            "type": "take_turn",
            "fields": {"player_id": "string", "extra_move_steps": "integer, optional"},
            "description": "Roll deterministic dice and dispatch the landing for a player.",
        },
        {
            "type": "purchase_property",
            "fields": {"player_id": "string", "tile_index": "integer"},
            "description": "Buy an unowned property in blitz mode.",
        },
        {
            "type": "place_property_bid",
            "fields": {"player_id": "string", "tile_index": "integer", "bid_amount": "integer"},
            "description": "Place a daily claim-auction bid for an unowned property.",
        },
        {
            "type": "run_daily_settlement",
            "fields": {"execute_standing_orders": "boolean, optional"},
            "description": "Settle daily bids, optional standing orders, and advance the day.",
        },
        {
            "type": "run_quarterly_affairs",
            "fields": {
                "player_id": "string",
                "choices": "object with stock, loan, education, vehicle, insurance fields",
            },
            "description": "Apply quarterly income, stock prices, loan choices, and upkeep.",
        },
        {
            "type": "resolve_cash_shortfall",
            "fields": {"player_id": "string"},
            "description": "Run the M2 liquidation and bailout path for a negative-cash player.",
        },
        {
            "type": "advance_phase",
            "fields": {"phase": "settling|finished", "reason": "string, optional"},
            "description": "Close a completed runner game through legal phase transitions.",
        },
    )


def run_auto_game(
    spec: RunnerSpec,
    config: ConfigSnapshot,
    towns: Sequence[Mapping[str, object]] | None = None,
) -> GameRunResult:
    initial = create_initial_state(spec, config, towns)
    working = initial
    events: list[Event] = []
    working = _seed_runner_alliances(working, spec.strategy, config, events)
    turns_executed = 0
    rng = random.Random(f"{spec.seed}:{spec.strategy}")

    while working.phase == "active" and turns_executed < spec.max_turns:
        if _runner_complete(working, turns_executed):
            break
        before_turn = working.turn_seq
        if working.mode == "daily":
            working = _run_daily_day(
                working, spec.strategy, spec.strategy_offset, config, rng, events
            )
        else:
            player_id = _next_blitz_player_id(working)
            working = _run_player_turn(
                working, player_id, spec.strategy, spec.strategy_offset, config, rng, events
            )
        turns_executed += max(1, working.turn_seq - before_turn)
        working = _resolve_negative_cash_players(working, config, events)

    completed = working.phase != "active" or _runner_complete(working, turns_executed)
    if working.phase == "active" and completed:
        working = _apply_runner_command(
            working,
            AdvancePhaseCommand(
                type="advance_phase",
                phase="settling",
                reason="runner_complete",
            ),
            config,
            events,
        )
    if working.phase == "settling":
        working = _apply_runner_command(
            working,
            AdvancePhaseCommand(
                type="advance_phase",
                phase="finished",
                reason="runner_complete",
            ),
            config,
            events,
        )

    final_digest = ""
    replay_digest = ""
    replay_verified = False
    if spec.verify_replay:
        final_digest = state_digest(working)
        replayed = replay_events(initial, events)
        replay_digest = state_digest(replayed)
        replay_verified = replay_digest == final_digest
    return GameRunResult(
        spec=spec,
        initial_state=initial,
        final_state=working,
        events=tuple(events),
        replay_digest=replay_digest,
        final_digest=final_digest,
        replay_checked=spec.verify_replay,
        replay_verified=replay_verified,
        turns_executed=turns_executed,
        completed=working.phase == "finished" and (not spec.verify_replay or replay_verified),
    )


def create_initial_state(
    spec: RunnerSpec,
    config: ConfigSnapshot,
    towns: Sequence[Mapping[str, object]] | None = None,
) -> GameState:
    player_ids = tuple(f"p{index + 1}" for index in range(spec.player_count))
    return start_game(
        spec=GameStartSpec(
            game_id=spec.game_id,
            mode=spec.mode,
            player_ids=player_ids,
            server_seed=spec.seed,
            game_seed=_game_seed(spec.seed),
            target_minutes=spec.target_minutes,
        ),
        config=config,
        towns=towns or synthetic_towns(config),
    )


def replay_event_stream(initial_state: GameState, events: Iterable[Event]) -> tuple[GameState, str]:
    final_state = replay_events(initial_state, tuple(events))
    return final_state, state_digest(final_state)


def command_from_dict(payload: Mapping[str, Any]) -> Command:
    command_type = payload.get("type")
    if command_type == "take_turn":
        return TakeTurnCommand(
            type="take_turn",
            player_id=_string(payload, "player_id"),
            extra_move_steps=_optional_int(payload.get("extra_move_steps")),
        )
    if command_type == "purchase_property":
        return PurchasePropertyCommand(
            type="purchase_property",
            player_id=_string(payload, "player_id"),
            tile_index=_int(payload, "tile_index"),
        )
    if command_type == "place_property_bid":
        return PlacePropertyBidCommand(
            type="place_property_bid",
            player_id=_string(payload, "player_id"),
            tile_index=_int(payload, "tile_index"),
            bid_amount=_int(payload, "bid_amount"),
        )
    if command_type == "run_daily_settlement":
        execute_standing_orders = payload.get("execute_standing_orders", True)
        if not isinstance(execute_standing_orders, bool):
            raise ValueError("execute_standing_orders must be a boolean")
        return RunDailySettlementCommand(
            type="run_daily_settlement",
            execute_standing_orders=execute_standing_orders,
        )
    if command_type == "run_quarterly_affairs":
        choices = payload.get("choices", {})
        if not isinstance(choices, Mapping):
            raise ValueError("choices must be an object")
        return RunQuarterlyAffairsCommand(
            type="run_quarterly_affairs",
            player_id=_string(payload, "player_id"),
            choices=_quarterly_choices_from_dict(choices),
        )
    if command_type == "resolve_cash_shortfall":
        return ResolveCashShortfallCommand(
            type="resolve_cash_shortfall",
            player_id=_string(payload, "player_id"),
        )
    if command_type == "advance_phase":
        phase = _string(payload, "phase")
        if phase not in {"settling", "finished"}:
            raise ValueError("advance_phase supports settling or finished from the CLI")
        return AdvancePhaseCommand(
            type="advance_phase",
            phase=cast(GamePhase, phase),
            reason=_optional_string(payload.get("reason")),
        )
    raise ValueError(f"unsupported command type: {command_type}")


def apply_command_payload(
    state: GameState,
    payload: Mapping[str, Any],
    config: ConfigSnapshot,
) -> Transition:
    return execute_command(state, command_from_dict(payload), config)


def synthetic_towns(config: ConfigSnapshot) -> list[dict[str, object]]:
    board = _mapping(config.get("board"), "config.board")
    towns: list[dict[str, object]] = []
    code = 1
    for region in _list(board.get("regions"), "board.regions"):
        row = _mapping(region, "board.regions[]")
        region_key = _string(row, "key")
        for county in _list(row.get("counties"), "board.regions[].counties"):
            county_name = str(county)
            for offset in range(6):
                tier = offset % 5 + 1
                towns.append(
                    {
                        "code": f"T{code:04d}",
                        "name": f"{county_name}-{offset}",
                        "county": county_name,
                        "region": region_key,
                        "avg_price_per_ping": 50_000 + tier * 100_000 + code,
                        "price_tier": tier,
                        "population": 30_000 + code * 100,
                    }
                )
                code += 1
    return towns


def _run_daily_day(
    state: GameState,
    strategy: StrategyName,
    strategy_offset: int,
    config: ConfigSnapshot,
    rng: random.Random,
    events: list[Event],
) -> GameState:
    working = state
    if working.rolls_per_day is None:
        raise InvalidCommandError("daily runner requires rolls_per_day")
    for player_id in daily_player_order(working):
        if _player_exited(working.player(player_id)):
            continue
        while (
            working.phase == "active"
            and not _player_exited(working.player(player_id))
            and working.player(player_id).rolls_used_today < working.rolls_per_day
        ):
            working = _run_player_turn(
                working, player_id, strategy, strategy_offset, config, rng, events
            )
            working = _resolve_negative_cash_players(working, config, events)
    if working.phase != "active":
        return working
    return _apply_runner_command(
        working,
        RunDailySettlementCommand(
            type="run_daily_settlement",
            execute_standing_orders=False,
        ),
        config,
        events,
    )


def _run_player_turn(
    state: GameState,
    player_id: str,
    strategy: StrategyName,
    strategy_offset: int,
    config: ConfigSnapshot,
    rng: random.Random,
    events: list[Event],
) -> GameState:
    if _player_exited(state.player(player_id)):
        return state
    player_strategy = _player_strategy(strategy, player_id, strategy_offset)
    transition = execute_command(
        state,
        TakeTurnCommand(
            type="take_turn",
            player_id=player_id,
            extra_move_steps=_vehicle_extra_move_steps(state, player_id, player_strategy, config),
        ),
        config,
    )
    events.extend(transition.events)
    return _apply_strategy_after_turn(
        transition.state,
        player_id,
        player_strategy,
        config,
        rng,
        events,
        transition.events,
    )


def _apply_strategy_after_turn(
    state: GameState,
    player_id: str,
    strategy: StrategyName,
    config: ConfigSnapshot,
    rng: random.Random,
    events: list[Event],
    turn_events: Sequence[Event],
) -> GameState:
    working = _maybe_run_quarterly(
        state,
        player_id,
        strategy,
        config,
        rng,
        events,
        turn_events,
    )
    if working.board is None:
        return working
    player = working.player(player_id)
    tile = working.board.tiles[player.position]
    if tile.kind != "property" or working.property_at(tile.index) is not None:
        return working
    if not _strategy_wants_property(strategy, player, tile, rng):
        return working
    try:
        if working.mode == "daily":
            command: Command = PlacePropertyBidCommand(
                type="place_property_bid",
                player_id=player_id,
                tile_index=tile.index,
                bid_amount=_bid_amount(strategy, tile),
            )
        else:
            command = PurchasePropertyCommand(
                type="purchase_property",
                player_id=player_id,
                tile_index=tile.index,
            )
        return _apply_runner_command(working, command, config, events)
    except InvalidCommandError:
        return working


def _maybe_run_quarterly(
    state: GameState,
    player_id: str,
    strategy: StrategyName,
    config: ConfigSnapshot,
    rng: random.Random,
    events: list[Event],
    turn_events: Sequence[Event],
) -> GameState:
    if not any(
        event.type == "quarterly_affairs_triggered" and event.player_id == player_id
        for event in turn_events
    ):
        return state
    choices = QuarterlyChoices()
    if strategy == "stock_education":
        choices = _stock_education_choices(state, player_id, config)
    elif strategy == "vehicle":
        choices = _vehicle_choices(state, player_id, config)
    elif strategy == "random" and rng.random() < 0.5:
        choices = _random_quarterly_choices(state, player_id, config, rng)
    try:
        return _apply_runner_command(
            state,
            RunQuarterlyAffairsCommand(
                type="run_quarterly_affairs",
                player_id=player_id,
                choices=choices,
            ),
            config,
            events,
        )
    except InvalidCommandError:
        return state


def _stock_education_choices(
    state: GameState,
    player_id: str,
    config: ConfigSnapshot,
) -> QuarterlyChoices:
    player = state.player(player_id)
    stock_code = _first_stock_code(config)
    career_change_to = _best_education_career(player, config)
    course_key, tuition = _first_affordable_course(config, player)
    buy_value = 0
    if stock_code is not None and player.cash > 120_000:
        buy_value = min(500_000, max(0, player.cash * 3 // 5))
    return QuarterlyChoices(
        buy_stock_code=stock_code if buy_value > 0 else None,
        buy_stock_value=buy_value,
        education_course_key=(
            course_key if career_change_to is None and tuition <= player.cash - buy_value else None
        ),
        career_change_to=career_change_to,
    )


def _random_quarterly_choices(
    state: GameState,
    player_id: str,
    config: ConfigSnapshot,
    rng: random.Random,
) -> QuarterlyChoices:
    player = state.player(player_id)
    stock_code = _first_stock_code(config)
    if stock_code is None or player.cash <= 100_000:
        return QuarterlyChoices()
    return QuarterlyChoices(
        buy_stock_code=stock_code if rng.random() < 0.5 else None,
        buy_stock_value=min(50_000, max(0, player.cash // 5)),
    )


def _vehicle_choices(
    state: GameState,
    player_id: str,
    config: ConfigSnapshot,
) -> QuarterlyChoices:
    player = state.player(player_id)
    vehicle_key, price = _first_affordable_vehicle(config, player)
    if vehicle_key is None:
        return QuarterlyChoices()
    return QuarterlyChoices(vehicle_key=vehicle_key if player.cash - price >= 80_000 else None)


def _vehicle_extra_move_steps(
    state: GameState,
    player_id: str,
    strategy: StrategyName,
    config: ConfigSnapshot,
) -> int:
    if strategy != "vehicle":
        return 0
    player = state.player(player_id)
    return max(
        (
            _int_value(vehicle.get("move_choice_extra"), "vehicle.move_choice_extra")
            for vehicle in _vehicle_rows(config)
            if vehicle.get("key") in player.vehicles
        ),
        default=0,
    )


def _resolve_negative_cash_players(
    state: GameState,
    config: ConfigSnapshot,
    events: list[Event],
) -> GameState:
    working = state
    for player in working.players:
        if working.phase != "active":
            return working
        if player.cash < 0 and not player.is_bankrupt and not player.has_quit:
            working = _apply_runner_command(
                working,
                ResolveCashShortfallCommand(
                    type="resolve_cash_shortfall",
                    player_id=player.id,
                    reason="runner_cash_shortfall",
                ),
                config,
                events,
            )
    return working


def _player_exited(player: PlayerState) -> bool:
    return player.is_bankrupt or player.has_quit


def _seed_runner_alliances(
    state: GameState,
    strategy: StrategyName,
    config: ConfigSnapshot,
    events: list[Event],
) -> GameState:
    if strategy not in {"alliance", "mixed"} or len(state.players) < 4:
        return state

    working = state
    pair_count = max(1, len(state.players) // 4)
    for pair_index in range(pair_count):
        left_index = pair_index * 2
        right_index = left_index + 1
        if right_index >= len(working.players):
            break
        left = working.players[left_index].id
        right = working.players[right_index].id
        proposal_id = f"runner-alliance-{pair_index + 1}"
        try:
            working = _apply_runner_command(
                working,
                ProposeAllianceCommand(
                    type="propose_alliance",
                    from_player_id=left,
                    to_player_id=right,
                    tier="couple",
                    proposal_id=proposal_id,
                ),
                config,
                events,
            )
            working = _apply_runner_command(
                working,
                RespondAllianceProposalCommand(
                    type="respond_alliance_proposal",
                    proposal_id=proposal_id,
                    accepted=True,
                    alliance_id=f"runner-alliance:{pair_index + 1}",
                ),
                config,
                events,
            )
        except InvalidCommandError:
            continue
    return working


def player_strategy(
    global_strategy: StrategyName, player_id: str, strategy_offset: int = 0
) -> StrategyName:
    return _player_strategy(global_strategy, player_id, strategy_offset)


def _player_strategy(
    global_strategy: StrategyName, player_id: str, strategy_offset: int
) -> StrategyName:
    if global_strategy != "mixed":
        return global_strategy
    cycle: tuple[StrategyName, ...] = (
        "conservative",
        "aggressive",
        "stock_education",
        "vehicle",
        "random",
    )
    suffix = "".join(char for char in player_id if char.isdigit())
    index = int(suffix) - 1 if suffix else sum(ord(char) for char in player_id)
    return cycle[(index + strategy_offset) % len(cycle)]


def _apply_runner_command(
    state: GameState,
    command: Command,
    config: ConfigSnapshot,
    events: list[Event],
) -> GameState:
    transition = execute_command(state, command, config)
    events.extend(transition.events)
    return transition.state


def _runner_complete(state: GameState, turns_executed: int) -> bool:
    if state.phase != "active":
        return True
    if state.day_limit is not None and state.day > state.day_limit:
        return True
    if state.lap_limit > 0 and any(player.lap >= state.lap_limit for player in state.players):
        return True
    if state.net_worth_threshold > 0:
        return any(
            player_net_worth(state, player.id) >= state.net_worth_threshold
            for player in state.players
        )
    alive_count = sum(
        1 for player in state.players if not player.is_bankrupt and not player.has_quit
    )
    return turns_executed > 0 and alive_count <= 1


def _next_blitz_player_id(state: GameState) -> str:
    alive = [
        player_id
        for player_id in state.base_turn_order
        if not state.player(player_id).is_bankrupt and not state.player(player_id).has_quit
    ]
    if not alive:
        raise InvalidCommandError("no active players remain")
    return alive[state.turn_seq % len(alive)]


def daily_player_order(state: GameState) -> tuple[str, ...]:
    if state.mode != "daily":
        return state.base_turn_order
    # The simulation scheduler must not give a stable base-order seat first access every day.
    rng = random.Random(f"{state.server_seed}:{state.id}:daily-order:{state.day}")
    order = list(state.base_turn_order)
    rng.shuffle(order)
    return tuple(order)


def _strategy_wants_property(
    strategy: StrategyName,
    player: PlayerState,
    tile: BoardTile,
    rng: random.Random,
) -> bool:
    base_price = tile.base_price or 0
    if strategy == "aggressive":
        return player.cash >= base_price
    if strategy == "conservative":
        return player.cash - base_price >= 150_000
    if strategy == "stock_education":
        return player.cash - base_price >= 75_000
    return player.cash >= base_price and rng.random() < 0.5


def _bid_amount(strategy: StrategyName, tile: BoardTile) -> int:
    base_price = tile.base_price or 0
    if strategy == "aggressive":
        return round(base_price * 1.10)
    if strategy == "random":
        return round(base_price * 0.95)
    return base_price


def _first_stock_code(config: ConfigSnapshot) -> str | None:
    stocks = _mapping(config.get("stocks"), "config.stocks")
    for key in ("equities", "etfs_passive", "etfs_active"):
        for raw_stock in _list(stocks.get(key, []), f"stocks.{key}"):
            stock = _mapping(raw_stock, "stock")
            code = stock.get("code")
            if isinstance(code, str) and code:
                return code
    return None


def _first_affordable_course(
    config: ConfigSnapshot,
    player: PlayerState,
) -> tuple[str | None, int]:
    occupations = _mapping(config.get("occupations"), "config.occupations")
    education = _mapping(occupations.get("education"), "occupations.education")
    for raw_course in _list(education.get("courses", []), "education.courses"):
        course = _mapping(raw_course, "course")
        key = course.get("key")
        tuition = course.get("tuition")
        unlocked_tier = course.get("unlocks_tier")
        if (
            isinstance(key, str)
            and isinstance(tuition, int)
            and isinstance(unlocked_tier, int)
            and unlocked_tier > (player.education_unlocked_tier or 0)
            and player.cash >= tuition
        ):
            return key, tuition
    return None, 0


def _best_education_career(player: PlayerState, config: ConfigSnapshot) -> str | None:
    unlocked_tier = player.education_unlocked_tier
    if unlocked_tier is None:
        return None
    occupations = _mapping(config.get("occupations"), "config.occupations")
    rows = [
        _mapping(row, "occupation") for row in _list(occupations.get("occupations"), "occupations")
    ]
    current_tier = next(
        (
            _int_value(row.get("tier"), "occupation.tier")
            for row in rows
            if row.get("key") == player.occupation_key
        ),
        1,
    )
    eligible = [
        row
        for row in rows
        if current_tier < _int_value(row.get("tier"), "occupation.tier") <= unlocked_tier
    ]
    if not eligible:
        return None
    target = max(
        eligible,
        key=lambda row: (
            _int_value(row.get("monthly_salary"), "occupation.monthly_salary"),
            _string(row, "key"),
        ),
    )
    return _string(target, "key")


def _first_affordable_vehicle(
    config: ConfigSnapshot,
    player: PlayerState,
) -> tuple[str | None, int]:
    for vehicle in _vehicle_rows(config):
        key = vehicle.get("key")
        price = vehicle.get("price")
        if (
            isinstance(key, str)
            and key != "none"
            and key not in player.vehicles
            and isinstance(price, int)
            and player.cash >= price
        ):
            return key, price
    return None, 0


def _vehicle_rows(config: ConfigSnapshot) -> list[Mapping[str, object]]:
    vehicles = _mapping(config.get("vehicles"), "config.vehicles")
    return [
        _mapping(vehicle, "vehicle")
        for vehicle in _list(vehicles.get("vehicles"), "vehicles.vehicles")
    ]


def _quarterly_choices_from_dict(payload: Mapping[str, Any]) -> QuarterlyChoices:
    return QuarterlyChoices(
        buy_stock_code=_optional_string(payload.get("buy_stock_code")),
        buy_stock_value=_optional_int(payload.get("buy_stock_value")),
        sell_stock_code=_optional_string(payload.get("sell_stock_code")),
        sell_stock_value=_optional_int(payload.get("sell_stock_value")),
        open_loan_product_key=_optional_string(payload.get("open_loan_product_key")),
        open_loan_amount=_optional_int(payload.get("open_loan_amount")),
        education_course_key=_optional_string(payload.get("education_course_key")),
        career_change_to=_optional_string(payload.get("career_change_to")),
        vehicle_key=_optional_string(payload.get("vehicle_key")),
        insurance_policy_key=_optional_string(payload.get("insurance_policy_key")),
    )


def _game_seed(seed: str) -> int:
    return sum((index + 1) * ord(char) for index, char in enumerate(seed))


def _mapping(value: object, path: str) -> Mapping[str, object]:
    if not isinstance(value, Mapping):
        raise ValueError(f"{path} must be an object")
    return value


def _list(value: object, path: str) -> list[object]:
    if not isinstance(value, list):
        raise ValueError(f"{path} must be a list")
    return value


def _string(payload: Mapping[str, Any], key: str) -> str:
    value = payload.get(key)
    if not isinstance(value, str) or not value:
        raise ValueError(f"{key} must be a non-empty string")
    return value


def _optional_string(value: object) -> str | None:
    if value is None:
        return None
    if not isinstance(value, str):
        raise ValueError("expected a string or null")
    return value


def _int(payload: Mapping[str, Any], key: str) -> int:
    value = payload.get(key)
    if isinstance(value, bool) or not isinstance(value, int):
        raise ValueError(f"{key} must be an integer")
    return value


def _int_value(value: object, field_name: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise ValueError(f"{field_name} must be an integer")
    return value


def _optional_int(value: object) -> int:
    if value is None:
        return 0
    if isinstance(value, bool) or not isinstance(value, int):
        raise ValueError("expected an integer or null")
    return value
