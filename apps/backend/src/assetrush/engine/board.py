"""動態棋盤抽樣。"""

from __future__ import annotations

import math
import random
from collections import Counter
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, replace

from assetrush.engine.errors import BoardSamplingError
from assetrush.engine.state import BoardReference, BoardTile, Money, TileKind, Town

ConfigSnapshot = Mapping[str, object]
TownInput = Mapping[str, object]


def build_board(
    *,
    config: ConfigSnapshot,
    towns: Sequence[TownInput],
    seed: int,
    total_tiles: int,
    property_tiles: int,
) -> BoardReference:
    """依 config/board.json 約束抽樣並物化棋盤。"""

    if total_tiles <= 0 or property_tiles <= 0 or property_tiles >= total_tiles:
        raise BoardSamplingError("total_tiles and property_tiles are inconsistent")

    board_config = _mapping(config.get("board"), "config.board")
    version = _string(board_config.get("version"), "board.version")
    layout = _function_layout(board_config, total_tiles)
    function_count = sum(count for kind, count in layout.items() if kind != "start")
    if function_count + 1 + property_tiles != total_tiles:
        raise BoardSamplingError(
            f"layout for {total_tiles} tiles expects {function_count + 1} function tiles "
            f"and {property_tiles} property tiles"
        )

    parsed_towns = parse_towns(board_config, towns)
    selected = _sample_property_towns(
        parsed_towns,
        board_config,
        seed=seed,
        property_tiles=property_tiles,
    )
    arranged = _arrange_property_towns(selected)
    tiles = _insert_function_tiles(
        arranged,
        layout,
        seed=seed,
        total_tiles=total_tiles,
    )
    return BoardReference(
        seed=seed,
        total_tiles=total_tiles,
        property_tiles=property_tiles,
        config_version=version,
        tiles=tuple(tiles),
    )


def parse_towns(board_config: ConfigSnapshot, towns: Sequence[TownInput]) -> tuple[Town, ...]:
    regions = _regions_by_county(board_config)
    parsed: list[Town] = []
    for index, raw in enumerate(towns):
        path = f"towns[{index}]"
        county = _string(raw.get("county"), f"{path}.county")
        parsed.append(
            Town(
                code=_string(raw.get("code"), f"{path}.code"),
                name=_string(raw.get("name"), f"{path}.name"),
                county=county,
                region=_optional_string(raw.get("region")) or regions.get(county, county),
                avg_price_per_ping=_int(raw.get("avg_price_per_ping"), f"{path}.avg_price"),
                price_tier=_int(raw.get("price_tier"), f"{path}.price_tier"),
                population=_int(raw.get("population"), f"{path}.population"),
                is_active=_bool(raw.get("is_active", True), f"{path}.is_active"),
            )
        )
    active = tuple(town for town in parsed if town.is_active)
    if not active:
        raise BoardSamplingError("no active towns available")
    return active


def _sample_property_towns(
    towns: Sequence[Town],
    board_config: ConfigSnapshot,
    *,
    seed: int,
    property_tiles: int,
) -> list[Town]:
    last_error: BoardSamplingError | None = None
    for attempt in range(32):
        try:
            return _sample_property_towns_once(
                towns,
                board_config,
                seed=seed + attempt,
                property_tiles=property_tiles,
            )
        except BoardSamplingError as exc:
            last_error = exc
    if last_error is None:
        raise BoardSamplingError("property town sampling did not run")
    raise BoardSamplingError(
        f"cannot satisfy board sampling constraints after 32 attempts: {last_error}"
    )


def _sample_property_towns_once(
    towns: Sequence[Town],
    board_config: ConfigSnapshot,
    *,
    seed: int,
    property_tiles: int,
) -> list[Town]:
    constraints = _constraints(property_tiles)
    tier_weight = _tier_weight(board_config)
    rng = random.Random(seed)
    selected: list[Town] = []

    for region in sorted({town.region for town in towns}):
        for _ in range(constraints.min_per_region):
            selected.append(
                _pick_one(
                    towns,
                    selected,
                    tier_weight,
                    rng,
                    constraints.max_per_county,
                    reason=f"region {region}",
                    predicate=_region_candidate(region),
                    max_tier5=constraints.tier5_max,
                )
            )

    while _count_tier(selected, 5) < constraints.tier5_min:
        selected.append(
            _pick_one(
                towns,
                selected,
                tier_weight,
                rng,
                constraints.max_per_county,
                reason="tier5",
                predicate=lambda town: town.price_tier == 5,
                max_tier5=constraints.tier5_max,
            )
        )

    while _count_low_tier(selected) < constraints.low_tier_min:
        selected.append(
            _pick_one(
                towns,
                selected,
                tier_weight,
                rng,
                constraints.max_per_county,
                reason="tier1+tier2",
                predicate=lambda town: town.price_tier in {1, 2},
                max_tier5=constraints.tier5_max,
            )
        )

    while _county_group_count(selected) < constraints.counties_with_2_to_3:
        selected.append(
            _pick_one(
                towns,
                selected,
                tier_weight,
                rng,
                constraints.max_per_county,
                reason="county monopoly groups",
                predicate=_county_group_candidate(selected),
                max_tier5=constraints.tier5_max,
            )
        )

    while len(selected) < property_tiles:
        selected.append(
            _pick_one(
                towns,
                selected,
                tier_weight,
                rng,
                constraints.max_per_county,
                reason="fill",
                predicate=_fill_candidate(selected, constraints),
                max_tier5=constraints.tier5_max,
            )
        )

    _validate_constraints(selected, constraints, property_tiles)
    return selected


def _arrange_property_towns(towns: Sequence[Town]) -> list[Town]:
    return sorted(towns, key=lambda town: (town.avg_price_per_ping, town.code))


def _insert_function_tiles(
    property_towns: Sequence[Town],
    layout: Mapping[TileKind, int],
    *,
    seed: int,
    total_tiles: int,
) -> list[BoardTile]:
    rng = random.Random(seed ^ 0xB04D)
    function_kinds: list[TileKind] = []
    for kind, count in sorted(layout.items()):
        if kind == "start":
            continue
        function_kinds.extend([kind] * count)

    function_positions = _choose_function_positions(rng, total_tiles, len(function_kinds))
    rng.shuffle(function_kinds)
    functions_by_position = dict(zip(function_positions, function_kinds, strict=True))

    property_iter = iter(property_towns)
    tiles: list[BoardTile] = []
    for index in range(total_tiles):
        if index == 0:
            tiles.append(BoardTile(index=0, kind="start"))
        elif index in functions_by_position:
            tiles.append(BoardTile(index=index, kind=functions_by_position[index]))
        else:
            town = next(property_iter)
            tiles.append(_property_tile(index, town))

    return tiles


def _choose_function_positions(
    rng: random.Random,
    total_tiles: int,
    function_count: int,
) -> list[int]:
    selected: list[int] = []
    candidates = list(range(2, total_tiles))
    for _ in range(function_count):
        valid = [
            position
            for position in candidates
            if position not in selected
            and position - 1 not in selected
            and position + 1 not in selected
            and not (position == total_tiles - 1 and 0 in selected)
        ]
        if not valid:
            raise BoardSamplingError("cannot place function tiles without adjacency")
        position = rng.choice(valid)
        selected.append(position)
    return sorted(selected)


def _property_tile(index: int, town: Town) -> BoardTile:
    return BoardTile(
        index=index,
        kind="property",
        town_code=town.code,
        name=town.name,
        county=town.county,
        region=town.region,
        price_tier=town.price_tier,
        base_price=_base_price(town),
    )


def _pick_one(
    towns: Sequence[Town],
    selected: Sequence[Town],
    tier_weight: Mapping[int, float],
    rng: random.Random,
    max_per_county: int,
    *,
    reason: str,
    predicate: Callable[[Town], bool],
    max_tier5: int,
) -> Town:
    selected_codes = {town.code for town in selected}
    county_counts = Counter(town.county for town in selected)
    tier5_count = _count_tier(selected, 5)
    candidates = [
        town
        for town in towns
        if town.code not in selected_codes
        and county_counts[town.county] < max_per_county
        and (town.price_tier != 5 or tier5_count < max_tier5)
        and predicate(town)
    ]
    if not candidates:
        raise BoardSamplingError(f"cannot satisfy board sampling constraint: {reason}")
    return _weighted_choice(candidates, tier_weight, rng)


def _weighted_choice(
    candidates: Sequence[Town],
    tier_weight: Mapping[int, float],
    rng: random.Random,
) -> Town:
    weights = [
        max(1.0, math.log(max(town.population, 2))) * tier_weight.get(town.price_tier, 1.0)
        for town in candidates
    ]
    total = sum(weights)
    marker = rng.random() * total
    running = 0.0
    for town, weight in zip(candidates, weights, strict=True):
        running += weight
        if running >= marker:
            return town
    return candidates[-1]


def _county_group_candidate(selected: Sequence[Town]) -> Callable[[Town], bool]:
    counts = Counter(town.county for town in selected)
    one_tile_counties = {county for county, count in counts.items() if count == 1}
    if one_tile_counties:
        return lambda town: town.county in one_tile_counties
    return lambda _town: True


def _region_candidate(region: str) -> Callable[[Town], bool]:
    return lambda town: town.region == region


def _fill_candidate(
    selected: Sequence[Town],
    constraints: _Constraints,
) -> Callable[[Town], bool]:
    counts = Counter(town.county for town in selected)
    if _county_group_count(selected) <= constraints.counties_with_2_to_3:
        return lambda town: counts[town.county] != 3
    return lambda _town: True


def _validate_constraints(
    selected: Sequence[Town],
    constraints: _Constraints,
    property_tiles: int,
) -> None:
    if len(selected) != property_tiles:
        raise BoardSamplingError(f"expected {property_tiles} property towns, got {len(selected)}")
    if len({town.code for town in selected}) != len(selected):
        raise BoardSamplingError("duplicate town selected")
    region_counts = Counter(town.region for town in selected)
    if any(count < constraints.min_per_region for count in region_counts.values()):
        raise BoardSamplingError("region minimum constraint failed")
    tier5 = _count_tier(selected, 5)
    if not constraints.tier5_min <= tier5 <= constraints.tier5_max:
        raise BoardSamplingError("tier5 constraint failed")
    if _count_low_tier(selected) < constraints.low_tier_min:
        raise BoardSamplingError("tier1+tier2 minimum constraint failed")
    if max(Counter(town.county for town in selected).values()) > constraints.max_per_county:
        raise BoardSamplingError("county maximum constraint failed")
    if _county_group_count(selected) < constraints.counties_with_2_to_3:
        raise BoardSamplingError("county monopoly group constraint failed")


def _function_layout(board_config: ConfigSnapshot, total_tiles: int) -> dict[TileKind, int]:
    function_tiles = _mapping(board_config.get("function_tiles"), "board.function_tiles")
    layouts = _mapping(function_tiles.get("layouts"), "board.function_tiles.layouts")
    layout_key = _nearest_layout_key(layouts, total_tiles)
    raw_layout = _list(layouts.get(layout_key), f"board layouts {layout_key}")
    result: dict[TileKind, int] = {}
    for index, item in enumerate(raw_layout):
        row = _mapping(item, f"layout[{index}]")
        kind = _tile_kind(row.get("kind"), f"layout[{index}].kind")
        result[kind] = result.get(kind, 0) + _int(row.get("count"), f"layout[{index}].count")
    if result.get("start") != 1:
        raise BoardSamplingError(f"layout for {total_tiles} must contain exactly one start")
    return result


def _nearest_layout_key(layouts: Mapping[str, object], total_tiles: int) -> str:
    available: list[int] = []
    for key in layouts:
        try:
            available.append(int(key))
        except ValueError as exc:
            raise BoardSamplingError(f"board layout key must be an integer: {key}") from exc
    if not available:
        raise BoardSamplingError("board.function_tiles.layouts must not be empty")
    nearest = min(available, key=lambda value: (abs(value - total_tiles), value))
    return str(nearest)


def _regions_by_county(board_config: ConfigSnapshot) -> dict[str, str]:
    regions = _list(board_config.get("regions"), "board.regions")
    result: dict[str, str] = {}
    for index, raw in enumerate(regions):
        region = _mapping(raw, f"regions[{index}]")
        key = _string(region.get("key"), f"regions[{index}].key")
        for county in _list(region.get("counties"), f"regions[{index}].counties"):
            result[_string(county, "county")] = key
    return result


def _tier_weight(board_config: ConfigSnapshot) -> dict[int, float]:
    sampling = _mapping(board_config.get("sampling"), "board.sampling")
    raw = _mapping(sampling.get("tier_weight"), "board.sampling.tier_weight")
    return {int(key): _float(value, f"tier_weight[{key}]") for key, value in raw.items()}


def _constraints(property_tiles: int) -> _Constraints:
    return _Constraints(
        min_per_region=2 if property_tiles >= 18 else 1,
        tier5_min=2 if property_tiles >= 18 else 1,
        tier5_max=3 if property_tiles >= 18 else 1,
        low_tier_min=max(3, round(property_tiles * 0.35)),
        max_per_county=max(3, round(property_tiles * 0.22)),
        counties_with_2_to_3=max(2, math.floor(property_tiles / 5)),
    )


@dataclass(frozen=True, slots=True)
class _Constraints:
    min_per_region: int
    tier5_min: int
    tier5_max: int
    low_tier_min: int
    max_per_county: int
    counties_with_2_to_3: int


def _count_tier(towns: Sequence[Town], tier: int) -> int:
    return sum(1 for town in towns if town.price_tier == tier)


def _count_low_tier(towns: Sequence[Town]) -> int:
    return sum(1 for town in towns if town.price_tier in {1, 2})


def _county_group_count(towns: Sequence[Town]) -> int:
    return sum(1 for count in Counter(town.county for town in towns).values() if 2 <= count <= 3)


def _base_price(town: Town) -> Money:
    return round(town.avg_price_per_ping * 0.4)


def replace_tile_owner_marker(tile: BoardTile, index: int) -> BoardTile:
    """保留給後續地產所有權事件；#20 目前只需要穩定 tile dataclass。"""

    return replace(tile, index=index)


def _mapping(value: object, path: str) -> Mapping[str, object]:
    if not isinstance(value, Mapping):
        raise BoardSamplingError(f"{path} must be an object")
    return value


def _list(value: object, path: str) -> list[object]:
    if not isinstance(value, list):
        raise BoardSamplingError(f"{path} must be a list")
    return value


def _string(value: object, path: str) -> str:
    if not isinstance(value, str) or not value:
        raise BoardSamplingError(f"{path} must be a non-empty string")
    return value


def _optional_string(value: object) -> str | None:
    return value if isinstance(value, str) and value else None


def _int(value: object, path: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise BoardSamplingError(f"{path} must be an integer")
    return value


def _float(value: object, path: str) -> float:
    if isinstance(value, bool) or not isinstance(value, int | float):
        raise BoardSamplingError(f"{path} must be a number")
    return float(value)


def _bool(value: object, path: str) -> bool:
    if not isinstance(value, bool):
        raise BoardSamplingError(f"{path} must be a boolean")
    return value


def _tile_kind(value: object, path: str) -> TileKind:
    allowed: set[TileKind] = {
        "start",
        "property",
        "opportunity",
        "fate",
        "leisure",
        "tax",
        "jail",
        "hospital",
    }
    if value not in allowed:
        raise BoardSamplingError(f"{path} has unsupported tile kind {value!r}")
    return value
