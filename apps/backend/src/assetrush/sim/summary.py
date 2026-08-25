"""Structured summaries for M3 simulation output."""

from __future__ import annotations

import traceback
from collections import Counter
from collections.abc import Mapping, Sequence
from dataclasses import asdict, dataclass
from typing import Any

from assetrush.engine import player_net_worth
from assetrush.engine.events import Event
from assetrush.engine.state import GameState, Money
from assetrush.sim.runner import GameRunResult, RunnerSpec, daily_player_order, player_strategy


@dataclass(frozen=True, slots=True)
class PlayerRunSummary:
    player_id: str
    strategy: str
    initial_turn_order_index: int
    initial_background_key: str | None
    initial_occupation_key: str | None
    initial_cash: Money
    initial_net_worth: Money
    initial_monthly_salary: Money
    initial_has_vehicle: bool
    final_cash: Money
    final_net_worth: Money
    final_rank: int
    final_lap: int
    final_property_count: int
    final_stock_value: Money
    final_debt: Money
    bankrupt: bool
    alliance_member: bool
    vehicle_ever_owned: bool
    education_started: bool
    education_completed: bool
    education_effective: bool
    property_ever_owned: bool


@dataclass(frozen=True, slots=True)
class BidRunSummary:
    player_id: str
    won: bool
    bid_amount: Money
    base_price: Money
    premium_ratio: float
    high_cash_player: bool
    contested: bool = False


@dataclass(frozen=True, slots=True)
class GameRunSummary:
    game_id: str
    mode: str
    player_count: int
    seed: str
    strategy: str
    target_minutes: int | None
    max_turns: int
    completed: bool
    replay_checked: bool
    replay_verified: bool
    failed: bool
    error: str | None
    turns_executed: int
    event_count: int
    final_phase: str | None
    day: int | None
    day_limit: int | None
    lap_limit: int | None
    net_worth_threshold: Money | None
    max_lap: int
    end_reason: str
    event_counts: dict[str, int]
    confinement_counts: dict[str, int]
    first_bankruptcy_day: int | None
    players: tuple[PlayerRunSummary, ...]
    bids: tuple[BidRunSummary, ...]

    def to_json_dict(self) -> dict[str, Any]:
        return asdict(self)


def summarize_game_result(result: GameRunResult) -> GameRunSummary:
    event_counts: Counter[str] = Counter(event.type for event in result.events)
    final = result.final_state
    players = _player_summaries(result)
    return GameRunSummary(
        game_id=result.spec.game_id,
        mode=result.spec.mode,
        player_count=result.spec.player_count,
        seed=result.spec.seed,
        strategy=result.spec.strategy,
        target_minutes=result.spec.target_minutes,
        max_turns=result.spec.max_turns,
        completed=result.completed,
        replay_checked=result.replay_checked,
        replay_verified=result.replay_verified,
        failed=False,
        error=None,
        turns_executed=result.turns_executed,
        event_count=len(result.events),
        final_phase=final.phase,
        day=final.day,
        day_limit=final.day_limit,
        lap_limit=final.lap_limit,
        net_worth_threshold=final.net_worth_threshold,
        max_lap=max((player.lap for player in final.players), default=0),
        end_reason=_end_reason(final, event_counts),
        event_counts=dict(sorted(event_counts.items())),
        confinement_counts=_confinement_counts(result.events),
        first_bankruptcy_day=_first_bankruptcy_day(result.events),
        players=players,
        bids=_bid_summaries(result),
    )


def game_summary_from_json_dict(payload: Mapping[str, Any]) -> GameRunSummary:
    players = tuple(
        PlayerRunSummary(**_dict(row, "players[]"))
        for row in _list(payload.get("players"), "players")
    )
    bids = tuple(
        BidRunSummary(**_dict(row, "bids[]")) for row in _list(payload.get("bids"), "bids")
    )
    return GameRunSummary(
        game_id=_string(payload.get("game_id"), "game_id"),
        mode=_string(payload.get("mode"), "mode"),
        player_count=_int(payload.get("player_count"), "player_count"),
        seed=_string(payload.get("seed"), "seed"),
        strategy=_string(payload.get("strategy"), "strategy"),
        target_minutes=_optional_int(payload.get("target_minutes"), "target_minutes"),
        max_turns=_int(payload.get("max_turns"), "max_turns"),
        completed=_bool(payload.get("completed"), "completed"),
        replay_checked=_bool(payload.get("replay_checked"), "replay_checked"),
        replay_verified=_bool(payload.get("replay_verified"), "replay_verified"),
        failed=_bool(payload.get("failed"), "failed"),
        error=_optional_string(payload.get("error"), "error"),
        turns_executed=_int(payload.get("turns_executed"), "turns_executed"),
        event_count=_int(payload.get("event_count"), "event_count"),
        final_phase=_optional_string(payload.get("final_phase"), "final_phase"),
        day=_optional_int(payload.get("day"), "day"),
        day_limit=_optional_int(payload.get("day_limit"), "day_limit"),
        lap_limit=_optional_int(payload.get("lap_limit"), "lap_limit"),
        net_worth_threshold=_optional_int(
            payload.get("net_worth_threshold"), "net_worth_threshold"
        ),
        max_lap=_int(payload.get("max_lap"), "max_lap"),
        end_reason=_string(payload.get("end_reason"), "end_reason"),
        event_counts=_int_dict(payload.get("event_counts"), "event_counts"),
        confinement_counts=_int_dict(payload.get("confinement_counts"), "confinement_counts"),
        first_bankruptcy_day=_optional_int(
            payload.get("first_bankruptcy_day"), "first_bankruptcy_day"
        ),
        players=players,
        bids=bids,
    )


def failed_game_summary(spec: RunnerSpec, exc: BaseException) -> GameRunSummary:
    return GameRunSummary(
        game_id=spec.game_id,
        mode=spec.mode,
        player_count=spec.player_count,
        seed=spec.seed,
        strategy=spec.strategy,
        target_minutes=spec.target_minutes,
        max_turns=spec.max_turns,
        completed=False,
        replay_checked=spec.verify_replay,
        replay_verified=False,
        failed=True,
        error="".join(traceback.format_exception_only(type(exc), exc)).strip(),
        turns_executed=0,
        event_count=0,
        final_phase=None,
        day=None,
        day_limit=None,
        lap_limit=None,
        net_worth_threshold=None,
        max_lap=0,
        end_reason="failed",
        event_counts={},
        confinement_counts={},
        first_bankruptcy_day=None,
        players=(),
        bids=(),
    )


def summarize_many(summaries: Sequence[GameRunSummary]) -> dict[str, object]:
    completed = [summary for summary in summaries if summary.completed]
    failed = [summary for summary in summaries if summary.failed]
    event_counts: Counter[str] = Counter()
    for summary in summaries:
        event_counts.update(summary.event_counts)
    return {
        "games": len(summaries),
        "completed_games": len(completed),
        "failed_games": len(failed),
        "modes": dict(Counter(summary.mode for summary in summaries)),
        "strategies": dict(Counter(summary.strategy for summary in summaries)),
        "event_counts": dict(sorted(event_counts.items())),
    }


def _player_summaries(result: GameRunResult) -> tuple[PlayerRunSummary, ...]:
    initial_by_id = {player.id: player for player in result.initial_state.players}
    final_by_id = {player.id: player for player in result.final_state.players}
    ranks = _final_ranks(result.final_state)
    vehicle_players = _event_player_ids(
        result.events,
        {"vehicle_purchased", "vehicle_liquidated"},
        "player_id",
    )
    education_started = _event_player_ids(result.events, {"education_started"}, "player_id")
    education_completed = _event_player_ids(
        [
            event
            for event in result.events
            if event.type == "education_progressed" and event.completed
        ],
        {"education_progressed"},
        "player_id",
    )
    education_effective = _event_player_ids(
        [
            event
            for event in result.events
            if event.type == "education_progressed" and event.effective
        ],
        {"education_progressed"},
        "player_id",
    )
    property_buyers = _event_player_ids(
        result.events,
        {"property_purchased", "bid_won"},
        "player_id",
    )
    effective_order = (
        daily_player_order(result.initial_state)
        if result.initial_state.mode == "daily"
        else result.initial_state.base_turn_order
    )
    turn_order_index = {player_id: index for index, player_id in enumerate(effective_order)}

    players: list[PlayerRunSummary] = []
    for player_id, final_player in final_by_id.items():
        initial_player = initial_by_id[player_id]
        players.append(
            PlayerRunSummary(
                player_id=player_id,
                strategy=player_strategy(
                    result.spec.strategy, player_id, result.spec.strategy_offset
                ),
                initial_turn_order_index=turn_order_index.get(player_id, -1),
                initial_background_key=initial_player.background_key,
                initial_occupation_key=initial_player.occupation_key,
                initial_cash=initial_player.cash,
                initial_net_worth=player_net_worth(result.initial_state, player_id),
                initial_monthly_salary=initial_player.monthly_salary,
                initial_has_vehicle=bool(initial_player.vehicles),
                final_cash=final_player.cash,
                final_net_worth=player_net_worth(result.final_state, player_id),
                final_rank=ranks[player_id],
                final_lap=final_player.lap,
                final_property_count=len(final_player.property_tile_indices),
                final_stock_value=sum(holding.value for holding in final_player.stock_holdings),
                final_debt=sum(loan.principal for loan in final_player.loans),
                bankrupt=final_player.is_bankrupt or final_player.has_quit,
                alliance_member=final_player.alliance_id is not None,
                vehicle_ever_owned=bool(initial_player.vehicles)
                or bool(final_player.vehicles)
                or player_id in vehicle_players,
                education_started=player_id in education_started,
                education_completed=player_id in education_completed,
                education_effective=player_id in education_effective,
                property_ever_owned=bool(initial_player.property_tile_indices)
                or bool(final_player.property_tile_indices)
                or player_id in property_buyers,
            )
        )
    return tuple(sorted(players, key=lambda player: player.player_id))


def _bid_summaries(result: GameRunResult) -> tuple[BidRunSummary, ...]:
    if result.final_state.board is None:
        return ()
    high_cash_players = _high_cash_players(result.initial_state)
    bid_events = [event for event in result.events if event.type in {"bid_won", "bid_lost"}]
    contested_auctions = {
        (event.tile_index, event.day)
        for event in bid_events
        if sum(
            1
            for candidate in bid_events
            if candidate.tile_index == event.tile_index and candidate.day == event.day
        )
        > 1
    }
    bids: list[BidRunSummary] = []
    for event in bid_events:
        base_price = (
            event.base_price
            if event.type == "bid_won"
            else result.final_state.board.tiles[event.tile_index].base_price or 0
        )
        premium = (event.bid_amount - base_price) / base_price if base_price > 0 else 0.0
        bids.append(
            BidRunSummary(
                player_id=event.player_id,
                won=event.type == "bid_won",
                bid_amount=event.bid_amount,
                base_price=base_price,
                premium_ratio=premium,
                high_cash_player=event.player_id in high_cash_players,
                contested=(event.tile_index, event.day) in contested_auctions,
            )
        )
    return tuple(bids)


def _high_cash_players(state: GameState) -> set[str]:
    ranked = sorted(
        ((player_net_worth(state, player.id), player.cash, player.id) for player in state.players),
        key=lambda row: (-row[0], -row[1], row[2]),
    )
    if not ranked:
        return set()
    top_count = max(1, len(ranked) // 4)
    return {player_id for _net_worth, _cash, player_id in ranked[:top_count]}


def _final_ranks(state: GameState) -> dict[str, int]:
    ranked = sorted(
        ((player_net_worth(state, player.id), player.id) for player in state.players),
        key=lambda row: (-row[0], row[1]),
    )
    return {player_id: index + 1 for index, (_net_worth, player_id) in enumerate(ranked)}


def _event_player_ids(events: Sequence[Event], event_types: set[str], field: str) -> set[str]:
    ids: set[str] = set()
    for event in events:
        if event.type in event_types:
            value = getattr(event, field, None)
            if isinstance(value, str):
                ids.add(value)
    return ids


def _end_reason(state: GameState, event_counts: Mapping[str, int]) -> str:
    if event_counts.get("bankruptcy_threshold_reached", 0) > 0:
        return "bankruptcy_threshold"
    if state.net_worth_threshold > 0 and any(
        player_net_worth(state, player.id) >= state.net_worth_threshold for player in state.players
    ):
        return "net_worth_threshold"
    if state.day_limit is not None and state.day > state.day_limit:
        return "day_limit"
    if state.lap_limit > 0 and any(player.lap >= state.lap_limit for player in state.players):
        return "lap_limit"
    if state.phase == "finished":
        return "finished"
    return "max_turns"


def _confinement_counts(events: Sequence[Event]) -> dict[str, int]:
    counts: Counter[str] = Counter()
    for event in events:
        if event.type == "player_confined":
            counts[event.kind] += 1
    return dict(sorted(counts.items()))


def _first_bankruptcy_day(events: Sequence[Event]) -> int | None:
    days = [event.day for event in events if event.type == "player_bankrupted"]
    return min(days) if days else None


def _dict(value: object, path: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise ValueError(f"{path} must be an object")
    return value


def _list(value: object, path: str) -> list[object]:
    if not isinstance(value, list):
        raise ValueError(f"{path} must be a list")
    return value


def _string(value: object, path: str) -> str:
    if not isinstance(value, str):
        raise ValueError(f"{path} must be a string")
    return value


def _optional_string(value: object, path: str) -> str | None:
    if value is None:
        return None
    return _string(value, path)


def _int(value: object, path: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise ValueError(f"{path} must be an integer")
    return value


def _optional_int(value: object, path: str) -> int | None:
    if value is None:
        return None
    return _int(value, path)


def _bool(value: object, path: str) -> bool:
    if not isinstance(value, bool):
        raise ValueError(f"{path} must be a boolean")
    return value


def _int_dict(value: object, path: str) -> dict[str, int]:
    data = _dict(value, path)
    return {key: _int(item, f"{path}.{key}") for key, item in data.items()}
