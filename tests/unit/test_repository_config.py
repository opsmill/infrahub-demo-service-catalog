"""Unit tests for `.infrahub.yml`: the `watch` lists and the optional DNS add-on.

Infrahub reads only a Python transform's or generator's own file to find what
it depends on. The `watch` list names the other repository files, so the
artifact is generated again when one of them changes and not on every commit.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from .builders import REPO_ROOT

if TYPE_CHECKING:
    from infrahub_sdk.schema.repository import InfrahubRepositoryConfig


def test_every_watched_file_exists(repository_config: InfrahubRepositoryConfig) -> None:
    """Each Python transform and generator declares `watch`, and every file it names exists."""
    for item in [*repository_config.python_transforms, *repository_config.generator_definitions]:
        assert item.watch is not None, item.name
        for path in item.watch.files:
            assert (REPO_ROOT / path).is_file(), (item.name, path)


def test_cost_of_service_watches_the_circuit_query_it_reads_from_disk(
    repository_config: InfrahubRepositoryConfig,
) -> None:
    transforms = {item.name: item for item in repository_config.python_transforms}

    watch = transforms["cost_of_service"].watch
    assert watch is not None
    assert "service_catalog/queries/cost_of_service_circuits.gql" in watch.files


def test_each_transform_that_traces_service_paths_watches_the_footprint_module(
    repository_config: InfrahubRepositoryConfig,
) -> None:
    """The three transforms import the footprint module, and it imports the generated protocols."""
    transforms = {item.name: item for item in repository_config.python_transforms}

    for name in ("affected_customers", "outreach_payload", "cost_of_service"):
        watch = transforms[name].watch
        assert watch is not None
        assert "service_catalog/business_impact/footprint.py" in watch.files, name
        assert "service_catalog/protocols_async.py" in watch.files, name


def test_the_dns_add_on_is_not_loaded_with_the_repository(repository_config: InfrahubRepositoryConfig) -> None:
    """`invoke seed-dns` loads the DNS schema, its menu file and its data. The repository import does not."""
    assert "schemas/dns" not in [path.as_posix() for path in repository_config.schemas]
    assert "menu_dns.yml" not in [path.as_posix() for path in repository_config.menus]
    assert not [path for path in repository_config.objects if path.as_posix().startswith("data/dns")]


def test_the_dns_retirement_query_is_not_a_stored_query(repository_config: InfrahubRepositoryConfig) -> None:
    """The check reads `checks/dns_retirement_guard.gql` from disk.

    Infrahub refuses a stored query that names a kind the schema does not have, so a stored DNS
    query would fail the repository import on every stack without the DNS schema.
    """
    assert "checks/dns_retirement_guard.gql" not in [query.file_path.as_posix() for query in repository_config.queries]


def test_the_dns_retirement_guard_binds_a_stored_query_that_names_no_dns_kind(
    repository_config: InfrahubRepositoryConfig,
) -> None:
    """Infrahub requires each check to bind a stored query, so the guard binds one every stack accepts."""
    queries = {query.name: query.file_path.as_posix() for query in repository_config.queries}

    assert queries["dns_retirement_guard"] == "checks/dns_retirement_guard_binding.gql"
    text = (REPO_ROOT / queries["dns_retirement_guard"]).read_text(encoding="utf-8")
    body = [line for line in text.splitlines() if not line.lstrip().startswith("#")]
    assert body
    assert not [line for line in body if "Dns" in line.replace("DnsRetirementGuard", "")]


def test_the_dns_retirement_guard_is_a_global_check(repository_config: InfrahubRepositoryConfig) -> None:
    """The DNS retirement guard runs in every proposed change, next to the unchanged Gold outage guard."""
    checks = {check.name: check for check in repository_config.check_definitions}

    guard = checks["dns_retirement_guard"]
    assert guard.file_path.as_posix() == "checks/dns_retirement_guard.py"
    assert guard.class_name == "DnsRetirementGuard"
    assert guard.targets is None
    assert checks["gold_outage_guard"].file_path.as_posix() == "checks/gold_outage_guard.py"
    assert checks["gold_outage_guard"].class_name == "GoldOutageGuard"
