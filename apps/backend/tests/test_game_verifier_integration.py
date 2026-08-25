from __future__ import annotations

import json
import os
from pathlib import Path
from uuid import UUID, uuid4

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from assetrush.config_bundle import load_config_bundle
from assetrush.engine import AdjustPlayerCashAction, ApplyActionCommand, GameStartSpec, start_game
from assetrush.engine.replay import state_digest
from assetrush.persistence import state_to_dict
from assetrush.services import GameStore, GameVerificationError, verify_game
from assetrush.sim.runner import synthetic_towns

REPO_ROOT = Path(__file__).resolve().parents[3]
TEST_DATABASE_URL = os.getenv("ASSETRUSH_TEST_DATABASE_URL")

pytestmark = pytest.mark.skipif(
    not TEST_DATABASE_URL,
    reason="ASSETRUSH_TEST_DATABASE_URL is required for PostgreSQL integration tests",
)


@pytest.mark.asyncio
async def test_verify_game_passes_and_detects_snapshot_and_event_corruption() -> None:
    assert TEST_DATABASE_URL is not None
    engine = create_async_engine(TEST_DATABASE_URL)
    sessions = async_sessionmaker(engine, expire_on_commit=False)
    store = GameStore(sessions)
    game_id, player_ids = await _create_fixture(sessions, store)
    try:
        persisted = await store.execute(
            game_id,
            expected_turn_seq=0,
            command=ApplyActionCommand(
                type="apply_action",
                action=AdjustPlayerCashAction(
                    type="adjust_player_cash",
                    player_id=str(player_ids[0]),
                    delta=17,
                ),
            ),
        )
        report = await verify_game(sessions, game_id)
        assert report.event_count == 1
        assert report.final_event_seq == 1

        async with sessions() as session, session.begin():
            await session.execute(
                text(
                    """
                    update public.game_snapshots
                       set current_state = jsonb_set(
                         current_state, '{players,0,cash}', to_jsonb(999999::bigint)
                       )
                     where game_id = :game_id
                    """
                ),
                {"game_id": game_id},
            )
        with pytest.raises(GameVerificationError) as snapshot_error:
            await verify_game(sessions, game_id)
        assert any(
            "current_state.players[0].cash" in mismatch
            for mismatch in snapshot_error.value.mismatches
        )

        async with sessions() as session, session.begin():
            await session.execute(
                text(
                    """
                    update public.game_snapshots
                       set current_state = cast(:state as jsonb), current_digest = :digest
                     where game_id = :game_id
                    """
                ),
                {
                    "game_id": game_id,
                    "state": json.dumps(state_to_dict(persisted.state)),
                    "digest": state_digest(persisted.state),
                },
            )
            await session.execute(
                text(
                    """
                    update public.game_events
                       set payload = jsonb_set(payload, '{delta}', '999'::jsonb)
                     where game_id = :game_id and event_seq = 1
                    """
                ),
                {"game_id": game_id},
            )
        with pytest.raises(GameVerificationError) as event_error:
            await verify_game(sessions, game_id)
        assert any(
            "event replay" in mismatch or "current_digest" in mismatch
            for mismatch in event_error.value.mismatches
        )
    finally:
        await _cleanup_fixture(sessions, game_id, player_ids)
        await engine.dispose()


async def _create_fixture(
    sessions: async_sessionmaker[AsyncSession], store: GameStore
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
        for index, player_id in enumerate(player_ids):
            await session.execute(
                text("insert into auth.users (id) values (:id)"), {"id": player_id}
            )
            await session.execute(
                text("insert into public.users (id, display_name) values (:id, :name)"),
                {"id": player_id, "name": f"verify-player-{index}"},
            )
    state = start_game(
        spec=GameStartSpec(
            game_id=str(game_id),
            mode="blitz",
            player_ids=tuple(str(player_id) for player_id in player_ids),
            server_seed="verify-game-seed",
            game_seed=91,
        ),
        config=config,
        towns=synthetic_towns(config),
    )
    await store.create_game(state, host_user_id=player_ids[0])
    return game_id, player_ids


async def _cleanup_fixture(
    sessions: async_sessionmaker[AsyncSession],
    game_id: UUID,
    player_ids: tuple[UUID, UUID],
) -> None:
    async with sessions() as session, session.begin():
        await session.execute(
            text("delete from public.games where id = :game_id"), {"game_id": game_id}
        )
        await session.execute(
            text("delete from public.users where id = any(cast(:ids as uuid[]))"),
            {"ids": list(player_ids)},
        )
        await session.execute(
            text("delete from auth.users where id = any(cast(:ids as uuid[]))"),
            {"ids": list(player_ids)},
        )
