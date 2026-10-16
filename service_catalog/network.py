"""Readers for stored query results, and the rule that pairs a service's devices into paths.

The business impact code (Planned maintenance page, Gold outage guard, notification) and
the cost of service code read the same query shapes and pair the same devices into paths,
so they count the same paths.

Nothing here imports another `service_catalog` module, so the Infrahub task worker can
import it from the commit worktree as `commits.<sha>.service_catalog.network`.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from typing import Any, Protocol, TypeVar

CORE_ROLE = "core"
EDGE_ROLE = "edge"


# Reading a query result


class QueryError(RuntimeError):
    """The stored query returned errors, so its result cannot be read."""

    def __init__(self, where: str, messages: list[str]) -> None:
        super().__init__(f"Could not read {where}: {'; '.join(messages)}")
        self.messages = messages


def query_errors(body: Mapping[str, Any]) -> list[str]:
    """The error messages of a stored query response; empty when it has none."""
    errors = body.get("errors") or []
    return [str(error.get("message", error)) if isinstance(error, dict) else str(error) for error in errors]


def query_data(body: dict[str, Any], where: str) -> dict[str, Any]:
    """The `data` part of a stored query response; raise `QueryError` when the response holds errors."""
    if messages := query_errors(body):
        raise QueryError(where, messages)
    data: dict[str, Any] = body.get("data") or body
    return data


def mapping(value: object) -> Mapping[str, object]:
    return value if isinstance(value, Mapping) else {}


def nodes(block: object) -> list[Mapping[str, object]]:
    """The nodes of an `edges` block, without empty ones."""
    edges = mapping(block).get("edges")
    if not isinstance(edges, list):
        return []
    return [node for edge in edges if (node := mapping(mapping(edge).get("node")))]


def peer(node: Mapping[str, object], name: str) -> Mapping[str, object]:
    """The peer node of the relationship `name`, or an empty mapping."""
    return mapping(mapping(node.get(name)).get("node"))


def attr(node: Mapping[str, object], name: str) -> object:
    """The value of the attribute `name`."""
    return mapping(node.get(name)).get("value")


def text(node: Mapping[str, object], name: str) -> str | None:
    """The attribute as text; None when it is empty."""
    value = attr(node, name)
    return str(value) if value not in {None, ""} else None


def number(node: Mapping[str, object], name: str) -> float | None:
    """The attribute as a number; None when it is empty or not a number."""
    value = attr(node, name)
    if isinstance(value, bool) or value in {None, ""}:
        return None
    try:
        return float(str(value))
    except ValueError:
        return None


def integer(node: Mapping[str, object], name: str) -> int | None:
    """The attribute as a whole number; None when it is empty or not a number."""
    value = number(node, name)
    return int(value) if value is not None else None


# Paths


class PathDevice(Protocol):
    """A device as a path sees it: its name, role, index and site."""

    @property
    def name(self) -> str: ...

    @property
    def role(self) -> str | None: ...

    @property
    def index(self) -> int | None: ...

    @property
    def site(self) -> str | None: ...


DeviceT = TypeVar("DeviceT", bound=PathDevice)


def pair_paths(devices: Iterable[DeviceT]) -> list[tuple[DeviceT, DeviceT]]:
    """Each switch paired with the edge router of the same index at the same site, switches by index.

    The order generator pairs switch N with edge router N, so each pair is one separate path. A device
    appears once, however many of the service's interfaces sit on it. A device with no index is in no path.
    """
    unique: dict[str, DeviceT] = {}
    for device in devices:
        unique.setdefault(device.name, device)
    indexed = [device for device in unique.values() if device.index is not None]
    switches = sorted((d for d in indexed if d.role == CORE_ROLE), key=lambda d: (d.index or 0, d.name))
    routers = sorted((d for d in indexed if d.role == EDGE_ROLE), key=lambda d: d.name)
    return [
        (switch, router)
        for switch in switches
        for router in routers
        if router.index == switch.index and router.site == switch.site
    ]
