from __future__ import annotations

from argparse import Namespace
from pathlib import Path
from typing import Any

import httpx
from play_cli import _api_game_id, _next_command, run_online

PLAYER_IDS = (
    "11111111-1111-4111-8111-111111111111",
    "22222222-2222-4222-8222-222222222222",
)


def test_http_runner_uses_typed_commands_and_finishes(capsys: Any) -> None:
    version = 0
    phase = "active"
    turn_seq = 0
    lap = 0
    command_types: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal version, phase, turn_seq, lap
        if request.method == "POST" and request.url.path == "/games":
            return httpx.Response(201, json=_game(version, phase, turn_seq, lap))
        if request.method == "POST" and request.url.path.endswith("/commands"):
            body = _json(request)
            assert body["expected_turn_seq"] == version
            command = body["command"]
            command_types.append(command["type"])
            version += 1
            events: list[dict[str, object]] = []
            if command["type"] == "take_turn":
                turn_seq += 1
                lap = 1
                events = [{"type": "dice_rolled", "seq": 1, "player_id": PLAYER_IDS[0]}]
            else:
                phase = command["phase"]
                events = [{"type": "phase_advanced", "seq": version, "phase": phase}]
            return httpx.Response(
                200,
                json={**_game(version, phase, turn_seq, lap), "events": events},
            )
        raise AssertionError(f"unexpected request: {request.method} {request.url}")

    transport = httpx.MockTransport(handler)

    def client_factory(**kwargs: object) -> httpx.Client:
        return httpx.Client(transport=transport, **kwargs)

    result = run_online(_args(), client_factory)

    assert result == 0
    assert command_types == ["take_turn", "advance_phase", "advance_phase"]
    assert '"transport": "http"' in capsys.readouterr().out


def test_http_scheduler_supports_daily_and_stable_named_game_ids() -> None:
    state = _game(0, "active", 0, 0)["state"]
    assert isinstance(state, dict)
    state["mode"] = "daily"
    state["rolls_per_day"] = 1
    command = _next_command(state)
    assert command == {"type": "take_turn", "player_id": PLAYER_IDS[0]}

    assert _api_game_id("named-game") == _api_game_id("named-game")
    assert _api_game_id("named-game") != _api_game_id("other-game")


def test_http_cli_module_does_not_import_persistence_or_engine_executor() -> None:
    source = (Path(__file__).parents[1] / "scripts" / "play_cli.py").read_text(encoding="utf-8")
    assert "assetrush.services" not in source
    assert "assetrush.db" not in source
    assert "execute_command" not in source


def _args() -> Namespace:
    return Namespace(
        player_id=list(PLAYER_IDS),
        players=2,
        game_id="http-runner-test",
        api_url="http://test",
        timeout=1.0,
        mode="blitz",
        target_minutes=None,
        seed="test",
        max_turns=10,
        pause_after_turns=None,
        events_out=None,
    )


def _game(version: int, phase: str, turn_seq: int, lap: int) -> dict[str, object]:
    return {
        "game_id": _api_game_id("http-runner-test"),
        "version": version,
        "state_digest": f"digest-{version}",
        "state": {
            "mode": "blitz",
            "phase": phase,
            "turn_seq": turn_seq,
            "lap_limit": 1,
            "day": 1,
            "day_limit": None,
            "base_turn_order": list(PLAYER_IDS),
            "players": [
                {
                    "id": player_id,
                    "cash": 100,
                    "lap": lap if index == 0 else 0,
                    "rolls_used_today": 0,
                    "is_bankrupt": False,
                    "has_quit": False,
                }
                for index, player_id in enumerate(PLAYER_IDS)
            ],
        },
    }


def _json(request: httpx.Request) -> dict[str, Any]:
    import json

    value = json.loads(request.content)
    assert isinstance(value, dict)
    return value
