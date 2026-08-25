from __future__ import annotations

import json
import os
from pathlib import Path
from uuid import UUID, uuid4

import asyncpg  # type: ignore[import-untyped]
import pytest
from migrate import apply_migrations, asyncpg_dsn, discover_migrations

from assetrush.config_bundle import load_config_bundle
from assetrush.engine.event_codec import event_from_dict, event_to_dict
from assetrush.engine.events import CashAdjustedEvent
from assetrush.engine.replay import state_digest
from assetrush.engine.setup import GameStartSpec, start_game
from assetrush.persistence import state_from_dict, state_to_dict
from assetrush.sim.runner import synthetic_towns

REPO_ROOT = Path(__file__).resolve().parents[3]
TEST_DATABASE_URL = os.getenv("ASSETRUSH_TEST_DATABASE_URL")

pytestmark = pytest.mark.skipif(
    not TEST_DATABASE_URL,
    reason="ASSETRUSH_TEST_DATABASE_URL is required for PostgreSQL integration tests",
)


@pytest.mark.asyncio
async def test_migrations_apply_and_daily_blitz_snapshots_round_trip() -> None:
    assert TEST_DATABASE_URL is not None
    connection = await asyncpg.connect(asyncpg_dsn(TEST_DATABASE_URL))
    try:
        await connection.execute("create schema if not exists auth")
        await connection.execute("create table if not exists auth.users (id uuid primary key)")
        migrations = discover_migrations(REPO_ROOT / "supabase" / "migrations")
        await apply_migrations(connection, migrations)

        transaction = connection.transaction()
        await transaction.start()
        try:
            config = load_config_bundle(REPO_ROOT / "config").raw
            scale = config["scale"]
            assert isinstance(scale, dict)
            config_version = str(scale["version"])
            await connection.execute(
                """
                insert into public.game_configs (version, payload, is_active)
                values ($1, $2::jsonb, true)
                on conflict (version) do update set payload = excluded.payload
                """,
                config_version,
                json.dumps(config),
            )

            game_ids = [
                await _assert_snapshot_round_trip(connection, config, config_version, mode)
                for mode in ("daily", "blitz")
            ]
            await connection.execute("update public.game_configs set is_active = false")
            await connection.execute(
                """
                insert into public.game_configs (version, payload, is_active)
                values ('next-version', '{}'::jsonb, true)
                """
            )
            pinned_versions = await connection.fetch(
                "select config_version from public.games where id = any($1::uuid[])",
                game_ids,
            )
            assert {row["config_version"] for row in pinned_versions} == {config_version}
        finally:
            await transaction.rollback()
    finally:
        await connection.close()


async def _assert_snapshot_round_trip(
    connection: asyncpg.Connection,
    config: dict[str, object],
    config_version: str,
    mode: str,
) -> UUID:
    game_id = uuid4()
    player_ids = (uuid4(), uuid4())
    for index, player_id in enumerate(player_ids, start=1):
        await connection.execute(
            "insert into auth.users (id) values ($1)",
            player_id,
        )
        await connection.execute(
            "insert into public.users (id, display_name) values ($1, $2)",
            player_id,
            f"player-{index}",
        )

    state = start_game(
        spec=GameStartSpec(
            game_id=str(game_id),
            mode=mode,  # type: ignore[arg-type]
            player_ids=tuple(str(player_id) for player_id in player_ids),
            server_seed=f"seed-{mode}",
            game_seed=42,
            target_minutes=20 if mode == "blitz" else None,
        ),
        config=config,
        towns=synthetic_towns(config),
    )
    snapshot = state_to_dict(state)
    digest = state_digest(state)

    await connection.execute(
        """
        insert into public.games (
          id, mode, status, config_version, game_seed, server_seed_hash, server_seed,
          host_user_id, player_count_at_start, target_minutes, total_tiles, lap_limit,
          day_limit, rolls_per_day, net_worth_threshold, current_day
        ) values (
          $1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11, $12, $13, $14, $15, $16
        )
        """,
        game_id,
        mode,
        state.phase,
        config_version,
        42,
        state.server_seed_hash,
        state.server_seed,
        player_ids[0],
        len(player_ids),
        20 if mode == "blitz" else None,
        state.board.total_tiles if state.board else None,
        state.lap_limit,
        state.day_limit,
        state.rolls_per_day,
        state.net_worth_threshold,
        state.day,
    )
    await connection.execute(
        """
        insert into public.game_snapshots (
          game_id, initial_state, current_state, initial_digest, current_digest
        ) values ($1, $2::jsonb, $2::jsonb, $3, $3)
        """,
        game_id,
        json.dumps(snapshot),
        digest,
    )
    for order, (player_id, player) in enumerate(zip(player_ids, state.players, strict=True)):
        await connection.execute(
            """
            insert into public.game_players (
              id, game_id, user_id, base_turn_order, player_color, cash, frozen_cash,
              position, lap, background_key, occupation_key, monthly_salary, health, luck
            ) values ($1, $2, $1, $3, $4, $5, $6, $7, $8, $9, $10, $11, $12, $13)
            """,
            player_id,
            game_id,
            order,
            f"color-{order}",
            player.cash,
            player.frozen_cash,
            player.position,
            player.lap,
            player.background_key,
            player.occupation_key,
            player.monthly_salary,
            player.health,
            player.luck,
        )

    stored = await connection.fetchval(
        "select current_state from public.game_snapshots where game_id = $1",
        game_id,
    )
    restored = state_from_dict(json.loads(stored))
    assert state_digest(restored) == digest

    event = CashAdjustedEvent(
        type="cash_adjusted",
        player_id=str(player_ids[0]),
        delta=5,
        balance_after=state.players[0].cash + 5,
        seq=1,
    )
    payload = event_to_dict(event)
    await connection.execute(
        """
        insert into public.game_events (
          game_id, event_seq, turn_seq, actor_id, event_type, payload
        ) values ($1, 1, 0, $2, $3, $4::jsonb)
        """,
        game_id,
        player_ids[0],
        event.type,
        json.dumps(payload),
    )
    stored_event = await connection.fetchval(
        "select payload from public.game_events where game_id = $1 and event_seq = 1",
        game_id,
    )
    assert event_from_dict(json.loads(stored_event)) == event

    savepoint = connection.transaction()
    await savepoint.start()
    try:
        with pytest.raises(asyncpg.UniqueViolationError):
            await connection.execute(
                """
                insert into public.game_events (
                  game_id, event_seq, turn_seq, actor_id, event_type, payload
                ) values ($1, 1, 0, $2, $3, $4::jsonb)
                """,
                game_id,
                player_ids[0],
                event.type,
                json.dumps(payload),
            )
    finally:
        await savepoint.rollback()
    return game_id
