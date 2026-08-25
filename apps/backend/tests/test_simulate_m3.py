from __future__ import annotations

import json
from pathlib import Path

from simulate import main as simulate_main

from assetrush.sim.metrics import build_balance_report
from assetrush.sim.summary import GameRunSummary, PlayerRunSummary, summarize_many

CONFIG_DIR = Path(__file__).resolve().parents[3] / "config"


def test_simulate_cli_writes_reproducible_jsonl_and_report(tmp_path: Path) -> None:
    first_jsonl = tmp_path / "first.jsonl"
    second_jsonl = tmp_path / "second.jsonl"
    report_path = tmp_path / "report.json"
    args = [
        "--config-dir",
        str(CONFIG_DIR),
        "--mode",
        "blitz",
        "--players",
        "2",
        "--games",
        "2",
        "--seed",
        "deterministic",
        "--max-turns",
        "300",
        "--jsonl-out",
        str(first_jsonl),
        "--report-out",
        str(report_path),
    ]

    assert simulate_main(args) == 0
    assert simulate_main([*args[:-3], str(second_jsonl)]) == 0

    first_lines = first_jsonl.read_text(encoding="utf-8").splitlines()
    assert first_lines == second_jsonl.read_text(encoding="utf-8").splitlines()
    assert len(first_lines) == 2
    assert all(json.loads(line)["completed"] for line in first_lines)

    report = json.loads(report_path.read_text(encoding="utf-8"))
    assert report["summary"]["games"] == 2
    assert len(report["balance_report"]["metrics"]) == 13


def test_simulate_m3_scenario_cycles_core_modes_and_player_counts(tmp_path: Path) -> None:
    jsonl_path = tmp_path / "m3.jsonl"

    assert (
        simulate_main(
            [
                "--config-dir",
                str(CONFIG_DIR),
                "--scenario",
                "m3",
                "--games",
                "5",
                "--seed",
                "scenario",
                "--max-turns",
                "300",
                "--jsonl-out",
                str(jsonl_path),
            ]
        )
        == 0
    )

    rows = [json.loads(line) for line in jsonl_path.read_text(encoding="utf-8").splitlines()]
    assert {(row["mode"], row["player_count"]) for row in rows} == {
        ("daily", 4),
        ("daily", 10),
        ("daily", 30),
        ("blitz", 4),
        ("blitz", 8),
    }


def test_simulate_m3_core_scenario_excludes_crowded_daily_run(tmp_path: Path) -> None:
    jsonl_path = tmp_path / "m3-core.jsonl"

    assert (
        simulate_main(
            [
                "--config-dir",
                str(CONFIG_DIR),
                "--scenario",
                "m3-core",
                "--games",
                "4",
                "--seed",
                "scenario-core",
                "--max-turns",
                "300",
                "--jsonl-out",
                str(jsonl_path),
            ]
        )
        == 0
    )

    rows = [json.loads(line) for line in jsonl_path.read_text(encoding="utf-8").splitlines()]
    assert {(row["mode"], row["player_count"]) for row in rows} == {
        ("daily", 4),
        ("daily", 10),
        ("blitz", 4),
        ("blitz", 8),
    }


def test_simulate_rotates_mixed_strategy_assignments_between_repeated_rows(tmp_path: Path) -> None:
    jsonl_path = tmp_path / "m3-core-rotated.jsonl"

    assert (
        simulate_main(
            [
                "--config-dir",
                str(CONFIG_DIR),
                "--scenario",
                "m3-core",
                "--games",
                "8",
                "--seed",
                "strategy-offset",
                "--max-turns",
                "300",
                "--jsonl-out",
                str(jsonl_path),
            ]
        )
        == 0
    )

    rows = [json.loads(line) for line in jsonl_path.read_text(encoding="utf-8").splitlines()]
    first_player_strategies = [
        row["players"][0]["strategy"]
        for row in rows
        if row["mode"] == "daily" and row["player_count"] == 4
    ]
    assert first_player_strategies == ["conservative", "aggressive"]


def test_simulate_aggregates_existing_jsonl_files_into_report(tmp_path: Path) -> None:
    first = tmp_path / "first.jsonl"
    second = tmp_path / "second.jsonl"
    report_path = tmp_path / "combined-report.json"
    summaries = [_synthetic_summary(index) for index in range(2)]
    first.write_text(
        json.dumps(summaries[0].to_json_dict(), ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    second.write_text(
        json.dumps(summaries[1].to_json_dict(), ensure_ascii=False) + "\n",
        encoding="utf-8",
    )

    assert (
        simulate_main(
            [
                "--jsonl-in",
                str(first),
                str(second),
                "--report-out",
                str(report_path),
            ]
        )
        == 0
    )

    report = json.loads(report_path.read_text(encoding="utf-8"))
    assert report["summary"]["games"] == 2
    assert len(report["balance_report"]["metrics"]) == 13


def test_simulate_records_timed_out_game_as_failed_summary(tmp_path: Path) -> None:
    jsonl_path = tmp_path / "timeout.jsonl"

    assert (
        simulate_main(
            [
                "--config-dir",
                str(CONFIG_DIR),
                "--mode",
                "daily",
                "--players",
                "10",
                "--games",
                "1",
                "--seed",
                "timeout",
                "--max-game-seconds",
                "0.001",
                "--jsonl-out",
                str(jsonl_path),
            ]
        )
        == 1
    )

    row = json.loads(jsonl_path.read_text(encoding="utf-8"))
    assert row["failed"] is True
    assert "max-game-seconds" in row["error"]


def test_balance_report_outputs_all_m3_metrics_with_pass_fail_status() -> None:
    summaries = [_synthetic_summary(index) for index in range(20)]
    report = build_balance_report(summaries)
    metrics = {metric.key: metric for metric in report.metrics}

    assert set(metrics) == {
        "starting_advantage",
        "alliance_win_rate_gap",
        "vehicle_win_rate_gap",
        "bid_premium_control",
        "education_vs_property",
        "threshold_end_ratio",
        "first_bankruptcy_timing",
        "turn_order_fairness",
        "thirty_player_duration",
        "dominant_strategy",
        "confinement_frequency",
        "finance_bankruptcy_impact",
        "winner_stock_share",
    }
    assert all(metric.status in {"pass", "fail", "insufficient_data"} for metric in report.metrics)
    assert metrics["dominant_strategy"].status == "pass"
    assert metrics["winner_stock_share"].status == "pass"


def test_summarize_many_keeps_failed_games_visible() -> None:
    completed = _synthetic_summary(0)
    failed = GameRunSummary(
        game_id="failed",
        mode="daily",
        player_count=10,
        seed="failed",
        strategy="mixed",
        target_minutes=None,
        max_turns=1,
        completed=False,
        replay_checked=True,
        replay_verified=False,
        failed=True,
        error="boom",
        turns_executed=0,
        event_count=0,
        final_phase=None,
        day=None,
        day_limit=None,
        lap_limit=None,
        net_worth_threshold=None,
        max_lap=0,
        end_reason="failed",
        event_counts={},
        confinement_counts={},
        first_bankruptcy_day=None,
        players=(),
        bids=(),
    )

    summary = summarize_many([completed, failed])

    assert summary["games"] == 2
    assert summary["completed_games"] == 1
    assert summary["failed_games"] == 1


def _synthetic_summary(index: int) -> GameRunSummary:
    mode = "daily" if index < 10 else "blitz"
    player_count = 30 if index < 5 else 10
    p1_wins = index % 2 == 0
    players = (
        _player(
            "p1",
            strategy="conservative",
            initial_net_worth=200_000,
            rank=1 if p1_wins else 2,
            alliance_member=True,
            vehicle=True,
            education=True,
            finance=index < 5,
        ),
        _player(
            "p2",
            strategy="aggressive",
            initial_net_worth=100_000,
            rank=2 if p1_wins else 1,
            alliance_member=False,
            vehicle=False,
            education=False,
            finance=False,
        ),
    )
    confinement_counts = {"jail": 1} if index in {0, 1, 2, 3} else {}
    if index in {4, 5, 6, 7, 8, 9, 10, 11}:
        confinement_counts = {**confinement_counts, "hospital": 1}
    bids = ()
    if mode == "daily":
        bids = (
            {
                "player_id": "p1",
                "won": p1_wins,
                "bid_amount": 100_000,
                "base_price": 100_000,
                "premium_ratio": 0.0,
                "high_cash_player": True,
            },
            {
                "player_id": "p2",
                "won": not p1_wins,
                "bid_amount": 100_000,
                "base_price": 100_000,
                "premium_ratio": 0.0,
                "high_cash_player": False,
            },
        )
    return GameRunSummary(
        game_id=f"synthetic-{index}",
        mode=mode,
        player_count=player_count,
        seed=f"seed-{index}",
        strategy="mixed",
        target_minutes=None,
        max_turns=100,
        completed=True,
        replay_checked=True,
        replay_verified=True,
        failed=False,
        error=None,
        turns_executed=100,
        event_count=10,
        final_phase="finished",
        day=13 if player_count == 30 else 6,
        day_limit=21 if mode == "daily" else None,
        lap_limit=21 if mode == "daily" else 4,
        net_worth_threshold=1_000_000,
        max_lap=4,
        end_reason="net_worth_threshold" if index % 4 == 0 else "lap_limit",
        event_counts={"salary_paid": 2},
        confinement_counts=confinement_counts,
        first_bankruptcy_day=5 if index < 5 else None,
        players=players,
        bids=tuple(_bid_from_dict(row) for row in bids),
    )


def _player(
    player_id: str,
    *,
    strategy: str,
    initial_net_worth: int,
    rank: int,
    alliance_member: bool,
    vehicle: bool,
    education: bool,
    finance: bool,
) -> PlayerRunSummary:
    return PlayerRunSummary(
        player_id=player_id,
        strategy=strategy,
        initial_turn_order_index=0 if player_id == "p1" else 1,
        initial_background_key="middle",
        initial_occupation_key="finance" if finance else "office_worker",
        initial_cash=initial_net_worth,
        initial_net_worth=initial_net_worth,
        initial_monthly_salary=50_000,
        initial_has_vehicle=vehicle,
        final_cash=200_000,
        final_net_worth=500_000,
        final_rank=rank,
        final_lap=4,
        final_property_count=1,
        final_stock_value=100_000 if rank == 1 else 25_000,
        final_debt=0,
        bankrupt=False,
        alliance_member=alliance_member,
        vehicle_ever_owned=vehicle,
        education_started=education,
        education_completed=education,
        education_effective=education,
        property_ever_owned=True,
    )


def _bid_from_dict(payload: dict[str, object]):
    from assetrush.sim.summary import BidRunSummary

    return BidRunSummary(
        player_id=str(payload["player_id"]),
        won=bool(payload["won"]),
        bid_amount=int(payload["bid_amount"]),
        base_price=int(payload["base_price"]),
        premium_ratio=float(payload["premium_ratio"]),
        high_cash_player=bool(payload["high_cash_player"]),
    )
