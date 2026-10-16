"""Builders shared by the unit tests: query results, SDK stand-ins and the expected messages.

`build_q1` builds `data` dicts in the shape of the stored query
`business_impact_services` for the twelve seed services and sixteen devices
that `invoke seed` creates. Each service has two dedicated interfaces, as the
generator builds them: a customer port on the pinned switch (role `core`) and a
gateway interface on the edge router with the same index (role `edge`).
`second_paths` adds a second pair of interfaces to a service, as `invoke seed`
does for the Paris Gold services. Only the eight par01 and bru01 devices carry
a description, as in `data/08_device.yml`.

Each builder adds the footprint of each active service, as the code adds it from
Infrahub's path traversal: `traced` runs `footprint.service_footprints` with
`TraversalClient`, which answers each traversal from the fixture. A service
reaches a device when it has an interface on it, and a circuit when its gateway
edge router carries that circuit. A test that edits a fixture calls `traced`
again, so the footprints follow the edit.

`build_cost_data` builds the `cost_of_service` query result for the same seed:
the list prices of `data/06_device_type.yml` and the circuits of
`data/business_impact/upstream_circuits.yml`, merged from the circuit query as
the page and the transform merge them. Each switch port and each gateway
interface of a path is active, and each edge router's `Ethernet4` is active
because it carries the circuit. `stored_only` drops the circuit query result,
as before `invoke seed` loads the circuit schema.
"""

from __future__ import annotations

import asyncio
import re
from collections import Counter
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from pathlib import Path
from types import SimpleNamespace
from typing import TYPE_CHECKING, Any

from service_catalog.business_impact.blast_radius import parse_services
from service_catalog.business_impact.footprint import FOOTPRINTS, service_footprints, with_footprints

if TYPE_CHECKING:
    from collections.abc import Callable, Collection, Coroutine, Mapping

    from service_catalog.business_impact.blast_radius import BlastRadius, ServiceRow

REPO_ROOT = Path(__file__).resolve().parents[2]

# The names of the seeded maintenance proposed changes.
PARIS = "Paris router 1 maintenance"
BRUSSELS = "Brussels switch 1 maintenance"
NEW_YORK = "New York router 1 maintenance"


def value(content: object) -> dict[str, object]:
    """An attribute as a query result holds it."""
    return {"value": content}


def sdk_value(content: object) -> SimpleNamespace:
    """An attribute as an SDK node holds it."""
    return SimpleNamespace(value=content)


def proposed_change(name: str, branch: str, tags: Collection[str] = ()) -> SimpleNamespace:
    """An open proposed change as the SDK returns it, with its tag names."""
    peers = [SimpleNamespace(peer=SimpleNamespace(name=sdk_value(tag))) for tag in tags]
    return SimpleNamespace(
        name=sdk_value(name),
        source_branch=sdk_value(branch),
        state=sdk_value("open"),
        tags=SimpleNamespace(peers=peers),
    )


# Path traversal answered from a fixture


def _hop(kind: str, label: str, node_id: str = "") -> SimpleNamespace:
    return SimpleNamespace(node=SimpleNamespace(kind=kind, display_label=label, id=node_id))


def _body(data: Mapping[str, Any]) -> Mapping[str, Any]:
    return data.get("data", data) if "errors" not in data else data


class TraversalClient:
    """Stand-in for `InfrahubClient.traverse_paths`, answered from query data by branch.

    A service reaches a device when one of its interfaces is on the device, and a circuit when an edge
    router behind its interfaces has its upstream interface connected to the circuit's endpoint.
    """

    def __init__(self, data_by_branch: Mapping[str, Mapping[str, Any]]) -> None:
        self.data_by_branch = data_by_branch
        self.traversals: list[tuple[str, str, dict[str, Any]]] = []
        # Service identifiers whose searches Infrahub stops early, with the depth it stopped at.
        self.truncated: dict[str, int] = {}

    async def traverse_paths(self, source: str, destination: str, **kwargs: Any) -> SimpleNamespace:  # noqa: ANN401
        self.traversals.append((source, destination, kwargs))
        data = _body(self.data_by_branch[str(kwargs["branch"])])
        service = next(
            edge["node"] for edge in data["ServiceDedicatedInternet"]["edges"] if edge["node"].get("id") == source
        )
        identifier = service["service_identifier"]["value"]
        behind = [interface["node"]["device"]["node"] for interface in service["dedicated_interfaces"]["edges"]]
        names = {device["name"]["value"] for device in behind}
        devices = {edge["node"]["id"]: edge["node"] for edge in data["DcimDevice"]["edges"]}
        if destination in devices:
            name = devices[destination]["name"]["value"]
            if name not in names:
                return SimpleNamespace(count=0, paths=[], truncated_at_depth=self.truncated.get(identifier))
            hops = [
                _hop("ServiceDedicatedInternet", identifier),
                _hop("DcimInterface", ""),
                _hop("DcimDevice", name, destination),
            ]
            return SimpleNamespace(count=1, paths=[SimpleNamespace(hops=hops)], truncated_at_depth=None)
        circuit = next(
            edge["node"]["circuit_id"]["value"]
            for edge in data["DcimCircuit"]["edges"]
            if edge["node"]["id"] == destination
        )
        endpoints = {
            edge["node"]["id"]: edge["node"]["circuit"]["node"]["circuit_id"]["value"]
            for edge in data["DcimCircuitEndpoint"]["edges"]
        }
        for router in sorted(names):
            node: dict[str, Any] = next(
                (device for device in devices.values() if device["name"]["value"] == router), {}
            )
            for upstream in (node.get("upstream") or {}).get("edges", []):
                endpoint = (upstream["node"]["connected_endpoint"]["node"] or {}).get("id")
                if node["role"]["value"] == "edge" and endpoints.get(endpoint) == circuit:
                    hops = [
                        _hop("ServiceDedicatedInternet", identifier),
                        _hop("DcimInterfaceL3", ""),
                        _hop("DcimDevice", router, node["id"]),
                        _hop("DcimInterfaceL3", "Ethernet4"),
                        _hop("DcimCircuitEndpoint", "Endpoint A"),
                        _hop("DcimCircuit", circuit),
                    ]
                    return SimpleNamespace(count=1, paths=[SimpleNamespace(hops=hops)], truncated_at_depth=None)
        return SimpleNamespace(count=0, paths=[], truncated_at_depth=self.truncated.get(identifier))


def run(coroutine: Coroutine[Any, Any, Any]) -> Any:  # noqa: ANN401
    """Run `coroutine` to the end, also from inside a running event loop (an async test)."""
    try:
        asyncio.get_running_loop()
    except RuntimeError:
        return asyncio.run(coroutine)
    with ThreadPoolExecutor(1) as pool:
        return pool.submit(asyncio.run, coroutine).result()


def run_async_on_fixture(read: Callable[..., Coroutine[Any, Any, Any]], data: Mapping[str, Any], branch: str) -> Any:  # noqa: ANN401
    """Stand-in for `infrahub.run_async(read, data, branch)` on a page: `TraversalClient` answers from `data`."""
    return run(read(TraversalClient({branch: data}), data, branch))


def traced(data: Mapping[str, Any], branch: str = "main") -> dict[str, Any]:
    """`data` with the footprint of each active service, from `TraversalClient`; earlier footprints are replaced."""
    plain = {key: block for key, block in data.items() if key != FOOTPRINTS}
    client = TraversalClient({branch: plain})
    footprints = run(service_footprints(client, plain, branch, circuits="DcimCircuit" in plain))
    return with_footprints(plain, footprints)


# The stored query `business_impact_services`

Q1Data = dict[str, Any]

TIER_MIN_PATHS = {"Gold": 1, "Silver": 0, "Bronze": 0}
TIERS = tuple(TIER_MIN_PATHS)
# The second path `invoke seed` adds to each Paris Gold service: (switch, edge router).
PARIS_SECOND_PATHS = {
    "DI-1001": ("sw02-par01", "rb02-par01"),
    "DI-1002": ("sw02-par01", "rb02-par01"),
    "DI-1003": ("sw01-par01", "rb01-par01"),
}

DESCRIPTIONS = {
    "rb01-par01": "Paris edge router 1",
    "rb02-par01": "Paris edge router 2",
    "rb01-bru01": "Brussels edge router 1",
    "rb02-bru01": "Brussels edge router 2",
    "sw01-par01": "Paris switch 1",
    "sw02-par01": "Paris switch 2",
    "sw01-bru01": "Brussels switch 1",
    "sw02-bru01": "Brussels switch 2",
}

SITES = ("bru01", "par01", "nyc01", "dal01")
SITE_NAMES = {"bru01": "Brussels", "par01": "Paris", "nyc01": "New York", "dal01": "Dallas"}


@dataclass(frozen=True)
class SeedRow:
    identifier: str
    customer: str | None
    tier: str | None
    bandwidth: str
    switch: str
    router: str
    status: str = "active"


SEED = (
    SeedRow("DI-1001", "Northbank", "Gold", "10000", "sw01-par01", "rb01-par01"),
    SeedRow("DI-1002", "Northbank", "Gold", "1000", "sw01-par01", "rb01-par01"),
    SeedRow("DI-1003", "Helix Health", "Gold", "1000", "sw02-par01", "rb02-par01"),
    SeedRow("DI-1004", "Maison Verte", "Silver", "1000", "sw01-par01", "rb01-par01"),
    SeedRow("DI-1005", "Maison Verte", "Silver", "100", "sw02-par01", "rb02-par01"),
    SeedRow("DI-1006", "Rapid Freight", "Bronze", "100", "sw01-par01", "rb01-par01"),
    SeedRow("DI-1007", "Rapid Freight", "Bronze", "1000", "sw02-par01", "rb02-par01"),
    SeedRow("DI-2001", "Helix Health", "Gold", "10000", "sw01-bru01", "rb01-bru01"),
    SeedRow("DI-2002", "Northbank", "Gold", "1000", "sw02-bru01", "rb02-bru01"),
    SeedRow("DI-2003", "Maison Verte", "Silver", "1000", "sw01-bru01", "rb01-bru01"),
    SeedRow("DI-2004", "Rapid Freight", "Bronze", "100", "sw02-bru01", "rb02-bru01"),
    SeedRow("DI-2005", "Rapid Freight", "Bronze", "1000", "sw01-bru01", "rb01-bru01"),
)


def _device_names() -> list[str]:
    return [f"{prefix}0{index}-{site}" for site in SITES for prefix in ("sw", "rb") for index in (1, 2)]


def _device_node(name: str, status: str) -> dict[str, object]:
    return {
        "id": f"device-{name}",
        "name": value(name),
        "description": value(DESCRIPTIONS.get(name)),
        "role": value("core" if name.startswith("sw") else "edge"),
        "status": value(status),
        "index": value(int(name[2:4])),
        "location": {"node": {"__typename": "LocationSite", "shortname": value(name.split("-")[1])}},
    }


def _interface(name: str, device: dict[str, object]) -> dict[str, object]:
    return {"node": {"name": value(name), "device": {"node": device}}}


def _second(second_paths: Mapping[str, tuple[str, str]] | None, identifier: str) -> list[tuple[str, str]]:
    pair = (second_paths or {}).get(identifier)
    return [pair] if pair else []


def build_q1(
    statuses: Mapping[str, str] | None = None,
    rows: tuple[SeedRow, ...] = SEED,
    tiers: Collection[str] = TIERS,
    min_paths: Mapping[str, int | None] | None = None,
    second_paths: Mapping[str, tuple[str, str]] | None = None,
) -> dict[str, Any]:
    """Build query `data` with every device active unless `statuses` says otherwise.

    `tiers` names the tiers of the `ServiceTier` block. `min_paths` sets each tier's minimum separate paths
    during a change (name to number); it defaults to Gold 1, Silver 0, Bronze 0. A tier set to `None`, or
    not named, gets an empty value. `second_paths` gives a service a second switch and edge router, by
    service identifier.
    """
    rule_of = TIER_MIN_PATHS if min_paths is None else min_paths
    status_of = dict.fromkeys(_device_names(), "active")
    status_of.update(statuses or {})
    switch_ports: dict[str, int] = {}
    service_edges: list[dict[str, object]] = []
    for index, row in enumerate(rows):
        site = row.switch.split("-")[1]
        interfaces: list[dict[str, object]] = []
        for switch, router in ((row.switch, row.router), *_second(second_paths, row.identifier)):
            port = switch_ports.get(switch, 4)
            switch_ports[switch] = port + 1
            interfaces.extend(
                (
                    _interface(f"Ethernet{port}", _device_node(switch, status_of[switch])),
                    _interface(f"vlan_{1000 + index}", _device_node(router, status_of[router])),
                )
            )
        service_edges.append(
            {
                "node": {
                    "id": f"service-{row.identifier}",
                    "service_identifier": value(row.identifier),
                    "status": value(row.status),
                    "bandwidth": value(row.bandwidth),
                    "location": {"node": {"shortname": value(site), "name": value(SITE_NAMES[site])}},
                    "customer": {"node": {"name": value(row.customer)} if row.customer else None},
                    "tier": {"node": {"name": value(row.tier)} if row.tier else None},
                    "dedicated_interfaces": {"edges": interfaces},
                }
            }
        )
    device_edges = [{"node": _device_node(name, status_of[name])} for name in _device_names()]
    tier_edges = [{"node": {"name": value(name), "min_paths": value(rule_of.get(name))}} for name in tiers]
    return traced(
        {
            "ServiceDedicatedInternet": {"edges": service_edges},
            "DcimDevice": {"edges": device_edges},
            "ServiceTier": {"edges": tier_edges},
        }
    )


def build_seeded_q1(statuses: Mapping[str, str] | None = None) -> dict[str, Any]:
    """`build_q1` after `invoke seed`: the Paris Gold services have two paths."""
    return build_q1(statuses, second_paths=PARIS_SECOND_PATHS)


def service_row(data: Mapping[str, object], identifier: str) -> ServiceRow:
    """The parsed service `identifier` of the query data."""
    return next(service for service in parse_services(data) if service.identifier == identifier)


def tiles(result: BlastRadius) -> dict[str, str]:
    """Each tile's label with its value."""
    return {tile.label: tile.value for tile in result.tiles}


# Copy rules

MONEY_WORDS = re.compile(r"EUR|€|\bSLA\b|credit|contract value|price|charge", re.IGNORECASE)

# "at risk" is allowed: it is the status of a service with fewer separate paths during a change.
# "branch" is a word of its own: a field name such as `source_branch` is not copy.
FORBIDDEN_COPY = re.compile(
    r"\bbranch|\bROI\b|\bsavings?\b|\bhours?\b|time saved|outage cost|cost of an outage|\bloss\b|\bchurn\b",
    re.IGNORECASE,
)
ALLOWED_CAPTION = "Not calculated: outage cost, time saved, ROI, churn."


# The Gold outage guard

BRUSSELS_MESSAGE = (
    "Brussels switch 1 maintenance leaves 1 Gold service for Helix Health with no other path (DI-2001). "
    "It has 1 separate path on the current network and 0 during this change. "
    "Move this service to Brussels switch 2 first. "
    "Gold requires at least 1 separate path during a change, and this change leaves 0."
)

RAISE_SILVER = "Promise two paths to Silver customers"
RAISE_SILVER_MESSAGE = (
    "Promise two paths to Silver customers raises the Silver rule from 0 to 2 separate paths during a change, "
    "and 3 active Silver services have fewer (DI-1004, DI-1005, DI-2003: 1 each). "
    "Build the paths first, or keep the rule at 0."
)


class QueryClient(TraversalClient):
    """Stand-in for the SDK client: the stored query and path traversal by branch, and one open proposed change.

    The stored query returns the fixture without its footprints, as Infrahub returns it.
    """

    def __init__(self, data_by_branch: dict[str, dict[str, Any]], change_name: str | None) -> None:
        super().__init__(data_by_branch)
        self.change_name = change_name
        self.reads: list[tuple[str, str]] = []

    async def query_gql_query(self, name: str, branch_name: str, **_: object) -> dict[str, Any]:
        self.reads.append((name, branch_name))
        body = self.data_by_branch[branch_name]
        if "errors" in body:
            return dict(body)
        return {"data": {key: block for key, block in body.items() if key != FOOTPRINTS}}

    async def filters(self, **kwargs: object) -> list[object]:
        if self.change_name is None:
            return []
        return [proposed_change(self.change_name, str(kwargs.get("source_branch__value", "")))]


# The stored query `cost_of_service`

ROUTER_PRICE = 12000
SWITCH_PRICE = 6000
# The circuits of data/business_impact/upstream_circuits.yml: edge router to circuit ID and monthly cost.
CIRCUITS = {
    "rb01-par01": ("COG-PAR-TR-1001", 2500),
    "rb02-par01": ("COLT-PAR-TR-2001", 2500),
    "rb01-bru01": ("ZAYO-BRU-TR-1001", 2000),
    "rb02-bru01": ("COLT-BRU-TR-2001", 2000),
    "rb01-nyc01": ("COG-NYC-TR-1001", 3000),
    "rb02-nyc01": ("LUMEN-NYC-TR-2001", 3000),
    "rb01-dal01": ("ZAYO-DAL-TR-1001", 3000),
    "rb02-dal01": ("LUMEN-DAL-TR-2001", 3000),
}


def _cost_paths(
    rows: tuple[SeedRow, ...], second_paths: Mapping[str, tuple[str, str]]
) -> dict[str, list[tuple[str, str]]]:
    return {
        row.identifier: [
            (row.switch, row.router),
            *([second_paths[row.identifier]] if row.identifier in second_paths else []),
        ]
        for row in rows
    }


def build_cost_data(
    rows: tuple[SeedRow, ...] = SEED,
    second_paths: Mapping[str, tuple[str, str]] = PARIS_SECOND_PATHS,
    prices: Mapping[str, int | None] | None = None,
    circuits: Mapping[str, tuple[str, int | None]] = CIRCUITS,
    active: Mapping[str, int] | None = None,
) -> dict[str, Any]:
    """The `cost_of_service` query result for the seed, merged with the circuit query result.

    `active` overrides a device's active interface count.
    """
    price_of = {"Generic router": ROUTER_PRICE, "Generic switch": SWITCH_PRICE, **(prices or {})}
    paths = _cost_paths(rows, second_paths)
    count: Counter[str] = Counter()
    for pairs in paths.values():
        for switch, router in pairs:
            count[switch] += 1
            count[router] += 1
    for router in circuits:
        count[router] += 1
    counts = {**count, **(active or {})}

    def device(name: str) -> dict[str, object]:
        device_type = "Generic switch" if name.startswith("sw") else "Generic router"
        return {
            "id": f"device-{name}",
            "name": value(name),
            "role": value("core" if name.startswith("sw") else "edge"),
            "index": value(int(name[2:4])),
            "location": {"node": {"__typename": "LocationSite", "shortname": value(name.split("-")[1])}},
            "device_type": {"node": {"name": value(device_type), "list_price": value(price_of[device_type])}},
            "interfaces": {"count": counts.get(name, 0)},
        }

    def upstream(name: str) -> dict[str, object]:
        circuit = circuits.get(name)
        endpoint = (
            {"node": {"id": circuit_endpoint_id(name), "__typename": "DcimCircuitEndpoint"}}
            if circuit
            else {"node": None}
        )
        return {
            "edges": [
                {
                    "node": {
                        "name": value("Ethernet4"),
                        "status": value("active" if circuit else "free"),
                        "connected_endpoint": endpoint,
                    }
                },
                {"node": {"name": value("Ethernet5"), "status": value("free"), "connected_endpoint": {"node": None}}},
            ]
        }

    services_block = [
        {
            "node": {
                "id": f"service-{row.identifier}",
                "service_identifier": value(row.identifier),
                "status": value(row.status),
                "bandwidth": value(row.bandwidth),
                "location": {"node": {"__typename": "LocationSite", "shortname": value(row.switch.split("-")[1])}},
                "customer": {"node": {"name": value(row.customer)}} if row.customer else {"node": None},
                "tier": {"node": {"name": value(row.tier)}} if row.tier else {"node": None},
                "dedicated_interfaces": {
                    "edges": [
                        {"node": {"name": value(interface), "device": {"node": device(name)}}}
                        for switch, router in paths[row.identifier]
                        for interface, name in (("Ethernet", switch), ("vlan", router))
                    ]
                },
            }
        }
        for row in rows
    ]
    devices = [
        {"node": {**device(name), "upstream": upstream(name)} if name.startswith("rb") else device(name)}
        for name in _device_names()
    ]
    return traced(
        {
            "ServiceDedicatedInternet": {"edges": services_block},
            "DcimDevice": {"edges": devices},
            **build_circuit_data(circuits),
        }
    )


def stored_only(data: dict[str, Any]) -> dict[str, Any]:
    """`data` without the circuit query result: the stored query result alone, with footprints without circuits."""
    return traced({key: block for key, block in data.items() if key not in {"DcimCircuitEndpoint", "DcimCircuit"}})


def circuit_endpoint_id(router: str) -> str:
    """The ID of the circuit endpoint connected to the Ethernet4 of `router`."""
    return f"endpoint-{router}"


def build_circuit_data(circuits: Mapping[str, tuple[str, int | None]] = CIRCUITS) -> dict[str, Any]:
    """The result of the circuit query `cost_of_service_circuits`: each circuit with its site, and each endpoint
    ID with its circuit."""
    return {
        "DcimCircuit": {
            "edges": [
                {
                    "node": {
                        "id": f"circuit-{circuit_id}",
                        "circuit_id": value(circuit_id),
                        "monthly_cost": value(cost),
                        "location": {"node": {"__typename": "LocationSite", "shortname": value(router.split("-")[1])}},
                    }
                }
                for router, (circuit_id, cost) in circuits.items()
            ]
        },
        "DcimCircuitEndpoint": {
            "edges": [
                {
                    "node": {
                        "id": circuit_endpoint_id(router),
                        "circuit": {"node": {"circuit_id": value(circuit_id), "monthly_cost": value(cost)}},
                    }
                }
                for router, (circuit_id, cost) in circuits.items()
            ]
        },
    }


SEEDED = build_cost_data()
