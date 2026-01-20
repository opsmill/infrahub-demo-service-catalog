from fast_depends import Provider

from infrahub_sdk import InfrahubClientSync
from service_catalog.infrahub import get_client, get_dropdown_options
from service_catalog.protocols_sync import ServiceDedicatedInternet


def test_get_dropdown_options_txt(provider: Provider, schema_01_client: InfrahubClientSync) -> None:
    def get_test_client(branch: str = "main") -> InfrahubClientSync:
        return schema_01_client

    provider.override(get_client, get_test_client)

    options: list[str] = get_dropdown_options(kind="ServiceDedicatedInternet", attribute_name="status")
    assert options == [
        "in-delivery",
        "in-decomissioning",
        "draft",
        "decomissioned",
        "active",
    ]


def test_get_dropdown_options_protocols(provider: Provider, schema_01_client: InfrahubClientSync) -> None:
    def get_test_client(branch: str = "main") -> InfrahubClientSync:
        return schema_01_client

    provider.override(get_client, get_test_client)

    options: list[str] = get_dropdown_options(kind=ServiceDedicatedInternet, attribute_name="status")
    assert options == [
        "in-delivery",
        "in-decomissioning",
        "draft",
        "decomissioned",
        "active",
    ]
