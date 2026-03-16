FROM semaphoreui/semaphore:v2.17.12

USER root

RUN apk add --no-cache python3 py3-pip && \
    pip3 install --break-system-packages infrahub-sdk && \
    ansible-galaxy collection install opsmill.infrahub

USER semaphore
