# syntax=docker/dockerfile:1
# Prepay public demo: fictional pools + a synthetic-trained model, built from scratch in the image.
# No Freddie Mac data, raw files or real-trained artifacts can enter this build (see .dockerignore).

ARG PYTHON_IMAGE=python:3.12-slim-bookworm@sha256:e697c81897302a4c4333bade000d98038fbb21eb064f8ee1fd42d02ebcd9d337
ARG NODE_IMAGE=node:24-bookworm-slim@sha256:be8204d4bd327363357f532187b752ff62759c31bedf98e9e18fc08c9cbd605c
ARG UV_IMAGE=ghcr.io/astral-sh/uv:0.12.1@sha256:cf4eedcaa81655197f625739489effcbe71b61ceb1506f332c3facae5deceded

FROM ${UV_IMAGE} AS uv

# ---------------------------------------------------------------- web UI
FROM ${NODE_IMAGE} AS web
WORKDIR /web
COPY web/package.json web/package-lock.json web/.npmrc ./
RUN npm ci --ignore-scripts
COPY web/ ./
RUN npm run build

# ---------------------------------------------------------------- fictional pipeline -> bundle
FROM ${PYTHON_IMAGE} AS builder
# LightGBM needs the OpenMP runtime.
RUN apt-get update \
    && apt-get install -y --no-install-recommends libgomp1 \
    && rm -rf /var/lib/apt/lists/*
COPY --from=uv /uv /usr/local/bin/uv
ENV UV_FROZEN=1 UV_LINK_MODE=copy UV_PYTHON_DOWNLOADS=never UV_COMPILE_BYTECODE=1
WORKDIR /app
COPY pyproject.toml uv.lock README.md ./
COPY src ./src
COPY transform ./transform
RUN uv sync --no-default-groups --group transform --group api
ARG DEMO_PRESET=ci
RUN uv run --no-sync prepay --log-level WARNING demo build --out /bundle --preset "${DEMO_PRESET}"
# Runtime environment: the package (non-editable) plus API dependencies only.
RUN UV_PROJECT_ENVIRONMENT=/opt/venv uv sync --no-default-groups --group api --no-editable

# ---------------------------------------------------------------- runtime
FROM ${PYTHON_IMAGE} AS runtime
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 PATH="/opt/venv/bin:${PATH}"
RUN apt-get update \
    && apt-get install -y --no-install-recommends libgomp1 \
    && rm -rf /var/lib/apt/lists/* \
    && useradd --uid 10001 --create-home --shell /usr/sbin/nologin prepay
COPY --from=builder /opt/venv /opt/venv
COPY --from=builder /bundle /srv/prepay/bundle
COPY --from=web /web/dist /srv/prepay/web
USER prepay
WORKDIR /srv/prepay
EXPOSE 8000
HEALTHCHECK --interval=30s --timeout=5s --start-period=60s --retries=3 \
  CMD ["python", "-c", "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/api/health', timeout=4)"]
CMD ["prepay", "serve", "--bundle", "/srv/prepay/bundle", "--web-dist", "/srv/prepay/web", "--host", "0.0.0.0", "--port", "8000", "--proxy-headers"]
