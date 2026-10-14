"""Proposed change steps the integration tests share: wait for the Gold outage guard, then try a merge."""

from __future__ import annotations

from typing import TYPE_CHECKING

from infrahub_sdk.exceptions import GraphQLError
from infrahub_sdk.protocols import CoreProposedChange, CoreValidator
from service_catalog.business_impact import seed

if TYPE_CHECKING:
    from infrahub_sdk import InfrahubClientSync
    from infrahub_sdk.node import InfrahubNodeSync

MERGE_MUTATION = """
mutation MergeProposedChange($id: String!) {
  CoreProposedChangeMerge(data: {id: $id}, wait_until_completion: true) {
    ok
  }
}
"""


def wait_for_guard(client_sync: InfrahubClientSync, proposed_change_id: str, what: str) -> list[seed.ValidatorRow]:
    """Wait until the Gold outage guard validator of a proposed change has finished; return the validators."""
    latest: list[seed.ValidatorRow] = []

    def finished() -> bool:
        nonlocal latest
        latest = [
            seed.ValidatorRow(label=node.label.value, state=node.state.value, conclusion=node.conclusion.value)
            for node in client_sync.filters(kind=CoreValidator, proposed_change__ids=[proposed_change_id])
        ]
        return seed.validators_finished(latest, required=(seed.GUARD_VALIDATOR_LABEL,))

    seed.wait_until(finished, seed.PIPELINE_TIMEOUT_S, f"the pipeline of {what}")
    return latest


def open_change(client_sync: InfrahubClientSync, source_branch: str, name: str) -> InfrahubNodeSync:
    """Open a proposed change from `source_branch` into main and wait for its Gold outage guard."""
    proposed_change = client_sync.create(
        kind=CoreProposedChange,
        branch="main",
        name=name,
        source_branch=source_branch,
        destination_branch="main",
    )
    proposed_change.save()
    wait_for_guard(client_sync, proposed_change.id, name)
    return proposed_change


def try_merge(client_sync: InfrahubClientSync, proposed_change_id: str) -> str:
    """Send the merge mutation and say what it answered: its response, or the GraphQL error it raised."""
    try:
        response = client_sync.execute_graphql(query=MERGE_MUTATION, variables={"id": proposed_change_id})
    except GraphQLError as exc:
        return f"mutation raised GraphQLError: {exc.errors[0].get('message') if exc.errors else exc}"
    return f"mutation returned {response}"
