# Streamlit Service Catalog portal image.
#
# The build context is the repository root, because the dependency versions
# come from pyproject.toml and uv.lock:
#
#   docker build -f service_catalog/Dockerfile -t infrahub-demo-service-catalog-streamlit .
#
# Published as registry.opsmill.io/opsmill/infrahub-demo-service-catalog-streamlit.
# The Infrahub image of the local stack is built from the Dockerfile at the
# repository root.
FROM python:3.12-slim

# Same uv version as the CI workflows (UV_VERSION in .github/workflows/ci.yml).
COPY --from=ghcr.io/astral-sh/uv:0.9.18 /uv /usr/local/bin/uv

RUN apt-get update \
    && apt-get install -y --no-install-recommends curl \
    && rm -rf /var/lib/apt/lists/* \
    && useradd --create-home --uid 1000 app

WORKDIR /app

# Install only what the portal needs, at the versions pinned in uv.lock, so the
# image matches what the integration tests ran against.
COPY pyproject.toml uv.lock /tmp/lock/
COPY service_catalog/requirements.txt /tmp/requirements.txt
RUN uv export --frozen --no-dev --no-hashes --no-emit-project \
        --directory /tmp/lock --output-file /tmp/constraints.txt \
    && uv pip install --system --no-cache \
        --requirement /tmp/requirements.txt --constraint /tmp/constraints.txt \
    && rm -rf /tmp/lock /tmp/requirements.txt /tmp/constraints.txt

# The pages import the package by name (`service_catalog.navigation`), so /app,
# the folder that holds the package, is on the import path.
COPY --chown=app:app service_catalog/ ./service_catalog/

USER app

# Streamlit reads these variables. A deployment that needs another port, such as
# Styrmin's generic-app driver (8080), overrides STREAMLIT_SERVER_PORT.
ENV PYTHONPATH=/app \
    STREAMLIT_SERVER_PORT=8501 \
    STREAMLIT_SERVER_ADDRESS=0.0.0.0 \
    STREAMLIT_SERVER_HEADLESS=true \
    STREAMLIT_BROWSER_GATHER_USAGE_STATS=false

EXPOSE 8501

HEALTHCHECK --interval=30s --timeout=10s --start-period=5s --retries=3 \
  CMD curl --fail "http://localhost:${STREAMLIT_SERVER_PORT}/_stcore/health" || exit 1

CMD ["streamlit", "run", "service_catalog/portal.py"]
