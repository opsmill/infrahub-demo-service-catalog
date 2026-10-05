import json
from typing import Any

import httpx
import pytest
from fast_depends import Provider
from pytest_httpx import HTTPXMock

from infrahub_sdk import InfrahubClientSync
from service_catalog.infrahub import get_client, get_dropdown_options, run_query
from service_catalog.protocols_sync import ServiceDedicatedInternet


def test_get_dropdown_options_txt(provider: Provider, schema_01_client: InfrahubClientSync) -> None:
    def get_test_client(branch: str = "main") -> InfrahubClientSync:
        return schema_01_client

    provider.override(get_client, get_test_client)

    options: list[str] = get_dropdown_options(kind="ServiceDedicatedInternet", attribute_name="status")
    assert options == [
        "in-delivery",
        "in-decommissioning",
        "draft",
        "decommissioned",
        "active",
    ]


def test_get_dropdown_options_protocols(provider: Provider, schema_01_client: InfrahubClientSync) -> None:
    def get_test_client(branch: str = "main") -> InfrahubClientSync:
        return schema_01_client

    provider.override(get_client, get_test_client)

    options: list[str] = get_dropdown_options(kind=ServiceDedicatedInternet, attribute_name="status")
    assert options == [
        "in-delivery",
        "in-decommissioning",
        "draft",
        "decommissioned",
        "active",
    ]


def _override_client(provider: Provider, client: InfrahubClientSync) -> None:
    def get_test_client(branch: str = "main") -> InfrahubClientSync:
        return client

    provider.override(get_client, get_test_client)


def _query_url(httpx_mock: HTTPXMock) -> httpx.URL:
    requests = httpx_mock.get_requests()
    assert len(requests) == 1
    return requests[0].url


def test_run_query_returns_data(provider: Provider, client: InfrahubClientSync, httpx_mock: HTTPXMock) -> None:
    _override_client(provider, client)
    httpx_mock.add_response(
        method="POST",
        json={"data": {"ServiceDedicatedInternet": {"count": 3}}},
    )

    data: dict[str, Any] = run_query(name="business_impact_services", variables={"x": 1}, branch="maintenance-par01")

    assert data == {"ServiceDedicatedInternet": {"count": 3}}
    url = _query_url(httpx_mock)
    assert url.path == "/api/query/business_impact_services"
    assert url.params["branch"] == "maintenance-par01"
    assert url.params["update_group"] == "false"
    assert json.loads(httpx_mock.get_requests()[0].content) == {"variables": {"x": 1}}


def test_run_query_raises_on_errors(provider: Provider, client: InfrahubClientSync, httpx_mock: HTTPXMock) -> None:
    _override_client(provider, client)
    httpx_mock.add_response(
        method="POST",
        json={"data": None, "errors": [{"message": "Cannot query field 'foo'"}]},
    )

    with pytest.raises(RuntimeError, match="Cannot query field 'foo'"):
        run_query(name="business_impact_services")

    url = _query_url(httpx_mock)
    assert url.params["branch"] == "main"
    assert url.params["update_group"] == "false"
