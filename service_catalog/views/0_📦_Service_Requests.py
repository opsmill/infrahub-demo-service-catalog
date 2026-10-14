from __future__ import annotations

import pandas as pd
import streamlit as st

from service_catalog.infrahub import filter_nodes
from service_catalog.protocols_sync import ServiceDedicatedInternet

st.set_page_config(page_title="Service Requests", page_icon="📦", layout="wide")

st.markdown("# Service Requests")
st.write(
    "You will find on this page all services requests opened. For the one delivered you'll also find allocated assets.",
)


def render_asset_table(data: ServiceDedicatedInternet) -> None:
    if data:
        dedicated_interfaces: list = []

        if data.dedicated_interfaces.initialized and len(data.dedicated_interfaces.peers) > 0:
            for interface in data.dedicated_interfaces.peers:
                dedicated_interfaces.append(f"{interface.peer.device.hfid[0]}.{interface.peer.name.value}")  # noqa: PERF401
        df = pd.DataFrame(
            {
                "vlan_id": [data.vlan.peer.vlan_id.value if data.vlan.initialized else None],
                "gateway_ip_address": [
                    data.gateway_ip_address.peer.display_label if data.gateway_ip_address.initialized else None,
                ],
                "prefix": [data.prefix.peer.display_label if data.prefix.initialized else None],
                "dedicated_interfaces": [dedicated_interfaces],
            },
        )
        st.dataframe(
            df,
            column_config={
                "vlan_id": st.column_config.TextColumn(
                    "Vlan ID",
                ),
                "gateway_ip_address": "Gateway Ip Address",
                "prefix": "Prefix",
                "dedicated_interfaces": st.column_config.ListColumn(
                    "Dedicated Interfaces",
                ),
            },
            hide_index=True,
        )


def render_details_table(data: ServiceDedicatedInternet) -> None:
    if data:
        st.dataframe(
            pd.DataFrame(
                {
                    "service_id": [data.service_identifier.value],
                    "account_ref": [
                        data.account_reference.value,
                    ],
                    "status": [data.status.value],
                    "location": [data.location.peer.display_label],
                    "bandwidth": [data.bandwidth.value],
                    "ip_package": [data.ip_package.value],
                },
            ),
            column_config={
                "service_id": "Service Identifier",
                "account_ref": "Account Reference",
                "status": "Status",
                "location": "Location",
                "bandwidth": "Bandwidth",
                "ip_package": "Ip Package",
            },
            hide_index=True,
        )


# Get the data
services: list[ServiceDedicatedInternet] = filter_nodes(
    kind=ServiceDedicatedInternet,
    include=["prefix", "interfaces"],
)

if len(services) == 0:
    st.warning("There is currently no service ...")

# Render the containers
for service in services:
    with st.container(border=True):
        # Display title
        st.title(service.service_identifier.value)

        render_details_table(service)

        st.write("#### Assets")

        if service.status.value == "draft":
            st.warning("Service is in the building process ...")
        else:
            render_asset_table(service)
