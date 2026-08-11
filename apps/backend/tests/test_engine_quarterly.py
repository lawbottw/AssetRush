from __future__ import annotations

import pytest

from assetrush.engine import (
    GameState,
    InvalidCommandError,
    PlayerLoan,
    PlayerState,
    QuarterlyChoices,
    RunQuarterlyAffairsCommand,
    StockHolding,
    available_quarterly_actions,
    execute_command,
    replay_events,
    state_digest,
)


def test_quarterly_affairs_are_deterministic_and_replayable() -> None:
    state = _state(cash=100_000, monthly_salary=10_000)
    command = RunQuarterlyAffairsCommand(
        type="run_quarterly_affairs",
        player_id="p1",
        choices=QuarterlyChoices(buy_stock_code="2330", buy_stock_value=20_000),
    )

    first = execute_command(state, command, _config())
    second = execute_command(state, command, _config())

    assert first.events == second.events
    assert state_digest(first.state) == state_digest(second.state)
    assert state_digest(replay_events(state, first.events)) == state_digest(first.state)
    assert first.state.player("p1").cash == 110_000
    assert first.state.player("p1").stock_holdings == (StockHolding(code="2330", value=20_000),)


def test_quarterly_action_list_excludes_disabled_stock_pledge_and_mlm() -> None:
    actions = available_quarterly_actions(_state(), "p1", _config())

    assert "open_loan:credit" in actions
    assert "open_loan:stock_pledge" not in actions
    assert "side_job:online_reseller" in actions
    assert "side_job:mlm" not in actions


def test_stock_trading_rejects_margin_and_short_selling() -> None:
    with pytest.raises(InvalidCommandError, match="insufficient cash"):
        execute_command(
            _state(cash=10_000),
            RunQuarterlyAffairsCommand(
                type="run_quarterly_affairs",
                player_id="p1",
                choices=QuarterlyChoices(buy_stock_code="2330", buy_stock_value=50_000),
            ),
            _config(),
        )

    with pytest.raises(InvalidCommandError, match="cannot sell more stock"):
        execute_command(
            _state(cash=100_000, stock_holdings=(StockHolding(code="2330", value=10_000),)),
            RunQuarterlyAffairsCommand(
                type="run_quarterly_affairs",
                player_id="p1",
                choices=QuarterlyChoices(sell_stock_code="2330", sell_stock_value=20_000),
            ),
            _config(),
        )


def test_quarterly_auto_settlement_and_choices_update_player_finances() -> None:
    state = _state(
        cash=2_000_000,
        monthly_salary=32_000,
        lap=4,
        occupation_key="service",
        loans=(PlayerLoan(product_key="credit", principal=100_000, rate_per_lap=0.02),),
        vehicles=("scooter",),
        insurance_policies=("health",),
        education_course_key="vocational",
        education_remaining_laps=1,
    )

    transition = execute_command(
        state,
        RunQuarterlyAffairsCommand(
            type="run_quarterly_affairs",
            player_id="p1",
            choices=QuarterlyChoices(
                career_change_to="civil_servant",
                open_loan_product_key="credit",
                open_loan_amount=10_000,
                insurance_policy_key="accident",
            ),
        ),
        _config(),
    )

    player = transition.state.player("p1")
    assert player.cash == 2_030_000
    assert player.loans[0].principal == 95_000
    assert player.loans[1].principal == 10_000
    assert player.loans[1].rate_per_lap == 0.02
    assert player.vehicles == ("scooter",)
    assert player.insurance_policies == ("health", "accident")
    assert player.education_course_key is None
    assert player.education_unlocked_tier == 2
    assert player.occupation_key == "civil_servant"
    assert player.monthly_salary == 48_000


def test_config_changes_affect_salary_loan_premium_and_stock_price() -> None:
    config = _config()
    cheaper_config = _config(
        education_salary_multiplier=1.0,
        credit_rate=0.05,
        accident_premium=1_000,
        stock_clamp=0.0,
    )
    state = _state(
        cash=1_000_000,
        monthly_salary=10_000,
        education_course_key="mba",
        education_remaining_laps=2,
    )
    command = RunQuarterlyAffairsCommand(
        type="run_quarterly_affairs",
        player_id="p1",
        choices=QuarterlyChoices(
            open_loan_product_key="credit",
            open_loan_amount=10_000,
            insurance_policy_key="accident",
        ),
    )

    base = execute_command(state, command, config)
    changed = execute_command(state, command, cheaper_config)

    assert base.state.player("p1").cash != changed.state.player("p1").cash
    assert base.state.player("p1").loans[0].rate_per_lap == 0.02
    assert changed.state.player("p1").loans[0].rate_per_lap == 0.05
    assert base.state.stock_prices[0].price != changed.state.stock_prices[0].price


def _state(
    *,
    cash: int = 100_000,
    monthly_salary: int = 0,
    lap: int = 1,
    occupation_key: str | None = None,
    stock_holdings: tuple[StockHolding, ...] = (),
    loans: tuple[PlayerLoan, ...] = (),
    vehicles: tuple[str, ...] = (),
    insurance_policies: tuple[str, ...] = (),
    education_course_key: str | None = None,
    education_remaining_laps: int = 0,
) -> GameState:
    return GameState(
        id="game-q",
        phase="active",
        server_seed="quarterly-seed",
        players=(
            PlayerState(
                id="p1",
                cash=cash,
                lap=lap,
                occupation_key=occupation_key,
                monthly_salary=monthly_salary,
                stock_holdings=stock_holdings,
                loans=loans,
                vehicles=vehicles,
                insurance_policies=insurance_policies,
                education_course_key=education_course_key,
                education_remaining_laps=education_remaining_laps,
            ),
        ),
    )


def _config(
    *,
    education_salary_multiplier: float = 0.5,
    credit_rate: float = 0.02,
    accident_premium: int = 8_000,
    stock_clamp: float = 0.10,
) -> dict[str, object]:
    return {
        "stocks": {
            "trading": {"daily_return_clamp": stock_clamp},
            "equities": [{"code": "2330", "seed_price": 2405}],
        },
        "loans": {
            "products": [
                {"key": "credit", "rate_per_lap": credit_rate},
                {"key": "stock_pledge", "enabled": False, "rate_per_lap": 0.015},
            ],
            "origination_points": {"quarterly_affairs": {"products": ["credit", "stock_pledge"]}},
            "occupation_credit_modifiers": {
                "civil_servant": {"rate_discount": 0.005},
            },
        },
        "vehicles": {
            "vehicles": [
                {"key": "none", "price": 0, "upkeep_per_turn": 0},
                {"key": "scooter", "price": 80_000, "upkeep_per_turn": 1_000},
            ],
        },
        "insurance": {
            "policies": [
                {"key": "health", "premium_per_year": 12_000},
                {"key": "accident", "premium_per_year": accident_premium},
            ],
        },
        "wellbeing": {
            "health": {
                "bands": [
                    {"max": 20, "disease_risk_multiplier": 2.0},
                    {"max": 40, "disease_risk_multiplier": 1.5},
                    {"max": 75, "disease_risk_multiplier": 1.0},
                    {"max": 100, "disease_risk_multiplier": 0.75},
                ],
            },
        },
        "occupations": {
            "occupations": [
                {"key": "service", "tier": 1, "monthly_salary": 32_000},
                {"key": "civil_servant", "tier": 2, "monthly_salary": 48_000},
            ],
            "education": {
                "outcome": {"success_chance": 1.0},
                "courses": [
                    {"key": "vocational", "tuition": 60_000, "turns": 2, "unlocks_tier": 2},
                    {
                        "key": "mba",
                        "tuition": 800_000,
                        "turns": 4,
                        "unlocks_tier": 3,
                        "permanent_salary_multiplier": 1.2,
                    },
                ],
                "salary_multiplier_while_studying": education_salary_multiplier,
            },
            "side_jobs": {
                "jobs": [
                    {"key": "online_reseller", "enabled": True},
                    {"key": "mlm", "enabled": False},
                ],
            },
        },
    }
