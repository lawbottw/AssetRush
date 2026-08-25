"""Replay-based verification for persisted games and their read models."""

from __future__ import annotations

import hashlib
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from decimal import Decimal
from typing import Any
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.engine import RowMapping
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from assetrush.engine.errors import EngineError
from assetrush.engine.event_codec import event_from_dict
from assetrush.engine.replay import replay_events, state_digest
from assetrush.persistence import state_from_dict, state_to_dict


class GameVerificationError(RuntimeError):
    def __init__(self, mismatches: Sequence[str]) -> None:
        self.mismatches = tuple(mismatches)
        super().__init__("persisted game verification failed:\n- " + "\n- ".join(self.mismatches))


@dataclass(frozen=True, slots=True)
class VerificationReport:
    game_id: UUID
    event_count: int
    final_event_seq: int
    digest_sha256: str


async def verify_game(
    sessions: async_sessionmaker[AsyncSession], game_id: UUID
) -> VerificationReport:
    async with sessions() as session:
        row = (
            (
                await session.execute(
                    text(
                        """
                    select g.status::text as status, g.engine_turn_seq,
                           g.current_event_seq, g.rng_seq, g.current_day, g.treasury,
                           s.initial_state, s.current_state,
                           s.initial_digest, s.current_digest
                      from public.games g
                      join public.game_snapshots s on s.game_id = g.id
                     where g.id = :game_id
                    """
                    ),
                    {"game_id": game_id},
                )
            )
            .mappings()
            .one_or_none()
        )
        if row is None:
            raise GameVerificationError((f"game not found: {game_id}",))
        event_rows = (
            (
                await session.execute(
                    text(
                        """
                    select event_seq, payload
                      from public.game_events
                     where game_id = :game_id
                     order by event_seq
                    """
                    ),
                    {"game_id": game_id},
                )
            )
            .mappings()
            .all()
        )
        player_rows = (
            (
                await session.execute(
                    text(
                        """
                    select user_id::text as player_id, cash, frozen_cash, position, lap,
                           rolls_used_today, is_blacklisted, is_bankrupt, has_quit
                      from public.game_players
                     where game_id = :game_id
                    """
                    ),
                    {"game_id": game_id},
                )
            )
            .mappings()
            .all()
        )
        property_rows = (
            (
                await session.execute(
                    text(
                        """
                    select p.tile_idx, gp.user_id::text as owner_id, p.level, p.invested,
                           p.is_mortgaged
                      from public.properties p
                      join public.game_players gp
                        on gp.game_id = p.game_id and gp.id = p.owner_id
                     where p.game_id = :game_id and p.owner_id is not null
                    """
                    ),
                    {"game_id": game_id},
                )
            )
            .mappings()
            .all()
        )
        holding_rows = (
            (
                await session.execute(
                    text(
                        """
                    select gp.user_id::text as player_id, h.stock_code, h.value
                      from public.holdings h
                      join public.game_players gp
                        on gp.game_id = h.game_id and gp.id = h.player_id
                     where h.game_id = :game_id
                    """
                    ),
                    {"game_id": game_id},
                )
            )
            .mappings()
            .all()
        )

    mismatches: list[str] = []
    initial_payload = _object(row["initial_state"], "initial_state", mismatches)
    current_payload = _object(row["current_state"], "current_state", mismatches)
    if initial_payload is None or current_payload is None:
        raise GameVerificationError(mismatches)

    try:
        initial = state_from_dict(initial_payload)
        current = state_from_dict(current_payload)
    except (TypeError, ValueError) as exc:
        raise GameVerificationError((f"snapshot decode: {exc}",)) from exc

    initial_digest = state_digest(initial)
    if row["initial_digest"] != initial_digest:
        mismatches.append("initial_digest differs from canonical initial_state")

    expected_sequences = list(range(initial.event_seq + 1, initial.event_seq + len(event_rows) + 1))
    actual_sequences = [int(event_row["event_seq"]) for event_row in event_rows]
    if actual_sequences != expected_sequences:
        mismatches.append(
            f"game_events.event_seq expected {expected_sequences[:5]}... "
            f"but got {actual_sequences[:5]}..."
        )

    events = []
    for index, event_row in enumerate(event_rows):
        payload = _object(event_row["payload"], f"events[{index}].payload", mismatches)
        if payload is None:
            continue
        if payload.get("seq") != event_row["event_seq"]:
            mismatches.append(
                f"events[{index}].payload.seq expected {event_row['event_seq']!r}, "
                f"got {payload.get('seq')!r}"
            )
        try:
            events.append(event_from_dict(payload))
        except (EngineError, TypeError, ValueError) as exc:
            mismatches.append(f"events[{index}] decode: {exc}")

    replayed = initial
    if len(events) == len(event_rows):
        try:
            replayed = replay_events(initial, tuple(events))
        except (EngineError, TypeError, ValueError) as exc:
            mismatches.append(f"event replay: {exc}")

    replayed_digest = state_digest(replayed)
    if row["current_digest"] != replayed_digest:
        mismatches.append("current_digest differs from replayed canonical digest")
    _diff(state_to_dict(replayed), current_payload, "current_state", mismatches)
    _diff(state_to_dict(current), current_payload, "decoded_current_state", mismatches)
    _compare_game_projection(row, replayed, mismatches)
    _compare_player_projection(player_rows, replayed.players, mismatches)
    _compare_property_projection(property_rows, replayed.properties, mismatches)
    _compare_holding_projection(holding_rows, replayed.players, mismatches)

    if mismatches:
        raise GameVerificationError(mismatches[:30])
    return VerificationReport(
        game_id=game_id,
        event_count=len(events),
        final_event_seq=replayed.event_seq,
        digest_sha256=hashlib.sha256(replayed_digest.encode()).hexdigest(),
    )


def _compare_game_projection(row: RowMapping, state: Any, mismatches: list[str]) -> None:
    expected = {
        "status": state.phase,
        "engine_turn_seq": state.turn_seq,
        "current_event_seq": state.event_seq,
        "rng_seq": state.rng_seq,
        "current_day": state.day,
        "treasury": state.treasury,
    }
    actual = {key: _plain(row[key]) for key in expected}
    _diff(expected, actual, "games", mismatches)


def _compare_player_projection(
    rows: Sequence[RowMapping], players: Sequence[Any], mismatches: list[str]
) -> None:
    expected = {
        player.id: {
            "cash": player.cash,
            "frozen_cash": player.frozen_cash,
            "position": player.position,
            "lap": player.lap,
            "rolls_used_today": player.rolls_used_today,
            "is_blacklisted": player.is_blacklisted,
            "is_bankrupt": player.is_bankrupt,
            "has_quit": player.has_quit,
        }
        for player in players
    }
    actual = {
        str(row["player_id"]): {
            key: _plain(row[key])
            for key in (
                "cash",
                "frozen_cash",
                "position",
                "lap",
                "rolls_used_today",
                "is_blacklisted",
                "is_bankrupt",
                "has_quit",
            )
        }
        for row in rows
    }
    _diff(expected, actual, "game_players", mismatches)


def _compare_property_projection(
    rows: Sequence[RowMapping], properties: Sequence[Any], mismatches: list[str]
) -> None:
    expected = {
        item.tile_index: {
            "owner_id": item.owner_id,
            "level": item.level,
            "invested": item.invested,
            "is_mortgaged": item.mortgaged,
        }
        for item in properties
    }
    actual = {
        int(row["tile_idx"]): {
            "owner_id": str(row["owner_id"]),
            "level": int(row["level"]),
            "invested": int(row["invested"]),
            "is_mortgaged": bool(row["is_mortgaged"]),
        }
        for row in rows
    }
    _diff(expected, actual, "properties", mismatches)


def _compare_holding_projection(
    rows: Sequence[RowMapping], players: Sequence[Any], mismatches: list[str]
) -> None:
    expected = {
        f"{player.id}:{holding.code}": holding.value
        for player in players
        for holding in player.stock_holdings
    }
    actual = {f"{row['player_id']}:{row['stock_code']}": int(row["value"]) for row in rows}
    _diff(expected, actual, "holdings", mismatches)


def _object(value: object, label: str, mismatches: list[str]) -> dict[str, Any] | None:
    if not isinstance(value, dict):
        mismatches.append(f"{label} must be a JSON object")
        return None
    return value


def _plain(value: object) -> object:
    if isinstance(value, Decimal):
        return int(value)
    return value


def _diff(expected: object, actual: object, path: str, output: list[str]) -> None:
    if len(output) >= 30:
        return
    if isinstance(expected, Mapping) and isinstance(actual, Mapping):
        for key in sorted(set(expected) | set(actual), key=str):
            child = f"{path}.{key}"
            if key not in expected:
                output.append(f"{child} unexpected value {_short(actual[key])}")
            elif key not in actual:
                output.append(f"{child} missing; expected {_short(expected[key])}")
            else:
                _diff(expected[key], actual[key], child, output)
        return
    if isinstance(expected, list) and isinstance(actual, list):
        if len(expected) != len(actual):
            output.append(f"{path}.length expected {len(expected)}, got {len(actual)}")
        for index, (expected_item, actual_item) in enumerate(zip(expected, actual, strict=False)):
            _diff(expected_item, actual_item, f"{path}[{index}]", output)
        return
    if expected != actual:
        output.append(f"{path} expected {_short(expected)}, got {_short(actual)}")


def _short(value: object) -> str:
    rendered = repr(value)
    return rendered if len(rendered) <= 120 else rendered[:117] + "..."
