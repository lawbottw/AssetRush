"""Config schema 與跨檔不變式驗證。"""

from __future__ import annotations

from collections.abc import Mapping

from pydantic import BaseModel, ConfigDict, Field, ValidationError, model_validator

from assetrush.engine.effects import EFFECT_HANDLERS
from assetrush.engine.errors import FormulaError
from assetrush.engine.formula import FormulaContext, evaluate_formula

REQUIRED_CONFIG_FILES = frozenset(
    {
        "alliances",
        "board",
        "confinement",
        "endgame",
        "events",
        "identities",
        "insurance",
        "loans",
        "occupations",
        "properties",
        "scale",
        "stocks",
        "vehicles",
        "wellbeing",
    }
)

FORMULA_VARIABLES: FormulaContext = {
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
    "property_market_value": (120000, 200000),
    "property_tiles": 20,
    "remaining_turns": 2,
    "rolled_profit_rate": 0.2,
    "salary_multiple_for_tier": 22,
    "shortfall_amount": 80000,
    "stock_market_value": (50000, 75000),
    "tender_amount": 1000000,
    "tier_weight_for_price_tier": 1.5,
    "unmortgaged_property_market_value": (100000, 250000),
    "used_vehicle_extra_step": 1,
    "vehicle_residual": 80000,
}


class ConfigValidationError(ValueError):
    """Config schema 或跨檔不變式驗證失敗。"""


class ConfigModel(BaseModel):
    model_config = ConfigDict(extra="allow", populate_by_name=True)


class RawConfig(ConfigModel):
    version: str


class EffectSpec(ConfigModel):
    type: str
    amount: int | None = None
    formula: str | None = None
    amount_formula: str | None = None
    key: str | None = None
    value: str | int | float | bool | None = None
    laps: int | None = None
    requires_side_job: str | None = None
    requires_any_policy: bool = False


class EventCard(ConfigModel):
    id: str
    name: str
    weight: int
    effect: EffectSpec
    category: str | None = None


class EventsConfig(RawConfig):
    opportunity: list[EventCard]
    fate: list[EventCard]
    fate_category_weights: dict[str, int | str] = Field(
        default_factory=dict,
        alias="_fate_category_weights",
    )


class BoardRegion(ConfigModel):
    key: str
    name: str
    counties: list[str]


class FunctionTileLayout(ConfigModel):
    kind: str
    count: int
    fixed_index: int | None = None


class FunctionTiles(ConfigModel):
    kinds: list[str]
    layouts: dict[str, list[FunctionTileLayout]]


class BoardConfig(RawConfig):
    regions: list[BoardRegion]
    function_tiles: FunctionTiles


class PropertyLevel(ConfigModel):
    level: int
    name: str
    upgrade_cost_ratio: float | None = None
    rent_ratio: float


class PropertiesConfig(RawConfig):
    levels: list[PropertyLevel]


class LoanProduct(ConfigModel):
    key: str
    name: str
    enabled: bool = True


class LoansConfig(RawConfig):
    products: list[LoanProduct]


class MainSkill(ConfigModel):
    effect: EffectSpec


class Occupation(ConfigModel):
    key: str
    name: str
    main_skill: MainSkill | None = None


class SideJobOption(ConfigModel):
    key: str
    name: str
    enabled: bool = True


class SideJobs(ConfigModel):
    options: list[SideJobOption]


class OccupationsConfig(RawConfig):
    occupations: list[Occupation]
    side_jobs: SideJobs


class InsurancePolicy(ConfigModel):
    key: str
    name: str


class InsuranceConfig(RawConfig):
    policies: list[InsurancePolicy]


class GameConfig(ConfigModel):
    alliances: RawConfig
    board: BoardConfig
    confinement: RawConfig
    endgame: RawConfig
    events: EventsConfig
    identities: RawConfig
    insurance: InsuranceConfig
    loans: LoansConfig
    occupations: OccupationsConfig
    properties: PropertiesConfig
    scale: RawConfig
    stocks: RawConfig
    vehicles: RawConfig
    wellbeing: RawConfig
    version: str

    @model_validator(mode="after")
    def validate_invariants(self) -> GameConfig:
        _validate_versions(self)
        _validate_events(self)
        _validate_board(self.board)
        _validate_properties(self.properties)
        _validate_unique(
            "loans.products.key",
            [product.key for product in self.loans.products],
        )
        _validate_unique(
            "occupations.occupations.key",
            [occupation.key for occupation in self.occupations.occupations],
        )
        _validate_unique(
            "occupations.side_jobs.options.key",
            [option.key for option in self.occupations.side_jobs.options],
        )
        _validate_unique(
            "insurance.policies.key",
            [policy.key for policy in self.insurance.policies],
        )
        _validate_cross_references(self)
        _validate_formulas(self)
        return self


def validate_config_bundle(raw: Mapping[str, object]) -> GameConfig:
    missing = sorted(REQUIRED_CONFIG_FILES - set(raw))
    if missing:
        raise ConfigValidationError(f"missing config files: {', '.join(missing)}")
    try:
        return GameConfig.model_validate({**raw, "version": _first_version(raw)})
    except ValidationError as exc:
        raise ConfigValidationError(str(exc)) from exc


def _first_version(raw: Mapping[str, object]) -> str:
    for config_name in sorted(REQUIRED_CONFIG_FILES):
        value = raw.get(config_name)
        if isinstance(value, dict):
            version = value.get("version")
            if isinstance(version, str):
                return version
    raise ConfigValidationError("no config version found")


def _validate_versions(config: GameConfig) -> None:
    versions = {
        name: getattr(config, name).version
        for name in REQUIRED_CONFIG_FILES
        if isinstance(getattr(config, name), RawConfig)
    }
    unique_versions = set(versions.values())
    if len(unique_versions) != 1:
        details = ", ".join(f"{name}={version}" for name, version in sorted(versions.items()))
        raise ConfigValidationError(f"config versions must match: {details}")
    if config.version not in unique_versions:
        raise ConfigValidationError("GameConfig.version must match config roots")


def _validate_events(config: GameConfig) -> None:
    _validate_unique("events.opportunity.id", [card.id for card in config.events.opportunity])
    _validate_unique("events.fate.id", [card.id for card in config.events.fate])
    _validate_weight_total("events.opportunity", config.events.opportunity)
    _validate_weight_total("events.fate", config.events.fate)
    _validate_fate_category_weights(config.events)

    for card in (*config.events.opportunity, *config.events.fate):
        if card.effect.type not in EFFECT_HANDLERS:
            raise ConfigValidationError(f"{card.id}: unknown effect type {card.effect.type!r}")


def _validate_weight_total(path: str, cards: list[EventCard]) -> None:
    total = sum(card.weight for card in cards)
    if total != 100:
        raise ConfigValidationError(f"{path} weight total must be 100, got {total}")


def _validate_fate_category_weights(events: EventsConfig) -> None:
    actual: dict[str, int] = {}
    for card in events.fate:
        if card.category is None:
            raise ConfigValidationError(f"{card.id}: fate card category is required")
        actual[card.category] = actual.get(card.category, 0) + card.weight

    expected = {
        key: value
        for key, value in events.fate_category_weights.items()
        if not key.startswith("_") and isinstance(value, int)
    }
    if expected != actual:
        raise ConfigValidationError(
            f"events._fate_category_weights mismatch: expected {expected}, actual {actual}"
        )


def _validate_board(board: BoardConfig) -> None:
    _validate_unique("board.regions.key", [region.key for region in board.regions])
    for region in board.regions:
        if not region.counties:
            raise ConfigValidationError(f"board.regions[{region.key}].counties must not be empty")

    allowed_kinds = set(board.function_tiles.kinds)
    if "start" not in allowed_kinds:
        raise ConfigValidationError("board.function_tiles.kinds must contain start")

    for layout_key, layout in board.function_tiles.layouts.items():
        starts = [tile for tile in layout if tile.kind == "start"]
        if len(starts) != 1:
            raise ConfigValidationError(f"board layout {layout_key} must contain exactly one start")
        if starts[0].fixed_index != 0:
            raise ConfigValidationError(f"board layout {layout_key} start fixed_index must be 0")
        for tile in layout:
            if tile.kind not in allowed_kinds:
                raise ConfigValidationError(
                    f"board layout {layout_key} has unknown function kind {tile.kind!r}"
                )
            if tile.count <= 0:
                raise ConfigValidationError(
                    f"board layout {layout_key}.{tile.kind} count must be > 0"
                )


def _validate_properties(properties: PropertiesConfig) -> None:
    levels = sorted(properties.levels, key=lambda level: level.level)
    _validate_unique("properties.levels.level", [level.level for level in levels])
    expected = list(range(len(levels)))
    actual = [level.level for level in levels]
    if actual != expected:
        raise ConfigValidationError(f"properties.levels must be contiguous from 0, got {actual}")
    for level in levels:
        if level.rent_ratio < 0:
            raise ConfigValidationError(f"properties.levels[{level.level}].rent_ratio must be >= 0")
        if level.level == 0:
            continue
        if level.upgrade_cost_ratio is None or level.upgrade_cost_ratio < 0:
            raise ConfigValidationError(
                f"properties.levels[{level.level}].upgrade_cost_ratio must be >= 0"
            )


def _validate_cross_references(config: GameConfig) -> None:
    side_jobs = {option.key: option for option in config.occupations.side_jobs.options}
    policies = {policy.key for policy in config.insurance.policies}

    for card in (*config.events.opportunity, *config.events.fate):
        required_side_job = card.effect.requires_side_job
        if required_side_job is not None:
            side_job = side_jobs.get(required_side_job)
            if side_job is None:
                raise ConfigValidationError(
                    f"{card.id}: requires_side_job references missing {required_side_job!r}"
                )
            if not side_job.enabled:
                raise ConfigValidationError(
                    f"{card.id}: requires_side_job references disabled {required_side_job!r}"
                )
        if card.effect.requires_any_policy and not policies:
            raise ConfigValidationError(f"{card.id}: requires_any_policy but no policies exist")


def _validate_formulas(config: GameConfig) -> None:
    for path, formula in _walk_formulas(config.model_dump(by_alias=True)):
        try:
            evaluate_formula(formula, FORMULA_VARIABLES)
        except FormulaError as exc:
            raise ConfigValidationError(f"{path}: invalid formula {formula!r}: {exc}") from exc


def _walk_formulas(value: object, path: str = "$") -> list[tuple[str, str]]:
    if isinstance(value, dict):
        dict_formulas: list[tuple[str, str]] = []
        for key, item in value.items():
            child_path = f"{path}.{key}"
            if isinstance(item, str) and (
                key.endswith("formula") or key.endswith("_formula") or key.startswith("C")
            ):
                dict_formulas.append((child_path, item))
            else:
                dict_formulas.extend(_walk_formulas(item, child_path))
        return dict_formulas
    if isinstance(value, list):
        list_formulas: list[tuple[str, str]] = []
        for index, item in enumerate(value):
            list_formulas.extend(_walk_formulas(item, f"{path}[{index}]"))
        return list_formulas
    return []


def _validate_unique(path: str, values: list[object]) -> None:
    seen: set[object] = set()
    duplicates: set[object] = set()
    for value in values:
        if value in seen:
            duplicates.add(value)
        seen.add(value)
    if duplicates:
        formatted = sorted(repr(value) for value in duplicates)
        raise ConfigValidationError(f"{path} has duplicates: {formatted!r}")
