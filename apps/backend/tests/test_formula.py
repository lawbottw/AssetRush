from __future__ import annotations

import json
from pathlib import Path

import pytest

from assetrush.engine import FormulaError
from assetrush.engine.formula import evaluate_formula, resolve_amount

CONFIG_DIR = Path(__file__).resolve().parents[3] / "config"

FORMULA_VARIABLES = {
    "K": 0.4,
    "M": 38000,
    "NW": 500000,
    "Q": 114000,
    "accrued_interest": 5000,
    "avg_NW": 450000,
    "avg_lap_income_last_4_laps": 120000,
    "avg_price_per_ping": 300000,
    "avg_quarterly_salary": 120000,
    "avg_starting_net_worth": 450000,
    "available_loan_capacity": 300000,
    "balance": 100000,
    "base_amount": 250000,
    "base_price": 120000,
    "base_turns": 3,
    "cash": 100000,
    "civil_servant_handling_fee_rate": 0.3,
    "debt": 50000,
    "floor": 1,
    "gamma": 1.0,
    "holdings_market_value": (100000, 50000),
    "income_multiplier": 2.5,
    "invested": 20000,
    "lap_limit": 21,
    "lender_available_cash_after_reserve": 300000,
    "max_starting_multiplier": 1.6,
    "max_starting_net_worth": 1000000,
    "monthly_salary": 38000,
    "net_worth": 500000,
    "overdue_amount": 15000,
    "population": 100000,
    "price_tier": 3,
    "property_market_value": (120000, 200000),
    "property_tiles": 20,
    "remaining_turns": 2,
    "rolled_profit_rate": 0.2,
    "salary_multiple_for_tier": 22,
    "shortfall_amount": 80000,
    "stock_market_value": (50000, 75000),
    "tier_weight_for_price_tier": 1.5,
    "tender_amount": 1000000,
    "unmortgaged_property_market_value": (100000, 250000),
    "used_vehicle_extra_step": 1,
    "vehicle_residual": 80000,
}


def test_evaluate_formula_supports_runtime_config_expressions() -> None:
    assert evaluate_formula("NW * 0.03", FORMULA_VARIABLES) == 15000
    assert evaluate_formula("clamp(NW * 0.20, 100000, 1000000)", FORMULA_VARIABLES) == 100000
    assert evaluate_formula("2 if property_tiles >= 18 else 1", FORMULA_VARIABLES) == 2
    assert evaluate_formula("sum(property_market_value) - debt", FORMULA_VARIABLES) == 270000


def test_current_runtime_formulas_are_parseable() -> None:
    formulas = _collect_runtime_formulas(CONFIG_DIR)

    assert formulas
    for formula in formulas:
        evaluate_formula(formula, FORMULA_VARIABLES)


@pytest.mark.parametrize(
    "formula",
    [
        "__import__('os')",
        "().__class__",
        "salary_multiple[occupation_tier]",
        "lambda x: x",
        "[x for x in values]",
    ],
)
def test_evaluate_formula_rejects_unsafe_constructs(formula: str) -> None:
    with pytest.raises(FormulaError):
        evaluate_formula(formula, FORMULA_VARIABLES)


def test_resolve_amount_prefers_fixed_amount() -> None:
    assert resolve_amount({"amount": 123, "formula": "NW * 0.03"}, FORMULA_VARIABLES) == 123


def test_resolve_amount_evaluates_formula_to_money() -> None:
    assert resolve_amount({"formula": "NW * 0.03"}, FORMULA_VARIABLES) == 15000


def test_resolve_amount_rejects_missing_amount() -> None:
    with pytest.raises(FormulaError):
        resolve_amount({"type": "gain"}, FORMULA_VARIABLES)


def test_resolve_amount_rejects_non_numeric_amount() -> None:
    with pytest.raises(FormulaError):
        resolve_amount({"amount": "100"}, FORMULA_VARIABLES)


def _collect_runtime_formulas(config_dir: Path) -> list[str]:
    formulas: list[str] = []
    for path in config_dir.glob("*.json"):
        data = json.loads(path.read_text(encoding="utf-8"))
        formulas.extend(_walk_formulas(data))
    return formulas


def _walk_formulas(value: object) -> list[str]:
    if isinstance(value, dict):
        formulas: list[str] = []
        for key, item in value.items():
            if isinstance(item, str) and (
                key.endswith("formula") or key.endswith("_formula") or key.startswith("C")
            ):
                formulas.append(item)
            else:
                formulas.extend(_walk_formulas(item))
        return formulas
    if isinstance(value, list):
        formulas: list[str] = []
        for item in value:
            formulas.extend(_walk_formulas(item))
        return formulas
    return []
