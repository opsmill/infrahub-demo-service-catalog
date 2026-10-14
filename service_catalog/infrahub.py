from __future__ import annotations

import asyncio
import os
import time
from dataclasses import dataclass
from enum import StrEnum
from typing import TYPE_CHECKING, Any, TypeVar
from urllib.parse import urlencode

import streamlit as st
from fast_depends import Depends, inject

from infrahub_sdk import Config, InfrahubClient, InfrahubClientSync
from infrahub_sdk.branch import BranchData  # noqa: TC001
from infrahub_sdk.client import SchemaTypeSync  # noqa: TC001
from infrahub_sdk.protocols import CoreArtifact, CoreArtifactDefinition
from service_catalog.network import query_data

if TYPE_CHECKING:
    from collections.abc import Awaitable, Callable

T = TypeVar("T")


def get_instance_address() -> str:
    if "infrahub_address" not in st.session_state or not st.session_state.infrahub_address:
        st.session_state.infrahub_address = os.environ.get("INFRAHUB_ADDRESS")

    if st.session_state.infrahub_address is None:
        st.exception(Exception("Can't find `INFRAHUB_ADDRESS` in variable envs..."))

    return str(st.session_state.infrahub_address)


@st.cache_resource
def get_client(branch: str = "main") -> InfrahubClientSync:
    address: str = get_instance_address()
    return InfrahubClientSync(address=address, config=Config(default_branch=branch))


@inject
def create_branch(branch_name: str, client: InfrahubClientSync = Depends(get_client)) -> BranchData:
    return client.branch.create(branch_name=branch_name, sync_with_git=False)


@inject(cast=False)  # type: ignore[arg-type]
def create_and_save(
    kind: type[SchemaTypeSync],
    data: dict[str, Any],
    branch: str = "main",
    client: InfrahubClientSync = Depends(get_client),
) -> SchemaTypeSync:
    infrahub_node = client.create(
        kind=kind,
        branch=branch,
        **data,
    )
    infrahub_node.save(allow_upsert=True)
    return infrahub_node


@inject(cast=False)  # type: ignore[arg-type]
def filter_nodes(
    kind: type[SchemaTypeSync],
    filters: dict[str, Any] | None = None,
    include: list[str] | None = None,
    branch: str = "main",
    client: InfrahubClientSync = Depends(get_client),
) -> list[SchemaTypeSync]:
    """Filter nodes by kind, branch, include and filters."""
    filters = filters or {}
    result: list[SchemaTypeSync] = client.filters(
        kind=kind,
        branch=branch,
        include=include,
        prefetch_relationships=True,
        **filters,
    )
    return result


@inject(cast=False)  # type: ignore[arg-type]
def get_dropdown_label_mapping(
    kind: str | type[SchemaTypeSync],
    attribute_name: str,
    branch: str = "main",
    client: InfrahubClientSync = Depends(get_client),
) -> dict[str, str]:
    """The choices of a dropdown attribute, in schema order: each choice name with its label.

    A choice without a label maps to its name. Raises ValueError when the kind has no such attribute.
    """
    attribute = client.schema.get(kind=kind, branch=branch).get_attribute(attribute_name)
    return {choice["name"]: choice.get("label") or choice["name"] for choice in attribute.choices or []}


@inject(cast=False)  # type: ignore[arg-type]
def run_query(
    name: str,
    variables: dict[str, Any] | None = None,
    branch: str = "main",
    client: InfrahubClientSync = Depends(get_client),
) -> dict[str, Any]:
    """Run a stored GraphQL query by name on a branch and return its `data`.

    `update_group=False` keeps the read from creating a query group in Infrahub.
    Raises QueryError, a RuntimeError, when the response body carries GraphQL errors.
    """
    body = client.query_gql_query(
        name=name,
        variables=variables or {},
        branch_name=branch,
        update_group=False,
    )
    return query_data(body, f"query `{name}` on branch `{branch}`")


# The status Infrahub gives an artifact: "Pending" and "Processing" while it renders, then "Ready" or "Error".
ARTIFACT_READY = "Ready"
ARTIFACT_ERROR = "Error"


@dataclass(frozen=True)
class StoredArtifact:
    """An artifact's status, and its content when the status is Ready."""

    status: str | None
    content: str | None = None

    @property
    def failed(self) -> bool:
        """True when Infrahub could not generate the artifact."""
        return self.status == ARTIFACT_ERROR


def _find_artifact(client: InfrahubClientSync, artifact_name: str, branch: str) -> CoreArtifact | None:
    """The `CoreArtifact` node named `artifact_name` on `branch`, or None when there is none."""
    artifacts = client.filters(kind=CoreArtifact, name__value=artifact_name, branch=branch)
    return artifacts[0] if artifacts else None


@inject(cast=False)  # type: ignore[arg-type]
def read_stored_artifact(
    artifact_name: str,
    branch: str = "main",
    client: InfrahubClientSync = Depends(get_client),
) -> StoredArtifact | None:
    """The artifact named `artifact_name` on `branch`, or None when Infrahub has no such artifact.

    Reads the `CoreArtifact` node on the branch, then, only when its status is Ready, its content from the
    object store. An artifact that is pending, processing or failed has no content, so an earlier content
    is never shown as current.
    """
    artifact = _find_artifact(client, artifact_name, branch)
    if artifact is None:
        return None
    status = artifact.status.value
    if status != ARTIFACT_READY or not artifact.storage_id.value:
        return StoredArtifact(status)
    content: str = client.object_store.get(identifier=str(artifact.storage_id.value))
    return StoredArtifact(status, content)


@inject(cast=False)  # type: ignore[arg-type]
def read_artifact(
    artifact_name: str,
    branch: str = "main",
    client: InfrahubClientSync = Depends(get_client),
) -> str | None:
    """The content of the artifact named `artifact_name` on `branch`, or None when it is not Ready."""
    stored: StoredArtifact | None = read_stored_artifact(artifact_name, branch=branch, client=client)
    return stored.content if stored is not None else None


# Artifact generation requested from a page. Infrahub queues the request and answers at once, so the
# page reads the artifact again every `GENERATE_POLL_S` seconds until it has new content.
GENERATE_TIMEOUT_S = 60
GENERATE_POLL_S = 2
# The statuses of an artifact Infrahub is still generating.
ARTIFACT_IN_PROGRESS = ("Pending", "Processing")


class Generation(StrEnum):
    """The outcome of a generation request: new content, a failed generation, or no answer in time."""

    READY = "ready"
    FAILED = "failed"
    TIMEOUT = "timeout"


def _artifact_state(client: InfrahubClientSync, artifact_name: str, branch: str) -> tuple[str | None, str | None]:
    """The status and checksum of the artifact named `artifact_name` on `branch`, or (None, None) when it has none."""
    artifact = _find_artifact(client, artifact_name, branch)
    if artifact is None:
        return None, None
    checksum = artifact.checksum.value if artifact.storage_id.value else None
    return artifact.status.value, checksum


@inject(cast=False)  # type: ignore[arg-type]
def generate_artifact(
    artifact_name: str,
    branch: str = "main",
    timeout_s: float = GENERATE_TIMEOUT_S,
    poll_s: float = GENERATE_POLL_S,
    client: InfrahubClientSync = Depends(get_client),
) -> Generation:
    """Ask Infrahub to generate the artifact named `artifact_name` on `branch`, and wait for its new content.

    Finds the artifact definition by its artifact name, sends `POST /api/artifact/generate/<definition id>`
    for `branch`, then reads the artifact until it is Ready with a checksum other than the one it had
    before the request, or Ready after a generation was seen in progress or after a status other than
    Ready. When the first read finds no generation in progress, the request is sent a second time, in
    case the first one ran before the branch was ready for it. Returns FAILED when the artifact ends in
    Error after the request: after a run seen in progress, from a status other than Error, or still in Error
    after the second request. Returns TIMEOUT when nothing changes within `timeout_s` seconds; a fast
    generation with the same content also ends there, because it looks the same as a request not yet run.
    """
    definitions = client.filters(kind=CoreArtifactDefinition, artifact_name__value=artifact_name, branch=branch)
    if not definitions:
        raise LookupError(f"No artifact definition generates `{artifact_name}` on branch `{branch}`")
    url = f"{client.address}/api/artifact/generate/{definitions[0].id}?{urlencode({'branch': branch})}"
    status_before, checksum_before = _artifact_state(client, artifact_name, branch)

    def request() -> None:
        # The SDK's `generate` method sends no branch, so the request goes through the client's POST helper.
        client._post(url=url, payload={}).raise_for_status()  # noqa: SLF001

    request()
    deadline = time.monotonic() + timeout_s
    sent_again = False
    polled_after_resend = False
    in_progress = False
    while time.monotonic() < deadline:
        time.sleep(poll_s)
        status, checksum = _artifact_state(client, artifact_name, branch)
        # A generation that ends Ready after a run Infrahub was seen doing, or after an artifact that was not
        # Ready, is done even when its content, and so its checksum, is the same as before.
        finished = checksum != checksum_before or in_progress or status_before != ARTIFACT_READY
        if status == ARTIFACT_READY and checksum is not None and finished:
            return Generation.READY
        if status in ARTIFACT_IN_PROGRESS:
            in_progress = True
        elif status == ARTIFACT_ERROR and (in_progress or status_before != ARTIFACT_ERROR or polled_after_resend):
            # A generation can fail between two reads, so Error counts even when no run was seen in progress.
            return Generation.FAILED
        elif not sent_again:
            request()
            sent_again = True
        else:
            polled_after_resend = True
    return Generation.TIMEOUT


def run_async(read: Callable[..., Awaitable[T]], *args: object) -> T:
    """`read(client, *args)` with an async Infrahub client, for code the page shares with the transforms."""

    async def run() -> T:
        return await read(InfrahubClient(address=get_instance_address()), *args)

    return asyncio.run(run())
