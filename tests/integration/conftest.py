"""Fixtures for the integration tier.

The container stack itself comes from the SDK's ``TestInfrahubDockerClient`` base class, so this
module holds no deployment plumbing. What it does own is *which image that stack runs*: the SDK path
and ``infrahub_testcontainers``' ``.env`` writer read different variables for the same concept, so
resolution happens once in ``stack_config`` and the result is written to every variable both paths
consult.
"""

from __future__ import annotations

import os

import pytest
from infrahub_testcontainers import __version__ as testcontainers_version

from .stack_config import StackImage, resolve_stack_image

# Resolved and applied at import time, before any fixture starts the stack. Nothing is passed beyond
# the packaged version: this repository's integration tests run *vanilla* Infrahub, so it takes the
# default repository, and the tag falls through to the installed `infrahub-testcontainers` version.
# That fall-through is the point -- it is derivation from a committed file, since the installed
# version comes from the pin in pyproject.toml resolved through uv.lock, so bumping the pin is what
# changes the version under test, with no CI wiring at all.
#
# In particular `custom_build` is left False and no `default_tag` is passed. This repository has a
# Dockerfile with `ARG INFRAHUB_BASE_VERSION`, but that arg is the base for the Streamlit demo image
# built by docker-compose.override.yml -- the test stack has nothing to do with it, and CI never
# builds it. Feeding it in here would point the suite at
# `opsmill/infrahub-demo-service-catalog:<version>`, an image nothing builds, and the generators
# under test import only infrahub_sdk, so vanilla Infrahub runs them fine.
_STACK_IMAGE = resolve_stack_image(os.environ, testcontainers_version)
os.environ.update(_STACK_IMAGE.as_env())


@pytest.fixture(scope="session")
def stack_image() -> StackImage:
    """Image and tag the integration stack runs.

    Returns:
        The resolved image. See ``stack_config`` for why this does not read
        ``PROJECT_ENV_VARIABLES``.
    """
    return _STACK_IMAGE
