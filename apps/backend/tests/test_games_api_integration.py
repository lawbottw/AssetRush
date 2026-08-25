from __future__ import annotations

import json
import os
from pathlib import Path
from uuid import UUID, uuid4

import httpx
import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from assetrush.config_bundle import load_config_bundle
from assetrush.main import app
from assetrush.routers.games import get_game_store
from assetrush.services import GameStore

REPO_ROOT = Path(__file__).resolve().parents[3]
TEST_DATABASE_URL = os.getenv("ASSETRUSH_TEST_DATABASE_URL")

pytestmark = pytest.mark.skipif(
    not TEST_DATABASE_URL,
    reason="ASSETRUSH_TEST_DATABASE_URL is required for PostgreSQL integration tests",
)


@pytest.mark.asyncio
async def test_persisted_game_api_round_trip_conflict_events_and_restart() -> None:
    assert TEST_DATABASE_URL is not None
    engine = create_async_engine(TEST_DATABASE_URL)
    sessions = async_sessionmaker(engine, expire_on_commit=False)
    store = GameStore(sessions)
    game_id = uuid4()
    second_game_id = uuid4()
    player_ids = (uuid4(), uuid4())
    await _seed_api_fixture(sessions, player_ids)
    app.dependency_overrides[get_game_store] = lambda: store
    transport = httpx.ASGITransport(app=app)
    try:
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            created_response = await client.post(
                "/games",
                json={
                    "game_id": str(game_id),
                    "mode": "daily",
                    "player_ids": [str(player_id) for player_id in player_ids],
                    "host_user_id": str(player_ids[0]),
                    "seed": "api-integration-seed",
                },
            )
            assert created_response.status_code == 201, created_response.text
            created = created_response.json()
            assert created["version"] == 0
            _assert_public_state(created["state"])

            command = {
                "expected_turn_seq": 0,
                "command": {"type": "take_turn", "player_id": str(player_ids[0])},
            }
            command_response = await client.post(f"/games/{game_id}/commands", json=command)
            assert command_response.status_code == 200, command_response.text
            commanded = command_response.json()
            assert commanded["version"] == 1
            assert commanded["events"]
            assert all("type" in event and "seq" in event for event in commanded["events"])
            _assert_public_state(commanded["state"])

            stale_response = await client.post(f"/games/{game_id}/commands", json=command)
            assert stale_response.status_code == 409
            assert stale_response.json()["detail"] == {
                "code": "stale_turn",
                "message": "stale turn: expected version 0, current version is 1",
                "expected": 0,
                "actual": 1,
            }

            domain_response = await client.post(
                f"/games/{game_id}/commands",
                json={
                    "expected_turn_seq": 1,
                    "command": {"type": "take_turn", "player_id": str(uuid4())},
                },
            )
            assert domain_response.status_code == 409
            assert domain_response.json()["detail"]["code"] == "domain_error"

            events_response = await client.get(f"/games/{game_id}/events")
            assert events_response.status_code == 200
            event_page = events_response.json()
            assert event_page["events"] == commanded["events"]
            assert event_page["next_cursor"] > 0

            # A new service instance models an API process restart.
            app.dependency_overrides[get_game_store] = lambda: GameStore(sessions)
            reloaded_response = await client.get(f"/games/{game_id}")
            assert reloaded_response.status_code == 200
            reloaded = reloaded_response.json()
            assert reloaded["version"] == 1
            assert reloaded["state_digest"] == commanded["state_digest"]
            _assert_public_state(reloaded["state"])

            second_game = await client.post(
                "/games",
                json={
                    "game_id": str(second_game_id),
                    "mode": "daily",
                    "player_ids": [str(player_id) for player_id in player_ids],
                    "host_user_id": str(player_ids[0]),
                    "seed": "same-users-second-game",
                },
            )
            assert second_game.status_code == 201, second_game.text
    finally:
        app.dependency_overrides.clear()
        await _cleanup_api_fixture(sessions, (game_id, second_game_id), player_ids)
        await engine.dispose()


@pytest.mark.asyncio
async def test_game_api_has_typed_validation_and_stable_errors() -> None:
    assert TEST_DATABASE_URL is not None
    engine = create_async_engine(TEST_DATABASE_URL)
    sessions = async_sessionmaker(engine, expire_on_commit=False)
    store = GameStore(sessions)
    player_ids = (uuid4(), uuid4())
    game_id = uuid4()
    unknown = uuid4()
    await _seed_api_fixture(sessions, player_ids)
    app.dependency_overrides[get_game_store] = lambda: store
    transport = httpx.ASGITransport(app=app)
    try:
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            invalid = await client.post(
                f"/games/{game_id}/commands",
                json={
                    "expected_turn_seq": -1,
                    "command": {"type": "not_a_command"},
                },
            )
            assert invalid.status_code == 422

            missing = await client.get(f"/games/{game_id}")
            assert missing.status_code == 404
            assert missing.json()["detail"]["code"] == "game_not_found"

            rejected = await client.post(
                "/games",
                json={
                    "game_id": str(game_id),
                    "mode": "blitz",
                    "player_ids": [str(player_ids[0]), str(unknown)],
                    "host_user_id": str(player_ids[0]),
                },
            )
            assert rejected.status_code == 409
            assert rejected.json()["detail"]["code"] == "persistence_contract"
    finally:
        app.dependency_overrides.clear()
        await _cleanup_api_fixture(sessions, (game_id,), (*player_ids, unknown))
        await engine.dispose()


def test_game_api_openapi_documents_command_discriminator_and_event_union() -> None:
    schema = app.openapi()
    request_schema = schema["components"]["schemas"]["ExecuteCommandRequest"]
    command_schema = request_schema["properties"]["command"]
    assert command_schema["discriminator"]["propertyName"] == "type"
    assert len(command_schema["oneOf"]) == 7

    response_schema = schema["components"]["schemas"]["CommandResponse"]
    event_schema = response_schema["properties"]["events"]["items"]
    assert len(event_schema["anyOf"]) > 10


def _assert_public_state(state: dict[str, object]) -> None:
    assert "server_seed" not in state
    assert state["standing_orders"] == []
    assert state["trade_offers"] == []
    assert state["pending_effects"] == []
    players = state["players"]
    assert isinstance(players, list)
    assert all(player["loans"] == [] for player in players)


async def _seed_api_fixture(
    sessions: async_sessionmaker[AsyncSession], player_ids: tuple[UUID, ...]
) -> None:
    config = load_config_bundle(REPO_ROOT / "config").raw
    scale = config["scale"]
    assert isinstance(scale, dict)
    version = str(scale["version"])
    async with sessions() as session, session.begin():
        await session.execute(text("update public.game_configs set is_active = false"))
        await session.execute(
            text(
                """
                insert into public.game_configs (version, payload, is_active)
                values (:version, cast(:payload as jsonb), true)
                on conflict (version) do update
                  set payload = excluded.payload, is_active = true
                """
            ),
            {"version": version, "payload": json.dumps(config)},
        )
        for index, player_id in enumerate(player_ids, start=1):
            await session.execute(
                text("insert into auth.users (id) values (:id) on conflict do nothing"),
                {"id": player_id},
            )
            await session.execute(
                text(
                    """
                    insert into public.users (id, display_name)
                    values (:id, :display_name)
                    on conflict (id) do nothing
                    """
                ),
                {"id": player_id, "display_name": f"api-player-{index}"},
            )


async def _cleanup_api_fixture(
    sessions: async_sessionmaker[AsyncSession],
    game_ids: tuple[UUID, ...],
    player_ids: tuple[UUID, ...],
) -> None:
    async with sessions() as session, session.begin():
        await session.execute(
            text("delete from public.games where id = any(cast(:ids as uuid[]))"),
            {"ids": list(game_ids)},
        )
        await session.execute(
            text("delete from public.users where id = any(cast(:ids as uuid[]))"),
            {"ids": list(player_ids)},
        )
        await session.execute(
            text("delete from auth.users where id = any(cast(:ids as uuid[]))"),
            {"ids": list(player_ids)},
        )
