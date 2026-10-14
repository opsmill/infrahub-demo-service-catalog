"""`read_circuits` runs the circuit query only when the branch's schema has the circuit endpoint kind."""

from __future__ import annotations

import asyncio
from types import SimpleNamespace
from typing import TYPE_CHECKING, Any, cast

from infrahub_sdk.exceptions import SchemaNotFoundError
from service_catalog.cost_of_service.circuits import CIRCUIT_ENDPOINT_KIND, read_circuits

if TYPE_CHECKING:
    from infrahub_sdk import InfrahubClient


class _Client:
    def __init__(self, kinds: set[str]) -> None:
        self.lookups: list[tuple[str, str]] = []
        self.queries: list[str] = []

        async def get(kind: str, branch: str) -> object:  # noqa: RUF029 - the SDK method is async
            self.lookups.append((kind, branch))
            if kind not in kinds:
                raise SchemaNotFoundError(identifier=kind)
            return object()

        self.schema = SimpleNamespace(get=get)

    async def execute_graphql(self, query: str, branch_name: str) -> dict[str, Any]:
        self.queries.append(branch_name)
        return {"DcimCircuitEndpoint": {"edges": []}}


def test_no_circuit_schema_reads_as_none_without_a_query() -> None:
    client = _Client(set())

    assert asyncio.run(read_circuits(cast("InfrahubClient", client), "main")) is None
    assert client.lookups == [(CIRCUIT_ENDPOINT_KIND, "main")]
    assert client.queries == []


def test_circuit_schema_runs_the_circuit_query_on_the_branch() -> None:
    client = _Client({CIRCUIT_ENDPOINT_KIND})

    assert asyncio.run(read_circuits(cast("InfrahubClient", client), "main")) == {"DcimCircuitEndpoint": {"edges": []}}
    assert client.queries == ["main"]
