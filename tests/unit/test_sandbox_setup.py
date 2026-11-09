"""The `sandbox-setup` task, which the public sandbox pipeline runs, and the Semaphore client it uses.

No test contacts Infrahub or Semaphore: the steps of the task are replaced, and the Semaphore
client talks to a fake transport.
"""

from __future__ import annotations

from unittest.mock import MagicMock

import httpx
import pytest
from invoke import Context, Exit

import tasks

SEMAPHORE_URL = "http://semaphore.test"


def _context() -> MagicMock:
    """A context that records every call, and that invoke accepts as a Context."""
    return MagicMock(spec=Context)


@pytest.fixture
def steps(monkeypatch: pytest.MonkeyPatch) -> list[str]:
    """Replace the steps of `sandbox_setup` with recorders, and return the list they append to."""
    recorded: list[str] = []
    monkeypatch.setattr(tasks, "_register_repository", lambda: recorded.append("repository"))
    monkeypatch.setattr(tasks, "init_semaphore", lambda _context: recorded.append("semaphore"))
    monkeypatch.setattr(tasks, "seed", lambda _context: recorded.append("seed"))
    monkeypatch.setenv("INFRAHUB_ADDRESS", "https://infrahub.test")
    monkeypatch.delenv("SEMAPHORE_URL", raising=False)
    monkeypatch.delenv("SEMAPHORE_ADMIN_PASSWORD", raising=False)
    return recorded


def test_sets_up_the_repository_then_semaphore_then_seeds(steps: list[str], monkeypatch: pytest.MonkeyPatch) -> None:
    """With a Semaphore to configure, the three steps run in this order."""
    monkeypatch.setenv("SEMAPHORE_URL", SEMAPHORE_URL)
    monkeypatch.setenv("SEMAPHORE_ADMIN_PASSWORD", "not-the-default")

    tasks.sandbox_setup(_context())

    assert steps == ["repository", "semaphore", "seed"]


def test_loads_no_demo_account(steps: list[str]) -> None:
    """The task itself runs no command: the accounts of `bootstrap/permissions.yml` stay out of a sandbox."""
    context = _context()

    tasks.sandbox_setup(context)

    assert steps == ["repository", "seed"]
    assert context.mock_calls == []


def test_leaves_semaphore_out_without_its_address(steps: list[str]) -> None:
    """Without SEMAPHORE_URL, Semaphore is not configured and the rest still runs."""
    tasks.sandbox_setup(_context())

    assert "semaphore" not in steps
    assert steps[-1] == "seed"


def test_stops_without_the_infrahub_address(steps: list[str], monkeypatch: pytest.MonkeyPatch) -> None:
    """Nothing is changed when INFRAHUB_ADDRESS is missing."""
    monkeypatch.delenv("INFRAHUB_ADDRESS")

    with pytest.raises(Exit) as stopped:
        tasks.sandbox_setup(_context())

    assert stopped.value.code == 1
    assert steps == []


@pytest.mark.parametrize("password", [None, ""])
def test_requires_the_semaphore_password_with_its_address(
    steps: list[str], monkeypatch: pytest.MonkeyPatch, password: str | None
) -> None:
    """A Semaphore address without a password never falls back to the published default, and nothing is changed first.

    GitHub gives a secret that does not exist to a job as an empty string, so an empty password counts as missing.
    """
    monkeypatch.setenv("SEMAPHORE_URL", SEMAPHORE_URL)
    if password is not None:
        monkeypatch.setenv("SEMAPHORE_ADMIN_PASSWORD", password)

    with pytest.raises(Exit) as stopped:
        tasks.sandbox_setup(_context())

    assert stopped.value.code == 1
    assert "SEMAPHORE_ADMIN_PASSWORD" in str(stopped.value.message)
    assert steps == []


def _semaphore(handler: httpx.MockTransport) -> tasks._SemaphoreClient:
    """A Semaphore client whose requests go to `handler`."""
    api = tasks._SemaphoreClient(SEMAPHORE_URL)  # noqa: SLF001
    api._client = httpx.Client(base_url=SEMAPHORE_URL, transport=handler)  # noqa: SLF001
    return api


def test_creates_a_resource_when_semaphore_answers_null_for_an_empty_list() -> None:
    """Semaphore 2.17 answers null, not [], for a list with no item yet."""

    def handler(request: httpx.Request) -> httpx.Response:
        if request.method == "GET":
            return httpx.Response(200, content=b"null", headers={"content-type": "application/json"})
        return httpx.Response(201, json={"id": 7})

    api = _semaphore(httpx.MockTransport(handler))

    assert api.find_or_create("/api/projects", "/api/projects", "Service Catalog", {"name": "Service Catalog"}) == 7


def test_waits_while_semaphore_answers_with_an_error_status(monkeypatch: pytest.MonkeyPatch) -> None:
    """A proxy that answers 503 while Semaphore starts is not ready: the check tries again."""
    answers = iter([503, 502, 200])
    pauses: list[float] = []
    monkeypatch.setattr("tasks.time.sleep", pauses.append)

    api = _semaphore(httpx.MockTransport(lambda _request: httpx.Response(next(answers))))
    api.wait_until_ready()

    assert pauses == [2, 4]


def test_stops_when_semaphore_never_answers_with_a_success_status(monkeypatch: pytest.MonkeyPatch) -> None:
    """After 8 attempts that all get a 503, the task stops with an error."""
    pauses: list[float] = []
    monkeypatch.setattr("tasks.time.sleep", pauses.append)

    api = _semaphore(httpx.MockTransport(lambda _request: httpx.Response(503)))
    with pytest.raises(SystemExit) as stopped:
        api.wait_until_ready()

    assert stopped.value.code == 1
    assert len(pauses) == 8
