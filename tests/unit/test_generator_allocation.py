from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from generators.implement_dedicated_internet import IP_PACKAGE_TO_PREFIX_SIZE, DedicatedInternetGenerator
from infrahub_sdk.node import InfrahubNode


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


async def test_allocate_vlan_reuses_existing_vlan_and_skips_create() -> None:
    """Regression test for the HFID/upsert fix.

    `vlan_id` is pool-sourced and part of `IpamVLAN`'s human_friendly_id, so its value is
    unresolved before creation and `save(allow_upsert=True)` cannot look up the HFID
    (infrahub-sdk >= 1.10 raises a ValidationError). Re-running the generator on a service
    that already has a VLAN must reuse it via the `service__ids` filter instead of upserting.
    """
    client = AsyncMock()
    existing_vlan = MagicMock()
    existing_vlan.name = MagicMock(value="vlan__test-1")
    existing_vlan.save = AsyncMock()
    client.filters.return_value = [existing_vlan]

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
    client = AsyncMock()
    existing_vlan = MagicMock()
    existing_vlan.name = MagicMock(value="vlan__test-1")
    existing_vlan.save = AsyncMock()
    client.filters.return_value = [existing_vlan]

    generator = make_generator(client)
    await generator.allocate_vlan()

    existing_vlan.save.assert_awaited_once_with(allow_upsert=True)


async def test_allocate_prefix_uses_pool_and_prefix_length() -> None:
    client = AsyncMock()
    resource_pool = MagicMock()
    client.get.return_value = resource_pool
    allocated_prefix = MagicMock()
    allocated_prefix.save = AsyncMock()
    client.allocate_next_ip_prefix.return_value = allocated_prefix

    generator = make_generator(client)
    generator.allocated_vlan = MagicMock(id="vlan-id")
    generator.prefix_length = 29

    await generator.allocate_prefix()

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
    client = AsyncMock()
    client.get.return_value = MagicMock()
    allocated_prefix = MagicMock()
    allocated_prefix.save = AsyncMock()
    client.allocate_next_ip_prefix.return_value = allocated_prefix

    generator = make_generator(client)
    generator.allocated_vlan = MagicMock(id="vlan-id")
    generator.prefix_length = 29

    await generator.allocate_prefix()

    data = client.allocate_next_ip_prefix.call_args.kwargs["data"]
    assert "service" not in data
    assert "vlan" not in data
    assert allocated_prefix.service is generator.customer_service
    assert allocated_prefix.vlan is generator.allocated_vlan


async def test_allocate_port_raises_when_no_free_port_available() -> None:
    client = AsyncMock()
    generator = make_generator(client)
    generator.customer_service.dedicated_interfaces = MagicMock()
    generator.customer_service.dedicated_interfaces.fetch = AsyncMock()
    generator.customer_service.dedicated_interfaces.peers = []

    switch = MagicMock()
    switch.interfaces = MagicMock()
    switch.interfaces.fetch = AsyncMock()
    switch.interfaces.peers = []
    client.get.return_value = switch

    with pytest.raises(RuntimeError, match="no physical port"):
        await generator.allocate_port()


async def test_allocate_port_reuses_already_allocated_core_interface() -> None:
    generator = make_generator(AsyncMock())
    generator.customer_service.dedicated_interfaces = MagicMock()
    generator.customer_service.dedicated_interfaces.fetch = AsyncMock()

    core_device = MagicMock(role=MagicMock(value="core"), index=MagicMock(value=1))
    interface_peer = MagicMock()
    interface_peer.device = MagicMock(fetch=AsyncMock(), peer=core_device)
    interface_peer.save = AsyncMock()
    existing_interface = MagicMock(peer=interface_peer)
    generator.customer_service.dedicated_interfaces.peers = [existing_interface]
    generator.customer_service.bandwidth = MagicMock(value="100")
    generator.allocated_vlan = MagicMock(id="vlan-id")

    await generator.allocate_port()

    interface_peer.save.assert_awaited_once_with(allow_upsert=True)
    assert generator.index == 1
