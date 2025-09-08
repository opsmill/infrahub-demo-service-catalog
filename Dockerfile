# This Dockerfile serves two purposes:
# 1. It builds a custom Infrahub image with the `service_catalog` python module included. It can now be imported and used within the Infrahub environment (in generators for example).
# 2. It builds a container that runs streamlit to serve the service catalog web application.
ARG INFRAHUB_BASE_VERSION=1.4.3
FROM registry.opsmill.io/opsmill/infrahub:${INFRAHUB_BASE_VERSION}

WORKDIR /opt/local
COPY pyproject.toml poetry.lock README.md ./
COPY service_catalog/ service_catalog/

RUN poetry install --no-ansi --no-interaction

WORKDIR /source