import json
from types import SimpleNamespace
from typing import Any, cast

import httpx
import pytest
from fast_depends import Provider
from pytest_httpx import HTTPXMock

from infrahub_sdk import InfrahubClientSync
from infrahub_sdk.protocols import CoreArtifactDefinition
from service_catalog.infrahub import (
    ARTIFACT_ERROR,
    ARTIFACT_READY,
    Generation,
    StoredArtifact,
    generate_artifact,
    get_client,
    get_dropdown_label_mapping,
    read_artifact,
    read_stored_artifact,
    run_query,
)
from service_catalog.network import QueryError
from service_catalog.protocols_sync import ServiceDedicatedInternet

STATUS_CHOICES = ["in-delivery", "in-decommissioning", "draft", "decommissioned", "active"]


def _override_client(provider: Provider, client: InfrahubClientSync) -> None:
    def get_test_client(branch: str = "main") -> InfrahubClientSync:
        return client

    provider.override(get_client, get_test_client)


@pytest.mark.parametrize("kind", ["ServiceDedicatedInternet", ServiceDedicatedInternet])
def test_get_dropdown_label_mapping_lists_the_choices_in_schema_order(
    provider: Provider, schema_01_client: InfrahubClientSync, kind: str | type[ServiceDedicatedInternet]
) -> None:
    _override_client(provider, schema_01_client)

    mapping: dict[str, str] = get_dropdown_label_mapping(kind=kind, attribute_name="status")

    assert list(mapping) == STATUS_CHOICES
    assert all(isinstance(label, str) and label for label in mapping.values())


def test_get_dropdown_label_mapping_raises_for_an_unknown_attribute(
    provider: Provider, schema_01_client: InfrahubClientSync
) -> None:
    _override_client(provider, schema_01_client)

    with pytest.raises(ValueError, match="no_such_attribute"):
        get_dropdown_label_mapping(kind="ServiceDedicatedInternet", attribute_name="no_such_attribute")


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

    with pytest.raises(QueryError, match="query `business_impact_services` on branch `main`: Cannot query field 'foo'"):
        run_query(name="business_impact_services")

    url = _query_url(httpx_mock)
    assert url.params["branch"] == "main"
    assert url.params["update_group"] == "false"


def _artifact_client(*artifacts: tuple[str, str | None]) -> InfrahubClientSync:
    """A client whose artifacts have these (status, storage id) pairs; the object store returns `content-<id>`."""
    nodes = [
        SimpleNamespace(status=SimpleNamespace(value=status), storage_id=SimpleNamespace(value=storage_id))
        for status, storage_id in artifacts
    ]
    client = SimpleNamespace(
        filters=lambda **_: nodes,
        object_store=SimpleNamespace(get=lambda identifier: f"content-{identifier}"),
    )
    return cast("InfrahubClientSync", client)


def test_a_ready_artifact_has_its_content() -> None:
    client = _artifact_client((ARTIFACT_READY, "abc"))

    assert read_stored_artifact("affected-customers", branch="maint", client=client) == StoredArtifact(
        ARTIFACT_READY, "content-abc"
    )
    assert read_artifact("affected-customers", branch="maint", client=client) == "content-abc"


@pytest.mark.parametrize("status", ["Pending", "Processing", ARTIFACT_ERROR])
def test_an_artifact_that_is_not_ready_has_no_content(status: str) -> None:
    """An artifact being generated or failed keeps the storage id of an earlier content, which is not current."""
    client = _artifact_client((status, "old"))

    stored: StoredArtifact | None = read_stored_artifact("affected-customers", branch="maint", client=client)

    assert stored == StoredArtifact(status)
    assert stored is not None
    assert stored.failed is (status == ARTIFACT_ERROR)
    assert read_artifact("affected-customers", branch="maint", client=client) is None


def test_no_artifact_reads_as_none() -> None:
    client = _artifact_client()

    assert read_stored_artifact("affected-customers", branch="maint", client=client) is None
    assert read_artifact("affected-customers", branch="maint", client=client) is None


class _GenerationClient:
    """A client with one artifact definition and an artifact whose (status, checksum) changes on each read.

    The first read is the one before the request; each later read takes the next state, then keeps the last.
    """

    address = "http://infrahub"

    def __init__(self, *states: tuple[str, str]) -> None:
        self.states = list(states)
        self.posts: list[str] = []

    def filters(self, kind: type, **_: Any) -> list[SimpleNamespace]:  # noqa: ANN401
        if kind is CoreArtifactDefinition:
            return [SimpleNamespace(id="def-1")]
        status, checksum = self.states.pop(0) if len(self.states) > 1 else self.states[0]
        return [
            SimpleNamespace(
                status=SimpleNamespace(value=status),
                checksum=SimpleNamespace(value=checksum),
                storage_id=SimpleNamespace(value=f"store-{checksum}"),
            )
        ]

    def _post(self, url: str, payload: dict) -> httpx.Response:
        self.posts.append(url)
        return httpx.Response(200, request=httpx.Request("POST", url))


def _generate(client: _GenerationClient) -> Generation:
    outcome: Generation = generate_artifact(
        "cost-of-service", branch="maint-1", timeout_s=1, poll_s=0, client=cast("InfrahubClientSync", client)
    )
    return outcome


def test_generation_waits_for_a_ready_artifact_with_new_content() -> None:
    client = _GenerationClient((ARTIFACT_READY, "old"), ("Processing", "old"), (ARTIFACT_READY, "new"))

    assert _generate(client) == Generation.READY
    # The request names the definition and the branch, and is not sent again while Infrahub is generating.
    assert client.posts == ["http://infrahub/api/artifact/generate/def-1?branch=maint-1"]


def test_generation_sends_the_request_again_when_nothing_is_in_progress() -> None:
    client = _GenerationClient((ARTIFACT_READY, "old"), (ARTIFACT_READY, "old"), (ARTIFACT_READY, "new"))

    assert _generate(client) == Generation.READY
    assert len(client.posts) == 2


def test_generation_that_ends_in_error_has_failed() -> None:
    client = _GenerationClient((ARTIFACT_READY, "old"), ("Processing", "old"), (ARTIFACT_ERROR, "old"))

    assert _generate(client) == Generation.FAILED


def test_generation_that_fails_between_two_reads_has_failed() -> None:
    """The run started and failed before the first read, so no Processing status was ever seen."""
    client = _GenerationClient((ARTIFACT_READY, "old"), (ARTIFACT_ERROR, "old"))

    assert _generate(client) == Generation.FAILED
    assert len(client.posts) == 1


def test_generation_that_stays_in_error_after_the_second_request_has_failed() -> None:
    client = _GenerationClient((ARTIFACT_ERROR, "old"))

    assert _generate(client) == Generation.FAILED
    assert len(client.posts) == 2


def test_generation_after_a_failure_with_the_same_content_is_ready() -> None:
    client = _GenerationClient((ARTIFACT_ERROR, "old"), (ARTIFACT_READY, "old"))

    assert _generate(client) == Generation.READY


def test_generation_with_the_same_content_after_processing_is_ready() -> None:
    client = _GenerationClient((ARTIFACT_READY, "old"), ("Processing", "old"), (ARTIFACT_READY, "old"))

    assert _generate(client) == Generation.READY


def test_generation_without_new_content_times_out() -> None:
    client = _GenerationClient((ARTIFACT_READY, "old"))

    assert _generate(client) == Generation.TIMEOUT
