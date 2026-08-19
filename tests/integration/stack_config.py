"""Which image and tag the integration stack runs, resolved in one place.

``infrahub_testcontainers.container`` keeps its defaults in a module-level ``PROJECT_ENV_VARIABLES``
dict. That dict is consulted against ``os.environ`` when the ``.env`` file is written
(``container.py:182-183``), so an environment override does reach the deployment -- but nothing merges
the override back into the dict, so *Python-side* reads of it never see one. Reading the image name
from that dict therefore yields ``registry.opsmill.io/opsmill/infrahub`` even in a repository that has
pointed the stack at its own image, which is how a helper container ends up running the wrong image
entirely rather than merely the wrong tag.

Resolution lives here, as a pure function over an environment mapping, so it can be tested without
Docker and reused by the repositories that run custom images.

Repositories adopting this file also need to set stack knobs of their own -- typically
``INFRAHUB_TESTING_DOCKER_IMAGE``, ``INFRAHUB_TESTING_DOCKER_PULL=false`` and
``INFRAHUB_TESTING_TASKMGR_BACKGROUND_SVC_REPLICAS=1`` -- and where those assignments go matters for
exactly one variable. ``INFRAHUB_TESTING_DOCKER_IMAGE``, ``..._DOCKER_PULL`` and
``..._TASKMGR_BACKGROUND_SVC_REPLICAS`` reach the deployment whenever they are set, as long as it is
before the ``.env`` file is written, because the writer reads ``os.environ`` per key at write time.
``INFRAHUB_TESTING_WEB_CONCURRENCY`` is the exception: ``container.py:40`` interpolates it into the
``INFRAHUB_TESTING_DOCKER_ENTRYPOINT`` default while that module is being imported, so it must be set
in job-level ``env:`` or in ``tests/conftest.py``, never in a module that runs afterwards. Never
hardcode ``INFRAHUB_TESTING_DOCKER_ENTRYPOINT`` itself -- ``container.py:152-159`` rewrites it for the
enterprise edition, and hardcoding the community form pins the repository to community.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import Mapping

DEFAULT_IMAGE_REPOSITORY = "registry.opsmill.io/opsmill/infrahub"

# Both spellings are in use, and they feed different code paths, which is why anything resolving one
# must resolve the other. ``INFRAHUB_TESTING_IMAGE_VER`` is read unconditionally by ``helpers.py:24``
# (the class-scoped fixture) and by ``container.py:92-94`` only when the tag is the "local" sentinel;
# the longer ``INFRAHUB_TESTING_IMAGE_VERSION`` is the key the ``.env`` writer emits. Setting one and
# leaving the other on the packaged default is how a suite reports one version while running another.
_TAG_VARIABLES = ("INFRAHUB_TESTING_IMAGE_VER", "INFRAHUB_TESTING_IMAGE_VERSION")
_REPOSITORY_VARIABLE = "INFRAHUB_TESTING_DOCKER_IMAGE"
_PULL_VARIABLE = "INFRAHUB_TESTING_DOCKER_PULL"
# The build arg both custom-image repositories use for their own image. Deliberately consulted only
# when the caller passes custom_build=True: a repository can hold a Dockerfile for its demo stack and
# still run its tests against vanilla Infrahub, and reading this unconditionally would silently point
# such a suite at an image nothing ever builds.
_BUILD_ARG_VARIABLE = "INFRAHUB_BASE_VERSION"
# Accepted spellings for the pull flag. `1` is the conventional spelling for Docker-adjacent boolean
# environment variables, so treating only the literal "true" as truthy would silently invert it -- and
# `as_env()` would then write that inversion back out, so a repository setting `=1` and merging
# `as_env()` into `os.environ` would overwrite its own value with "false" and run a stale local image
# while the suite reported the resolved tag. Anything outside both sets is rejected rather than guessed,
# the same way the "local" sentinel is.
_TRUTHY = frozenset({"true", "1", "yes", "on"})
_FALSY = frozenset({"false", "0", "no", "off"})


@dataclass(frozen=True)
class StackImage:
    """The image the integration stack runs, and the environment that makes every path agree.

    Attributes:
        repository: Image repository, without a tag.
        tag: Image tag, which for this stack is an Infrahub version.
        pull: Whether the stack should pull the image. False for a locally built one.
        custom_build: Whether this repository builds its own image rather than running vanilla
            Infrahub.
    """

    repository: str
    tag: str
    pull: bool
    custom_build: bool

    @property
    def reference(self) -> str:
        """Full ``repository:tag`` reference, as Docker expects it.

        Returns:
            The joined reference, suitable for ``docker image inspect``.
        """
        return f"{self.repository}:{self.tag}"

    def as_env(self) -> dict[str, str]:
        """Every variable that must be set for the fixture path and the ``.env`` writer to agree.

        Returns:
            A mapping to merge into ``os.environ`` before the stack starts. Both tag spellings are
            set to the same value on purpose -- see the note on ``_TAG_VARIABLES``.
        """
        return {
            _REPOSITORY_VARIABLE: self.repository,
            "INFRAHUB_TESTING_IMAGE_VERSION": self.tag,
            "INFRAHUB_TESTING_IMAGE_VER": self.tag,
            _PULL_VARIABLE: "true" if self.pull else "false",
        }


def resolve_stack_image(
    env: Mapping[str, str],
    packaged_version: str,
    *,
    repository: str = DEFAULT_IMAGE_REPOSITORY,
    default_tag: str = "",
    custom_build: bool = False,
) -> StackImage:
    """Decide which image the integration stack should run.

    Resolution order for the tag, most explicit first: an ``INFRAHUB_TESTING_IMAGE_VER`` or
    ``INFRAHUB_TESTING_IMAGE_VERSION`` override; then ``INFRAHUB_BASE_VERSION`` but only when
    ``custom_build``; then the repository's own ``default_tag``; then the installed package version.

    Args:
        env: Environment mapping to read overrides from, normally ``os.environ``.
        packaged_version: Installed ``infrahub-testcontainers`` version, the last-resort tag. This is
            what makes a dependency bump self-validating: moving the pin moves the version under
            test, with no CI wiring at all.
        repository: Image repository this stack runs. Defaults to vanilla Infrahub, so a repository
            that says nothing gets vanilla.
        default_tag: The repository's own committed default tag, if it pins one. Most repositories
            should leave this empty: falling through to ``packaged_version`` *is* derivation from a
            committed file, since the installed version comes from the pin in ``pyproject.toml``
            resolved through ``uv.lock``, and it needs no conftest wiring at all. Only a repository
            whose stack must run a tag its dependency pin does not select should set this -- and then
            it should pass a value read from a committed file rather than a literal restated here,
            because a literal in a conftest becomes one more copy of a version that already lives in
            the Dockerfile and the compose override. A repository that runs vanilla Infrahub must
            **not** feed its ``ARG INFRAHUB_BASE_VERSION`` in here: that arg belongs to a demo-stack
            image and has nothing to do with the version under test.
        custom_build: True when this repository builds its own image. Opt-in, never inferred: the
            presence of a ``Dockerfile`` does not mean the *test stack* uses it.

    Returns:
        The resolved image.

    Raises:
        ValueError: If the resolved tag is the ``"local"`` sentinel, which ``container.py:92-94``
            treats specially by re-reading ``INFRAHUB_TESTING_IMAGE_VER``. Resolving to it would make
            the returned tag and the tag the stack runs disagree, which is the class of bug this
            function exists to prevent. Also raised if ``INFRAHUB_TESTING_DOCKER_PULL`` is set to a
            value that is neither a recognised truthy nor falsy spelling -- guessing it would invert
            the caller's intent silently, the same failure mode the tag check above exists to prevent.
    """
    resolved_repository = env.get(_REPOSITORY_VARIABLE) or repository
    candidates = [env.get(name) for name in _TAG_VARIABLES]
    if custom_build:
        candidates.append(env.get(_BUILD_ARG_VARIABLE))
    candidates.extend([default_tag, packaged_version])
    tag = next(candidate for candidate in candidates if candidate)

    if tag == "local":
        msg = (
            "resolved tag is the 'local' sentinel, which infrahub-testcontainers re-resolves from "
            "INFRAHUB_TESTING_IMAGE_VER; set an explicit tag instead"
        )
        raise ValueError(msg)

    explicit_pull = env.get(_PULL_VARIABLE, "").strip().lower()
    if explicit_pull and explicit_pull not in _TRUTHY | _FALSY:
        msg = f"{_PULL_VARIABLE}={explicit_pull!r} is not a recognised boolean"
        raise ValueError(msg)
    pull = explicit_pull in _TRUTHY if explicit_pull else not custom_build
    return StackImage(
        repository=resolved_repository,
        tag=tag,
        pull=pull,
        custom_build=custom_build,
    )
