# This Dockerfile serves two purposes:
# 1. It builds a custom Infrahub image with the `service_catalog` python module included. It can now be imported and used within the Infrahub environment (in generators for example).
# 2. It builds a container that runs streamlit to serve the service catalog web application.
ARG INFRAHUB_BASE_VERSION=1.6.2
FROM registry.opsmill.io/opsmill/infrahub:${INFRAHUB_BASE_VERSION}

WORKDIR /opt/local
COPY pyproject.toml uv.lock README.md ./
COPY service_catalog/ service_catalog/

# Install service_catalog package and its dependencies into the existing Infrahub venv
# Using uv pip install instead of uv sync to avoid overwriting Infrahub dependencies
RUN uv pip install -e .

WORKDIR /source
