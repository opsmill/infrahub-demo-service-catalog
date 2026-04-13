from __future__ import annotations

import streamlit as st

from infrahub_sdk.protocols import CoreProposedChange
from service_catalog.infrahub import (
    create_and_save,
    create_branch,
    filter_nodes,
    get_dropdown_label_mapping,
    get_dropdown_options,
)
from service_catalog.protocols_sync import LocationSite, ServiceDedicatedInternet

st.set_page_config(page_title="Dedicated Internet", page_icon="🔌")

st.markdown("# Dedicated Internet")
st.write("This form will allow you to request the implementation of a new dedicated internet service.")


def get_location_label_mapping() -> dict[str, str]:
    """Return a mapping of shortname -> display name for locations."""
    site_list: list[LocationSite] = filter_nodes(
        kind=LocationSite,
        filters={},
    )

    return {site.shortname.value: site.name.value for site in site_list}


with st.form("new_dedicated_internet_form"):
    # Identifiers
    service_identifier = st.text_input("Service Identifier", key="input-service-identifier")
    account_reference = st.text_input("Account Reference", key="input-account-reference")

    # Location
    location_label_mapping: dict[str, str] = get_location_label_mapping()
    location = st.selectbox(
        "Location",
        options=list(location_label_mapping.keys()),
        format_func=lambda x: location_label_mapping[x],
        key="select-location",
    )

    # Bandwidth
    bandwidth_options: list = get_dropdown_options(
        kind=ServiceDedicatedInternet,
        attribute_name="bandwidth",
    )
    bandwidth_label_mapping: dict[str, str] = get_dropdown_label_mapping(
        kind=ServiceDedicatedInternet,
        attribute_name="bandwidth",
    )
    bandwidth = st.selectbox(
        "Bandwidth",
        options=bandwidth_options,
        format_func=lambda x: bandwidth_label_mapping.get(x, x),
        key="select-bandwidth",
    )

    # IP package
    ip_package_options: list = get_dropdown_options(
        kind=ServiceDedicatedInternet,
        attribute_name="ip_package",
    )
    ip_package_label_mapping: dict[str, str] = get_dropdown_label_mapping(
        kind=ServiceDedicatedInternet,
        attribute_name="ip_package",
    )

    ip_package = st.select_slider(
        "IP Package",
        options=ip_package_options,
        format_func=lambda x: ip_package_label_mapping.get(x, x),
        key="select-ip-package",
    )

    # Submit button
    submitted = st.form_submit_button("Submit", use_container_width=True)

if submitted:
    with st.status("Submitting new service request...", expanded=True) as status:
        # TODO: Implement some validation in the inputs

        st.write("Creating branch...")
        branch_name: str = f"implement_{service_identifier.lower()}"
        create_branch(branch_name)

        st.write("Creating service object...")
        service: dict = {
            "service_identifier": service_identifier,
            "account_reference": account_reference,
            "status": "draft",
            "bandwidth": bandwidth,
            "ip_package": ip_package,
            "member_of_groups": ["automated_dedicated_internet"],
            "location": [location],
        }
        service_obj: ServiceDedicatedInternet = create_and_save(
            kind=ServiceDedicatedInternet,
            data=service,
            branch=branch_name,
        )

        st.write("Opening proposed change request...")
        proposed_change: dict = {
            "name": f"Implement service {service_identifier.lower()}",
            "source_branch": branch_name,
            "description": "This request is coming from service catalog form!",
            "destination_branch": "main",
            "tags": ["service_request"],
        }

        proposed_change_obj: CoreProposedChange = create_and_save(
            kind=CoreProposedChange,
            data=proposed_change,
        )

        status.update(label="Service request opened!", state="complete", expanded=False)
