"""JSON helpers for engine event streams."""

from __future__ import annotations

from dataclasses import asdict, fields, is_dataclass
from typing import Any, cast, get_args, get_type_hints

from assetrush.engine.events import Event

EVENT_TYPES: dict[str, type[Any]] = {}
for event_class in get_args(Event):
    event_type = get_args(get_type_hints(event_class)["type"])[0]
    EVENT_TYPES[event_type] = event_class


def event_to_dict(event: Event) -> dict[str, object]:
    """Convert an event dataclass to a JSON-serializable object."""

    if not is_dataclass(event) or isinstance(event, type):
        raise TypeError(f"expected event dataclass, got {type(event)!r}")
    return asdict(event)


def event_from_dict(payload: dict[str, Any]) -> Event:
    """Build a typed engine event from decoded JSON."""

    event_type = payload.get("type")
    if not isinstance(event_type, str):
        raise ValueError("event payload requires a string type")
    event_class = EVENT_TYPES.get(event_type)
    if event_class is None:
        raise ValueError(f"unknown event type: {event_type}")

    kwargs: dict[str, object] = {}
    type_hints = get_type_hints(event_class)
    for field in fields(event_class):
        if field.name not in payload:
            continue
        value = payload[field.name]
        if _is_tuple_field(type_hints[field.name]) and isinstance(value, list):
            kwargs[field.name] = _tuple_from_json(value)
        else:
            kwargs[field.name] = value
    return cast(Event, event_class(**kwargs))


def _is_tuple_field(annotation: object) -> bool:
    origin = getattr(annotation, "__origin__", None)
    return origin is tuple


def _tuple_from_json(value: list[object]) -> tuple[object, ...]:
    return tuple(_tuple_from_json(item) if isinstance(item, list) else item for item in value)
