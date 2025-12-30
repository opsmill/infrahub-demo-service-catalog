import json
from pathlib import Path
from typing import Any

import pytest
from fast_depends import Provider, dependency_provider
from pytest_httpx import HTTPXMock

from infrahub_sdk import Config, InfrahubClientSync
from infrahub_sdk.ctl.repository import get_repository_config
from infrahub_sdk.schema.repository import InfrahubRepositoryConfig
from infrahub_sdk.yaml import SchemaFile

CURRENT_DIR = Path(__file__).parent


@pytest.fixture(scope="session")
def root_dir() -> Path:
    return Path(__file__).parent / ".."


@pytest.fixture(scope="session")
def fixtures_dir() -> Path:
    return CURRENT_DIR / "fixtures"


@pytest.fixture(scope="session")
def schema_dir(root_dir: Path) -> Path:
    return root_dir / "schemas"


@pytest.fixture(scope="session")
def data_dir(root_dir: Path) -> Path:
    return root_dir / "data"


@pytest.fixture(scope="session")
def schemas_data(schema_dir: Path) -> list[dict]:
    data_files = SchemaFile.load_from_disk(paths=[schema_dir])
    return [item.content for item in data_files]


@pytest.fixture
def client() -> InfrahubClientSync:
    return InfrahubClientSync(address="http://mock")


@pytest.fixture
def provider() -> Provider:  # type: ignore[misc]
    yield dependency_provider
    dependency_provider.clear()


@pytest.fixture(scope="session")
def repository_config(root_dir: Path) -> InfrahubRepositoryConfig:
    return get_repository_config(repo_config_file=root_dir / ".infrahub.yml")


@pytest.fixture
def schema_01(fixtures_dir: Path) -> dict[str, Any]:
    response_text = (fixtures_dir / "schemas" / "schema01.json").read_text(encoding="UTF-8")
    return dict(json.loads(response_text))


@pytest.fixture
def schema_01_client(schema_01: dict[str, Any]) -> InfrahubClientSync:
    client = InfrahubClientSync(address="http://mock", config=Config(insert_tracker=True))
    client.schema.set_cache(schema_01)
    return client


@pytest.fixture
def mock_schema_query_01(fixtures_dir: Path, httpx_mock: HTTPXMock) -> HTTPXMock:
    response_text = (fixtures_dir / "schemas" / "schema01.json").read_text(encoding="UTF-8")

    httpx_mock.add_response(
        method="GET",
        url="http://mock/api/schema?branch=main",
        json=json.loads(response_text),
        is_reusable=True,
    )
    return httpx_mock
