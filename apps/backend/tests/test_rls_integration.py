from __future__ import annotations

import json
import os
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from dataclasses import dataclass
from pathlib import Path
from uuid import UUID, uuid4

import asyncpg  # type: ignore[import-untyped]
import pytest
from migrate import apply_migrations, asyncpg_dsn, discover_migrations

REPO_ROOT = Path(__file__).resolve().parents[3]
TEST_DATABASE_URL = os.getenv("ASSETRUSH_TEST_DATABASE_URL")

pytestmark = pytest.mark.skipif(
    not TEST_DATABASE_URL,
    reason="ASSETRUSH_TEST_DATABASE_URL is required for PostgreSQL integration tests",
)


@dataclass(frozen=True, slots=True)
class RlsRows:
    users: tuple[UUID, UUID, UUID]
    games: tuple[UUID, UUID]
    players: tuple[UUID, UUID, UUID]
    alliance_id: UUID


@pytest.mark.asyncio
async def test_rls_visibility_private_fields_and_write_boundary() -> None:
    assert TEST_DATABASE_URL is not None
    connection = await asyncpg.connect(asyncpg_dsn(TEST_DATABASE_URL))
    rows: RlsRows | None = None
    try:
        await _bootstrap_and_migrate(connection)
        protected_tables = await connection.fetch(
            """
            select relname
              from pg_class
             where relnamespace = 'public'::regnamespace
               and relrowsecurity
            """
        )
        assert {
            "users",
            "games",
            "game_snapshots",
            "game_players",
            "board_tiles",
            "properties",
            "property_claims",
            "holdings",
            "game_stock_prices",
            "alliances",
            "alliance_members",
            "alliance_proposals",
            "loans",
            "player_vehicles",
            "insurance_policies",
            "player_modifiers",
            "pending_effects",
            "bankruptcy_records",
            "game_events",
            "trade_offers",
            "standing_orders",
        } <= {row["relname"] for row in protected_tables}
        rows = await _seed_rls_rows(connection)
        user1, _, _ = rows.users
        game1, game2 = rows.games
        player1, _, _ = rows.players

        async with _as_role(connection, "authenticated", user1):
            visible_games = await connection.fetch("select id from public.games_public")
            assert {row["id"] for row in visible_games} == {game1}
            assert await connection.fetchval("select count(*) from public.game_events") == 1
            assert await connection.fetchval("select count(*) from public.standing_orders") == 1
            assert await connection.fetchval("select count(*) from public.trade_offers") == 1
            assert await connection.fetchval("select count(*) from public.loans") == 1
            assert (
                await connection.fetchval("select public.get_finished_game_seed($1)", game1) is None
            )
            assert (
                await connection.fetchval("select public.get_finished_game_seed($1)", game2) is None
            )

            public_holdings = await connection.fetch(
                "select player_id, shares from public.holdings_public order by player_id"
            )
            assert len(public_holdings) == 2
            private_holdings = await connection.fetch(
                "select * from public.get_my_holdings($1)", game1
            )
            assert [row["player_id"] for row in private_holdings] == [player1]

            public_members = await connection.fetch(
                "select player_id from public.alliance_members_public"
            )
            assert len(public_members) == 2
            private_members = await connection.fetch(
                "select player_id, contributed from public.get_my_alliance_members($1)",
                rows.alliance_id,
            )
            assert len(private_members) == 2

            with pytest.raises(asyncpg.InsufficientPrivilegeError):
                await connection.fetch("select server_seed from public.games")
            with pytest.raises(asyncpg.InsufficientPrivilegeError):
                await connection.fetch("select avg_cost from public.holdings")
            with pytest.raises(asyncpg.InsufficientPrivilegeError):
                await connection.fetch("select contributed from public.alliance_members")
            with pytest.raises(asyncpg.InsufficientPrivilegeError):
                await connection.execute(
                    "update public.game_players set cash = cash + 1 where id = $1",
                    player1,
                )
            with pytest.raises(asyncpg.InsufficientPrivilegeError):
                await connection.execute(
                    """
                    insert into public.game_events (
                      game_id, event_seq, turn_seq, actor_id, event_type, payload
                    ) values ($1, 2, 0, $2, 'cash_adjusted', $3::jsonb)
                    """,
                    game1,
                    player1,
                    json.dumps({"type": "cash_adjusted", "seq": 2}),
                )

            assert (
                await connection.execute(
                    "update public.users set display_name = 'updated' where id = $1", user1
                )
                == "UPDATE 1"
            )
            assert (
                await connection.execute(
                    "update public.users set display_name = 'blocked' where id = $1",
                    rows.users[1],
                )
                == "UPDATE 0"
            )
            with pytest.raises(asyncpg.InsufficientPrivilegeError):
                await connection.execute(
                    "update public.users set line_user_id = 'forbidden' where id = $1",
                    user1,
                )

        await connection.execute("update public.games set status = 'finished' where id = $1", game1)
        async with _as_role(connection, "authenticated", user1):
            assert (
                await connection.fetchval("select public.get_finished_game_seed($1)", game1)
                == "secret-one"
            )

        async with _as_role(connection, "anon"):
            assert await connection.fetchval("select count(*) from public.game_configs") >= 1
            with pytest.raises(asyncpg.InsufficientPrivilegeError):
                await connection.fetch("select * from public.games_public")
            with pytest.raises(asyncpg.InsufficientPrivilegeError):
                await connection.execute(
                    "update public.game_players set cash = 0 where id = $1", player1
                )

        async with _as_role(connection, "service_role"):
            assert (
                await connection.fetchval(
                    "select count(*) from public.game_snapshots where game_id = $1", game1
                )
                == 1
            )
            assert (
                await connection.execute(
                    "update public.game_players set cash = cash + 1 where id = $1", player1
                )
                == "UPDATE 1"
            )
    finally:
        await connection.execute("reset role")
        if rows is not None:
            await connection.execute(
                "delete from public.games where id = any($1::uuid[])", rows.games
            )
            await connection.execute(
                "delete from public.users where id = any($1::uuid[])", rows.users
            )
            await connection.execute(
                "delete from auth.users where id = any($1::uuid[])", rows.users
            )
        await connection.close()


async def _bootstrap_and_migrate(connection: asyncpg.Connection) -> None:
    await connection.execute(
        """
        do $$
        begin
          if not exists (select 1 from pg_roles where rolname = 'anon') then
            create role anon nologin;
          end if;
          if not exists (select 1 from pg_roles where rolname = 'authenticated') then
            create role authenticated nologin;
          end if;
          if not exists (select 1 from pg_roles where rolname = 'service_role') then
            create role service_role nologin bypassrls;
          end if;
        end
        $$;
        create schema if not exists auth;
        create table if not exists auth.users (id uuid primary key);
        create or replace function auth.uid()
        returns uuid language sql stable
        as $$ select nullif(current_setting('request.jwt.claim.sub', true), '')::uuid $$;
        """
    )
    await apply_migrations(
        connection,
        discover_migrations(REPO_ROOT / "supabase" / "migrations"),
    )


async def _seed_rls_rows(connection: asyncpg.Connection) -> RlsRows:
    users = (uuid4(), uuid4(), uuid4())
    games = (uuid4(), uuid4())
    players = (uuid4(), uuid4(), uuid4())
    config_version = f"rls-{uuid4()}"
    stock_code = f"RLS{uuid4().hex[:8]}"
    alliance_id = uuid4()

    await connection.executemany("insert into auth.users (id) values ($1)", [(u,) for u in users])
    await connection.executemany(
        "insert into public.users (id, display_name) values ($1, $2)",
        [(user_id, f"user-{index}") for index, user_id in enumerate(users)],
    )
    await connection.execute(
        "insert into public.game_configs (version, payload) values ($1, '{}'::jsonb)",
        config_version,
    )
    await connection.executemany(
        """
        insert into public.games (
          id, mode, status, config_version, game_seed, server_seed_hash, server_seed,
          host_user_id
        ) values ($1, 'daily', 'active', $2, 1, 'hash', $3, $4)
        """,
        [
            (games[0], config_version, "secret-one", users[0]),
            (games[1], config_version, "secret-two", users[2]),
        ],
    )
    await connection.executemany(
        """
        insert into public.game_players (
          id, game_id, user_id, base_turn_order, player_color, cash
        ) values ($1, $2, $3, $4, $5, 1000)
        """,
        [
            (players[0], games[0], users[0], 0, "red"),
            (players[1], games[0], users[1], 1, "blue"),
            (players[2], games[1], users[2], 0, "green"),
        ],
    )
    await connection.executemany(
        """
        insert into public.game_snapshots (
          game_id, initial_state, current_state, initial_digest, current_digest
        ) values ($1, '{}'::jsonb, '{}'::jsonb, 'initial', 'current')
        """,
        [(games[0],), (games[1],)],
    )
    await connection.execute(
        "insert into public.stocks (code, name) values ($1, 'RLS stock')", stock_code
    )
    await connection.executemany(
        """
        insert into public.holdings (
          game_id, player_id, stock_code, value, shares, avg_cost
        ) values ($1, $2, $3, 1000, 10, $4)
        """,
        [
            (games[0], players[0], stock_code, 90),
            (games[0], players[1], stock_code, 110),
            (games[1], players[2], stock_code, 120),
        ],
    )
    await connection.execute(
        """
        insert into public.alliances (
          id, game_id, tier, pool_balance, created_at_seq
        ) values ($1, $2, 'couple', 300, 0)
        """,
        alliance_id,
        games[0],
    )
    await connection.executemany(
        """
        insert into public.alliance_members (
          alliance_id, player_id, contributed, joined_at_seq
        ) values ($1, $2, $3, 0)
        """,
        [(alliance_id, players[0], 100), (alliance_id, players[1], 200)],
    )
    await connection.executemany(
        """
        insert into public.loans (
          game_id, player_id, product_key, principal, balance, rate_per_lap
        ) values ($1, $2, 'credit', 100, 100, 0.02)
        """,
        [(games[0], players[0]), (games[0], players[1])],
    )
    await connection.executemany(
        """
        insert into public.standing_orders (
          game_id, player_id, slot, rule
        ) values ($1, $2, 0, '{}'::jsonb)
        """,
        [(games[0], players[0]), (games[0], players[1])],
    )
    await connection.execute(
        """
        insert into public.trade_offers (
          id, game_id, from_player, to_player
        ) values ($1, $2, $3, $4)
        """,
        uuid4(),
        games[0],
        players[0],
        players[1],
    )
    await connection.executemany(
        """
        insert into public.game_events (
          game_id, event_seq, turn_seq, actor_id, event_type, payload
        ) values ($1, 1, 0, $2, 'cash_adjusted', $3::jsonb)
        """,
        [
            (games[0], players[0], json.dumps({"type": "cash_adjusted", "seq": 1})),
            (games[1], players[2], json.dumps({"type": "cash_adjusted", "seq": 1})),
        ],
    )
    return RlsRows(users=users, games=games, players=players, alliance_id=alliance_id)


@asynccontextmanager
async def _as_role(
    connection: asyncpg.Connection,
    role: str,
    user_id: UUID | None = None,
) -> AsyncIterator[None]:
    if role not in {"anon", "authenticated", "service_role"}:
        raise ValueError(f"unsupported test role: {role}")
    await connection.execute(
        "select set_config('request.jwt.claim.sub', $1, false)",
        str(user_id) if user_id else "",
    )
    await connection.execute(f"set role {role}")
    try:
        yield
    finally:
        await connection.execute("reset role")
        await connection.execute("reset request.jwt.claim.sub")
