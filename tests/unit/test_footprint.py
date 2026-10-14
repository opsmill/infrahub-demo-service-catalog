"""Unit tests for the service footprints: the devices and circuits Infrahub's path traversal reaches from a service.

`TraversalClient` in `builders.py` answers each traversal from the seed-shaped fixtures: a service reaches
a device when it has an interface on it, and a circuit when its gateway edge router carries the circuit.
"""

from __future__ import annotations

import asyncio
from types import SimpleNamespace
from typing import TYPE_CHECKING, Any, cast

import pytest

from service_catalog.business_impact.footprint import (
    CIRCUIT_HOPS,
    DEVICE_HOPS,
    FOOTPRINTS,
    MAX_CONCURRENT,
    Footprint,
    TraversalTruncatedError,
    service_footprints,
    with_footprints,
)
from service_catalog.protocols_async import (
    DcimCircuit,
    DcimCircuitEndpoint,
    DcimDevice,
    DcimInterfaceL2,
    DcimInterfaceL3,
    ServiceDedicatedInternet,
)

from .builders import (
    SEED,
    SEEDED,
    SeedRow,
    TraversalClient,
    build_q1,
    build_seeded_q1,
    run,
    stored_only,
)

if TYPE_CHECKING:
    from infrahub_sdk import InfrahubClient

PARIS_DEVICES = frozenset({"sw01-par01", "sw02-par01", "rb01-par01", "rb02-par01"})


def _footprints(client: TraversalClient, data: dict[str, Any], *, circuits: bool = False) -> dict[str, Footprint]:
    footprints: dict[str, Footprint] = run(
        service_footprints(cast("InfrahubClient", client), data, "main", circuits=circuits)
    )
    return footprints


def test_each_service_reaches_the_devices_its_interfaces_are_on() -> None:
    data = build_seeded_q1()

    footprints = _footprints(TraversalClient({"main": data}), data)

    assert footprints["DI-1001"] == Footprint(PARIS_DEVICES)
    assert footprints["DI-1004"] == Footprint(frozenset({"sw01-par01", "rb01-par01"}))
    assert footprints["DI-2002"] == Footprint(frozenset({"sw02-bru01", "rb02-bru01"}))


def test_each_service_reaches_the_circuits_of_its_edge_routers() -> None:
    footprints = _footprints(TraversalClient({"main": SEEDED}), SEEDED, circuits=True)

    assert footprints["DI-1001"].circuits == {"COG-PAR-TR-1001": "rb01-par01", "COLT-PAR-TR-2001": "rb02-par01"}
    assert footprints["DI-1004"].circuits == {"COG-PAR-TR-1001": "rb01-par01"}
    assert footprints["DI-2001"].circuits == {"ZAYO-BRU-TR-1001": "rb01-bru01"}


def test_the_traversal_is_filtered_by_protocol_classes_with_a_hop_limit() -> None:
    """The kind filter uses the generated protocol classes, which the SDK turns into kind names."""
    client = TraversalClient({"main": SEEDED})

    _footprints(client, SEEDED, circuits=True)

    device_calls = [kwargs for _, destination, kwargs in client.traversals if destination.startswith("device-")]
    circuit_calls = [kwargs for _, destination, kwargs in client.traversals if destination.startswith("circuit-")]
    assert device_calls
    assert circuit_calls
    for kwargs in device_calls:
        assert kwargs == {
            "kind_filter": [ServiceDedicatedInternet, DcimInterfaceL2, DcimInterfaceL3, DcimDevice],
            "max_depth": DEVICE_HOPS,
            "branch": "main",
        }
    for kwargs in circuit_calls:
        assert kwargs == {
            "kind_filter": [ServiceDedicatedInternet, DcimInterfaceL3, DcimDevice, DcimCircuitEndpoint, DcimCircuit],
            "max_depth": CIRCUIT_HOPS,
            "branch": "main",
        }
    assert (DEVICE_HOPS, CIRCUIT_HOPS) == (2, 5)


def test_only_the_devices_and_circuits_at_the_service_site_are_traversed() -> None:
    client = TraversalClient({"main": SEEDED})

    _footprints(client, SEEDED, circuits=True)

    di_1001 = [destination for source, destination, _ in client.traversals if source == "service-DI-1001"]
    assert sorted(di_1001) == [
        "circuit-COG-PAR-TR-1001",
        "circuit-COLT-PAR-TR-2001",
        "device-rb01-par01",
        "device-rb02-par01",
        "device-sw01-par01",
        "device-sw02-par01",
    ]
    # Twelve services, each with four devices and two circuits at its site.
    assert len(client.traversals) == len(SEED) * 6


def test_without_circuits_no_circuit_is_traversed() -> None:
    data = stored_only(SEEDED)
    client = TraversalClient({"main": data})

    footprints = _footprints(client, data)

    assert all(destination.startswith("device-") for _, destination, _ in client.traversals)
    assert all(not footprint.circuits for footprint in footprints.values())


def test_a_service_that_is_not_active_has_no_footprint() -> None:
    rows = (*SEED, SeedRow("DI-1099", "Northbank", "Gold", "100", "sw01-par01", "rb01-par01", status="draft"))
    data = build_q1(rows=rows)
    client = TraversalClient({"main": data})

    footprints = _footprints(client, data)

    assert "DI-1099" not in footprints
    assert all(source != "service-DI-1099" for source, _, _ in client.traversals)


def test_at_most_a_few_traversals_run_at_the_same_time() -> None:
    running = SimpleNamespace(now=0, most=0)

    class SlowClient(TraversalClient):
        async def traverse_paths(self, source: str, destination: str, **kwargs: Any) -> SimpleNamespace:  # noqa: ANN401
            running.now += 1
            running.most = max(running.most, running.now)
            await asyncio.sleep(0)
            running.now -= 1
            return await super().traverse_paths(source, destination, **kwargs)

    _footprints(SlowClient({"main": SEEDED}), SEEDED, circuits=True)

    assert running.most == MAX_CONCURRENT


def test_with_footprints_adds_the_footprints_to_the_query_result() -> None:
    data = stored_only(SEEDED)
    footprints = {"DI-1001": Footprint(PARIS_DEVICES)}

    merged = with_footprints(data, footprints)

    assert merged[FOOTPRINTS] == footprints
    assert {key: block for key, block in merged.items() if key != FOOTPRINTS} == {
        key: block for key, block in data.items() if key != FOOTPRINTS
    }


def test_a_search_that_stops_early_without_a_path_is_an_error() -> None:
    """Reading a stopped search as "no path" would hide a path, so the guard and the pages must not trust it."""
    data = build_seeded_q1()
    client = TraversalClient({"main": data})
    client.truncated["DI-1004"] = 2

    with pytest.raises(TraversalTruncatedError, match="DI-1004"):
        _footprints(client, data)


def test_a_search_that_stops_early_after_finding_a_path_still_counts() -> None:
    """Paths found before the search stopped are complete, so the device is in the footprint."""
    data = build_seeded_q1()

    class PartlyStopped(TraversalClient):
        async def traverse_paths(self, source: str, destination: str, **kwargs: Any) -> SimpleNamespace:  # noqa: ANN401
            found = await super().traverse_paths(source, destination, **kwargs)
            return SimpleNamespace(count=found.count, paths=found.paths, truncated_at_depth=2 if found.count else None)

    footprints = _footprints(PartlyStopped({"main": data}), data)

    assert footprints["DI-1004"] == Footprint(frozenset({"sw01-par01", "rb01-par01"}))


def test_the_circuit_router_is_the_edge_router_hop_wherever_it_is_on_the_path() -> None:
    """The router comes from the hop whose node is an edge router at the site, not from a fixed hop position."""

    class LongerPath(TraversalClient):
        async def traverse_paths(self, source: str, destination: str, **kwargs: Any) -> SimpleNamespace:  # noqa: ANN401
            found = await super().traverse_paths(source, destination, **kwargs)
            for path in found.paths:
                path.hops.insert(1, SimpleNamespace(node=SimpleNamespace(kind="DcimInterfaceL2", id="extra")))
            return found

    footprints = _footprints(LongerPath({"main": SEEDED}), SEEDED, circuits=True)

    assert footprints["DI-1001"].circuits == {"COG-PAR-TR-1001": "rb01-par01", "COLT-PAR-TR-2001": "rb02-par01"}
