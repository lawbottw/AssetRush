"""Pure text game runner for M2.

Examples:
    uv run python scripts/play_cli.py run --mode blitz --players 4 --seed demo
    uv run python scripts/play_cli.py list-commands
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from collections.abc import Sequence
from pathlib import Path
from typing import Any, cast

from assetrush.config_bundle import load_raw_config
from assetrush.console import force_utf8_output
from assetrush.engine import GameMode, state_digest
from assetrush.engine.event_codec import event_from_dict, event_to_dict
from assetrush.engine.events import Event
from assetrush.sim.runner import (
    RunnerSpec,
    StrategyName,
    apply_command_payload,
    available_cli_commands,
    create_initial_state,
    replay_event_stream,
    run_auto_game,
)


def main(argv: list[str] | None = None) -> int:
    force_utf8_output()
    parser = _parser()
    args = parser.parse_args(argv)
    if args.command == "list-commands":
        print(json.dumps(available_cli_commands(), ensure_ascii=False, indent=2))
        return 0
    if args.command == "run":
        return _run(args)
    if args.command == "replay":
        return _replay(args)
    if args.command == "apply":
        return _apply(args)
    parser.error("missing command")
    return 2


def _run(args: argparse.Namespace) -> int:
    config = load_raw_config(args.config_dir)
    spec = _runner_spec(args)
    result = run_auto_game(spec, config)
    if args.events_out is not None:
        _write_events(args.events_out, result.events)
    print(
        json.dumps(
            {
                "game_id": result.spec.game_id,
                "mode": result.spec.mode,
                "players": result.spec.player_count,
                "strategy": result.spec.strategy,
                "turns_executed": result.turns_executed,
                "event_count": len(result.events),
                "final_phase": result.final_state.phase,
                "final_digest": _digest_hash(result.final_digest),
                "replay_digest": _digest_hash(result.replay_digest),
                "replay_verified": result.final_digest == result.replay_digest,
                "completed": result.completed,
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0 if result.completed else 1


def _replay(args: argparse.Namespace) -> int:
    config = load_raw_config(args.config_dir)
    initial = create_initial_state(_runner_spec(args), config)
    events = tuple(event_from_dict(row) for row in _read_jsonl(args.events_in))
    final_state, digest = replay_event_stream(initial, events)
    print(
        json.dumps(
            {
                "event_count": len(events),
                "final_phase": final_state.phase,
                "digest": _digest_hash(digest),
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0


def _apply(args: argparse.Namespace) -> int:
    config = load_raw_config(args.config_dir)
    state = create_initial_state(_runner_spec(args), config)
    payload = json.loads(args.command_json)
    if not isinstance(payload, dict):
        raise ValueError("--command-json must decode to an object")
    transition = apply_command_payload(state, payload, config)
    if args.events_out is not None:
        _write_events(args.events_out, transition.events)
    print(
        json.dumps(
            {
                "event_count": len(transition.events),
                "state_digest": _digest_hash(state_digest(transition.state)),
                "events": [event_to_dict(event) for event in transition.events],
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command")

    subparsers.add_parser("list-commands", help="List supported manual command payloads.")

    run = subparsers.add_parser("run", help="Run a full automatic game.")
    _add_game_args(run)
    run.add_argument("--strategy", choices=_strategy_choices(), default="conservative")
    run.add_argument("--max-turns", type=int, default=1000)
    run.add_argument("--events-out", type=Path)

    replay = subparsers.add_parser("replay", help="Replay a JSONL event stream.")
    _add_game_args(replay)
    replay.add_argument("--events-in", type=Path, required=True)

    apply = subparsers.add_parser("apply", help="Apply one command payload to a new game.")
    _add_game_args(apply)
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


def _runner_spec(args: argparse.Namespace) -> RunnerSpec:
    strategy = getattr(args, "strategy", "conservative")
    max_turns = getattr(args, "max_turns", 1000)
    return RunnerSpec(
        mode=_game_mode(args.mode),
        player_count=args.players,
        seed=args.seed,
        game_id=args.game_id,
        target_minutes=args.target_minutes,
        strategy=_strategy_name(strategy),
        max_turns=max_turns,
    )


def _game_mode(value: str) -> GameMode:
    if value == "blitz" or value == "daily":
        return cast(GameMode, value)
    raise ValueError(f"unsupported mode: {value}")


def _strategy_name(value: str) -> StrategyName:
    if value in _strategy_choices():
        return value
    raise ValueError(f"unsupported strategy: {value}")


def _strategy_choices() -> tuple[StrategyName, ...]:
    return ("conservative", "aggressive", "random", "stock_education")


def _write_events(path: Path, events: Sequence[Event]) -> None:
    with path.open("w", encoding="utf-8", newline="\n") as handle:
        for event in events:
            handle.write(json.dumps(event_to_dict(event), ensure_ascii=False, sort_keys=True))
            handle.write("\n")


def _read_jsonl(path: Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    with path.open(encoding="utf-8") as handle:
        for line_number, line in enumerate(handle, start=1):
            if not line.strip():
                continue
            value = json.loads(line)
            if not isinstance(value, dict):
                raise ValueError(f"{path}:{line_number}: expected object")
            rows.append(value)
    return rows


def _digest_hash(digest: str) -> str:
    return hashlib.sha256(digest.encode("utf-8")).hexdigest()


if __name__ == "__main__":
    sys.exit(main())
