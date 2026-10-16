"""Unit tests for the `watch` lists in `.infrahub.yml`.

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
