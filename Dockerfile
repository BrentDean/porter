# syntax=docker/dockerfile:1

FROM python:3.12-slim-bookworm

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PORTER_DATA_DIR=/var/lib/porter \
    PORTER_WEB_HOST=0.0.0.0

RUN apt-get update \
    && apt-get install -y --no-install-recommends ca-certificates passwd qalc tzdata \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /opt/porter

COPY pyproject.toml README.md ./
COPY src ./src

RUN python -m pip install --no-cache-dir '.[web]' \
    && groupadd --gid 10001 porter \
    && useradd \
        --uid 10001 \
        --gid porter \
        --create-home \
        --home-dir /home/porter \
        --shell /usr/sbin/nologin \
        porter \
    && mkdir -p /var/lib/porter \
    && chown porter:porter /var/lib/porter

USER porter:porter

EXPOSE 8000

HEALTHCHECK --interval=10s --timeout=3s --start-period=5s --retries=3 \
    CMD ["python", "-c", "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/healthz', timeout=2).read()"]

STOPSIGNAL SIGTERM

CMD ["porter", "web", "--port", "8000"]
