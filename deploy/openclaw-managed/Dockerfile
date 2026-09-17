ARG OPENCLAW_IMAGE
FROM ${OPENCLAW_IMAGE}

USER root

RUN apt-get update \
    && apt-get install -y --no-install-recommends python3 python3-venv \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt /tmp/stockanalyse-requirements.txt
RUN python3 -m venv /opt/stockanalyse-venv \
    && /opt/stockanalyse-venv/bin/python -m pip install --no-cache-dir --upgrade pip \
    && /opt/stockanalyse-venv/bin/python -m pip install --no-cache-dir \
        -r /tmp/stockanalyse-requirements.txt \
    && rm -f /tmp/stockanalyse-requirements.txt

ARG OPENCLAW_RUNTIME_USER=node
USER ${OPENCLAW_RUNTIME_USER}
