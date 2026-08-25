from __future__ import annotations

import json
import types
from dataclasses import MISSING, fields
from pathlib import Path
from typing import Any, Literal, Union, cast, get_args, get_origin, get_type_hints

import pytest
from migrate import asyncpg_dsn, discover_migrations

from assetrush.config_bundle import load_config_bundle
from assetrush.engine.event_codec import EVENT_TYPES, event_from_dict, event_to_dict
from assetrush.engine.replay import state_digest
from assetrush.engine.state import GameMode
from assetrush.persistence import state_from_dict, state_to_dict
from assetrush.sim.runner import RunnerSpec, create_initial_state

REPO_ROOT = Path(__file__).resolve().parents[3]


@pytest.mark.parametrize("mode", ["daily", "blitz"])
def test_initial_state_json_contract_is_lossless(mode: str) -> None:
    config = load_config_bundle(REPO_ROOT / "config").raw
    state = create_initial_state(
        RunnerSpec(
            mode=cast(GameMode, mode),
            player_count=2,
            seed=f"persistence-{mode}",
            game_id=f"00000000-0000-0000-0000-0000000000{1 if mode == 'daily' else 2}1",
        ),
        config,
    )

    restored = state_from_dict(json.loads(json.dumps(state_to_dict(state))))

    assert restored == state
    assert state_digest(restored) == state_digest(state)


def test_every_engine_event_has_a_lossless_json_contract() -> None:
    for event_type, event_class in EVENT_TYPES.items():
        hints = get_type_hints(event_class)
        kwargs: dict[str, object] = {}
        for field in fields(event_class):
            if field.default is not MISSING or field.default_factory is not MISSING:
                continue
            kwargs[field.name] = _sample_value(hints[field.name], event_type)

        event = event_class(**kwargs)
        encoded = json.loads(json.dumps(event_to_dict(event)))

        assert event_from_dict(encoded) == event, event_type


def test_migration_plan_is_ordered_and_contains_m4_schema() -> None:
    migrations = discover_migrations(REPO_ROOT / "supabase" / "migrations")

    assert [migration.version for migration in migrations] == sorted(
        migration.version for migration in migrations
    )
    sql = "\n".join(migration.sql.lower() for migration in migrations)
    required_tables = {
        "users",
        "towns",
        "town_price_history",
        "stocks",
        "stock_prices",
        "market_calendar",
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
    }
    for table in required_tables:
        assert f"create table public.{table}" in sql


@pytest.mark.parametrize(
    ("url", "expected"),
    [
        ("postgresql+asyncpg://user:pass@host/db", "postgresql://user:pass@host/db"),
        ("postgresql://user:pass@host/db", "postgresql://user:pass@host/db"),
        ("postgres://user:pass@host/db", "postgres://user:pass@host/db"),
    ],
)
def test_asyncpg_dsn_accepts_supported_postgres_schemes(url: str, expected: str) -> None:
    assert asyncpg_dsn(url) == expected


def test_asyncpg_dsn_rejects_non_postgres_scheme() -> None:
    with pytest.raises(ValueError, match="PostgreSQL"):
        asyncpg_dsn("sqlite:///tmp/test.db")


def _sample_value(annotation: object, event_type: str) -> object:
    origin = get_origin(annotation)
    args = get_args(annotation)
    if origin is Literal:
        return event_type if event_type in args else args[0]
    if origin is tuple:
        if len(args) == 2 and args[1] is Ellipsis:
            return (_sample_value(args[0], event_type),)
        return tuple(_sample_value(arg, event_type) for arg in args)
    if origin in (types.UnionType, Union):
        candidate = next(arg for arg in args if arg is not type(None))
        return _sample_value(candidate, event_type)
    if annotation is str:
        return "sample"
    if annotation is int:
        return 1
    if annotation is float:
        return 0.5
    if annotation is bool:
        return True
    if annotation is Any:
        return "sample"
    raise AssertionError(f"no sample value for {annotation!r}")
