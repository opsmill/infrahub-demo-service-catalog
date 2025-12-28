import logging
from typing import Any

from infrahub_sdk import InfrahubClient
from infrahub_sdk.node import InfrahubNode

DEVICE_TYPES = ["Generic router", "Generic switch"]
PREFIXES = ["172.16.1.0/24", "203.0.113.0/24"]


# TODO: eventually we would like to capture that in infrahub in a device template object
INTERFACE_TEMPLATES = {
    "router": [
        {
            "name": "Ethernet1",
            "speed": 1000,
            "role": "backbone",
            "description": "Connected to peer router",
            "kind": "DcimInterfaceL3",
        },
        {
            "name": "Ethernet2",
            "speed": 1000,
            "role": "backbone",
            "description": "Connected to switch 1",
            "kind": "DcimInterfaceL3",
        },
        {
            "name": "Ethernet3",
            "speed": 1000,
            "role": "backbone",
            "description": "Connected to switch 2",
            "kind": "DcimInterfaceL3",
        },
        {
            "name": "Ethernet4",
            "speed": 1000,
            "role": "upstream",
            "description": "Connected to transit",
            "kind": "DcimInterfaceL3",
        },
        {
            "name": "Ethernet5",
            "speed": 1000,
            "role": "upstream",
            "description": "Connected to transit",
            "kind": "DcimInterfaceL3",
        },
    ],
    "switch": [
        {
            "name": "Ethernet1",
            "speed": 1000,
            "role": "backbone",
            "description": "Connected to peer switch",
            "kind": "DcimInterfaceL3",
        },
        {
            "name": "Ethernet2",
            "speed": 1000,
            "role": "backbone",
            "description": "Connected to router 1",
            "kind": "DcimInterfaceL3",
        },
        {
            "name": "Ethernet3",
            "speed": 1000,
            "role": "backbone",
            "description": "Connected to router 2",
            "kind": "DcimInterfaceL3",
        },
        {
            "name": "Ethernet4",
            "speed": 1000,
            "role": "customer",
            "kind": "DcimInterfaceL2",
            "enabled": False,
            "status": "free",
        },
        {
            "name": "Ethernet5",
            "speed": 1000,
            "role": "customer",
            "kind": "DcimInterfaceL2",
            "enabled": False,
            "status": "free",
        },
        {
            "name": "Ethernet6",
            "speed": 1000,
            "role": "customer",
            "kind": "DcimInterfaceL2",
            "enabled": False,
            "status": "free",
        },
        {
            "name": "Ethernet7",
            "speed": 1000,
            "role": "customer",
            "kind": "DcimInterfaceL2",
            "enabled": False,
            "status": "free",
        },
        {
            "name": "Ethernet8",
            "speed": 1000,
            "role": "customer",
            "kind": "DcimInterfaceL2",
            "enabled": False,
            "status": "free",
        },
        {
            "name": "Ethernet9",
            "speed": 1000,
            "role": "customer",
            "kind": "DcimInterfaceL2",
            "enabled": False,
            "status": "free",
        },
    ],
}


LOCATIONS: list[dict[str, Any]] = [
    {
        "name": "France",
        "shortname": "FR",
        "timezone": "CET",
        "metros": [
            {
                "name": "Lyon",
                "shortname": "lyn",
                "sites": [
                    {
                        "name": "Lyon 1",
                        "shortname": "lyn01",
                    },
                ],
            },
            {
                "name": "Paris",
                "shortname": "par",
                "sites": [
                    {
                        "name": "Paris 1",
                        "shortname": "par01",
                    },
                ],
            },
        ],
    },
    {
        "name": "Belgium",
        "shortname": "BE",
        "timezone": "CET",
        "metros": [
            {
                "name": "Brussels",
                "shortname": "bru",
                "sites": [
                    {
                        "name": "Brussels 1",
                        "shortname": "bru01",
                    },
                ],
            },
        ],
    },
    {
        "name": "Netherlands",
        "shortname": "NL",
        "timezone": "CET",
        "metros": [
            {
                "name": "Amsterdam",
                "shortname": "ams",
                "sites": [
                    {
                        "name": "Amsterdam 1",
                        "shortname": "ams01",
                    },
                ],
            },
        ],
    },
]


async def create_org(client: InfrahubClient, log: logging.Logger, branch: str) -> None:
    manufacturer_obj = await client.create(
        kind="OrganizationManufacturer",
        name="Generic Manufacturer",
    )

    await manufacturer_obj.save(allow_upsert=True)

    for type_name in DEVICE_TYPES:
        # here we +1 to not have switch 0
        device_type_obj = await client.create(kind="DcimDeviceType", name=type_name, manufacturer=manufacturer_obj)

        await device_type_obj.save(allow_upsert=True)

    group_obj = await client.create(
        kind="CoreStandardGroup",
        name="automated_dedicated_internet",
    )
    await group_obj.save(allow_upsert=True)

    tag_obj = await client.create(
        kind="BuiltinTag",
        name="service_request",
    )
    await tag_obj.save(allow_upsert=True)


async def create_location(client: InfrahubClient, log: logging.Logger, branch: str) -> None:
    for country in LOCATIONS:
        # Create country
        country_obj = await client.create(
            kind="LocationCountry",
            name=country["name"],
            shortname=country["shortname"],
        )
        await country_obj.save(allow_upsert=True)

        for metro in country["metros"]:
            # Create metro
            metro_obj = await client.create(
                kind="LocationMetro",
                name=metro["name"],
                shortname=metro["shortname"],
                parent=country_obj,
            )
            await metro_obj.save(allow_upsert=True)

            for site in metro["sites"]:
                site_obj = await client.create(
                    kind="LocationSite",
                    name=site["name"],
                    shortname=site["shortname"],
                    parent=metro_obj,
                )
                await site_obj.save(allow_upsert=True)


async def create_prefixes(client: InfrahubClient, log: logging.Logger, branch: str) -> None:
    # Create l2 domain
    l2_domain = await client.create(
        kind="IpamL2Domain",
        name="default",
    )
    await l2_domain.save(allow_upsert=True)

    # Create public prefix
    public_prefix = await client.create(
        kind="IpamPrefix",
        status="active",
        prefix="203.0.113.0/24",
        member_type="prefix",
        role="public",
    )
    await public_prefix.save(allow_upsert=True)

    # Create management prefix
    management_prefix = await client.create(
        kind="IpamPrefix",
        status="active",
        prefix="172.16.1.0/24",
        member_type="address",
        role="management",
    )
    await management_prefix.save(allow_upsert=True)

    # Create management ip pool
    management_pool = await client.create(
        kind="CoreIPAddressPool",
        name="Management IP pool",
        default_prefix_type="IpamIPPrefix",
        default_prefix_length=24,
        default_address_type="IpamIPAddress",
        default_member_type="address",
        ip_namespace="default",
        resources=[management_prefix],
    )
    await management_pool.save(allow_upsert=True)

    customer_prefix_pool = await client.create(
        kind="CoreIPPrefixPool",
        name="Customer prefixes pool",
        default_prefix_type="IpamPrefix",
        default_prefix_length=29,
        default_member_type="address",
        ip_namespace="default",
        resources=[public_prefix],
    )
    await customer_prefix_pool.save(allow_upsert=True)

    customer_vlan_pool = await client.create(
        kind="CoreNumberPool",
        name="Customer vlan pool",
        node="IpamVLAN",
        node_attribute="vlan_id",
        start_range=1000,
        end_range=2000,
    )
    await customer_vlan_pool.save(allow_upsert=True)


async def create_interfaces(
    client: InfrahubClient, device_obj: InfrahubNode, interface_list: list[dict[str, Any]]
) -> None:
    # Prepare the batch object for interfaces
    interface_batch = await client.create_batch()

    # Loop over interface templates
    for interface_template in interface_list:
        interface_data: dict = {
            "name": interface_template["name"],
            "device": device_obj,
            "speed": interface_template["speed"],
            "status": "active",
            "role": interface_template["role"],
        }

        # If we have status defined in the template
        if "status" in interface_template:
            interface_data["status"] = interface_template["status"]

        # If we have description defined in the template
        if "description" in interface_template:
            interface_data["description"] = interface_template["description"]

        # If we have enable defined in the template
        if "enabled" in interface_template:
            interface_data["enabled"] = interface_template["enabled"]

        # Create interface
        interface_obj = await client.create(kind=interface_template["kind"], data=interface_data)

        # Add save operation to the batch
        interface_batch.add(task=interface_obj.save, node=interface_obj, allow_upsert=True)

    # Execute the batch
    async for node, _ in interface_batch.execute():
        pass  # TODO: Improve that part


async def create_devices(client: InfrahubClient, log: logging.Logger, branch: str) -> None:
    # Query related info
    site_list = await client.all("LocationSite")
    management_pool = await client.get(name__value="Management IP pool", kind="CoreIPAddressPool")

    for site in site_list:
        for i in range(1, 3):
            # Create router object
            router_obj = await client.create(
                kind="DcimDevice",
                name=f"rb0{i!s}-{site.shortname.value}",
                description="Border router.",
                status="active",
                role="edge",
                location=site,
                device_type=["Generic router"],
                primary_address=management_pool,
                index=i,
            )

            await router_obj.save(allow_upsert=True)

            # Add some interfaces to router
            await create_interfaces(client, router_obj, INTERFACE_TEMPLATES["router"])

            # Create switch object
            switch_obj = await client.create(
                kind="DcimDevice",
                name=f"sw0{i!s}-{site.shortname.value}",
                description="Core switch.",
                status="active",
                role="core",
                location=site,
                device_type=["Generic switch"],
                primary_address=management_pool,
                index=i,
            )

            await switch_obj.save(allow_upsert=True)

            await create_interfaces(client, switch_obj, INTERFACE_TEMPLATES["switch"])


async def run(client: InfrahubClient, log: logging.Logger, branch: str) -> None:
    log.info("Generate all org related data...")
    await create_org(client=client, branch=branch, log=log)

    log.info("Generate all prefixes related data...")
    await create_prefixes(client=client, branch=branch, log=log)

    log.info("Generate all location related data...")
    await create_location(client=client, branch=branch, log=log)

    log.info("Generate all device related data...")
    await create_devices(client=client, branch=branch, log=log)
