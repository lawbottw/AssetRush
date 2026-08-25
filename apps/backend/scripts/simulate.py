"""Run M3 Monte Carlo simulations and emit balance metrics.

Examples:
    uv run python scripts/simulate.py --mode daily --players 10 --games 1000
    uv run python scripts/simulate.py --mode blitz --players 4 --games 100 --jsonl-out runs.jsonl
"""

from __future__ import annotations

import argparse
import json
import multiprocessing
import queue
import sys
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol, cast

from assetrush.config_bundle import load_raw_config
from assetrush.console import force_utf8_output
from assetrush.engine import GameMode
from assetrush.sim.metrics import build_balance_report, failing_metrics
from assetrush.sim.runner import RunnerSpec, StrategyName, run_auto_game
from assetrush.sim.summary import (
    GameRunSummary,
    failed_game_summary,
    game_summary_from_json_dict,
    summarize_game_result,
    summarize_many,
)

STRATEGIES: tuple[StrategyName, ...] = (
    "mixed",
    "conservative",
    "aggressive",
    "stock_education",
    "vehicle",
    "alliance",
    "random",
)


@dataclass(frozen=True, slots=True)
class ScenarioRow:
    mode: GameMode
    player_count: int
    strategy: StrategyName


M3_SCENARIO: tuple[ScenarioRow, ...] = (
    ScenarioRow(mode="daily", player_count=4, strategy="mixed"),
    ScenarioRow(mode="daily", player_count=10, strategy="mixed"),
    ScenarioRow(mode="daily", player_count=30, strategy="mixed"),
    ScenarioRow(mode="blitz", player_count=4, strategy="mixed"),
    ScenarioRow(mode="blitz", player_count=8, strategy="mixed"),
)
M3_CORE_SCENARIO: tuple[ScenarioRow, ...] = tuple(
    row for row in M3_SCENARIO if not (row.mode == "daily" and row.player_count == 30)
)
M3_CROWDED_SCENARIO: tuple[ScenarioRow, ...] = (
    ScenarioRow(mode="daily", player_count=30, strategy="mixed"),
)


def main(argv: list[str] | None = None) -> int:
    force_utf8_output()
    parser = _parser()
    args = parser.parse_args(argv)
    if args.jsonl_in is not None and args.jsonl_out is not None:
        parser.error("--jsonl-in cannot be combined with --jsonl-out")

    summaries: list[GameRunSummary] = []
    if args.jsonl_in is not None:
        summaries = _read_jsonl_files(args.jsonl_in)
    elif args.jsonl_out is None:
        config = load_raw_config(args.config_dir)
        for summary in _run_specs(_build_specs(args), config, args.max_game_seconds):
            summaries.append(summary)
            _write_jsonl(sys.stdout, [summary])
    else:
        config = load_raw_config(args.config_dir)
        args.jsonl_out.parent.mkdir(parents=True, exist_ok=True)
        with args.jsonl_out.open("w", encoding="utf-8", newline="\n") as handle:
            for summary in _run_specs(_build_specs(args), config, args.max_game_seconds):
                summaries.append(summary)
                _write_jsonl(handle, [summary])
                handle.flush()

    report = build_balance_report(summaries)
    payload = {
        "summary": summarize_many(summaries),
        "balance_report": report.to_json_dict(),
    }
    encoded = json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True)
    if args.report_out is not None:
        args.report_out.parent.mkdir(parents=True, exist_ok=True)
        args.report_out.write_text(encoded + "\n", encoding="utf-8")
    print(encoded, file=sys.stderr if args.jsonl_out is None else sys.stdout)

    if args.fail_on_threshold and failing_metrics(report):
        return 1
    return 0 if not any(summary.failed for summary in summaries) else 1


def _run_specs(
    specs: Sequence[RunnerSpec],
    config: dict[str, object],
    max_game_seconds: float | None = None,
) -> Iterable[GameRunSummary]:
    for spec in specs:
        if max_game_seconds is not None:
            yield _run_spec_with_timeout(spec, config, max_game_seconds)
            continue
        try:
            yield summarize_game_result(run_auto_game(spec, config))
        except Exception as exc:  # noqa: BLE001 - batch simulations must record failed games.
            yield failed_game_summary(spec, exc)


def _run_spec_with_timeout(
    spec: RunnerSpec,
    config: dict[str, object],
    max_game_seconds: float,
) -> GameRunSummary:
    context = multiprocessing.get_context("spawn")
    output: multiprocessing.Queue[GameRunSummary] = context.Queue(maxsize=1)
    process = context.Process(target=_run_spec_worker, args=(spec, config, output))
    process.start()
    process.join(max_game_seconds)
    if process.is_alive():
        process.terminate()
        process.join()
        return failed_game_summary(
            spec,
            TimeoutError(f"game exceeded --max-game-seconds={max_game_seconds:g}"),
        )
    try:
        return output.get_nowait()
    except queue.Empty:
        return failed_game_summary(
            spec,
            RuntimeError(f"game worker exited without a summary; exitcode={process.exitcode}"),
        )


def _run_spec_worker(
    spec: RunnerSpec,
    config: dict[str, object],
    output: multiprocessing.Queue[GameRunSummary],
) -> None:
    try:
        output.put(summarize_game_result(run_auto_game(spec, config)))
    except Exception as exc:  # noqa: BLE001 - worker must preserve the failure as data.
        output.put(failed_game_summary(spec, exc))


def _build_specs(args: argparse.Namespace) -> tuple[RunnerSpec, ...]:
    specs: list[RunnerSpec] = []
    scenario_rows = _scenario_rows(args.scenario)
    if scenario_rows is not None:
        row_counts: dict[ScenarioRow, int] = {}
        for index in range(args.games):
            row = scenario_rows[index % len(scenario_rows)]
            row_counts[row] = row_counts.get(row, 0) + 1
            row_seed = f"{args.seed}:{row.mode}:{row.player_count}:{row_counts[row]}"
            specs.append(
                RunnerSpec(
                    mode=row.mode,
                    player_count=row.player_count,
                    seed=row_seed,
                    game_id=f"sim-{row.mode}-{row.player_count}-{row_counts[row]}",
                    target_minutes=args.target_minutes,
                    strategy=row.strategy,
                    strategy_offset=(row_counts[row] - 1) % 5,
                    max_turns=args.max_turns,
                    verify_replay=not args.skip_replay,
                )
            )
        return tuple(specs)

    strategies = STRATEGIES if args.strategy == "matrix" else (_strategy_name(args.strategy),)
    modes: tuple[GameMode, ...] = (
        ("blitz", "daily") if args.mode == "all" else (_game_mode(args.mode),)
    )
    for index in range(args.games):
        mode = modes[index % len(modes)]
        strategy = strategies[index % len(strategies)]
        specs.append(
            RunnerSpec(
                mode=mode,
                player_count=args.players,
                seed=f"{args.seed}:{index + 1}",
                game_id=f"sim-{mode}-{args.players}-{index + 1}",
                target_minutes=args.target_minutes,
                strategy=strategy,
                strategy_offset=index % 5,
                max_turns=args.max_turns,
                verify_replay=not args.skip_replay,
            )
        )
    return tuple(specs)


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config-dir", type=Path, default=Path("../../config"))
    parser.add_argument("--mode", choices=("blitz", "daily", "all"), default="daily")
    parser.add_argument("--players", type=int, default=10)
    parser.add_argument("--games", type=int, default=1000)
    parser.add_argument("--seed", default="m3")
    parser.add_argument("--strategy", choices=(*STRATEGIES, "matrix"), default="mixed")
    parser.add_argument(
        "--scenario",
        choices=("single", "m3", "m3-core", "m3-crowded"),
        default="single",
        help="single uses --mode/--players; m3 cycles the MVP balance scenario matrix.",
    )
    parser.add_argument("--target-minutes", type=int)
    parser.add_argument("--max-turns", type=int, default=5000)
    parser.add_argument("--jsonl-out", type=Path)
    parser.add_argument(
        "--jsonl-in",
        type=Path,
        nargs="+",
        help="Aggregate one or more existing simulation JSONL files into a report.",
    )
    parser.add_argument("--report-out", type=Path)
    parser.add_argument("--fail-on-threshold", action="store_true")
    parser.add_argument(
        "--max-game-seconds",
        type=float,
        help="Record a failed summary and continue when one game exceeds this runtime.",
    )
    parser.add_argument(
        "--skip-replay",
        action="store_true",
        help="Skip per-game event replay verification for large balance batches.",
    )
    return parser


def _game_mode(value: str) -> GameMode:
    if value == "blitz" or value == "daily":
        return cast(GameMode, value)
    raise ValueError(f"unsupported mode: {value}")


def _strategy_name(value: str) -> StrategyName:
    if value in STRATEGIES:
        return value
    raise ValueError(f"unsupported strategy: {value}")


def _scenario_rows(value: str) -> tuple[ScenarioRow, ...] | None:
    if value == "single":
        return None
    if value == "m3":
        return M3_SCENARIO
    if value == "m3-core":
        return M3_CORE_SCENARIO
    if value == "m3-crowded":
        return M3_CROWDED_SCENARIO
    raise ValueError(f"unsupported scenario: {value}")


def _read_jsonl_files(paths: Sequence[Path]) -> list[GameRunSummary]:
    summaries: list[GameRunSummary] = []
    for path in paths:
        with path.open(encoding="utf-8") as handle:
            for line_number, line in enumerate(handle, start=1):
                if not line.strip():
                    continue
                try:
                    payload = json.loads(line)
                    if not isinstance(payload, dict):
                        raise ValueError("row must be a JSON object")
                    summaries.append(game_summary_from_json_dict(payload))
                except Exception as exc:
                    raise ValueError(f"invalid JSONL row {path}:{line_number}: {exc}") from exc
    return summaries


def _write_jsonl(handle: object, summaries: Sequence[GameRunSummary]) -> None:
    writer = cast(SupportsWrite, handle)
    for summary in summaries:
        writer.write(json.dumps(summary.to_json_dict(), ensure_ascii=False, sort_keys=True))
        writer.write("\n")


class SupportsWrite(Protocol):
    def write(self, text: str) -> object: ...


if __name__ == "__main__":
    raise SystemExit(main())
