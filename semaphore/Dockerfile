# Semaphore image of the service catalog demo: Semaphore with the demo's Ansible
# playbooks, the opsmill.infrahub collection and the Infrahub SDK that the
# collection imports.
#
# The build context is the repository root, because the playbooks are in ansible/
# and the SDK version comes from uv.lock:
#
#   docker build -f semaphore/Dockerfile -t infrahub-demo-service-catalog-semaphore .
#
# Published as registry.opsmill.io/opsmill/infrahub-demo-service-catalog-semaphore.
FROM semaphoreui/semaphore:v2.17.12

# Same uv version as the portal image and the CI workflows.
COPY --from=ghcr.io/astral-sh/uv:0.9.18 /uv /usr/local/bin/uv

USER root

# Ansible runs from the virtual environment whose python3 comes first on PATH, so the
# SDK goes there, at the version pinned in uv.lock.
COPY pyproject.toml uv.lock /tmp/lock/
COPY semaphore/requirements.txt /tmp/requirements.txt
RUN uv export --frozen --no-dev --no-hashes --no-emit-project \
        --directory /tmp/lock --output-file /tmp/constraints.txt \
    && uv pip install --python "$(command -v python3)" --no-cache \
        --requirement /tmp/requirements.txt --constraint /tmp/constraints.txt \
    && rm -rf /tmp/lock /tmp/requirements.txt /tmp/constraints.txt

USER semaphore

COPY --chown=semaphore ansible/requirements.yml /tmp/ansible-requirements.yml
RUN mkdir -p /opt/semaphore/collections \
    && ansible-galaxy collection install -r /tmp/ansible-requirements.yml -p /opt/semaphore/collections \
    && rm /tmp/ansible-requirements.yml

# The playbooks, so that a Semaphore without the repository mounted can run them.
# docker-compose.catalog-dev.yml mounts ./ansible over this folder for local edits.
COPY --chown=semaphore ansible/ /opt/semaphore/playbooks/

# Semaphore listens on 3000. A deployment that needs another port, such as Styrmin's
# generic-app driver (8080), sets SEMAPHORE_PORT.
HEALTHCHECK --interval=30s --timeout=10s --start-period=15s --retries=3 \
  CMD curl --fail "http://localhost:${SEMAPHORE_PORT:-3000}/api/ping" || exit 1
