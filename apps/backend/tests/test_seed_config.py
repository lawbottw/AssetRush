from __future__ import annotations

import json
from typing import Any

import pytest
from seed_config import build_seed_command, seed_config

from assetrush.config_bundle import ConfigBundle
from assetrush.engine.config_models import GameConfig


class FakeSession:
    def __init__(self) -> None:
        self.executed: list[tuple[str, object | None]] = []

    async def execute(self, statement: object, parameters: object | None = None) -> object:
        self.executed.append((str(statement), parameters))
        return None


def test_build_seed_command_keeps_full_payload_and_version() -> None:
    bundle = ConfigBundle(raw={"scale": {"version": "v1"}}, config=_config("v1"))

    command = build_seed_command(bundle, activate=True, notes="release")

    assert command.version == "v1"
    assert command.activate is True
    assert command.notes == "release"
    assert json.loads(command.payload_json) == {"scale": {"version": "v1"}}


@pytest.mark.asyncio
async def test_seed_config_deactivates_existing_active_before_activated_upsert() -> None:
    session = FakeSession()
    command = build_seed_command(
        ConfigBundle(raw={"scale": {"version": "v1"}}, config=_config("v1")),
        activate=True,
        notes=None,
    )

    await seed_config(session, command)

    assert "update game_configs set is_active = false" in session.executed[0][0]
    assert "insert into game_configs" in session.executed[1][0]
    params = session.executed[1][1]
    assert isinstance(params, dict)
    assert params["version"] == "v1"
    assert params["activate"] is True


@pytest.mark.asyncio
async def test_seed_config_without_activate_preserves_existing_active_flag() -> None:
    session = FakeSession()
    command = build_seed_command(
        ConfigBundle(raw={"scale": {"version": "v1"}}, config=_config("v1")),
        activate=False,
        notes="draft",
    )

    await seed_config(session, command)

    assert len(session.executed) == 1
    sql = session.executed[0][0]
    assert "else game_configs.is_active" in sql
    params = session.executed[0][1]
    assert isinstance(params, dict)
    assert params["activate"] is False
    assert params["notes"] == "draft"


def _config(version: str) -> GameConfig:
    return GameConfig.model_construct(version=version, **_minimal_sections())


def _minimal_sections() -> dict[str, Any]:
    return {
        "alliances": None,
        "board": None,
        "confinement": None,
        "endgame": None,
        "events": None,
        "identities": None,
        "insurance": None,
        "loans": None,
        "occupations": None,
        "properties": None,
        "scale": None,
        "stocks": None,
        "vehicles": None,
        "wellbeing": None,
    }
