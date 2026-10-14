from __future__ import annotations

import logging
import re
from typing import TYPE_CHECKING

from infrahub_sdk.generator import InfrahubGenerator
from infrahub_sdk.protocols import CoreIPPrefixPool, CoreNumberPool

if TYPE_CHECKING:
    from infrahub_sdk.node import InfrahubNode

try:
    # When imported as part of a package (e.g., within Infrahub)
    from .protocols import (
        DcimDevice,
        DcimInterfaceL2,
        DcimInterfaceL3,
        IpamIPAddress,
        IpamPrefix,
        IpamVLAN,
        ServiceDedicatedInternet,
    )
except ImportError:
    # When imported directly (e.g., in unit tests)
    from protocols import (  # type: ignore[no-redef]
        DcimDevice,
        DcimInterfaceL2,
        DcimInterfaceL3,
        IpamIPAddress,
        IpamPrefix,
        IpamVLAN,
        ServiceDedicatedInternet,
    )

ACTIVE_STATUS = "active"
FREE_STATUS = "free"
CORE_ROLE = "core"
EDGE_ROLE = "edge"
CUSTOMER_ROLE = "customer"

# The data the generator allocates from, by the names the object files give it. Renaming one of them in
# data/05_resource_pools.yml or data/03_ipam_domain.yml means changing it here too. A unit test checks
# that each name below exists in those files.
SERVICE_VLAN_POOL: str = "Customer vlan pool"
SERVICE_PREFIX_POOL: str = "Customer prefixes pool"
SERVICE_L2_DOMAIN: str = "default"

IP_PACKAGE_TO_PREFIX_SIZE: dict[str, int] = {"small": 29, "medium": 28, "large": 27}


def natural_key(name: str) -> tuple[int | str, ...]:
    """Sort key that puts Ethernet2 before Ethernet10."""
    return tuple(int(part) if part.isdigit() else part for part in re.split(r"(\d+)", name))


def _device_index(interface: InfrahubNode, role: str) -> int | None:
    """The index of the interface's device when the device has this role, or None.

    The device comes from the generator query result, which the SDK converts into SDK nodes.
    """
    if not interface.device.id:
        return None
    device = interface.device.peer
    index = device.index.value
    return int(index) if device.role.value == role and index is not None else None


def existing_core_ports(service: InfrahubNode) -> dict[int, DcimInterfaceL2]:
    """The service's port on each core switch, by switch index, from the generator query result.

    When a switch has more than one port of the service, the first one the query returns is kept.
    """
    ports: dict[int, DcimInterfaceL2] = {}
    for related in service.dedicated_interfaces.peers:
        interface = related.peer
        index = _device_index(interface, CORE_ROLE)
        if index is not None:
            ports.setdefault(index, interface)
    return ports


def gateway_router_index(service: InfrahubNode) -> int | None:
    """The index of the edge router whose interface holds the service's gateway IP address, or None."""
    if not service.gateway_ip_address.id:
        return None
    gateway_ip = service.gateway_ip_address.peer
    if not gateway_ip.interface.id:
        return None
    return _device_index(gateway_ip.interface.peer, EDGE_ROLE)


class DedicatedInternetGenerator(InfrahubGenerator):
    customer_service: ServiceDedicatedInternet
    allocated_vlan: IpamVLAN
    allocated_prefix: IpamPrefix
    gateway_ip: IpamIPAddress
    # The index of the switch that holds the service's port, which also picks the edge router of the gateway.
    index: int

    log = logging.getLogger("infrahub.tasks")

    async def generate(self, data: dict) -> None:  # noqa: ARG002 - the SDK passes `data` by name; the nodes are read
        # `convert_query_response` in .infrahub.yml makes the SDK convert the query result into nodes:
        # the service in `self.nodes`, and its ports, devices and gateway IP address in the client store.
        if not self.nodes:
            self.log.error("No Dedicated Internet service matches this run; nothing to provision.")
            return
        self.customer_service = self.nodes[0]

        # Move the service as active
        # TODO: Not happy with having this one here...
        self.customer_service.status.value = ACTIVE_STATUS
        await self.customer_service.save(allow_upsert=True)

        # Allocate the VLAN to the service
        await self.allocate_vlan()

        # Translate teeshirt size to int
        self.prefix_length: int = IP_PACKAGE_TO_PREFIX_SIZE[self.customer_service.ip_package.value]

        # Allocate the prefix to the service
        await self.allocate_prefix()

        # Allocate port
        await self.allocate_port()

        # Create L3 interface for gateway
        await self.allocate_gateway()

    async def allocate_vlan(self) -> None:
        """Create a VLAN with ID coming from the pool provided and assign this VLAN to the service."""
        self.log.info("Allocating VLAN to this service...")

        # Identity here is "one VLAN per service", not the VLAN's human-friendly identifier.
        # `vlan_id` is allocated from a CoreNumberPool and is part of the HFID, so it has no
        # concrete value until creation; `allow_upsert=True` therefore cannot resolve the HFID
        # (infrahub-sdk >= 1.10 raises a ValidationError). Reuse the existing VLAN on re-runs and
        # create with a plain save otherwise. See opsmill/infrahub-sdk-python#339 and #396.
        existing_vlans = await self.client.filters(
            kind=IpamVLAN,
            service__ids=[self.customer_service.id],
        )
        if existing_vlans:
            self.allocated_vlan = existing_vlans[0]
            # Saved, not just returned: a generator run's group holds what that run saved, and Infrahub
            # deletes the members a later run does not save, so a VLAN only read back would be deleted.
            #
            # `allow_upsert=True` is safe here, unlike at creation: `vlan_id` is part of the HFID and
            # now holds the concrete value the pool allocated, so the HFID resolves.
            await self.allocated_vlan.save(allow_upsert=True)
            self.log.info(f"VLAN `{self.allocated_vlan.name.value}` already allocated to this service; reusing.")
            return

        # Get resource pool
        resource_pool = await self.client.get(
            kind=CoreNumberPool,
            name__value=SERVICE_VLAN_POOL,
        )

        # Craft and save the vlan
        self.allocated_vlan = await self.client.create(
            kind=IpamVLAN,
            name=f"vlan__{self.customer_service.service_identifier.value}",
            vlan_id=resource_pool,  # Here we get the vlan ID from the pool
            description=f"VLAN allocated to service {self.customer_service.service_identifier.value}",
            status=ACTIVE_STATUS,
            role=CUSTOMER_ROLE,
            l2domain=[SERVICE_L2_DOMAIN],
            service=self.customer_service,
            location=[self.customer_service.location.id],
        )

        # Plain create (not an upsert): the pool allocates a concrete vlan_id at creation time, and
        # idempotency on re-runs is handled by the lookup above.
        await self.allocated_vlan.save()

        self.log.info(f"VLAN `{self.allocated_vlan.name.value}` assigned!")

    async def allocate_prefix(self) -> None:
        """Allocate a prefix coming from a resource pool to the service."""
        self.log.info("Allocating prefix from pool...")

        # Get resource pool
        resource_pool = await self.client.get(
            kind=CoreIPPrefixPool,
            name__value=SERVICE_PREFIX_POOL,
        )

        # Craft the data dict for prefix. Relationship fields (`service`, `vlan`) are set below via
        # attribute assignment instead: the pool-allocation mutation's `data` input does not reliably
        # persist relationships, only plain attributes.
        prefix_data: dict = {
            "status": ACTIVE_STATUS,
            "description": f"Prefix allocated to service {self.customer_service.service_identifier.value}",
            "role": CUSTOMER_ROLE,
        }

        # Create resource from the pool
        self.allocated_prefix = await self.client.allocate_next_ip_prefix(
            resource_pool,
            kind=IpamPrefix,
            data=prefix_data,
            prefix_length=self.prefix_length,
            identifier=self.customer_service.service_identifier.value,
        )

        # Set the relationships explicitly; see comment above.
        self.allocated_prefix.service = self.customer_service
        self.allocated_prefix.vlan = self.allocated_vlan

        self.log.info(f"Prefix `{self.allocated_prefix}` assigned!")

        await self.allocated_prefix.save(allow_upsert=True)

    async def allocate_port(self) -> None:
        """Allocate a port to the service: the port it already has, or the first free port at its site."""
        self.log.info("Allocating port to this service...")

        core_ports = existing_core_ports(self.customer_service)
        allocated_port: DcimInterfaceL2
        if core_ports:
            # A service can have a port on each switch (a second path). A re-run keeps the first path:
            # the switch with the index of the edge router that holds the gateway IP, else the lowest index.
            gateway_index = gateway_router_index(self.customer_service) if len(core_ports) > 1 else None
            self.index = gateway_index if gateway_index in core_ports else min(core_ports)
            allocated_port = core_ports[self.index]
            self.log.info(f"Port `{allocated_port.display_label}` already allocated to the service.")
        else:
            self.log.info("Haven't found any port allocated to this service.")
            self.index, allocated_port = await self.free_port()
            self.log.info(f"Found port {allocated_port.display_label} to allocate to the service.")

        # Enforce all params of this interface
        allocated_port.enabled.value = True
        allocated_port.status.value = ACTIVE_STATUS
        allocated_port.l2_mode.value = "Access"
        allocated_port.role.value = CUSTOMER_ROLE
        allocated_port.description.value = f"Port allocated to service {self.customer_service.service_identifier.value}"
        allocated_port.speed.value = int(self.customer_service.bandwidth.value)
        allocated_port.service = self.customer_service
        allocated_port.untagged_vlan = self.allocated_vlan

        # Finally save. The port belongs to the switch, not to this generator: keep it out of the
        # tracking group, or a later run where the service uses another port would delete it.
        await allocated_port.save(allow_upsert=True, update_group_context=False)
        await self.release_port_from_group(allocated_port)
        await self.check_port_kept(allocated_port.id)

    async def free_port(self) -> tuple[int, DcimInterfaceL2]:
        """The first free customer port at the service's site, with its switch index: lowest switch index first,
        then lowest port name.

        Infrahub filters the ports by role and status, so a port another service already took is not offered.
        """
        switches = await self.client.filters(
            kind=DcimDevice, location__ids=[self.customer_service.location.id], role__value=CORE_ROLE
        )
        indexed = sorted((int(switch.index.value), switch) for switch in switches if switch.index.value is not None)
        for index, switch in indexed:
            ports = await self.client.filters(
                kind=DcimInterfaceL2, device__ids=[switch.id], role__value=CUSTOMER_ROLE, status__value=FREE_STATUS
            )
            free: list[DcimInterfaceL2] = [port for port in ports if port.service.id is None]
            if free:
                chosen: DcimInterfaceL2 = min(free, key=lambda port: natural_key(str(port.name.value)))
                return index, chosen

        identifier = self.customer_service.service_identifier.value
        msg = f"There is no physical port to allocate to customer on the core switches of the site of {identifier}"
        self.log.error(msg)
        raise RuntimeError(msg)

    async def check_port_kept(self, port_id: str) -> None:
        """Fail the run when another service took the port between the choice and the save.

        Two generator runs on the same branch can pick the same free port, and the last save wins. Reading
        the port back makes the run that lost fail with a message, instead of passing with a port it does
        not have; running the generator again picks another port. Runs on separate branches, as the portal
        creates them, do not see each other's ports: Infrahub shows two changes to the same port as a
        conflict in the proposed change of the second one.
        """
        port = await self.client.get(kind=DcimInterfaceL2, id=port_id)
        if port.service.id != self.customer_service.id:
            msg = (
                f"Port {port.display_label} was allocated to another service during this run. Run the generator again."
            )
            self.log.error(msg)
            raise RuntimeError(msg)

    async def release_port_from_group(self, port: InfrahubNode) -> None:
        """Take the port out of this generator's tracking group if an earlier run put it there.

        Earlier versions of this generator saved the port inside the group. At the end of the run the SDK
        deletes every member the run did not save, so it would delete the switch port of an existing service.
        """
        group = await self.client.group_context.get_group()
        if group is None or port.id not in group.members.peer_ids:
            return
        self.log.info(f"Removing port {port.display_label} from the generator group {group.display_label}")
        group.members.remove(port.id)
        await group.save(update_group_context=False)

    async def allocate_gateway(self) -> None:
        """Allocate a gateway to the service."""
        self.log.info("Allocating gateway to this service...")

        # Find the corresponding router
        router = await self.client.get(
            kind=DcimDevice,
            location__ids=[self.customer_service.location.id],
            role__value=EDGE_ROLE,
            index__value=self.index,
        )

        # Create interface
        gateway_interface = await self.client.create(
            kind=DcimInterfaceL3,
            name=f"vlan_{self.allocated_vlan.vlan_id.value}",
            speed=1000,
            device=router,
            status=ACTIVE_STATUS,
            role=CUSTOMER_ROLE,
            description=f"Gateway interface for service {self.customer_service.service_identifier.value}",
            enabled=True,
            service=self.customer_service,
        )
        await gateway_interface.save(allow_upsert=True)

        # Compute the gateway ip
        address: str = f"{next(self.allocated_prefix.prefix.value.hosts())!s}/{self.prefix_length!s}"

        # Create the IP object. Its `service` relationship is the service's `gateway_ip_address`: the
        # authoritative link from a service to its gateway. The prefix's `gateway` below points to the same
        # IP address for IPAM views; the generator sets both from the same node on each run.
        self.gateway_ip = await self.client.create(
            kind=IpamIPAddress,
            address=address,
            service=self.customer_service,
            interface=gateway_interface,
        )
        await self.gateway_ip.save(allow_upsert=True)

        self.log.info(f"Gateway `{self.gateway_ip.address.value}` assigned!")

        # Add gateway to prefix
        self.allocated_prefix.gateway = self.gateway_ip

        # Save prefix
        await self.allocated_prefix.save(allow_upsert=True)
