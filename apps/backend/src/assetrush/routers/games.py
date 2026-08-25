"""Minimal persisted-game HTTP API for M4."""

from __future__ import annotations

import hashlib
from typing import Annotated, Literal
from uuid import UUID, uuid4

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, ConfigDict, Field

from assetrush.db import get_sessionmaker
from assetrush.engine import (
    AdvancePhaseCommand,
    Command,
    Event,
    GameState,
    PlacePropertyBidCommand,
    PurchasePropertyCommand,
    QuarterlyChoices,
    ResolveCashShortfallCommand,
    RunDailySettlementCommand,
    RunQuarterlyAffairsCommand,
    TakeTurnCommand,
)
from assetrush.engine.errors import EngineError
from assetrush.engine.event_codec import event_from_dict
from assetrush.engine.replay import state_digest
from assetrush.persistence import state_to_dict
from assetrush.services import (
    GameAlreadyExistsError,
    GameNotFoundError,
    GameStore,
    PersistenceContractError,
    StaleTurnError,
    StoredGame,
)

router = APIRouter(prefix="/games", tags=["games"])


class ApiModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class CreateGameRequest(ApiModel):
    game_id: UUID | None = None
    mode: Literal["daily", "blitz"]
    player_ids: tuple[UUID, ...] = Field(min_length=2, max_length=30)
    host_user_id: UUID
    target_minutes: int | None = Field(default=None, gt=0)
    seed: str | None = Field(default=None, min_length=1, max_length=256)


class TakeTurnRequest(ApiModel):
    type: Literal["take_turn"]
    player_id: UUID
    extra_move_steps: int = Field(default=0, ge=0)


class PurchasePropertyRequest(ApiModel):
    type: Literal["purchase_property"]
    player_id: UUID
    tile_index: int = Field(ge=0)


class PlacePropertyBidRequest(ApiModel):
    type: Literal["place_property_bid"]
    player_id: UUID
    tile_index: int = Field(ge=0)
    bid_amount: int = Field(ge=0)


class RunDailySettlementRequest(ApiModel):
    type: Literal["run_daily_settlement"]
    execute_standing_orders: bool = True


class QuarterlyChoicesRequest(ApiModel):
    buy_stock_code: str | None = None
    buy_stock_value: int = Field(default=0, ge=0)
    sell_stock_code: str | None = None
    sell_stock_value: int = Field(default=0, ge=0)
    open_loan_product_key: str | None = None
    open_loan_amount: int = Field(default=0, ge=0)
    education_course_key: str | None = None
    career_change_to: str | None = None
    vehicle_key: str | None = None
    insurance_policy_key: str | None = None


class RunQuarterlyAffairsRequest(ApiModel):
    type: Literal["run_quarterly_affairs"]
    player_id: UUID
    choices: QuarterlyChoicesRequest = Field(default_factory=QuarterlyChoicesRequest)


class ResolveCashShortfallRequest(ApiModel):
    type: Literal["resolve_cash_shortfall"]
    player_id: UUID


class AdvancePhaseRequest(ApiModel):
    type: Literal["advance_phase"]
    phase: Literal["settling", "finished"]
    reason: str | None = None


CommandRequest = (
    TakeTurnRequest
    | PurchasePropertyRequest
    | PlacePropertyBidRequest
    | RunDailySettlementRequest
    | RunQuarterlyAffairsRequest
    | ResolveCashShortfallRequest
    | AdvancePhaseRequest
)


class ExecuteCommandRequest(ApiModel):
    expected_turn_seq: int = Field(ge=0)
    command: Annotated[CommandRequest, Field(discriminator="type")]


class GameResponse(ApiModel):
    game_id: UUID
    version: int
    state: dict[str, object]
    state_digest: str


class CommandResponse(GameResponse):
    events: list[Event]


class EventPage(ApiModel):
    events: list[Event]
    next_cursor: int


def get_game_store() -> GameStore:
    return GameStore(get_sessionmaker())


@router.post("", response_model=GameResponse, status_code=status.HTTP_201_CREATED)
async def create_game(
    request: CreateGameRequest,
    store: Annotated[GameStore, Depends(get_game_store)],
) -> GameResponse:
    try:
        stored = await store.create_from_spec(
            game_id=request.game_id or uuid4(),
            mode=request.mode,
            player_ids=request.player_ids,
            host_user_id=request.host_user_id,
            target_minutes=request.target_minutes,
            seed=request.seed,
        )
    except GameAlreadyExistsError as exc:
        raise _http_error(409, "game_exists", str(exc)) from exc
    except PersistenceContractError as exc:
        raise _http_error(409, "persistence_contract", str(exc)) from exc
    except EngineError as exc:
        raise _http_error(409, "domain_error", str(exc)) from exc
    return _game_response(stored)


@router.get("/{game_id}", response_model=GameResponse)
async def get_game(
    game_id: UUID,
    store: Annotated[GameStore, Depends(get_game_store)],
) -> GameResponse:
    try:
        stored = await store.get_game(game_id)
    except GameNotFoundError as exc:
        raise _http_error(404, "game_not_found", str(exc)) from exc
    return _game_response(stored)


@router.post("/{game_id}/commands", response_model=CommandResponse)
async def execute_game_command(
    game_id: UUID,
    request: ExecuteCommandRequest,
    store: Annotated[GameStore, Depends(get_game_store)],
) -> CommandResponse:
    try:
        persisted = await store.execute(
            game_id,
            expected_turn_seq=request.expected_turn_seq,
            command=_engine_command(request.command),
        )
    except GameNotFoundError as exc:
        raise _http_error(404, "game_not_found", str(exc)) from exc
    except StaleTurnError as exc:
        raise HTTPException(
            status_code=409,
            detail={
                "code": "stale_turn",
                "message": str(exc),
                "expected": exc.expected,
                "actual": exc.actual,
            },
        ) from exc
    except EngineError as exc:
        raise _http_error(409, "domain_error", str(exc)) from exc
    except PersistenceContractError as exc:
        raise _http_error(409, "persistence_contract", str(exc)) from exc
    stored = StoredGame(state=persisted.state, version=persisted.version, config={})
    response = _game_response(stored)
    return CommandResponse(**response.model_dump(), events=list(persisted.events))


@router.get("/{game_id}/events", response_model=EventPage)
async def get_game_events(
    game_id: UUID,
    store: Annotated[GameStore, Depends(get_game_store)],
    after_id: Annotated[int, Query(ge=0)] = 0,
    limit: Annotated[int, Query(ge=1, le=500)] = 200,
) -> EventPage:
    try:
        rows = await store.get_events(game_id, after_id=after_id, limit=limit)
    except GameNotFoundError as exc:
        raise _http_error(404, "game_not_found", str(exc)) from exc
    events = [event_from_dict(row.payload) for row in rows]
    return EventPage(events=events, next_cursor=rows[-1].id if rows else after_id)


def _engine_command(command: CommandRequest) -> Command:
    if isinstance(command, TakeTurnRequest):
        return TakeTurnCommand(
            type="take_turn",
            player_id=str(command.player_id),
            extra_move_steps=command.extra_move_steps,
        )
    if isinstance(command, PurchasePropertyRequest):
        return PurchasePropertyCommand(
            type="purchase_property",
            player_id=str(command.player_id),
            tile_index=command.tile_index,
        )
    if isinstance(command, PlacePropertyBidRequest):
        return PlacePropertyBidCommand(
            type="place_property_bid",
            player_id=str(command.player_id),
            tile_index=command.tile_index,
            bid_amount=command.bid_amount,
        )
    if isinstance(command, RunDailySettlementRequest):
        return RunDailySettlementCommand(
            type="run_daily_settlement",
            execute_standing_orders=command.execute_standing_orders,
        )
    if isinstance(command, RunQuarterlyAffairsRequest):
        return RunQuarterlyAffairsCommand(
            type="run_quarterly_affairs",
            player_id=str(command.player_id),
            choices=QuarterlyChoices(**command.choices.model_dump()),
        )
    if isinstance(command, ResolveCashShortfallRequest):
        return ResolveCashShortfallCommand(
            type="resolve_cash_shortfall", player_id=str(command.player_id)
        )
    if isinstance(command, AdvancePhaseRequest):
        return AdvancePhaseCommand(type="advance_phase", phase=command.phase, reason=command.reason)
    raise TypeError(f"unsupported command request: {type(command)!r}")


def _game_response(stored: StoredGame) -> GameResponse:
    payload = _safe_state(stored.state)
    digest = hashlib.sha256(state_digest(stored.state).encode()).hexdigest()
    return GameResponse(
        game_id=UUID(stored.state.id),
        version=stored.version,
        state=payload,
        state_digest=digest,
    )


def _safe_state(state: GameState) -> dict[str, object]:
    payload = state_to_dict(state)
    if state.phase != "finished":
        payload.pop("server_seed", None)
    payload["standing_orders"] = []
    payload["trade_offers"] = []
    payload["pending_effects"] = []
    players = payload.get("players")
    if isinstance(players, list):
        for player in players:
            if isinstance(player, dict):
                player["loans"] = []
    alliances = payload.get("alliances")
    if isinstance(alliances, list):
        for alliance in alliances:
            if isinstance(alliance, dict):
                alliance["member_states"] = []
    return payload


def _http_error(status_code: int, code: str, message: str) -> HTTPException:
    return HTTPException(status_code=status_code, detail={"code": code, "message": message})
