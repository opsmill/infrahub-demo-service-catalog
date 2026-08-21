import json
import os
from pathlib import Path
from typing import Any

import psutil
import pytest
from fast_depends import Provider, dependency_provider
from pytest_httpx import HTTPXMock

from infrahub_sdk import Config, InfrahubClientSync
from infrahub_sdk.ctl.repository import get_repository_config
from infrahub_sdk.schema.repository import InfrahubRepositoryConfig
from infrahub_sdk.yaml import SchemaFile

CURRENT_DIR = Path(__file__).parent

# ``infrahub_testcontainers`` registers a pytest plugin -- entry point
# ``pytest-infrahub-performance-test`` -- whose ``pytest_sessionstart`` builds a host profile:
# ``plugin.py:94`` -> ``performance_test.py:44 get_system_stats()`` -> ``host.py:15
# psutil.cpu_freq()``, called unguarded. On Apple Silicon that raises, killing the whole session with
# INTERNALERROR before collection -- the unit tier included, because the plugin loads whenever the
# package is installed, regardless of what is being collected. ``host.py:19-21`` already read the
# result as ``cpu_freq.current if cpu_freq else None``, so upstream meant it to be nullable and
# missed that the call itself can raise. Remove this once that is fixed upstream.
#
# Catching ``Exception`` is deliberate, not laziness. Two different failures have been observed on
# the same platform family: ``SystemError: <built-in function cpu_freq> returned a result with an
# exception set`` here, and ``RuntimeError: 'voltage-states1-sram' property not found`` in
# infrahub-solution-ai-dc. ``SystemError`` derives from ``Exception`` directly, so that repository's
# narrower clause -- ``(RuntimeError, OSError, NotImplementedError, AttributeError)`` -- does not
# catch this one. All three frequency fields are cosmetic telemetry; no reading here is worth an
# INTERNALERROR.
_original_cpu_freq = psutil.cpu_freq


def _cpu_freq_or_none(*args: object, **kwargs: object) -> Any:  # noqa: ANN401 - mirrors psutil's loose return type
    """Report CPU frequency, or ``None`` where the platform cannot.

    Args:
        *args: Passed through to ``psutil.cpu_freq``.
        **kwargs: Passed through to ``psutil.cpu_freq``.

    Returns:
        Whatever ``psutil.cpu_freq`` returns, or ``None`` when it raises.
    """
    try:
        return _original_cpu_freq(*args, **kwargs)
    except Exception:  # noqa: BLE001 - any failure here must degrade to None, never kill the session
        return None


psutil.cpu_freq = _cpu_freq_or_none

# docker/compose#13899: `up --wait` fails on a project containing a zero-replica service, reporting
# it as a missing dependency. The packaged compose file declares `task-manager-background-svc` with
# `replicas: ${INFRAHUB_TESTING_TASKMGR_BACKGROUND_SVC_REPLICAS:-0}` (container.py:124), so the
# default trips it. Scheduling one replica is harmless -- nothing depends on that service.
# `setdefault` so an explicit value still wins. This is a Compose-version issue, not a
# custom-image one, so it applies here even though this repository's tests run vanilla Infrahub.
os.environ.setdefault("INFRAHUB_TESTING_TASKMGR_BACKGROUND_SVC_REPLICAS", "1")


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
