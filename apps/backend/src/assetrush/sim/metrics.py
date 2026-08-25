"""M3 balance metrics for Monte Carlo simulation reports."""

from __future__ import annotations

import math
from collections import Counter, defaultdict
from collections.abc import Iterable, Sequence
from dataclasses import asdict, dataclass
from statistics import median
from typing import Any, Literal

from assetrush.sim.summary import GameRunSummary, PlayerRunSummary

MetricStatus = Literal["pass", "fail", "insufficient_data"]


@dataclass(frozen=True, slots=True)
class MetricResult:
    key: str
    title: str
    value: Any
    threshold: str
    status: MetricStatus
    sample_size: int
    notes: str = ""

    def to_json_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True, slots=True)
class BalanceReport:
    game_count: int
    completed_game_count: int
    metrics: tuple[MetricResult, ...]

    @property
    def passed(self) -> bool:
        return all(metric.status == "pass" for metric in self.metrics)

    def to_json_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["passed"] = self.passed
        payload["status_counts"] = dict(Counter(metric.status for metric in self.metrics))
        return payload


def build_balance_report(summaries: Sequence[GameRunSummary]) -> BalanceReport:
    completed = [summary for summary in summaries if summary.completed and not summary.failed]
    metrics = (
        _starting_advantage(completed),
        _alliance_gap(completed),
        _vehicle_gap(completed),
        _bid_premium(completed),
        _education_vs_property(completed),
        _threshold_end_ratio(completed),
        _first_bankruptcy_timing(completed),
        _turn_order_fairness(completed),
        _thirty_player_duration([summary for summary in summaries if not summary.failed]),
        _dominant_strategy(completed),
        _confinement_frequency(completed),
        _finance_bankruptcy_impact(completed),
        _winner_stock_share(completed),
    )
    return BalanceReport(
        game_count=len(summaries),
        completed_game_count=len(completed),
        metrics=metrics,
    )


def failing_metrics(report: BalanceReport) -> tuple[MetricResult, ...]:
    return tuple(metric for metric in report.metrics if metric.status != "pass")


def _starting_advantage(summaries: Sequence[GameRunSummary]) -> MetricResult:
    daily_players = [
        player for summary in summaries if summary.mode == "daily" for player in summary.players
    ]
    if len(daily_players) < 20:
        return _insufficient(
            "starting_advantage",
            "21 圈是否放大起手優勢",
            len(daily_players),
            "需要至少 20 個日常型玩家樣本。",
        )
    corr = _pearson(
        [player.initial_net_worth for player in daily_players],
        [-player.final_rank for player in daily_players],
    )
    value = abs(corr) if corr is not None else None
    if value is None:
        return _insufficient(
            "starting_advantage",
            "21 圈是否放大起手優勢",
            len(daily_players),
            "起始身價或排名沒有變異。",
        )
    return MetricResult(
        key="starting_advantage",
        title="21 圈是否放大起手優勢",
        value=round(value, 4),
        threshold="abs(corr(initial_net_worth, final_rank)) < 0.35",
        status="pass" if value < 0.35 else "fail",
        sample_size=len(daily_players),
    )


def _alliance_gap(summaries: Sequence[GameRunSummary]) -> MetricResult:
    allied = [player for player in _players(summaries) if player.alliance_member]
    single = [player for player in _players(summaries) if not player.alliance_member]
    if not allied or not single:
        return _insufficient(
            "alliance_win_rate_gap",
            "組隊是否過強",
            len(allied) + len(single),
            "需要同時有組隊者與單身者樣本。",
        )
    gap = abs(_win_rate(allied) - _win_rate(single))
    return MetricResult(
        key="alliance_win_rate_gap",
        title="組隊是否過強",
        value=round(gap, 4),
        threshold="abs(allied_win_rate - single_win_rate) < 0.08",
        status="pass" if gap < 0.08 else "fail",
        sample_size=len(allied) + len(single),
    )


def _vehicle_gap(summaries: Sequence[GameRunSummary]) -> MetricResult:
    holders = [player for player in _players(summaries) if player.vehicle_ever_owned]
    non_holders = [player for player in _players(summaries) if not player.vehicle_ever_owned]
    if not holders or not non_holders:
        return _insufficient(
            "vehicle_win_rate_gap",
            "日常型車輛是否有意義",
            len(holders) + len(non_holders),
            "需要同時有持車與無車玩家樣本。",
        )
    gap = abs(_win_rate(holders) - _win_rate(non_holders))
    return MetricResult(
        key="vehicle_win_rate_gap",
        title="日常型車輛是否有意義",
        value=round(gap, 4),
        threshold="abs(vehicle_win_rate - no_vehicle_win_rate) < 0.10",
        status="pass" if gap < 0.10 else "fail",
        sample_size=len(holders) + len(non_holders),
        notes="此指標驗證車輛不能成為必買或必避策略。",
    )


def _bid_premium(summaries: Sequence[GameRunSummary]) -> MetricResult:
    bids = [
        bid
        for summary in summaries
        if summary.mode == "daily"
        for bid in summary.bids
        if bid.contested
    ]
    high_cash_bids = [bid for bid in bids if bid.high_cash_player]
    winning_bids = [bid for bid in bids if bid.won]
    if len(high_cash_bids) < 10 or len(winning_bids) < 10:
        return _insufficient(
            "bid_premium_control",
            "認購溢價是否有效抑制碾壓",
            len(bids),
            "需要至少 10 筆競爭性高現金出價與 10 筆競爭性得標出價。",
        )
    high_cash_success = sum(1 for bid in high_cash_bids if bid.won) / len(high_cash_bids)
    average_premium = sum(max(0.0, bid.premium_ratio) for bid in winning_bids) / len(winning_bids)
    passed = high_cash_success < 0.60 and average_premium < 0.25
    return MetricResult(
        key="bid_premium_control",
        title="競爭性認購溢價是否有效抑制碾壓",
        value={
            "high_cash_success_rate": round(high_cash_success, 4),
            "average_winning_premium": round(average_premium, 4),
        },
        threshold="high_cash_success_rate < 0.60 and average_winning_premium < 0.25",
        status="pass" if passed else "fail",
        sample_size=len(bids),
    )


def _education_vs_property(summaries: Sequence[GameRunSummary]) -> MetricResult:
    educated = [player for player in _players(summaries) if player.education_started]
    property_only = [
        player
        for player in _players(summaries)
        if player.property_ever_owned and not player.education_started
    ]
    if not educated or not property_only:
        return _insufficient(
            "education_vs_property",
            "進修 vs 購地是否平衡",
            len(educated) + len(property_only),
            "需要同時有進修與純購地路徑樣本。",
        )
    gap = abs(_win_rate(educated) - _win_rate(property_only))
    return MetricResult(
        key="education_vs_property",
        title="進修 vs 購地是否平衡",
        value=round(gap, 4),
        threshold="abs(education_win_rate - property_win_rate) < 0.10",
        status="pass" if gap < 0.10 else "fail",
        sample_size=len(educated) + len(property_only),
    )


def _threshold_end_ratio(summaries: Sequence[GameRunSummary]) -> MetricResult:
    by_mode: dict[str, list[GameRunSummary]] = defaultdict(list)
    for summary in summaries:
        by_mode[summary.mode].append(summary)
    values: dict[str, float] = {}
    passed = True
    sample_size = 0
    for mode, mode_summaries in by_mode.items():
        if len(mode_summaries) < 10:
            continue
        ratio = sum(
            1 for summary in mode_summaries if summary.end_reason == "net_worth_threshold"
        ) / len(mode_summaries)
        values[mode] = round(ratio, 4)
        sample_size += len(mode_summaries)
        if mode == "blitz":
            passed = passed and 0.15 <= ratio <= 0.30
        elif mode == "daily":
            passed = passed and 0.20 <= ratio <= 0.40
    if not values:
        return _insufficient(
            "threshold_end_ratio",
            "資產門檻公式是否恰當",
            len(summaries),
            "每個模式至少需要 10 局樣本。",
        )
    return MetricResult(
        key="threshold_end_ratio",
        title="資產門檻公式是否恰當",
        value=values,
        threshold="blitz 15-30%; daily 20-40% of games end by net worth threshold",
        status="pass" if passed else "fail",
        sample_size=sample_size,
    )


def _first_bankruptcy_timing(summaries: Sequence[GameRunSummary]) -> MetricResult:
    first_days = [
        summary.first_bankruptcy_day
        for summary in summaries
        if summary.first_bankruptcy_day is not None
    ]
    if len(first_days) < 5:
        return _insufficient(
            "first_bankruptcy_timing",
            "破產會太早嗎",
            len(first_days),
            "需要至少 5 局發生破產才能估計中位數。",
        )
    value = float(median(first_days))
    return MetricResult(
        key="first_bankruptcy_timing",
        title="破產會太早嗎",
        value=round(value, 4),
        threshold="median(first_bankruptcy_day_or_lap) > 4",
        status="pass" if value > 4 else "fail",
        sample_size=len(first_days),
    )


def _turn_order_fairness(summaries: Sequence[GameRunSummary]) -> MetricResult:
    samples = [
        (player.initial_turn_order_index, -player.final_rank / summary.player_count)
        for summary in summaries
        if summary.mode == "daily"
        for player in summary.players
        if player.initial_turn_order_index >= 0
    ]
    if len(samples) < 20:
        return _insufficient(
            "turn_order_fairness",
            "順位輪替是否公平",
            len(samples),
            "需要至少 20 個玩家樣本。",
        )
    corr = _pearson(
        [turn_order_index for turn_order_index, _rank in samples],
        [rank for _turn_order_index, rank in samples],
    )
    value = abs(corr) if corr is not None else None
    if value is None:
        return _insufficient(
            "turn_order_fairness",
            "順位輪替是否公平",
            len(samples),
            "順位或排名沒有變異。",
        )
    return MetricResult(
        key="turn_order_fairness",
        title="順位輪替是否公平",
        value=round(value, 4),
        threshold="abs(corr(initial_turn_order_index, normalized_final_rank)) < 0.10",
        status="pass" if value < 0.10 else "fail",
        sample_size=len(samples),
    )


def _thirty_player_duration(summaries: Sequence[GameRunSummary]) -> MetricResult:
    rows = [
        summary
        for summary in summaries
        if summary.mode == "daily" and summary.player_count == 30 and summary.day is not None
    ]
    if len(rows) < 5:
        return _insufficient(
            "thirty_player_duration",
            "30 人局撐得住嗎",
            len(rows),
            "需要至少 5 局 30 人日常型樣本。",
        )
    value = float(median(summary.day or 0 for summary in rows))
    return MetricResult(
        key="thirty_player_duration",
        title="30 人局撐得住嗎",
        value=round(value, 4),
        threshold="median(day) > 12",
        status="pass" if value > 12 else "fail",
        sample_size=len(rows),
        notes="起始現金 x1.3 是否必要需對照 config 調整前後報表。",
    )


def _dominant_strategy(summaries: Sequence[GameRunSummary]) -> MetricResult:
    by_strategy: dict[str, list[PlayerRunSummary]] = defaultdict(list)
    for player in _players(summaries):
        by_strategy[player.strategy].append(player)
    if len(by_strategy) < 2 or min(len(players) for players in by_strategy.values()) < 5:
        return _insufficient(
            "dominant_strategy",
            "有沒有支配性策略",
            sum(len(players) for players in by_strategy.values()),
            "需要至少兩種策略，且每種策略至少 5 個玩家樣本。",
        )
    win_rates = {strategy: _win_rate(players) for strategy, players in sorted(by_strategy.items())}
    max_rate = max(win_rates.values())
    return MetricResult(
        key="dominant_strategy",
        title="有沒有支配性策略",
        value={strategy: round(rate, 4) for strategy, rate in win_rates.items()},
        threshold="max(strategy_win_rate) <= 0.60",
        status="pass" if max_rate <= 0.60 else "fail",
        sample_size=sum(len(players) for players in by_strategy.values()),
    )


def _confinement_frequency(summaries: Sequence[GameRunSummary]) -> MetricResult:
    player_years = sum(max(player.final_lap, 1) / 4 for player in _players(summaries))
    if player_years < 20:
        return _insufficient(
            "confinement_frequency",
            "監獄／醫院頻率是否合理",
            round(player_years),
            "需要至少 20 player-years 曝險樣本。",
        )
    jail = sum(summary.confinement_counts.get("jail", 0) for summary in summaries)
    hospital = sum(summary.confinement_counts.get("hospital", 0) for summary in summaries)
    jail_rate = jail / player_years
    hospital_rate = hospital / player_years
    passed = 0.08 <= jail_rate <= 0.24 and 0.135 <= hospital_rate <= 0.405
    return MetricResult(
        key="confinement_frequency",
        title="監獄／醫院頻率是否合理",
        value={
            "jail_per_player_year": round(jail_rate, 4),
            "hospital_per_player_year": round(hospital_rate, 4),
        },
        threshold="jail 0.08-0.24; hospital 0.135-0.405 per player-year",
        status="pass" if passed else "fail",
        sample_size=round(player_years),
    )


def _finance_bankruptcy_impact(summaries: Sequence[GameRunSummary]) -> MetricResult:
    with_finance = [
        summary
        for summary in summaries
        if any(player.initial_occupation_key == "finance" for player in summary.players)
    ]
    without_finance = [
        summary
        for summary in summaries
        if all(player.initial_occupation_key != "finance" for player in summary.players)
    ]
    if len(with_finance) < 5 or len(without_finance) < 5:
        return _insufficient(
            "finance_bankruptcy_impact",
            "金融業私人放貸是否過度影響破產率",
            len(with_finance) + len(without_finance),
            "需要至少 5 局有金融業與 5 局無金融業樣本。",
        )
    gap = abs(_bankruptcy_rate(with_finance) - _bankruptcy_rate(without_finance))
    return MetricResult(
        key="finance_bankruptcy_impact",
        title="金融業私人放貸是否過度影響破產率",
        value=round(gap, 4),
        threshold="abs(bankruptcy_rate_with_finance - without_finance) < 0.10",
        status="pass" if gap < 0.10 else "fail",
        sample_size=len(with_finance) + len(without_finance),
    )


def _winner_stock_share(summaries: Sequence[GameRunSummary]) -> MetricResult:
    winners = [player for player in _players(summaries) if player.final_rank == 1]
    shares = [
        player.final_stock_value / player.final_net_worth
        for player in winners
        if player.final_net_worth > 0
    ]
    if len(shares) < 10:
        return _insufficient(
            "winner_stock_share",
            "真實股價的尺度是否可玩",
            len(shares),
            "需要至少 10 位勝者且身價為正。",
        )
    value = sum(shares) / len(shares)
    return MetricResult(
        key="winner_stock_share",
        title="真實股價的尺度是否可玩",
        value=round(value, 4),
        threshold="winner stock share between 0.10 and 0.30",
        status="pass" if 0.10 <= value <= 0.30 else "fail",
        sample_size=len(shares),
    )


def _players(summaries: Sequence[GameRunSummary]) -> Iterable[PlayerRunSummary]:
    for summary in summaries:
        yield from summary.players


def _win_rate(players: Sequence[PlayerRunSummary]) -> float:
    return sum(1 for player in players if player.final_rank == 1) / len(players)


def _bankruptcy_rate(summaries: Sequence[GameRunSummary]) -> float:
    players = list(_players(summaries))
    return sum(1 for player in players if player.bankrupt) / len(players)


def _pearson(left: Sequence[float], right: Sequence[float]) -> float | None:
    if len(left) != len(right) or len(left) < 2:
        return None
    left_mean = sum(left) / len(left)
    right_mean = sum(right) / len(right)
    numerator = sum((x - left_mean) * (y - right_mean) for x, y in zip(left, right, strict=True))
    left_var = sum((x - left_mean) ** 2 for x in left)
    right_var = sum((y - right_mean) ** 2 for y in right)
    denominator = math.sqrt(left_var * right_var)
    if denominator == 0:
        return None
    return numerator / denominator


def _insufficient(key: str, title: str, sample_size: int, notes: str) -> MetricResult:
    return MetricResult(
        key=key,
        title=title,
        value=None,
        threshold="insufficient data",
        status="insufficient_data",
        sample_size=sample_size,
        notes=notes,
    )
