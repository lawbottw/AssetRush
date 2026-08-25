"""Lossless JSON contract for persisted :class:`GameState` snapshots.

The normalized tables are read models for RLS and efficient queries.  This codec is
the canonical, lossless representation used by the private ``game_snapshots`` table
and event-stream verification.
"""

from __future__ import annotations

import json
from collections.abc import Mapping
from typing import Any, cast

from assetrush.engine.replay import state_digest
from assetrush.engine.state import (
    AllianceMemberState,
    AllianceProposalState,
    AllianceState,
    BankruptcyRecord,
    BoardReference,
    BoardTile,
    ConfinementState,
    GameState,
    PendingEffect,
    PlayerLoan,
    PlayerModifier,
    PlayerState,
    PropertyBidState,
    PropertyState,
    StandingOrderState,
    StockHolding,
    StockPrice,
    TradeOfferState,
)


def state_to_dict(state: GameState) -> dict[str, object]:
    """Return the same canonical JSON object used by ``state_digest``."""

    payload = json.loads(state_digest(state))
    if not isinstance(payload, dict):  # pragma: no cover - GameState is always an object
        raise TypeError("GameState must encode to a JSON object")
    return cast(dict[str, object], payload)


def state_from_dict(payload: Mapping[str, Any]) -> GameState:
    """Rebuild a typed immutable state from a persisted JSON object."""

    board_payload = payload.get("board")
    return GameState(
        id=_str(payload, "id"),
        mode=cast(Any, _str(payload, "mode")),
        phase=cast(Any, _str(payload, "phase")),
        server_seed=_str(payload, "server_seed"),
        server_seed_hash=_str(payload, "server_seed_hash"),
        turn_seq=_int(payload, "turn_seq"),
        event_seq=_int(payload, "event_seq"),
        rng_seq=_int(payload, "rng_seq"),
        day=_int(payload, "day"),
        lap_limit=_int(payload, "lap_limit"),
        day_limit=_optional_int(payload, "day_limit"),
        rolls_per_day=_optional_int(payload, "rolls_per_day"),
        net_worth_threshold=_int(payload, "net_worth_threshold"),
        base_turn_order=tuple(_string_list(payload, "base_turn_order")),
        board=_board(_mapping_value(board_payload, "board")) if board_payload is not None else None,
        players=tuple(_player(row) for row in _mapping_list(payload, "players")),
        properties=tuple(_property(row) for row in _mapping_list(payload, "properties")),
        property_bids=tuple(_bid(row) for row in _mapping_list(payload, "property_bids")),
        standing_orders=tuple(
            _standing_order(row) for row in _mapping_list(payload, "standing_orders")
        ),
        trade_offers=tuple(_trade_offer(row) for row in _mapping_list(payload, "trade_offers")),
        bankruptcy_records=tuple(
            _bankruptcy(row) for row in _mapping_list(payload, "bankruptcy_records")
        ),
        alliances=tuple(_alliance(row) for row in _mapping_list(payload, "alliances")),
        alliance_proposals=tuple(
            _alliance_proposal(row) for row in _mapping_list(payload, "alliance_proposals")
        ),
        stock_prices=tuple(_stock_price(row) for row in _mapping_list(payload, "stock_prices")),
        treasury=_int(payload, "treasury"),
        pending_effects=tuple(
            _pending_effect(row) for row in _mapping_list(payload, "pending_effects")
        ),
    )


def _board(payload: Mapping[str, Any]) -> BoardReference:
    return BoardReference(
        seed=_int(payload, "seed"),
        total_tiles=_int(payload, "total_tiles"),
        property_tiles=_int(payload, "property_tiles"),
        config_version=_str(payload, "config_version"),
        tiles=tuple(_tile(row) for row in _mapping_list(payload, "tiles")),
    )


def _tile(payload: Mapping[str, Any]) -> BoardTile:
    return BoardTile(
        index=_int(payload, "index"),
        kind=cast(Any, _str(payload, "kind")),
        town_code=_optional_str(payload, "town_code"),
        name=_optional_str(payload, "name"),
        county=_optional_str(payload, "county"),
        region=_optional_str(payload, "region"),
        price_tier=_optional_int(payload, "price_tier"),
        base_price=_optional_int(payload, "base_price"),
    )


def _player(payload: Mapping[str, Any]) -> PlayerState:
    confinement_payload = payload.get("confinement")
    return PlayerState(
        id=_str(payload, "id"),
        cash=_int(payload, "cash"),
        frozen_cash=_int(payload, "frozen_cash"),
        position=_int(payload, "position"),
        lap=_int(payload, "lap"),
        background_key=_optional_str(payload, "background_key"),
        occupation_key=_optional_str(payload, "occupation_key"),
        monthly_salary=_int(payload, "monthly_salary"),
        health=_int(payload, "health"),
        luck=_int(payload, "luck"),
        rolls_used_today=_int(payload, "rolls_used_today"),
        default_count=_int(payload, "default_count"),
        is_blacklisted=_bool(payload, "is_blacklisted"),
        is_bankrupt=_bool(payload, "is_bankrupt"),
        has_quit=_bool(payload, "has_quit"),
        alliance_id=_optional_str(payload, "alliance_id"),
        relationship_changes=_int(payload, "relationship_changes"),
        confinement=(
            _confinement(_mapping_value(confinement_payload, "confinement"))
            if confinement_payload is not None
            else None
        ),
        stock_holdings=tuple(_holding(row) for row in _mapping_list(payload, "stock_holdings")),
        property_tile_indices=tuple(_integer_list(payload, "property_tile_indices")),
        loans=tuple(_loan(row) for row in _mapping_list(payload, "loans")),
        vehicles=tuple(_string_list(payload, "vehicles")),
        insurance_policies=tuple(_string_list(payload, "insurance_policies")),
        education_course_key=_optional_str(payload, "education_course_key"),
        education_remaining_laps=_int(payload, "education_remaining_laps"),
        education_unlocked_tier=_optional_int(payload, "education_unlocked_tier"),
        modifiers=tuple(_modifier(row) for row in _mapping_list(payload, "modifiers")),
    )


def _confinement(payload: Mapping[str, Any]) -> ConfinementState:
    return ConfinementState(
        kind=cast(Any, _str(payload, "kind")),
        remaining_turns=_int(payload, "remaining_turns"),
        reason=_optional_str(payload, "reason"),
    )


def _holding(payload: Mapping[str, Any]) -> StockHolding:
    return StockHolding(code=_str(payload, "code"), value=_int(payload, "value"))


def _loan(payload: Mapping[str, Any]) -> PlayerLoan:
    return PlayerLoan(
        product_key=_str(payload, "product_key"),
        principal=_int(payload, "principal"),
        rate_per_lap=_float(payload, "rate_per_lap"),
    )


def _modifier(payload: Mapping[str, Any]) -> PlayerModifier:
    return PlayerModifier(
        key=_str(payload, "key"),
        value=cast(Any, payload.get("value")),
        laps=_optional_int(payload, "laps"),
    )


def _property(payload: Mapping[str, Any]) -> PropertyState:
    return PropertyState(
        tile_index=_int(payload, "tile_index"),
        owner_id=_str(payload, "owner_id"),
        level=_int(payload, "level"),
        invested=_int(payload, "invested"),
        mortgaged=_bool(payload, "mortgaged"),
    )


def _bid(payload: Mapping[str, Any]) -> PropertyBidState:
    return PropertyBidState(
        tile_index=_int(payload, "tile_index"),
        player_id=_str(payload, "player_id"),
        bid_amount=_int(payload, "bid_amount"),
        day=_int(payload, "day"),
    )


def _standing_order(payload: Mapping[str, Any]) -> StandingOrderState:
    return StandingOrderState(
        player_id=_str(payload, "player_id"),
        bid_policy=cast(Any, _str(payload, "bid_policy")),
        cash_floor=_int(payload, "cash_floor"),
        max_bid_ratio=_float(payload, "max_bid_ratio"),
        enabled=_bool(payload, "enabled"),
    )


def _trade_offer(payload: Mapping[str, Any]) -> TradeOfferState:
    return TradeOfferState(
        offer_id=_str(payload, "offer_id"),
        from_player_id=_str(payload, "from_player_id"),
        to_player_id=_str(payload, "to_player_id"),
        cash_frozen=_int(payload, "cash_frozen"),
        property_tile_indices=tuple(_integer_list(payload, "property_tile_indices")),
    )


def _bankruptcy(payload: Mapping[str, Any]) -> BankruptcyRecord:
    return BankruptcyRecord(
        player_id=_str(payload, "player_id"),
        day=_int(payload, "day"),
        net_worth_before=_int(payload, "net_worth_before"),
        counts_for_end_condition=_bool(payload, "counts_for_end_condition"),
        reason=_str(payload, "reason"),
    )


def _alliance(payload: Mapping[str, Any]) -> AllianceState:
    core_partner_ids = payload.get("core_partner_ids")
    partners: tuple[str, str] | None = None
    if core_partner_ids is not None:
        values = _string_sequence(core_partner_ids, "core_partner_ids")
        if len(values) != 2:
            raise ValueError("core_partner_ids must contain exactly two player ids")
        partners = (values[0], values[1])
    return AllianceState(
        id=_str(payload, "id"),
        tier=cast(Any, _str(payload, "tier")),
        member_ids=tuple(_string_list(payload, "member_ids")),
        pool_balance=_int(payload, "pool_balance"),
        member_states=tuple(
            _alliance_member(row) for row in _mapping_list(payload, "member_states")
        ),
        core_partner_ids=partners,
        active=_bool(payload, "active"),
        name=_optional_str(payload, "name"),
    )


def _alliance_member(payload: Mapping[str, Any]) -> AllianceMemberState:
    return AllianceMemberState(
        player_id=_str(payload, "player_id"),
        contributed=_int(payload, "contributed"),
        relationship_changes=_int(payload, "relationship_changes"),
    )


def _alliance_proposal(payload: Mapping[str, Any]) -> AllianceProposalState:
    return AllianceProposalState(
        id=_str(payload, "id"),
        from_player_id=_str(payload, "from_player_id"),
        to_player_id=_str(payload, "to_player_id"),
        tier=cast(Any, _str(payload, "tier")),
        day=_int(payload, "day"),
        target_alliance_id=_optional_str(payload, "target_alliance_id"),
        formation_style=_optional_str(payload, "formation_style"),
    )


def _stock_price(payload: Mapping[str, Any]) -> StockPrice:
    return StockPrice(code=_str(payload, "code"), price=_float(payload, "price"))


def _pending_effect(payload: Mapping[str, Any]) -> PendingEffect:
    return PendingEffect(
        effect_type=_str(payload, "effect_type"),
        player_id=_str(payload, "player_id"),
        reason=_optional_str(payload, "reason"),
    )


def _mapping_list(payload: Mapping[str, Any], key: str) -> list[Mapping[str, Any]]:
    value = payload.get(key)
    if not isinstance(value, list):
        raise ValueError(f"{key} must be a list")
    return [_mapping_value(item, f"{key}[]") for item in value]


def _mapping_value(value: object, label: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise ValueError(f"{label} must be an object")
    return cast(Mapping[str, Any], value)


def _string_list(payload: Mapping[str, Any], key: str) -> list[str]:
    return _string_sequence(payload.get(key), key)


def _string_sequence(value: object, label: str) -> list[str]:
    if not isinstance(value, list) or any(not isinstance(item, str) for item in value):
        raise ValueError(f"{label} must be a string list")
    return cast(list[str], value)


def _integer_list(payload: Mapping[str, Any], key: str) -> list[int]:
    value = payload.get(key)
    if not isinstance(value, list) or any(not isinstance(item, int) for item in value):
        raise ValueError(f"{key} must be an integer list")
    return cast(list[int], value)


def _str(payload: Mapping[str, Any], key: str) -> str:
    value = payload.get(key)
    if not isinstance(value, str):
        raise ValueError(f"{key} must be a string")
    return value


def _optional_str(payload: Mapping[str, Any], key: str) -> str | None:
    value = payload.get(key)
    if value is None or isinstance(value, str):
        return value
    raise ValueError(f"{key} must be a string or null")


def _int(payload: Mapping[str, Any], key: str) -> int:
    value = payload.get(key)
    if not isinstance(value, int) or isinstance(value, bool):
        raise ValueError(f"{key} must be an integer")
    return value


def _optional_int(payload: Mapping[str, Any], key: str) -> int | None:
    value = payload.get(key)
    if value is None:
        return None
    if not isinstance(value, int) or isinstance(value, bool):
        raise ValueError(f"{key} must be an integer or null")
    return value


def _float(payload: Mapping[str, Any], key: str) -> float:
    value = payload.get(key)
    if not isinstance(value, int | float) or isinstance(value, bool):
        raise ValueError(f"{key} must be numeric")
    return float(value)


def _bool(payload: Mapping[str, Any], key: str) -> bool:
    value = payload.get(key)
    if not isinstance(value, bool):
        raise ValueError(f"{key} must be a boolean")
    return value
