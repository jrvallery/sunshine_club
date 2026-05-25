FROM python:3.13-slim AS base

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /app

RUN python -m pip install --upgrade pip

COPY pyproject.toml README.md ./
COPY apps/api ./apps/api
COPY apps/worker ./apps/worker
COPY packages ./packages

FROM base AS runtime
RUN python -m pip install .

FROM base AS dev
COPY tests ./tests
RUN python -m pip install -e ".[dev]"
