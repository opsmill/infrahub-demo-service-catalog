"""The devices and circuits each active service's paths go through, found by Infrahub's path traversal.

`service_footprints` asks Infrahub, for each active service, which core and edge devices at the
service's site a path reaches: service, interface, device. With `circuits`, it also asks which
upstream circuits at the site the service's traffic leaves through: service, gateway interface,
edge router, upstream interface, circuit endpoint, circuit. `with_footprints` adds the result to
a query result, where the Gold outage guard, the business impact pages and the cost of service read it.

The imports are relative so the Infrahub task worker can import this module from the commit worktree.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

from infrahub_sdk.exceptions import Error as SdkError

from ..network import CORE_ROLE, EDGE_ROLE, nodes, peer, text  # noqa: TID252 - the commit worktree import
from ..protocols_async import (  # noqa: TID252 - the commit worktree import
    DcimCircuit,
    DcimCircuitEndpoint,
    DcimDevice,
    DcimInterfaceL2,
    DcimInterfaceL3,
    ServiceDedicatedInternet,
)

if TYPE_CHECKING:
    from collections.abc import Mapping

    from infrahub_sdk import InfrahubClient

FOOTPRINTS = "footprints"
DEVICE_KINDS = [ServiceDedicatedInternet, DcimInterfaceL2, DcimInterfaceL3, DcimDevice]
CIRCUIT_KINDS = [ServiceDedicatedInternet, DcimInterfaceL3, DcimDevice, DcimCircuitEndpoint, DcimCircuit]
# Relationships from a service to a device: service, interface, device.
DEVICE_HOPS = 2
# Relationships from a service to an upstream circuit: service, gateway interface, edge router,
# upstream interface, circuit endpoint, circuit.
CIRCUIT_HOPS = 5
MAX_CONCURRENT = 8


class TraversalTruncatedError(SdkError):
    """Infrahub stopped a path search early and found no path, so "no path" is not known to be true."""

    def __init__(self, service: str, target: str, depth: int) -> None:
        super().__init__(
            f"Infrahub stopped the path search from {service} to {target} at depth {depth} without a result"
        )


@dataclass(frozen=True)
class Footprint:
    """The names of the devices and the IDs of the circuits that a service's paths go through."""

    devices: frozenset[str] = frozenset()
    # Each circuit ID, with the name of the edge router the path reaches it through.
    circuits: Mapping[str, str] = field(default_factory=dict)


def _at_site(data: Mapping[str, Any], block: str, site: str | None) -> list[Mapping[str, object]]:
    return [node for node in nodes(data.get(block)) if site and text(peer(node, "location"), "shortname") == site]


async def service_footprints(
    client: InfrahubClient, data: Mapping[str, Any], branch: str, *, circuits: bool = False
) -> dict[str, Footprint]:
    """The footprint of each active service in `data`, by service identifier, on `branch`."""
    limit = asyncio.Semaphore(MAX_CONCURRENT)
    devices: dict[str, set[str]] = {}
    routers: dict[str, dict[str, str]] = {}
    edge_routers = {
        str(device["id"]): text(device, "name") or ""
        for device in nodes(data.get("DcimDevice"))
        if text(device, "role") == EDGE_ROLE
    }

    async def trace(service: Mapping[str, object], target: Mapping[str, object], depth: int) -> None:
        async with limit:
            found = await client.traverse_paths(
                str(service["id"]),
                str(target["id"]),
                kind_filter=CIRCUIT_KINDS if depth == CIRCUIT_HOPS else DEVICE_KINDS,
                max_depth=depth,
                branch=branch,
            )
        name = text(service, "service_identifier") or ""
        if not found.count:
            # A search that stopped early proves nothing: reading it as "no path" would hide a path.
            if found.truncated_at_depth is not None:
                target_name = text(target, "name") or text(target, "circuit_id") or str(target["id"])
                raise TraversalTruncatedError(name, target_name, found.truncated_at_depth)
            return
        if depth == DEVICE_HOPS:
            devices[name].add(text(target, "name") or "")
            return
        # The edge router the path reaches the circuit through, matched by node ID, not by hop position.
        router = next(
            (edge_routers[hop.node.id] for path in found.paths for hop in path.hops if hop.node.id in edge_routers),
            None,
        )
        if router is not None:
            routers[name][text(target, "circuit_id") or ""] = router

    calls = []
    for service in nodes(data.get("ServiceDedicatedInternet")):
        if text(service, "status") != "active":
            continue
        name = text(service, "service_identifier") or ""
        devices[name], routers[name] = set(), {}
        site = text(peer(service, "location"), "shortname")
        calls += [
            trace(service, device, DEVICE_HOPS)
            for device in _at_site(data, "DcimDevice", site)
            if text(device, "role") in {CORE_ROLE, EDGE_ROLE}
        ]
        if circuits:
            calls += [trace(service, circuit, CIRCUIT_HOPS) for circuit in _at_site(data, "DcimCircuit", site)]
    await asyncio.gather(*calls)
    return {name: Footprint(frozenset(devices[name]), routers[name]) for name in devices}


def with_footprints(data: Mapping[str, Any], footprints: Mapping[str, Footprint]) -> dict[str, Any]:
    """The query result with the footprint of each service added."""
    return {**data, FOOTPRINTS: dict(footprints)}
