"""The DNS retirement guard against a live Infrahub, on one stack, in order:

1. Loads the repository schema and data and imports the repository with no DNS schema. The import
   succeeds and registers the `dns_retirement_guard` check definition, bound to its stored query.
2. A proposed change on a branch without the DNS schema: the check passes with no message.
3. Loads `schemas/dns` and `data/dns` on main, as `invoke seed-dns` does. A proposed change that marks
   `portal.example.net A` for retirement fails the check, and its message names the application
   "Customer portal" and the team "Web Platform".
4. A proposed change that marks `intranet.example.net A` for retirement passes the check: only a
   retired application uses that record.

The stack runs the stock Infrahub image, so step 3 also shows that the task worker reads the DNS query
next to the check file in the repository.

Marked `extended`: each proposed change pipeline takes about a minute.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest

from infrahub_sdk.protocols import CoreCheckDefinition, CoreProposedChange, CoreStandardCheck, CoreValidator
from infrahub_sdk.spec.object import ObjectFile
from infrahub_sdk.testing.docker import TestInfrahubDockerClient
from infrahub_sdk.testing.repository import GitRepo
from infrahub_sdk.yaml import SchemaFile
from service_catalog.business_impact import seed
from service_catalog.protocols_sync import DcimDevice, DnsRecord

from .proposed_changes import open_change

if TYPE_CHECKING:
    from pathlib import Path

    from infrahub_sdk.client import InfrahubClient, InfrahubClientSync

pytestmark = pytest.mark.extended

CHECK_NAME = "dns_retirement_guard"
VALIDATOR_LABEL = f"Check: {CHECK_NAME}"
SDK_PASS_MESSAGE = "Check succesfully completed"
NO_DNS = "dns-guard-no-schema"
RETIRE_PORTAL = "retire-portal-a"
RETIRE_INTRANET = "retire-intranet-a"


def _mark_for_retirement(client_sync: InfrahubClientSync, branch: str, name: str) -> None:
    """Create `branch` and set the A record `name.example.net` to `retiring` on it."""
    client_sync.branch.create(branch_name=branch, sync_with_git=False, description=f"Retire {name} A")
    record = client_sync.get(kind=DnsRecord, name__value=name, record_type__value="A", branch=branch)
    record.status.value = "retiring"
    record.save()


def _dns_guard(client_sync: InfrahubClientSync, name: str) -> tuple[str | None, list[str]]:
    """Conclusion of the DNS retirement guard validator on a proposed change, and its check messages.

    The check breaks each message into short lines, so the line breaks become spaces here.
    """
    proposed_change = client_sync.get(kind=CoreProposedChange, name__value=name)
    validators = client_sync.filters(kind=CoreValidator, proposed_change__ids=[proposed_change.id])
    guard = [validator for validator in validators if validator.label.value == VALIDATOR_LABEL]
    assert len(guard) == 1, f"{name}: validators {[validator.label.value for validator in validators]}"
    checks = client_sync.filters(kind=CoreStandardCheck, validator__ids=[guard[0].id])
    messages = [str(check.message.value or "").replace("\n", " ") for check in checks]
    return guard[0].conclusion.value, messages


def _own_messages(messages: list[str]) -> list[str]:
    """The messages except the SDK's line on a passing check.

    Infrahub stores each log entry as a block with its "Message:" and "Level:" lines.
    """
    return [message for message in messages if SDK_PASS_MESSAGE not in message]


class TestDnsRetirementGuard(TestInfrahubDockerClient):
    @pytest.fixture(scope="class")
    def default_branch(self) -> str:
        return "main"

    def test_schema_load(
        self, client_sync: InfrahubClientSync, repository_schemas: list[SchemaFile], default_branch: str
    ) -> None:
        client_sync.schema.load(schemas=[item.content for item in repository_schemas])
        client_sync.schema.wait_until_converged(branch=default_branch)

        assert "DnsRecord" not in client_sync.schema.all(branch=default_branch, refresh=True)

    async def test_data_load(
        self, client: InfrahubClient, repository_object_files: list[ObjectFile], default_branch: str
    ) -> None:
        await client.schema.all()
        for idx, file in enumerate(repository_object_files):
            file.validate_content()
            schema = await client.schema.get(kind=file.spec.kind, branch=default_branch)
            for item in file.spec.data:
                await file.spec.create_node(
                    client=client, position=[idx], schema=schema, data=item, branch=default_branch
                )

    async def test_add_repository(self, client: InfrahubClient, root_dir: Path, remote_repos_dir: Path) -> None:
        """The import succeeds on a stack without the DNS schema."""
        repo = GitRepo(name="infrahub-demo-service-catalog", src_directory=root_dir, dst_directory=remote_repos_dir)
        await repo.add_to_infrahub(client=client)
        assert await repo.wait_for_sync_to_complete(client=client, retries=24)

    def test_check_definition_imported(self, client_sync: InfrahubClientSync) -> None:
        """The import registers the check, bound to the stored query that names no DNS kind."""
        names = sorted(str(definition.name.value) for definition in client_sync.all(kind=CoreCheckDefinition))
        assert CHECK_NAME in names
        assert "gold_outage_guard" in names

        guard = client_sync.get(kind=CoreCheckDefinition, name__value=CHECK_NAME, prefetch_relationships=True)
        assert guard.query.peer.name.value == CHECK_NAME

    def test_check_passes_without_the_dns_schema(self, client_sync: InfrahubClientSync) -> None:
        """A proposed change on a branch without the DNS schema: the check passes with no message of its own."""
        client_sync.branch.create(branch_name=NO_DNS, sync_with_git=False, description="No DNS schema")
        device = client_sync.get(kind=DcimDevice, name__value="sw01-par01", branch=NO_DNS)
        device.description.value = "Paris switch 1, relabelled"
        device.save()

        open_change(client_sync, NO_DNS, "Relabel Paris switch 1", VALIDATOR_LABEL)

        conclusion, messages = _dns_guard(client_sync, "Relabel Paris switch 1")
        assert conclusion == "success"
        assert _own_messages(messages) == []

    def test_load_the_dns_schema(self, client_sync: InfrahubClientSync, root_dir: Path) -> None:
        """Load the DNS schema on main and wait for the repository, as `invoke seed-dns` does."""
        schemas = list(SchemaFile.load_from_disk(paths=[root_dir / "schemas" / "dns"]))
        client_sync.schema.load(schemas=[item.content for item in schemas])
        client_sync.schema.wait_until_converged(branch="main")
        seed.wait_until(
            lambda: "DnsRecord" in client_sync.schema.all(branch="main", refresh=True),
            seed.REPOSITORY_TIMEOUT_S,
            "the DNS schema on main",
            seed.ARTIFACT_POLL_INTERVAL_S,
        )
        # A repository import that runs during a schema load can fail, so wait until it is in sync.
        seed.wait_for_repository_in_sync(client_sync)

    async def test_load_the_dns_records(self, client: InfrahubClient, root_dir: Path) -> None:
        """Load the DNS zone, teams, applications and records on main, as `invoke seed-dns` does."""
        await client.schema.all(branch="main", refresh=True)
        for idx, file in enumerate(ObjectFile.load_from_disk(paths=[root_dir / "data" / "dns"])):
            file.validate_content()
            schema = await client.schema.get(kind=file.spec.kind, branch="main")
            for item in file.spec.data:
                await file.spec.create_node(client=client, position=[idx], schema=schema, data=item, branch="main")

        records = await client.all(kind="DnsRecord", branch="main")
        assert len(records) == 8
        assert {str(record.status.value) for record in records} == {"active"}

    def test_check_fails_when_portal_a_is_marked_for_retirement(self, client_sync: InfrahubClientSync) -> None:
        """An active application owned by an active team still uses the record."""
        _mark_for_retirement(client_sync, RETIRE_PORTAL, "portal")

        open_change(client_sync, RETIRE_PORTAL, "Retire portal A", VALIDATOR_LABEL)

        conclusion, messages = _dns_guard(client_sync, "Retire portal A")
        text = " ".join(messages)
        assert conclusion == "failure", messages
        assert "portal.example.net (A) is marked for retirement but still serves 1 active application" in text
        assert "Customer portal" in text
        assert "Web Platform" in text
        assert "web-platform@example.net" in text
        # The active CNAME `www` points at the record.
        assert "www.example.net (CNAME) points at portal.example.net" in text

    def test_check_passes_when_intranet_a_is_marked_for_retirement(self, client_sync: InfrahubClientSync) -> None:
        """Only a retired application uses the record."""
        _mark_for_retirement(client_sync, RETIRE_INTRANET, "intranet")

        open_change(client_sync, RETIRE_INTRANET, "Retire intranet A", VALIDATOR_LABEL)

        conclusion, messages = _dns_guard(client_sync, "Retire intranet A")
        assert conclusion == "success", messages
        assert _own_messages(messages) == []
