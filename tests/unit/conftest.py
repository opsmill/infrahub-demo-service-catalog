"""Fixtures shared by the unit tests."""

from __future__ import annotations

import sys
from typing import TYPE_CHECKING

import pytest
import streamlit as st

from service_catalog import infrahub

if TYPE_CHECKING:
    from collections.abc import Callable, Iterator
    from pathlib import Path


@pytest.fixture
def replace_reads(monkeypatch: pytest.MonkeyPatch) -> Iterator[Callable[..., None]]:
    """Replace functions of `service_catalog.infrahub` by name, with an empty Streamlit cache before and after."""

    def replace(**fakes: object) -> None:
        for name, fake in fakes.items():
            monkeypatch.setattr(infrahub, name, fake)

    st.cache_data.clear()
    yield replace
    st.cache_data.clear()


@pytest.fixture
def commit_worktree(tmp_path: Path) -> Iterator[Path]:
    """An empty commit worktree, `tmp_path/commits/<sha>`, laid out as the Infrahub task worker imports it.

    The worktree has the `service_catalog` package file, and `tmp_path` is on sys.path, so a test copies the
    files it needs and imports them as `commits.<sha>.<dir>.<file>`. Afterwards the path and every `commits`
    module are removed.
    """
    worktree = tmp_path / "commits" / "0f1e2d3c"
    (worktree / "service_catalog").mkdir(parents=True)
    (worktree / "service_catalog" / "__init__.py").write_text("")
    sys.path.append(str(tmp_path))
    try:
        yield worktree
    finally:
        sys.path.remove(str(tmp_path))
        for name in [name for name in sys.modules if name == "commits" or name.startswith("commits.")]:
            del sys.modules[name]
