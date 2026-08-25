from __future__ import annotations

import asyncio
import json
import os
from pathlib import Path
from uuid import UUID, uuid4

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from assetrush.config_bundle import load_config_bundle
from assetrush.engine import (
    AdjustPlayerCashAction,
    ApplyActionCommand,
    TakeTurnCommand,
    state_digest,
)
from assetrush.engine.setup import GameStartSpec, start_game
from assetrush.services import GameStore, StaleTurnError
from assetrush.sim.runner import synthetic_towns

REPO_ROOT = Path(__file__).resolve().parents[3]
TEST_DATABASE_URL = os.getenv("ASSETRUSH_TEST_DATABASE_URL")

pytestmark = pytest.mark.skipif(
    not TEST_DATABASE_URL,
    reason="ASSETRUSH_TEST_DATABASE_URL is required for PostgreSQL integration tests",
)


class InjectedFailure(RuntimeError):
    pass


class FailingGameStore(GameStore):
    async def _after_events_appended(self, session: AsyncSession) -> None:
        raise InjectedFailure


class BarrierGameStore(GameStore):
    def __init__(self, sessions: async_sessionmaker[AsyncSession]) -> None:
        super().__init__(sessions)
        self._arrivals = 0
        self._arrival_lock = asyncio.Lock()
        self._both_arrived = asyncio.Event()

    async def _after_events_appended(self, session: AsyncSession) -> None:
        async with self._arrival_lock:
            self._arrivals += 1
            if self._arrivals == 2:
                self._both_arrived.set()
        await asyncio.wait_for(self._both_arrived.wait(), timeout=2)


@pytest.mark.asyncio
async def test_game_store_persists_events_snapshots_and_materialized_state() -> None:
    assert TEST_DATABASE_URL is not None
    engine = create_async_engine(TEST_DATABASE_URL)
    sessions = async_sessionmaker(engine, expire_on_commit=False)
    store = GameStore(sessions)
    game_id, player_ids = await _create_game_fixture(sessions, store, "store-round-trip")
    try:
        before = await store.get_game(game_id)
        command = TakeTurnCommand(type="take_turn", player_id=str(player_ids[0]))

        persisted = await store.execute(game_id, expected_turn_seq=0, command=command)
        reloaded = await store.get_game(game_id)

        assert persisted.version == 1
        assert reloaded.version == 1
        assert state_digest(reloaded.state) == state_digest(persisted.state)
        assert len(persisted.events) > 0
        async with sessions() as session:
            assert await session.scalar(
                text("select count(*) from public.game_events where game_id = :game_id"),
                {"game_id": game_id},
            ) == len(persisted.events)
            row = (
                await session.execute(
                    text(
                        """
                        select position, cash
                          from public.game_players
                         where game_id = :game_id and user_id = :player_id
                        """
                    ),
                    {"game_id": game_id, "player_id": player_ids[0]},
                )
            ).one()
            player = persisted.state.player(str(player_ids[0]))
            assert row.position == player.position
            assert row.cash == player.cash

        with pytest.raises(StaleTurnError) as exc_info:
            await store.execute(game_id, expected_turn_seq=0, command=command)
        assert exc_info.value.actual == 1
        assert state_digest((await store.get_game(game_id)).state) == state_digest(persisted.state)
        assert state_digest(before.state) != state_digest(persisted.state)

        engine_turn_seq = persisted.state.turn_seq
        non_turn = await store.execute(
            game_id,
            expected_turn_seq=1,
            command=ApplyActionCommand(
                type="apply_action",
                action=AdjustPlayerCashAction(
                    type="adjust_player_cash",
                    player_id=str(player_ids[1]),
                    delta=1,
                ),
            ),
        )
        assert non_turn.version == 2
        assert non_turn.state.turn_seq == engine_turn_seq
    finally:
        await _cleanup_game_fixture(sessions, (game_id,), player_ids)
        await engine.dispose()


@pytest.mark.asyncio
async def test_same_game_concurrent_writes_commit_exactly_once() -> None:
    assert TEST_DATABASE_URL is not None
    engine = create_async_engine(TEST_DATABASE_URL, pool_size=4)
    sessions = async_sessionmaker(engine, expire_on_commit=False)
    store = GameStore(sessions)
    game_id, player_ids = await _create_game_fixture(sessions, store, "store-race")
    command = TakeTurnCommand(type="take_turn", player_id=str(player_ids[0]))
    try:
        results = await asyncio.gather(
            store.execute(game_id, expected_turn_seq=0, command=command),
            store.execute(game_id, expected_turn_seq=0, command=command),
            return_exceptions=True,
        )

        assert sum(not isinstance(result, Exception) for result in results) == 1
        stale = [result for result in results if isinstance(result, StaleTurnError)]
        assert len(stale) == 1
        assert (await store.get_game(game_id)).version == 1
        async with sessions() as session:
            event_sequences = (
                await session.scalars(
                    text(
                        """
                        select event_seq from public.game_events
                         where game_id = :game_id order by event_seq
                        """
                    ),
                    {"game_id": game_id},
                )
            ).all()
        assert event_sequences == list(range(1, len(event_sequences) + 1))
    finally:
        await _cleanup_game_fixture(sessions, (game_id,), player_ids)
        await engine.dispose()


@pytest.mark.asyncio
async def test_failure_after_event_append_rolls_back_everything() -> None:
    assert TEST_DATABASE_URL is not None
    engine = create_async_engine(TEST_DATABASE_URL)
    sessions = async_sessionmaker(engine, expire_on_commit=False)
    regular_store = GameStore(sessions)
    failing_store = FailingGameStore(sessions)
    game_id, player_ids = await _create_game_fixture(sessions, regular_store, "store-rollback")
    before = await regular_store.get_game(game_id)
    command = TakeTurnCommand(type="take_turn", player_id=str(player_ids[0]))
    try:
        with pytest.raises(InjectedFailure):
            await failing_store.execute(game_id, expected_turn_seq=0, command=command)

        after = await regular_store.get_game(game_id)
        assert after.version == 0
        assert state_digest(after.state) == state_digest(before.state)
        async with sessions() as session:
            assert (
                await session.scalar(
                    text("select count(*) from public.game_events where game_id = :game_id"),
                    {"game_id": game_id},
                )
                == 0
            )
    finally:
        await _cleanup_game_fixture(sessions, (game_id,), player_ids)
        await engine.dispose()


@pytest.mark.asyncio
async def test_different_games_do_not_share_a_global_lock() -> None:
    assert TEST_DATABASE_URL is not None
    engine = create_async_engine(TEST_DATABASE_URL, pool_size=4)
    sessions = async_sessionmaker(engine, expire_on_commit=False)
    regular_store = GameStore(sessions)
    store = BarrierGameStore(sessions)
    first_game, first_players = await _create_game_fixture(sessions, regular_store, "game-one")
    second_game, second_players = await _create_game_fixture(sessions, regular_store, "game-two")
    try:
        first, second = await asyncio.gather(
            store.execute(
                first_game,
                expected_turn_seq=0,
                command=TakeTurnCommand(type="take_turn", player_id=str(first_players[0])),
            ),
            store.execute(
                second_game,
                expected_turn_seq=0,
                command=TakeTurnCommand(type="take_turn", player_id=str(second_players[0])),
            ),
        )
        assert first.version == second.version == 1
    finally:
        await _cleanup_game_fixture(
            sessions,
            (first_game, second_game),
            (*first_players, *second_players),
        )
        await engine.dispose()


async def _create_game_fixture(
    sessions: async_sessionmaker[AsyncSession],
    store: GameStore,
    seed: str,
) -> tuple[UUID, tuple[UUID, UUID]]:
    config = load_config_bundle(REPO_ROOT / "config").raw
    scale = config["scale"]
    assert isinstance(scale, dict)
    config_version = str(scale["version"])
    game_id = uuid4()
    player_ids = (uuid4(), uuid4())
    async with sessions() as session, session.begin():
        await session.execute(
            text(
                """
                insert into public.game_configs (version, payload)
                values (:version, cast(:payload as jsonb))
                on conflict (version) do update set payload = excluded.payload
                """
            ),
            {"version": config_version, "payload": json.dumps(config)},
        )
        for index, player_id in enumerate(player_ids, start=1):
            await session.execute(
                text("insert into auth.users (id) values (:id)"), {"id": player_id}
            )
            await session.execute(
                text("insert into public.users (id, display_name) values (:id, :display_name)"),
                {"id": player_id, "display_name": f"store-player-{index}"},
            )

    state = start_game(
        spec=GameStartSpec(
            game_id=str(game_id),
            mode="daily",
            player_ids=tuple(str(player_id) for player_id in player_ids),
            server_seed=seed,
            game_seed=42,
        ),
        config=config,
        towns=synthetic_towns(config),
    )
    await store.create_game(state, host_user_id=player_ids[0])
    return game_id, player_ids


async def _cleanup_game_fixture(
    sessions: async_sessionmaker[AsyncSession],
    game_ids: tuple[UUID, ...],
    player_ids: tuple[UUID, ...],
) -> None:
    async with sessions() as session, session.begin():
        await session.execute(
            text("delete from public.games where id = any(cast(:game_ids as uuid[]))"),
            {"game_ids": list(game_ids)},
        )
        await session.execute(
            text("delete from public.users where id = any(cast(:player_ids as uuid[]))"),
            {"player_ids": list(player_ids)},
        )
        await session.execute(
            text("delete from auth.users where id = any(cast(:player_ids as uuid[]))"),
            {"player_ids": list(player_ids)},
        )
