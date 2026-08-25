"""Play AssetRush through its persisted HTTP API (or explicitly offline)."""

from __future__ import annotations

import argparse
import json
import os
import sys
from collections.abc import Callable
from pathlib import Path
from typing import Any
from uuid import NAMESPACE_URL, UUID, uuid5

import httpx

from assetrush.console import force_utf8_output

JsonObject = dict[str, Any]
ClientFactory = Callable[..., httpx.Client]


class ApiClientError(RuntimeError):
    pass


def main(argv: list[str] | None = None) -> int:
    force_utf8_output()
    parser = _parser()
    args = parser.parse_args(argv)
    try:
        if args.command == "run":
            if args.offline:
                from play_cli_offline import run

                return run(args)
            return run_online(args)
        if args.command == "list-commands":
            from play_cli_offline import list_commands

            return list_commands()
        if args.command == "replay":
            from play_cli_offline import replay

            return replay(args)
        if args.command == "apply":
            from play_cli_offline import apply

            return apply(args)
    except (ApiClientError, ValueError) as exc:
        print(f"play-cli: {exc}", file=sys.stderr)
        return 2
    parser.error("missing command")
    return 2


def run_online(args: argparse.Namespace, client_factory: ClientFactory = httpx.Client) -> int:
    player_ids = tuple(args.player_id or ())
    if len(player_ids) != args.players:
        raise ValueError(
            f"HTTP mode requires exactly --players={args.players} registered --player-id values"
        )
    for player_id in player_ids:
        UUID(player_id)
    game_id = _api_game_id(args.game_id)
    submitted_events: list[JsonObject] = []
    turns_executed = 0
    resumed = False
    turn_budget = args.pause_after_turns or args.max_turns

    with client_factory(base_url=args.api_url.rstrip("/"), timeout=args.timeout) as client:
        response = client.post(
            "/games",
            json={
                "game_id": game_id,
                "mode": args.mode,
                "player_ids": player_ids,
                "host_user_id": player_ids[0],
                "target_minutes": args.target_minutes,
                "seed": args.seed,
            },
        )
        if response.status_code == 409 and _error_code(response) == "game_exists":
            resumed = True
            game = _request(client, "GET", f"/games/{game_id}")
        else:
            game = _response_json(response)

        state = _object(game.get("state"), "game.state")
        version = _integer(game.get("version"), "game.version")
        while state.get("phase") == "active" and turns_executed < turn_budget:
            command = _next_command(state)
            if command is None:
                break
            game, emitted = _submit(client, game_id, version, command)
            submitted_events.extend(emitted)
            state = _object(game.get("state"), "command.state")
            version = _integer(game.get("version"), "command.version")
            if command["type"] == "take_turn":
                turns_executed += 1
                for player_id in _quarterly_players(emitted):
                    game, more_events = _submit(
                        client,
                        game_id,
                        version,
                        {
                            "type": "run_quarterly_affairs",
                            "player_id": player_id,
                            "choices": {},
                        },
                    )
                    submitted_events.extend(more_events)
                    state = _object(game.get("state"), "quarterly.state")
                    version = _integer(game.get("version"), "quarterly.version")
            game, resolution_events = _resolve_negative_cash(client, game_id, game, state, version)
            submitted_events.extend(resolution_events)
            state = _object(game.get("state"), "resolved.state")
            version = _integer(game.get("version"), "resolved.version")
            if _game_complete(state):
                break

        paused = args.pause_after_turns is not None and state.get("phase") == "active"
        if state.get("phase") == "active" and not paused:
            game, emitted = _submit(
                client,
                game_id,
                version,
                {"type": "advance_phase", "phase": "settling", "reason": "cli_complete"},
            )
            submitted_events.extend(emitted)
            state = _object(game.get("state"), "settling.state")
            version = _integer(game.get("version"), "settling.version")
        if state.get("phase") == "settling":
            game, emitted = _submit(
                client,
                game_id,
                version,
                {"type": "advance_phase", "phase": "finished", "reason": "cli_complete"},
            )
            submitted_events.extend(emitted)
            state = _object(game.get("state"), "finished.state")

    if args.events_out is not None:
        _write_jsonl(args.events_out, submitted_events)
    completed = state.get("phase") == "finished"
    print(
        json.dumps(
            {
                "transport": "http",
                "api_url": args.api_url,
                "game_id": game_id,
                "mode": args.mode,
                "players": len(player_ids),
                "resumed": resumed,
                "turns_executed": turns_executed,
                "event_count": len(submitted_events),
                "final_phase": state.get("phase"),
                "state_digest": game.get("state_digest"),
                "completed": completed,
                "paused": paused,
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0 if completed or paused else 1


def _next_command(state: JsonObject) -> JsonObject | None:
    alive = [
        player
        for player in _players(state)
        if not player.get("is_bankrupt") and not player.get("has_quit")
    ]
    if not alive:
        return None
    mode = state.get("mode")
    if mode == "daily":
        limit = _integer(state.get("rolls_per_day"), "state.rolls_per_day")
        for player in alive:
            if _integer(player.get("rolls_used_today"), "player.rolls_used_today") < limit:
                return {"type": "take_turn", "player_id": str(player["id"])}
        return {"type": "run_daily_settlement", "execute_standing_orders": True}
    if mode == "blitz":
        order = [str(value) for value in state.get("base_turn_order", [])]
        alive_ids = [player_id for player_id in order if any(p["id"] == player_id for p in alive)]
        if not alive_ids:
            return None
        turn_seq = _integer(state.get("turn_seq"), "state.turn_seq")
        return {"type": "take_turn", "player_id": alive_ids[turn_seq % len(alive_ids)]}
    raise ApiClientError(f"unsupported persisted game mode: {mode}")


def _quarterly_players(events: list[JsonObject]) -> list[str]:
    return [
        str(event["player_id"])
        for event in events
        if event.get("type") == "quarterly_affairs_triggered" and "player_id" in event
    ]


def _resolve_negative_cash(
    client: httpx.Client,
    game_id: str,
    game: JsonObject,
    state: JsonObject,
    version: int,
) -> tuple[JsonObject, list[JsonObject]]:
    events: list[JsonObject] = []
    for player in _players(state):
        if int(player.get("cash", 0)) >= 0 or player.get("is_bankrupt"):
            continue
        game, emitted = _submit(
            client,
            game_id,
            version,
            {"type": "resolve_cash_shortfall", "player_id": str(player["id"])},
        )
        events.extend(emitted)
        state = _object(game.get("state"), "resolved.state")
        version = _integer(game.get("version"), "resolved.version")
    return game, events


def _game_complete(state: JsonObject) -> bool:
    day_limit = state.get("day_limit")
    if isinstance(day_limit, int) and int(state.get("day", 0)) > day_limit:
        return True
    lap_limit = int(state.get("lap_limit", 0))
    return lap_limit > 0 and any(
        int(player.get("lap", 0)) >= lap_limit for player in _players(state)
    )


def _submit(
    client: httpx.Client, game_id: str, version: int, command: JsonObject
) -> tuple[JsonObject, list[JsonObject]]:
    game = _request(
        client,
        "POST",
        f"/games/{game_id}/commands",
        json={"expected_turn_seq": version, "command": command},
    )
    raw_events = game.get("events")
    if not isinstance(raw_events, list) or not all(isinstance(event, dict) for event in raw_events):
        raise ApiClientError("API command response has invalid events")
    return game, raw_events


def _request(
    client: httpx.Client, method: str, path: str, *, json: JsonObject | None = None
) -> JsonObject:
    try:
        response = client.request(method, path, json=json)
    except httpx.RequestError as exc:
        raise ApiClientError(f"cannot reach API: {exc}") from exc
    return _response_json(response)


def _response_json(response: httpx.Response) -> JsonObject:
    try:
        payload = response.json()
    except ValueError as exc:
        raise ApiClientError(f"API returned non-JSON HTTP {response.status_code}") from exc
    if response.is_error:
        detail = payload.get("detail", payload) if isinstance(payload, dict) else payload
        raise ApiClientError(f"API HTTP {response.status_code}: {detail}")
    return _object(payload, "API response")


def _error_code(response: httpx.Response) -> str | None:
    try:
        payload = response.json()
    except ValueError:
        return None
    if not isinstance(payload, dict) or not isinstance(payload.get("detail"), dict):
        return None
    value = payload["detail"].get("code")
    return value if isinstance(value, str) else None


def _players(state: JsonObject) -> list[JsonObject]:
    players = state.get("players")
    if not isinstance(players, list) or not all(isinstance(player, dict) for player in players):
        raise ApiClientError("API state has invalid players")
    return players


def _object(value: object, label: str) -> JsonObject:
    if not isinstance(value, dict):
        raise ApiClientError(f"{label} must be an object")
    return value


def _integer(value: object, label: str) -> int:
    if not isinstance(value, int) or isinstance(value, bool):
        raise ApiClientError(f"{label} must be an integer")
    return value


def _api_game_id(value: str) -> str:
    try:
        return str(UUID(value))
    except ValueError:
        return str(uuid5(NAMESPACE_URL, f"assetrush-cli:{value}"))


def _write_jsonl(path: Path, events: list[JsonObject]) -> None:
    with path.open("w", encoding="utf-8", newline="\n") as handle:
        for event in events:
            handle.write(json.dumps(event, ensure_ascii=False, sort_keys=True))
            handle.write("\n")


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command")
    subparsers.add_parser("list-commands", help="List offline manual command payloads.")
    run = subparsers.add_parser("run", help="Run or resume a full automatic game.")
    _add_game_args(run)
    run.add_argument("--api-url", default=os.getenv("ASSETRUSH_API_URL", "http://127.0.0.1:8000"))
    run.add_argument(
        "--player-id", action="append", help="Registered player UUID; repeat per player."
    )
    run.add_argument("--timeout", type=float, default=30.0)
    run.add_argument(
        "--offline", action="store_true", help="Use the pure simulator instead of HTTP."
    )
    run.add_argument("--strategy", choices=_strategy_choices(), default="conservative")
    run.add_argument("--max-turns", type=int, default=1000)
    run.add_argument(
        "--pause-after-turns",
        type=int,
        help="Leave the game active after this many turns so a later invocation can resume it.",
    )
    run.add_argument("--events-out", type=Path)
    replay = subparsers.add_parser("replay", help="Replay a JSONL event stream offline.")
    _add_offline_args(replay)
    replay.add_argument("--events-in", type=Path, required=True)
    apply = subparsers.add_parser("apply", help="Apply one command to a new offline game.")
    _add_offline_args(apply)
    apply.add_argument("--command-json", required=True)
    apply.add_argument("--events-out", type=Path)
    return parser


def _add_game_args(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--config-dir", type=Path, default=Path("../../config"))
    parser.add_argument("--mode", choices=("blitz", "daily"), default="blitz")
    parser.add_argument("--players", type=int, default=4)
    parser.add_argument("--seed", default="cli-seed")
    parser.add_argument("--game-id", default="cli-game")
    parser.add_argument("--target-minutes", type=int)


def _add_offline_args(parser: argparse.ArgumentParser) -> None:
    _add_game_args(parser)
    parser.add_argument("--strategy", choices=_strategy_choices(), default="conservative")
    parser.add_argument("--max-turns", type=int, default=1000)


def _strategy_choices() -> tuple[str, ...]:
    return (
        "conservative",
        "aggressive",
        "random",
        "stock_education",
        "vehicle",
        "alliance",
        "mixed",
    )


if __name__ == "__main__":
    sys.exit(main())
