# This Dockerfile builds a custom Infrahub image with the `service_catalog` python module included. It can be imported and used within the Infrahub environment (in generators for example).
# The Streamlit portal has its own, smaller image, built from service_catalog/Dockerfile and published by .github/workflows/publish-images.yml.
ARG INFRAHUB_BASE_VERSION=1.11.8
FROM registry.opsmill.io/opsmill/infrahub:${INFRAHUB_BASE_VERSION}

WORKDIR /opt/local
COPY pyproject.toml uv.lock README.md ./
COPY service_catalog/ service_catalog/

# Install service_catalog package and its dependencies into the existing Infrahub venv
# Using uv pip install instead of uv sync to avoid overwriting Infrahub dependencies
RUN uv pip install -e .

WORKDIR /source
