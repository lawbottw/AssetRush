"""Transactional bridge between the pure engine and PostgreSQL."""

from __future__ import annotations

import json
import secrets
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import cast
from uuid import UUID, uuid5

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from assetrush.engine import (
    BoardSamplingError,
    Command,
    Event,
    GameMode,
    GameStartSpec,
    GameState,
    derive_u64,
    execute_command,
    player_net_worth,
    start_game,
)
from assetrush.engine.event_codec import event_to_dict
from assetrush.engine.replay import state_digest
from assetrush.persistence import state_from_dict, state_to_dict
from assetrush.sim.runner import synthetic_towns


class GameStoreError(RuntimeError):
    """Base persistence error safe for service/router translation."""


class GameNotFoundError(GameStoreError):
    pass


class GameAlreadyExistsError(GameStoreError):
    pass


class StaleTurnError(GameStoreError):
    def __init__(self, *, expected: int, actual: int) -> None:
        self.expected = expected
        self.actual = actual
        super().__init__(f"stale turn: expected version {expected}, current version is {actual}")


class PersistenceContractError(GameStoreError):
    pass


@dataclass(frozen=True, slots=True)
class StoredGame:
    state: GameState
    version: int
    config: dict[str, object]


@dataclass(frozen=True, slots=True)
class PersistedTransition:
    state: GameState
    events: tuple[Event, ...]
    version: int


@dataclass(frozen=True, slots=True)
class StoredEvent:
    id: int
    payload: dict[str, object]


class GameStore:
    """Persist game commands behind one advisory-lock transaction boundary."""

    def __init__(self, sessionmaker: async_sessionmaker[AsyncSession]) -> None:
        self._sessionmaker = sessionmaker

    async def create_from_spec(
        self,
        *,
        game_id: UUID,
        mode: str,
        player_ids: tuple[UUID, ...],
        host_user_id: UUID,
        target_minutes: int | None = None,
        seed: str | None = None,
    ) -> StoredGame:
        if host_user_id not in player_ids:
            raise PersistenceContractError("host_user_id must be one of player_ids")
        async with self._sessionmaker() as session:
            known_player_ids = set(
                await session.scalars(
                    text(
                        """
                        select id
                          from public.users
                         where id = any(cast(:player_ids as uuid[]))
                        """
                    ),
                    {"player_ids": list(player_ids)},
                )
            )
            missing_player_ids = set(player_ids) - known_player_ids
            if missing_player_ids:
                missing = ", ".join(str(player_id) for player_id in sorted(missing_player_ids))
                raise PersistenceContractError(f"unknown player_ids: {missing}")
            row = (
                (
                    await session.execute(
                        text(
                            """
                        select version, payload
                          from public.game_configs
                         where is_active
                        """
                        )
                    )
                )
                .mappings()
                .one_or_none()
            )
            if row is None:
                raise PersistenceContractError("no active game config")
            config = _json_object(row["payload"], "active game config")
            towns = [
                dict(item)
                for item in (
                    await session.execute(
                        text(
                            """
                            select code, name, county, region,
                                   cast(avg_price_per_ping as bigint) as avg_price_per_ping,
                                   price_tier, population
                              from public.towns
                             where is_active and avg_price_per_ping is not null
                                   and price_tier is not null
                            """
                        )
                    )
                ).mappings()
            ]

        server_seed = seed or secrets.token_hex(32)
        spec = GameStartSpec(
            game_id=str(game_id),
            mode=_game_mode(mode),
            player_ids=tuple(str(player_id) for player_id in player_ids),
            server_seed=server_seed,
            game_seed=derive_u64(server_seed, str(game_id), "game-seed", 0) % (2**63 - 1),
            target_minutes=target_minutes,
        )
        try:
            state = start_game(spec=spec, config=config, towns=towns or synthetic_towns(config))
        except BoardSamplingError:
            if not towns:
                raise
            state = start_game(spec=spec, config=config, towns=synthetic_towns(config))
        return await self.create_game(
            state,
            host_user_id=host_user_id,
            target_minutes=target_minutes,
        )

    async def create_game(
        self,
        state: GameState,
        *,
        host_user_id: UUID,
        target_minutes: int | None = None,
    ) -> StoredGame:
        game_id = _uuid(state.id, "game id")
        if state.board is None:
            raise PersistenceContractError("persisted games require a materialized board")
        config_version = state.board.config_version
        snapshot = state_to_dict(state)
        digest = state_digest(state)

        async with self._sessionmaker() as session, session.begin():
            await _lock_game(session, game_id)
            existing = await session.scalar(
                text("select 1 from public.games where id = :game_id"),
                {"game_id": game_id},
            )
            if existing is not None:
                raise GameAlreadyExistsError(str(game_id))
            config = await _load_config(session, config_version)
            await session.execute(
                text(
                    """
                    insert into public.games (
                      id, mode, status, config_version, game_seed, server_seed_hash,
                      server_seed, host_user_id, player_count_at_start, target_minutes,
                      total_tiles, lap_limit, day_limit, rolls_per_day,
                      net_worth_threshold, current_turn_seq, engine_turn_seq,
                      current_event_seq, rng_seq, current_day, treasury, started_at,
                      finished_at
                    ) values (
                      :id, :mode, :status, :config_version, :game_seed, :server_seed_hash,
                      :server_seed, :host_user_id, :player_count, :target_minutes,
                      :total_tiles, :lap_limit, :day_limit, :rolls_per_day,
                      :net_worth_threshold, 0, :engine_turn_seq, :event_seq, :rng_seq,
                      :day, :treasury, :started_at, :finished_at
                    )
                    """
                ),
                {
                    "id": game_id,
                    "mode": state.mode,
                    "status": state.phase,
                    "config_version": config_version,
                    "game_seed": state.board.seed,
                    "server_seed_hash": state.server_seed_hash,
                    "server_seed": state.server_seed,
                    "host_user_id": host_user_id,
                    "player_count": len(state.players),
                    "target_minutes": target_minutes,
                    "total_tiles": state.board.total_tiles,
                    "lap_limit": state.lap_limit,
                    "day_limit": state.day_limit,
                    "rolls_per_day": state.rolls_per_day,
                    "net_worth_threshold": state.net_worth_threshold,
                    "engine_turn_seq": state.turn_seq,
                    "event_seq": state.event_seq,
                    "rng_seq": state.rng_seq,
                    "day": state.day,
                    "treasury": state.treasury,
                    "started_at": datetime.now(UTC) if state.phase != "lobby" else None,
                    "finished_at": datetime.now(UTC) if state.phase == "finished" else None,
                },
            )
            await session.execute(
                text(
                    """
                    insert into public.game_snapshots (
                      game_id, initial_state, current_state, initial_digest, current_digest
                    ) values (
                      :game_id, cast(:initial_state as jsonb), cast(:current_state as jsonb),
                      :initial_digest, :current_digest
                    )
                    """
                ),
                {
                    "game_id": game_id,
                    "initial_state": _json(snapshot),
                    "current_state": _json(snapshot),
                    "initial_digest": digest,
                    "current_digest": digest,
                },
            )
            await self._materialize_state(session, state, include_board=True)
            return StoredGame(state=state, version=0, config=config)

    async def get_game(self, game_id: UUID) -> StoredGame:
        async with self._sessionmaker() as session:
            return await _load_game(session, game_id)

    async def get_events(
        self,
        game_id: UUID,
        *,
        after_id: int = 0,
        limit: int = 200,
    ) -> tuple[StoredEvent, ...]:
        if limit < 1 or limit > 500:
            raise ValueError("event limit must be between 1 and 500")
        async with self._sessionmaker() as session:
            exists = await session.scalar(
                text("select 1 from public.games where id = :game_id"),
                {"game_id": game_id},
            )
            if exists is None:
                raise GameNotFoundError(str(game_id))
            rows = (
                await session.execute(
                    text(
                        """
                        select id, payload
                          from public.game_events
                         where game_id = :game_id and id > :after_id
                         order by id
                         limit :limit
                        """
                    ),
                    {"game_id": game_id, "after_id": after_id, "limit": limit},
                )
            ).mappings()
            return tuple(
                StoredEvent(
                    id=int(row["id"]),
                    payload=_json_object(row["payload"], "event payload"),
                )
                for row in rows
            )

    async def execute(
        self,
        game_id: UUID,
        *,
        expected_turn_seq: int,
        command: Command,
    ) -> PersistedTransition:
        async with self._sessionmaker() as session, session.begin():
            await _lock_game(session, game_id)
            stored = await _load_game(session, game_id)
            if stored.version != expected_turn_seq:
                raise StaleTurnError(expected=expected_turn_seq, actual=stored.version)

            transition = execute_command(stored.state, command, stored.config)
            _validate_event_sequence(stored.state, transition.state, transition.events)
            await self._append_events(session, game_id, transition.state, transition.events)
            await self._after_events_appended(session)

            next_version = expected_turn_seq + 1
            updated = await session.scalar(
                text(
                    """
                    update public.games
                       set status = cast(:status as public.game_status),
                           current_turn_seq = :next_version,
                           engine_turn_seq = :engine_turn_seq,
                           current_event_seq = :event_seq,
                           rng_seq = :rng_seq,
                           current_day = :day,
                           treasury = :treasury,
                           finished_at = case
                             when cast(:status as public.game_status) = 'finished'
                               then coalesce(finished_at, now())
                             else finished_at
                           end
                     where id = :game_id and current_turn_seq = :expected_version
                    returning current_turn_seq
                    """
                ),
                {
                    "game_id": game_id,
                    "status": transition.state.phase,
                    "next_version": next_version,
                    "engine_turn_seq": transition.state.turn_seq,
                    "event_seq": transition.state.event_seq,
                    "rng_seq": transition.state.rng_seq,
                    "day": transition.state.day,
                    "treasury": transition.state.treasury,
                    "expected_version": expected_turn_seq,
                },
            )
            if updated is None:
                actual = await session.scalar(
                    text("select current_turn_seq from public.games where id = :game_id"),
                    {"game_id": game_id},
                )
                if actual is None:
                    raise GameNotFoundError(str(game_id))
                raise StaleTurnError(expected=expected_turn_seq, actual=int(actual))

            snapshot = state_to_dict(transition.state)
            await session.execute(
                text(
                    """
                    update public.game_snapshots
                       set current_state = cast(:state as jsonb),
                           current_digest = :digest,
                           updated_at = now()
                     where game_id = :game_id
                    """
                ),
                {
                    "game_id": game_id,
                    "state": _json(snapshot),
                    "digest": state_digest(transition.state),
                },
            )
            await self._materialize_state(session, transition.state, include_board=False)
            return PersistedTransition(
                state=transition.state,
                events=tuple(transition.events),
                version=next_version,
            )

    async def _append_events(
        self,
        session: AsyncSession,
        game_id: UUID,
        state: GameState,
        events: list[Event],
    ) -> None:
        if not events:
            return
        rows = []
        for event in events:
            payload = event_to_dict(event)
            rows.append(
                {
                    "game_id": game_id,
                    "event_seq": _event_seq(payload),
                    "turn_seq": state.turn_seq,
                    "round_no": state.day,
                    "actor_id": _optional_player_row_id(game_id, payload.get("player_id")),
                    "event_type": str(payload["type"]),
                    "payload": _json(payload),
                }
            )
        await session.execute(
            text(
                """
                insert into public.game_events (
                  game_id, event_seq, turn_seq, round_no, actor_id, event_type, payload
                ) values (
                  :game_id, :event_seq, :turn_seq, :round_no, :actor_id, :event_type,
                  cast(:payload as jsonb)
                )
                """
            ),
            rows,
        )

    async def _after_events_appended(self, session: AsyncSession) -> None:
        """Test seam for proving transaction rollback after the event append."""

    async def _materialize_state(
        self,
        session: AsyncSession,
        state: GameState,
        *,
        include_board: bool,
    ) -> None:
        game_id = _uuid(state.id, "game id")
        if include_board:
            await _materialize_board(session, game_id, state)
        await _materialize_players(session, game_id, state)
        await _clear_mutable_read_models(session, game_id)
        await _materialize_trade_offers(session, game_id, state)
        await _materialize_properties(session, game_id, state)
        await _materialize_bids(session, game_id, state)
        await _materialize_stocks(session, game_id, state)
        await _materialize_alliances(session, game_id, state)
        await _materialize_player_details(session, game_id, state)


async def _lock_game(session: AsyncSession, game_id: UUID) -> None:
    await session.execute(
        text("select pg_advisory_xact_lock(hashtext(:game_id))"),
        {"game_id": str(game_id)},
    )


async def _load_config(session: AsyncSession, version: str) -> dict[str, object]:
    payload = await session.scalar(
        text("select payload from public.game_configs where version = :version"),
        {"version": version},
    )
    if payload is None:
        raise PersistenceContractError(f"config version not found: {version}")
    return _json_object(payload, "game config")


async def _load_game(session: AsyncSession, game_id: UUID) -> StoredGame:
    row = (
        (
            await session.execute(
                text(
                    """
                select s.current_state, g.current_turn_seq, c.payload as config
                  from public.games g
                  join public.game_snapshots s on s.game_id = g.id
                  join public.game_configs c on c.version = g.config_version
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
        raise GameNotFoundError(str(game_id))
    return StoredGame(
        state=state_from_dict(_json_object(row["current_state"], "current state")),
        version=int(row["current_turn_seq"]),
        config=_json_object(row["config"], "game config"),
    )


async def _materialize_board(session: AsyncSession, game_id: UUID, state: GameState) -> None:
    if state.board is None:
        raise PersistenceContractError("persisted games require a board")
    towns = {
        tile.town_code: tile
        for tile in state.board.tiles
        if tile.town_code is not None and tile.kind == "property"
    }
    if towns:
        await session.execute(
            text(
                """
                insert into public.towns (
                  code, name, county, region, population, avg_price_per_ping,
                  price_tier, is_imputed
                ) values (
                  :code, :name, :county, :region, 0, :avg_price, :price_tier, true
                )
                on conflict (code) do nothing
                """
            ),
            [
                {
                    "code": code,
                    "name": tile.name or code,
                    "county": tile.county or "unknown",
                    "region": tile.region or "unknown",
                    "avg_price": tile.base_price,
                    "price_tier": tile.price_tier,
                }
                for code, tile in towns.items()
            ],
        )
    await session.execute(
        text(
            """
            insert into public.board_tiles (
              game_id, idx, kind, town_code, town_name, county, region, base_price, price_tier
            ) values (
              :game_id, :idx, :kind, :town_code, :town_name, :county, :region,
              :base_price, :price_tier
            )
            """
        ),
        [
            {
                "game_id": game_id,
                "idx": tile.index,
                "kind": tile.kind,
                "town_code": tile.town_code,
                "town_name": tile.name,
                "county": tile.county,
                "region": tile.region,
                "base_price": tile.base_price,
                "price_tier": tile.price_tier,
            }
            for tile in state.board.tiles
        ],
    )


async def _materialize_players(session: AsyncSession, game_id: UUID, state: GameState) -> None:
    order = {player_id: index for index, player_id in enumerate(state.base_turn_order)}
    colors = ("red", "blue", "green", "amber", "violet", "cyan", "pink", "lime")
    for index, player in enumerate(state.players):
        user_id = _uuid(player.id, "player id")
        player_id = _player_row_id(game_id, user_id)
        confinement = player.confinement
        await session.execute(
            text(
                """
                insert into public.game_players (
                  id, game_id, user_id, base_turn_order, player_color, background_key,
                  occupation_key, cash, frozen_cash, debt, net_worth, position, lap,
                  monthly_salary, health, luck, rolls_used_today, default_count,
                  is_blacklisted, is_bankrupt, has_quit, alliance_id,
                  relationship_changes, confinement_kind, confinement_remaining,
                  confinement_reason, education_course_key, education_remaining_laps,
                  education_unlocked_tier, last_acted_day
                ) values (
                  :id, :game_id, :user_id, :base_turn_order, :player_color,
                  :background_key, :occupation_key, :cash, :frozen_cash, :debt,
                  :net_worth, :position, :lap, :monthly_salary, :health, :luck,
                  :rolls_used_today, :default_count, :is_blacklisted, :is_bankrupt,
                  :has_quit, null, :relationship_changes, :confinement_kind,
                  :confinement_remaining, :confinement_reason, :education_course_key,
                  :education_remaining_laps, :education_unlocked_tier, :last_acted_day
                )
                on conflict (id) do update set
                  base_turn_order = excluded.base_turn_order,
                  player_color = excluded.player_color,
                  background_key = excluded.background_key,
                  occupation_key = excluded.occupation_key,
                  cash = excluded.cash,
                  frozen_cash = excluded.frozen_cash,
                  debt = excluded.debt,
                  net_worth = excluded.net_worth,
                  position = excluded.position,
                  lap = excluded.lap,
                  monthly_salary = excluded.monthly_salary,
                  health = excluded.health,
                  luck = excluded.luck,
                  rolls_used_today = excluded.rolls_used_today,
                  default_count = excluded.default_count,
                  is_blacklisted = excluded.is_blacklisted,
                  is_bankrupt = excluded.is_bankrupt,
                  has_quit = excluded.has_quit,
                  alliance_id = null,
                  relationship_changes = excluded.relationship_changes,
                  confinement_kind = excluded.confinement_kind,
                  confinement_remaining = excluded.confinement_remaining,
                  confinement_reason = excluded.confinement_reason,
                  education_course_key = excluded.education_course_key,
                  education_remaining_laps = excluded.education_remaining_laps,
                  education_unlocked_tier = excluded.education_unlocked_tier,
                  last_acted_day = excluded.last_acted_day
                """
            ),
            {
                "id": player_id,
                "game_id": game_id,
                "user_id": user_id,
                "base_turn_order": order.get(player.id, index),
                "player_color": colors[index % len(colors)],
                "background_key": player.background_key,
                "occupation_key": player.occupation_key,
                "cash": player.cash,
                "frozen_cash": player.frozen_cash,
                "debt": sum(loan.principal for loan in player.loans),
                "net_worth": player_net_worth(state, player.id),
                "position": player.position,
                "lap": player.lap,
                "monthly_salary": player.monthly_salary,
                "health": player.health,
                "luck": player.luck,
                "rolls_used_today": player.rolls_used_today,
                "default_count": player.default_count,
                "is_blacklisted": player.is_blacklisted,
                "is_bankrupt": player.is_bankrupt,
                "has_quit": player.has_quit,
                "relationship_changes": player.relationship_changes,
                "confinement_kind": confinement.kind if confinement else None,
                "confinement_remaining": confinement.remaining_turns if confinement else None,
                "confinement_reason": confinement.reason if confinement else None,
                "education_course_key": player.education_course_key,
                "education_remaining_laps": player.education_remaining_laps,
                "education_unlocked_tier": player.education_unlocked_tier,
                "last_acted_day": state.day if player.rolls_used_today else max(0, state.day - 1),
            },
        )


async def _clear_mutable_read_models(session: AsyncSession, game_id: UUID) -> None:
    await session.execute(
        text(
            """
            delete from public.alliance_members
             where alliance_id in (
               select id from public.alliances where game_id = :game_id
             )
            """
        ),
        {"game_id": game_id},
    )
    tables = (
        "properties",
        "property_claims",
        "holdings",
        "game_stock_prices",
        "alliance_proposals",
        "loans",
        "player_vehicles",
        "insurance_policies",
        "player_modifiers",
        "pending_effects",
        "bankruptcy_records",
        "standing_orders",
        "trade_offers",
        "alliances",
    )
    for table in tables:
        await session.execute(
            text(f"delete from public.{table} where game_id = :game_id"),
            {"game_id": game_id},
        )


async def _materialize_trade_offers(session: AsyncSession, game_id: UUID, state: GameState) -> None:
    for offer in state.trade_offers:
        await session.execute(
            text(
                """
                insert into public.trade_offers (
                  id, game_id, from_player, to_player, cash_frozen,
                  property_tile_indices, give_payload, want_payload
                ) values (
                  :id, :game_id, :from_player, :to_player, :cash_frozen,
                  :property_tile_indices, cast(:give_payload as jsonb), '{}'::jsonb
                )
                """
            ),
            {
                "id": _uuid(offer.offer_id, "trade offer id"),
                "game_id": game_id,
                "from_player": _player_row_id(game_id, offer.from_player_id),
                "to_player": _player_row_id(game_id, offer.to_player_id),
                "cash_frozen": offer.cash_frozen,
                "property_tile_indices": list(offer.property_tile_indices),
                "give_payload": _json(
                    {
                        "cash": offer.cash_frozen,
                        "properties": list(offer.property_tile_indices),
                    }
                ),
            },
        )


async def _materialize_properties(session: AsyncSession, game_id: UUID, state: GameState) -> None:
    if state.board is None:
        return
    owned = {item.tile_index: item for item in state.properties}
    frozen = {
        tile_index: _uuid(offer.offer_id, "trade offer id")
        for offer in state.trade_offers
        for tile_index in offer.property_tile_indices
    }
    rows = []
    for tile in state.board.tiles:
        if tile.kind != "property":
            continue
        item = owned.get(tile.index)
        rows.append(
            {
                "game_id": game_id,
                "tile_idx": tile.index,
                "owner_id": _player_row_id(game_id, item.owner_id) if item else None,
                "level": item.level if item else 0,
                "invested": item.invested if item else 0,
                "is_mortgaged": item.mortgaged if item else False,
                "frozen_by_offer": frozen.get(tile.index),
            }
        )
    if rows:
        await session.execute(
            text(
                """
                insert into public.properties (
                  game_id, tile_idx, owner_id, level, invested, is_mortgaged,
                  frozen_by_offer
                ) values (
                  :game_id, :tile_idx, :owner_id, :level, :invested, :is_mortgaged,
                  :frozen_by_offer
                )
                """
            ),
            rows,
        )


async def _materialize_bids(session: AsyncSession, game_id: UUID, state: GameState) -> None:
    if not state.property_bids:
        return
    await session.execute(
        text(
            """
            insert into public.property_claims (
              game_id, tile_idx, player_id, bid_amount, game_day
            ) values (:game_id, :tile_idx, :player_id, :bid_amount, :game_day)
            """
        ),
        [
            {
                "game_id": game_id,
                "tile_idx": bid.tile_index,
                "player_id": _player_row_id(game_id, bid.player_id),
                "bid_amount": bid.bid_amount,
                "game_day": bid.day,
            }
            for bid in state.property_bids
        ],
    )


async def _materialize_stocks(session: AsyncSession, game_id: UUID, state: GameState) -> None:
    codes = {holding.code for player in state.players for holding in player.stock_holdings} | {
        price.code for price in state.stock_prices
    }
    if codes:
        await session.execute(
            text(
                """
                insert into public.stocks (code, name) values (:code, :code)
                on conflict (code) do nothing
                """
            ),
            [{"code": code} for code in sorted(codes)],
        )
    holdings = [
        {
            "game_id": game_id,
            "player_id": _player_row_id(game_id, player.id),
            "stock_code": holding.code,
            "value": holding.value,
        }
        for player in state.players
        for holding in player.stock_holdings
    ]
    if holdings:
        await session.execute(
            text(
                """
                insert into public.holdings (
                  game_id, player_id, stock_code, value, shares, avg_cost
                ) values (:game_id, :player_id, :stock_code, :value, 0, 0)
                """
            ),
            holdings,
        )
    if state.stock_prices:
        await session.execute(
            text(
                """
                insert into public.game_stock_prices (game_id, stock_code, price)
                values (:game_id, :stock_code, :price)
                """
            ),
            [
                {"game_id": game_id, "stock_code": price.code, "price": price.price}
                for price in state.stock_prices
            ],
        )


async def _materialize_alliances(session: AsyncSession, game_id: UUID, state: GameState) -> None:
    for alliance in state.alliances:
        alliance_id = _uuid(alliance.id, "alliance id")
        await session.execute(
            text(
                """
                insert into public.alliances (
                  id, game_id, tier, name, pool_balance, core_partner_ids,
                  created_at_seq, is_active
                ) values (
                  :id, :game_id, :tier, :name, :pool_balance, :core_partner_ids,
                  0, :is_active
                )
                """
            ),
            {
                "id": alliance_id,
                "game_id": game_id,
                "tier": alliance.tier,
                "name": alliance.name,
                "pool_balance": alliance.pool_balance,
                "core_partner_ids": (
                    [_player_row_id(game_id, value) for value in alliance.core_partner_ids]
                    if alliance.core_partner_ids
                    else None
                ),
                "is_active": alliance.active,
            },
        )
        member_state = {member.player_id: member for member in alliance.member_states}
        await session.execute(
            text(
                """
                insert into public.alliance_members (
                  alliance_id, player_id, contributed, relationship_changes, joined_at_seq
                ) values (
                  :alliance_id, :player_id, :contributed, :relationship_changes, 0
                )
                """
            ),
            [
                {
                    "alliance_id": alliance_id,
                    "player_id": _player_row_id(game_id, player_id),
                    "contributed": member_state[player_id].contributed
                    if player_id in member_state
                    else 0,
                    "relationship_changes": member_state[player_id].relationship_changes
                    if player_id in member_state
                    else 0,
                }
                for player_id in alliance.member_ids
            ],
        )
    for proposal in state.alliance_proposals:
        await session.execute(
            text(
                """
                insert into public.alliance_proposals (
                  id, game_id, from_player_id, to_player_id, tier, game_day,
                  target_alliance_id, formation_style
                ) values (
                  :id, :game_id, :from_player_id, :to_player_id, :tier, :game_day,
                  :target_alliance_id, :formation_style
                )
                """
            ),
            {
                "id": _uuid(proposal.id, "alliance proposal id"),
                "game_id": game_id,
                "from_player_id": _player_row_id(game_id, proposal.from_player_id),
                "to_player_id": _player_row_id(game_id, proposal.to_player_id),
                "tier": proposal.tier,
                "game_day": proposal.day,
                "target_alliance_id": _optional_uuid(proposal.target_alliance_id),
                "formation_style": proposal.formation_style,
            },
        )
    for player in state.players:
        if player.alliance_id is None:
            continue
        await session.execute(
            text(
                """
                update public.game_players set alliance_id = :alliance_id
                 where game_id = :game_id and id = :player_id
                """
            ),
            {
                "game_id": game_id,
                "player_id": _player_row_id(game_id, player.id),
                "alliance_id": _uuid(player.alliance_id, "player alliance id"),
            },
        )


async def _materialize_player_details(
    session: AsyncSession, game_id: UUID, state: GameState
) -> None:
    for player in state.players:
        player_id = _player_row_id(game_id, player.id)
        for loan in player.loans:
            await session.execute(
                text(
                    """
                    insert into public.loans (
                      game_id, player_id, product_key, principal, balance, rate_per_lap
                    ) values (
                      :game_id, :player_id, :product_key, :principal, :principal,
                      :rate_per_lap
                    )
                    """
                ),
                {
                    "game_id": game_id,
                    "player_id": player_id,
                    "product_key": loan.product_key,
                    "principal": loan.principal,
                    "rate_per_lap": loan.rate_per_lap,
                },
            )
        if player.vehicles:
            await session.execute(
                text(
                    """
                    insert into public.player_vehicles (game_id, player_id, vehicle_key)
                    values (:game_id, :player_id, :vehicle_key)
                    """
                ),
                [
                    {"game_id": game_id, "player_id": player_id, "vehicle_key": key}
                    for key in player.vehicles
                ],
            )
        if player.insurance_policies:
            await session.execute(
                text(
                    """
                    insert into public.insurance_policies (game_id, player_id, policy_key)
                    values (:game_id, :player_id, :policy_key)
                    """
                ),
                [
                    {"game_id": game_id, "player_id": player_id, "policy_key": key}
                    for key in player.insurance_policies
                ],
            )
        for modifier in player.modifiers:
            await session.execute(
                text(
                    """
                    insert into public.player_modifiers (game_id, player_id, key, value, laps)
                    values (:game_id, :player_id, :key, cast(:value as jsonb), :laps)
                    """
                ),
                {
                    "game_id": game_id,
                    "player_id": player_id,
                    "key": modifier.key,
                    "value": _json(modifier.value),
                    "laps": modifier.laps,
                },
            )
    for index, effect in enumerate(state.pending_effects):
        await session.execute(
            text(
                """
                insert into public.pending_effects (
                  game_id, player_id, effect_type, reason, ordinal
                ) values (:game_id, :player_id, :effect_type, :reason, :ordinal)
                """
            ),
            {
                "game_id": game_id,
                "player_id": _player_row_id(game_id, effect.player_id),
                "effect_type": effect.effect_type,
                "reason": effect.reason,
                "ordinal": index,
            },
        )
    for index, record in enumerate(state.bankruptcy_records):
        await session.execute(
            text(
                """
                insert into public.bankruptcy_records (
                  game_id, player_id, game_day, net_worth_before,
                  counts_for_end_condition, reason, ordinal
                ) values (
                  :game_id, :player_id, :game_day, :net_worth_before,
                  :counts_for_end_condition, :reason, :ordinal
                )
                """
            ),
            {
                "game_id": game_id,
                "player_id": _player_row_id(game_id, record.player_id),
                "game_day": record.day,
                "net_worth_before": record.net_worth_before,
                "counts_for_end_condition": record.counts_for_end_condition,
                "reason": record.reason,
                "ordinal": index,
            },
        )
    for order in state.standing_orders:
        await session.execute(
            text(
                """
                insert into public.standing_orders (
                  game_id, player_id, slot, rule, bid_policy, cash_floor,
                  max_bid_ratio, is_enabled
                ) values (
                  :game_id, :player_id, 0, cast(:rule as jsonb), :bid_policy,
                  :cash_floor, :max_bid_ratio, :is_enabled
                )
                """
            ),
            {
                "game_id": game_id,
                "player_id": _player_row_id(game_id, order.player_id),
                "rule": _json(
                    {
                        "bid_policy": order.bid_policy,
                        "cash_floor": order.cash_floor,
                        "max_bid_ratio": order.max_bid_ratio,
                    }
                ),
                "bid_policy": order.bid_policy,
                "cash_floor": order.cash_floor,
                "max_bid_ratio": order.max_bid_ratio,
                "is_enabled": order.enabled,
            },
        )


def _validate_event_sequence(before: GameState, after: GameState, events: list[Event]) -> None:
    encoded = [event_to_dict(event) for event in events]
    actual = [_event_seq(payload) for payload in encoded]
    expected = list(range(before.event_seq + 1, before.event_seq + len(events) + 1))
    if actual != expected:
        raise PersistenceContractError(
            f"non-contiguous event sequence: {actual}, expected {expected}"
        )
    expected_final = expected[-1] if expected else before.event_seq
    if after.event_seq != expected_final:
        raise PersistenceContractError(
            f"state event_seq is {after.event_seq}, expected {expected_final}"
        )


def _json(value: object) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _event_seq(payload: dict[str, object]) -> int:
    value = payload.get("seq")
    if not isinstance(value, int) or isinstance(value, bool):
        raise PersistenceContractError("event seq must be an integer")
    return value


def _json_object(value: object, label: str) -> dict[str, object]:
    if isinstance(value, str):
        value = json.loads(value)
    if not isinstance(value, dict):
        raise PersistenceContractError(f"{label} must be a JSON object")
    return {str(key): item for key, item in value.items()}


def _uuid(value: str | UUID, label: str) -> UUID:
    try:
        return value if isinstance(value, UUID) else UUID(value)
    except ValueError as exc:
        raise PersistenceContractError(f"{label} must be a UUID: {value}") from exc


def _player_row_id(game_id: UUID, player_id: str | UUID) -> UUID:
    return uuid5(game_id, str(_uuid(player_id, "player id")))


def _optional_player_row_id(game_id: UUID, value: object) -> UUID | None:
    if value is None or not isinstance(value, str | UUID):
        return None
    try:
        return _player_row_id(game_id, value)
    except PersistenceContractError:
        return None


def _optional_uuid(value: object) -> UUID | None:
    if value is None or not isinstance(value, str | UUID):
        return None
    try:
        return _uuid(value, "optional id")
    except PersistenceContractError:
        return None


def _game_mode(value: str) -> GameMode:
    if value not in {"daily", "blitz"}:
        raise PersistenceContractError(f"unsupported game mode: {value}")
    return cast(GameMode, value)
