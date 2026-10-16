from __future__ import annotations

import json
from itertools import starmap
from types import SimpleNamespace
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest
import yaml
from graphql import FieldNode, InlineFragmentNode, OperationDefinitionNode, SelectionSetNode, parse

from generators.implement_dedicated_internet import (
    IP_PACKAGE_TO_PREFIX_SIZE,
    SERVICE_L2_DOMAIN,
    SERVICE_PREFIX_POOL,
    SERVICE_VLAN_POOL,
    DedicatedInternetGenerator,
    existing_core_ports,
    gateway_router_index,
    natural_key,
)
from generators.protocols import DcimInterfaceL2
from infrahub_sdk import InfrahubClient
from infrahub_sdk.node import InfrahubNode

from .builders import REPO_ROOT


def make_generator(client: AsyncMock) -> DedicatedInternetGenerator:
    # `client` passed to the constructor only seeds `_init_client` (via `client.clone(...)`);
    # `allocate_*` methods use `self.client`, which InfrahubGenerator only sets inside `run()`'s
    # tracking context manager. Set it directly here to bypass that machinery in unit tests.
    generator = DedicatedInternetGenerator(query="", client=MagicMock(), infrahub_node=InfrahubNode, branch="main")
    generator.client = client
    generator.customer_service = MagicMock(
        id="service-id",
        service_identifier=MagicMock(value="test-1"),
        location=MagicMock(id="location-id"),
    )
    return generator


def test_ip_package_to_prefix_size_mapping() -> None:
    assert IP_PACKAGE_TO_PREFIX_SIZE == {"small": 29, "medium": 28, "large": 27}


async def test_allocate_vlan_creates_new_vlan_when_none_exists() -> None:
    client = AsyncMock()
    client.filters.return_value = []
    resource_pool = MagicMock()
    client.get.return_value = resource_pool
    created_vlan = MagicMock()
    created_vlan.save = AsyncMock()
    client.create.return_value = created_vlan

    generator = make_generator(client)
    await generator.allocate_vlan()

    client.create.assert_awaited_once()
    _, kwargs = client.create.call_args
    assert kwargs["kind"].__name__ == "IpamVLAN"
    assert kwargs["vlan_id"] is resource_pool
    assert kwargs["service"] is generator.customer_service
    created_vlan.save.assert_awaited_once_with()
    assert generator.allocated_vlan is created_vlan


def _client_with_vlan() -> tuple[AsyncMock, MagicMock]:
    """A client whose `filters` finds the service's existing VLAN, and that VLAN."""
    client = AsyncMock()
    existing_vlan = MagicMock()
    existing_vlan.name = MagicMock(value="vlan__test-1")
    existing_vlan.save = AsyncMock()
    client.filters.return_value = [existing_vlan]
    return client, existing_vlan


async def test_allocate_vlan_reuses_existing_vlan_and_skips_create() -> None:
    """Regression test for the HFID/upsert fix.

    `vlan_id` is pool-sourced and part of `IpamVLAN`'s human_friendly_id, so its value is
    unresolved before creation and `save(allow_upsert=True)` cannot look up the HFID
    (infrahub-sdk >= 1.10 raises a ValidationError). Re-running the generator on a service
    that already has a VLAN must reuse it via the `service__ids` filter instead of upserting.
    """
    client, existing_vlan = _client_with_vlan()

    generator = make_generator(client)
    await generator.allocate_vlan()

    client.create.assert_not_awaited()
    assert generator.allocated_vlan is existing_vlan


async def test_allocate_vlan_resaves_the_reused_vlan() -> None:
    """The reused VLAN must re-enter this run's group, or the cleanup deletes it.

    A generator run's group holds what that run produced, and Infrahub removes members a later run
    stops producing. Reading the VLAN back does not put it there, so a reuse branch that only
    returned left the VLAN out of the group and the next run's cleanup deleted it. Saving is what
    keeps it, and `allow_upsert=True` resolves here because `vlan_id` now holds a concrete value.
    """
    client, existing_vlan = _client_with_vlan()

    generator = make_generator(client)
    await generator.allocate_vlan()

    existing_vlan.save.assert_awaited_once_with(allow_upsert=True)


async def _allocate_prefix() -> tuple[AsyncMock, DedicatedInternetGenerator, MagicMock]:
    """Run `allocate_prefix` with a /29 and a pool that returns a new prefix; return the client, the generator
    and the prefix."""
    client = AsyncMock()
    client.get.return_value = MagicMock()
    allocated_prefix = MagicMock()
    allocated_prefix.save = AsyncMock()
    client.allocate_next_ip_prefix.return_value = allocated_prefix

    generator = make_generator(client)
    generator.allocated_vlan = MagicMock(id="vlan-id")
    generator.prefix_length = 29

    await generator.allocate_prefix()
    return client, generator, allocated_prefix


async def test_allocate_prefix_uses_pool_and_prefix_length() -> None:
    client, generator, allocated_prefix = await _allocate_prefix()
    resource_pool = client.get.return_value

    client.allocate_next_ip_prefix.assert_awaited_once()
    call = client.allocate_next_ip_prefix.call_args
    assert call.args[0] is resource_pool
    assert call.kwargs["prefix_length"] == 29
    assert call.kwargs["identifier"] == generator.customer_service.service_identifier.value
    allocated_prefix.save.assert_awaited_once_with(allow_upsert=True)
    assert generator.allocated_prefix is allocated_prefix


async def test_allocate_prefix_sets_relationships_via_attribute_assignment() -> None:
    """Regression test: the pool-allocation mutation's `data` input does not reliably persist
    relationship fields, only plain attributes. `service`/`vlan` must be set via attribute
    assignment on the returned node (mirroring `allocate_gateway`), not passed inside `data`."""
    client, generator, allocated_prefix = await _allocate_prefix()

    data = client.allocate_next_ip_prefix.call_args.kwargs["data"]
    assert "service" not in data
    assert "vlan" not in data
    assert allocated_prefix.service is generator.customer_service
    assert allocated_prefix.vlan is generator.allocated_vlan


def _port(name: str, port_id: str | None = None, service_id: str | None = None) -> MagicMock:
    """A switch port as `client.filters` and `client.get` return it."""
    port = MagicMock(id=port_id or name, display_label=name)
    port.name = MagicMock(value=name)
    port.service = MagicMock(id=service_id)
    port.save = AsyncMock()
    return port


def _switch(index: int | None) -> MagicMock:
    switch = MagicMock(id=f"sw0{index}")
    switch.index = MagicMock(value=index)
    return switch


def _port_client(ports_by_switch: dict[str, list[MagicMock]], switches: list[MagicMock]) -> AsyncMock:
    """A client whose site has these switches and free ports; `get` returns the port, now with the service."""
    client = AsyncMock()

    def filters(kind: type, **kwargs: object) -> list[MagicMock]:
        if kind.__name__ == "DcimDevice":
            return switches
        device_ids = kwargs["device__ids"]
        assert isinstance(device_ids, list)
        return ports_by_switch.get(device_ids[0], [])

    def get(kind: type, id: str) -> MagicMock:  # noqa: A002 - the SDK's argument name
        return _port(id, service_id="service-id")

    client.filters.side_effect = filters
    client.get.side_effect = get
    return client


def _related(peer: object | None) -> SimpleNamespace:
    """A cardinality-one relationship as the SDK gives it: the peer ID, and the peer from the client store."""
    return SimpleNamespace(id=getattr(peer, "id", None), peer=peer)


def _device(role: str, index: int) -> SimpleNamespace:
    return SimpleNamespace(id=f"{role}-{index}", role=MagicMock(value=role), index=MagicMock(value=index))


def _interface(port_id: str, role: str | None, index: int = 0) -> MagicMock:
    """An interface of the service; `role` None is a gateway interface, which the query returns without its device."""
    port = _port(port_id, port_id=port_id)
    port.device = _related(_device(role, index) if role is not None else None)
    return port


def _service(*ports: tuple[str, str | None, int], gateway: tuple[str, int] | None = None) -> SimpleNamespace:
    """The service's ports and gateway IP address, as the SDK converts them from the generator query result."""
    interfaces = list(starmap(_interface, ports))
    gateway_ip = None
    if gateway is not None:
        role, index = gateway
        gateway_ip = SimpleNamespace(id="gateway-ip", interface=_related(_interface("gateway-interface", role, index)))
    return SimpleNamespace(
        dedicated_interfaces=SimpleNamespace(peers=[_related(interface) for interface in interfaces]),
        gateway_ip_address=_related(gateway_ip),
    )


def _port_generator(client: AsyncMock, service: SimpleNamespace | None = None) -> DedicatedInternetGenerator:
    generator = make_generator(client)
    service = service or _service()
    generator.customer_service.dedicated_interfaces = service.dedicated_interfaces
    generator.customer_service.gateway_ip_address = service.gateway_ip_address
    generator.customer_service.bandwidth = MagicMock(value="100")
    generator.allocated_vlan = MagicMock(id="vlan-id")
    return generator


def test_natural_key_puts_ethernet2_before_ethernet10() -> None:
    assert sorted(["Ethernet10", "Ethernet2", "Ethernet1"], key=natural_key) == ["Ethernet1", "Ethernet2", "Ethernet10"]


async def test_a_new_service_gets_the_lowest_named_free_port_of_the_lowest_switch() -> None:
    """The choice is the same on every run: switch index 1 before 2, Ethernet2 before Ethernet10."""
    switches = [_switch(2), _switch(None), _switch(1)]
    client = _port_client(
        {"sw01": [_port("Ethernet10"), _port("Ethernet2"), _port("Ethernet3", service_id="other")]},
        switches,
    )
    generator = _port_generator(client)

    index, port = await generator.free_port()

    assert port.name.value == "Ethernet2"
    assert index == 1


async def test_a_full_switch_sends_the_service_to_the_next_switch() -> None:
    client = _port_client({"sw02": [_port("Ethernet5")]}, [_switch(1), _switch(2)])
    generator = _port_generator(client)

    index, port = await generator.free_port()

    assert (port.name.value, index) == ("Ethernet5", 2)


async def test_infrahub_filters_the_ports_by_role_and_status() -> None:
    client = _port_client({"sw01": [_port("Ethernet1")]}, [_switch(1)])
    generator = _port_generator(client)

    await generator.free_port()

    port_filters = [call.kwargs for call in client.filters.call_args_list if "device__ids" in call.kwargs]
    assert port_filters == [
        {"kind": DcimInterfaceL2, "device__ids": ["sw01"], "role__value": "customer", "status__value": "free"}
    ]


async def test_allocate_port_raises_when_no_free_port_available() -> None:
    client = _port_client({}, [_switch(1), _switch(2)])
    generator = _port_generator(client)

    with pytest.raises(RuntimeError, match="no physical port"):
        await generator.allocate_port()


async def test_allocate_port_saves_the_chosen_port_with_the_service() -> None:
    chosen = _port("Ethernet1", port_id="port-1")
    client = _port_client({"sw01": [chosen]}, [_switch(1)])
    generator = _port_generator(client)

    await generator.allocate_port()

    chosen.save.assert_awaited_once_with(allow_upsert=True, update_group_context=False)
    assert chosen.service is generator.customer_service
    assert (chosen.status.value, chosen.role.value, chosen.speed.value) == ("active", "customer", 100)


async def test_allocate_port_fails_when_another_service_took_the_port_during_the_run() -> None:
    client = _port_client({"sw01": [_port("Ethernet1", port_id="port-1")]}, [_switch(1)])
    client.get.side_effect = None
    client.get.return_value = _port("Ethernet1", port_id="port-1", service_id="other-service")
    generator = _port_generator(client)

    with pytest.raises(RuntimeError, match="allocated to another service"):
        await generator.allocate_port()


async def test_allocate_port_reuses_already_allocated_core_interface() -> None:
    """The port comes from the query result; the only read is the check that the service still has it."""
    client = _port_client({}, [])
    service = _service(("port-1", "core", 1), ("gateway-1", None, 0))
    generator = _port_generator(client, service)

    await generator.allocate_port()

    port = service.dedicated_interfaces.peers[0].peer
    assert generator.index == 1
    port.save.assert_awaited_once_with(allow_upsert=True, update_group_context=False)
    assert port.service is generator.customer_service
    assert [call.kwargs["id"] for call in client.get.call_args_list] == ["port-1"]
    assert not [call for call in client.filters.call_args_list if "device__ids" in call.kwargs]


@pytest.mark.parametrize("order", [(1, 2), (2, 1)])
@pytest.mark.parametrize(
    ("gateway", "expected_index"),
    [
        pytest.param(None, 1, id="no-gateway-ip-takes-lowest-index"),
        pytest.param(("edge", 1), 1, id="gateway-on-rb01"),
        pytest.param(("edge", 2), 2, id="gateway-on-rb02"),
        pytest.param(("core", 2), 1, id="address-on-a-switch-is-no-gateway"),
    ],
)
async def test_allocate_port_keeps_the_first_path_when_the_service_has_a_port_on_both_switches(
    order: tuple[int, int], gateway: tuple[str, int] | None, expected_index: int
) -> None:
    """A service with active ports on sw01-par01 and sw02-par01 keeps its first path on a re-run.

    The seed adds a second path to some Gold services. The first path is the one whose edge router holds
    the gateway IP (DI-1003 has it on rb02-par01); without a gateway IP the port on the lowest switch
    index is taken. The order in which Infrahub returns the ports does not change the choice.
    """
    client = _port_client({}, [])
    ports = [(f"port-{index}", "core", index) for index in order]
    generator = _port_generator(client, _service(*ports, gateway=gateway))

    await generator.allocate_port()

    assert generator.index == expected_index
    assert client.get.call_args_list[0].kwargs["id"] == f"port-{expected_index}"


def test_existing_core_ports_and_gateway_index_come_from_the_query_result() -> None:
    """Only ports on a core switch count; a gateway interface, which has no device in the query, is skipped."""
    service = _service(("port-2", "core", 2), ("edge-port", "edge", 2), ("gateway", None, 0), gateway=("edge", 2))

    assert {index: port.id for index, port in existing_core_ports(service).items()} == {2: "port-2"}
    assert gateway_router_index(service) == 2
    assert gateway_router_index(_service()) is None
    assert gateway_router_index(_service(gateway=("core", 1))) is None


def _missing_id_or_typename(selection_set: SelectionSetNode, path: str, in_fragment: bool = False) -> list[str]:
    """The paths of the `node` selections in the query that lack `id` or `__typename`.

    The check looks at the fields next to the inline fragments, not inside them, so it holds for every kind.
    """
    missing: list[str] = []
    fields = [item for item in selection_set.selections if isinstance(item, FieldNode)]
    fragments = [item for item in selection_set.selections if isinstance(item, InlineFragmentNode)]
    if path.endswith(".node") and not in_fragment:
        names = {field.name.value for field in fields}
        missing.extend(f"{path}.{name}" for name in ("id", "__typename") if name not in names)
    for field in fields:
        if field.selection_set is not None:
            missing.extend(_missing_id_or_typename(field.selection_set, f"{path}.{field.name.value}"))
    for fragment in fragments:
        missing.extend(_missing_id_or_typename(fragment.selection_set, path, in_fragment=True))
    return missing


QUERY_FILE = REPO_ROOT / "generators" / "dedicated_internet.gql"


def test_every_node_in_the_generator_query_selects_id_and_typename() -> None:
    """The SDK converts the query result into nodes and finds each peer in its store by ID and kind.

    A node without `id` is not stored, and one without `__typename` cannot be converted, so the generator
    would fail on a re-run when it reads the device of a port or the interface of the gateway IP address.
    """
    document = parse(QUERY_FILE.read_text())
    operation = document.definitions[0]

    assert _missing_id_or_typename(operation.selection_set, "query") == []  # type: ignore[attr-defined]


SCHEMA_FILE = REPO_ROOT / "tests" / "fixtures" / "schemas" / "schema01.json"


def _field(selection_set: SelectionSetNode, name: str) -> FieldNode:
    return next(item for item in selection_set.selections if isinstance(item, FieldNode) and item.name.value == name)


def _answer(node: dict[str, Any], selection_set: SelectionSetNode) -> dict[str, Any]:
    """What Infrahub answers for `node` to this part of the generator query.

    `node` holds attribute values and peers by name; a list of peers is a cardinality-many relationship.
    """
    answer: dict[str, Any] = {}
    for item in selection_set.selections:
        if isinstance(item, InlineFragmentNode):
            if item.type_condition is not None and node["__typename"] == item.type_condition.name.value:
                answer.update(_answer(node, item.selection_set))
            continue
        assert isinstance(item, FieldNode)
        name = item.name.value
        if item.selection_set is None:
            answer[name] = node[name]
        elif [field.name.value for field in item.selection_set.selections if isinstance(field, FieldNode)] == ["value"]:
            answer[name] = {"value": node.get(name)}
        elif isinstance(peers := node.get(name), list):
            peer_selection = _field(_field(item.selection_set, "edges").selection_set, "node").selection_set  # type: ignore[arg-type]
            answer[name] = {"count": len(peers), "edges": [{"node": _answer(peer, peer_selection)} for peer in peers]}  # type: ignore[arg-type]
        else:
            peer_selection = _field(item.selection_set, "node").selection_set
            answer[name] = {"node": _answer(peers, peer_selection) if peers else None}  # type: ignore[arg-type]
    return answer


def _device_node(name: str, role: str, index: int) -> dict[str, Any]:
    return {"__typename": "DcimDevice", "id": name, "name": name, "role": role, "index": index}


def _interface_node(kind: str, interface_id: str, device: dict[str, Any]) -> dict[str, Any]:
    return {
        "__typename": kind,
        "id": interface_id,
        "name": interface_id,
        "role": "customer",
        "status": "active",
        "device": device,
    }


async def _converted_service(gateway_index: int | None) -> InfrahubNode:
    """A Paris service with a port on both switches, converted by the SDK from the answer to the generator query.

    With a gateway index, the service's gateway interface is on that edge router, and the gateway IP address
    is on that interface: the gateway interface is then in the answer twice.
    """
    switches = [_device_node(f"sw0{index}-par01", "core", index) for index in (1, 2)]
    interfaces = [_interface_node("DcimInterfaceL2", f"port-{switch['index']}", switch) for switch in switches]
    gateway_ip = None
    if gateway_index is not None:
        router = _device_node(f"rb0{gateway_index}-par01", "edge", gateway_index)
        gateway = _interface_node("DcimInterfaceL3", "gateway-interface", router)
        interfaces.insert(1, gateway)
        gateway_ip = {"__typename": "IpamIPAddress", "id": "gateway-ip", "interface": gateway}
    service = {
        "__typename": "ServiceDedicatedInternet",
        "id": "service-id",
        "status": "active",
        "service_identifier": "DI-1003",
        "ip_package": "small",
        "bandwidth": "1000",
        "location": {"__typename": "LocationSite", "id": "site-id", "name": "par01"},
        "dedicated_interfaces": interfaces,
        "gateway_ip_address": gateway_ip,
    }
    operation = parse(QUERY_FILE.read_text()).definitions[0]
    assert isinstance(operation, OperationDefinitionNode)
    root = _field(operation.selection_set, "ServiceDedicatedInternet")
    service_selection = _field(_field(root.selection_set, "edges").selection_set, "node").selection_set  # type: ignore[arg-type]
    data = {"ServiceDedicatedInternet": {"edges": [{"node": _answer(service, service_selection)}]}}  # type: ignore[arg-type]

    generator = DedicatedInternetGenerator(
        query="",
        client=InfrahubClient(address="http://mock"),
        infrahub_node=InfrahubNode,
        branch="main",
        convert_query_response=True,
    )
    generator._init_client.schema.set_cache(json.loads(SCHEMA_FILE.read_text()), branch="main")  # noqa: SLF001
    await generator.process_nodes(data)
    return generator.nodes[0]


@pytest.mark.parametrize("gateway_index", [None, 1, 2])
async def test_the_converted_query_result_gives_the_ports_and_the_gateway_router(gateway_index: int | None) -> None:
    """The real query and the SDK conversion: both core ports by switch index, and the gateway's edge router.

    The gateway interface is both a dedicated interface of the service and the interface of its gateway IP
    address. The SDK store keeps one copy of it, so the query must select its device in both places, or the
    generator reads no gateway router and moves a service with two paths to the lowest switch.
    """
    service = await _converted_service(gateway_index)

    assert {index: port.id for index, port in existing_core_ports(service).items()} == {1: "port-1", 2: "port-2"}
    assert gateway_router_index(service) == gateway_index


async def test_generate_works_on_the_service_the_sdk_converted() -> None:
    """The service is the node the SDK converted from the query result; the generator sets it active."""
    client = AsyncMock()
    generator = make_generator(client)
    service = MagicMock(save=AsyncMock(), ip_package=MagicMock(value="medium"))
    generator.nodes.append(service)
    for step in ("allocate_vlan", "allocate_prefix", "allocate_port", "allocate_gateway"):
        setattr(generator, step, AsyncMock())

    await generator.generate({})

    assert generator.customer_service is service
    assert service.status.value == "active"
    service.save.assert_awaited_once_with(allow_upsert=True)
    assert generator.prefix_length == 28


async def test_release_port_from_group_removes_a_port_an_earlier_run_tracked() -> None:
    """A port saved inside the group by an earlier generator version must leave it, or the cleanup deletes it."""
    client = AsyncMock()
    group = MagicMock(save=AsyncMock())
    group.members.peer_ids = ["port-id", "vlan-id"]
    client.group_context.get_group.return_value = group
    generator = make_generator(client)

    await generator.release_port_from_group(MagicMock(id="port-id"))

    group.members.remove.assert_called_once_with("port-id")
    group.save.assert_awaited_once_with(update_group_context=False)


@pytest.mark.parametrize("group", [None, MagicMock(save=AsyncMock(), members=MagicMock(peer_ids=["vlan-id"]))])
async def test_release_port_from_group_leaves_the_group_alone_when_the_port_is_not_a_member(
    group: MagicMock | None,
) -> None:
    client = AsyncMock()
    client.group_context.get_group.return_value = group
    generator = make_generator(client)

    await generator.release_port_from_group(MagicMock(id="port-id"))

    if group is not None:
        group.members.remove.assert_not_called()
        group.save.assert_not_awaited()


@pytest.mark.parametrize("data", [{}, {"ServiceDedicatedInternet": {"edges": []}}])
async def test_generate_logs_an_error_and_stops_when_no_service_matches(
    data: dict, caplog: pytest.LogCaptureFixture
) -> None:
    """A run queued for a service that was deleted or renamed must stop with a message, not an IndexError."""
    client = AsyncMock()
    generator = make_generator(client)

    with caplog.at_level("ERROR", logger="infrahub.tasks"):
        await generator.generate(data)

    assert "No Dedicated Internet service matches this run" in caplog.text
    client.create.assert_not_awaited()


def test_the_pool_and_domain_names_exist_in_the_object_files() -> None:
    """The generator looks the pools and the layer 2 domain up by these names."""
    pools = {
        item["name"]
        for document in yaml.safe_load_all((REPO_ROOT / "data" / "05_resource_pools.yml").read_text())
        for item in document["spec"]["data"]
    }
    domains = {
        item["name"]
        for document in yaml.safe_load_all((REPO_ROOT / "data" / "03_ipam_domain.yml").read_text())
        if document["spec"]["kind"] == "IpamL2Domain"
        for item in document["spec"]["data"]
    }

    assert {SERVICE_VLAN_POOL, SERVICE_PREFIX_POOL} <= pools
    assert SERVICE_L2_DOMAIN in domains
