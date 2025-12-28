from __future__ import annotations

import os
from typing import Any

import streamlit as st
from fast_depends import Depends, inject

from infrahub_sdk import Config, InfrahubClientSync
from infrahub_sdk.branch import BranchData  # noqa: TC001
from infrahub_sdk.client import SchemaTypeSync  # noqa: TC001


def get_instance_address() -> str:
    if "infrahub_address" not in st.session_state or not st.session_state.infrahub_address:
        st.session_state.infrahub_address = os.environ.get("INFRAHUB_ADDRESS")

    if st.session_state.infrahub_address is None:
        st.exception(Exception("Can't find `INFRAHUB_ADDRESS` in variable envs..."))

    return str(st.session_state.infrahub_address)


@st.cache_resource
def get_client(branch: str = "main") -> InfrahubClientSync:
    address: str = get_instance_address()
    return InfrahubClientSync(address=address, config=Config(default_branch=branch))


@inject
def get_all_branches(
    client: InfrahubClientSync = Depends(get_client),
) -> dict[str, BranchData]:
    result: dict[str, BranchData] = client.branch.all()
    return result


@inject
def create_branch(branch_name: str, client: InfrahubClientSync = Depends(get_client)) -> BranchData:
    return client.branch.create(branch_name=branch_name, sync_with_git=False)


@inject(cast=False)  # type: ignore[call-overload]
def create_and_save(
    kind: type[SchemaTypeSync],
    data: dict[str, Any],
    branch: str = "main",
    client: InfrahubClientSync = Depends(get_client),
) -> SchemaTypeSync:
    infrahub_node = client.create(
        kind=kind,
        branch=branch,
        **data,
    )
    infrahub_node.save(allow_upsert=True)
    return infrahub_node


@inject(cast=False)  # type: ignore[call-overload]
def filter_nodes(
    kind: type[SchemaTypeSync],
    filters: dict[str, Any] | None = None,
    include: list[str] | None = None,
    branch: str = "main",
    client: InfrahubClientSync = Depends(get_client),
) -> list[SchemaTypeSync]:
    """Filter nodes by kind, branch, include and filters."""
    filters = filters or {}
    result: list[SchemaTypeSync] = client.filters(
        kind=kind,
        branch=branch,
        include=include,
        prefetch_relationships=True,
        **filters,
    )
    return result


@inject(cast=False)  # type: ignore[call-overload]
def get_dropdown_options(
    kind: str | type[SchemaTypeSync],
    attribute_name: str,
    branch: str = "main",
    client: InfrahubClientSync = Depends(get_client),
) -> list[str]:
    """Get dropdown options for a given attribute."""
    # Get schema for this kind

    schema = client.schema.get(kind=kind, branch=branch)

    # Find desired attribute
    matched_attribute = next((att for att in schema.attributes if att.name == attribute_name), None)

    if matched_attribute is None:
        raise Exception(f"Can't find attribute `{attribute_name}` for kind `{kind}`")
    return [choice["name"] for choice in matched_attribute.choices]
