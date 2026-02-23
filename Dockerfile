ARG PYTHON_VERSION=3.13
FROM python:${PYTHON_VERSION}-slim

ARG SETUPTOOLS_SCM_PRETEND_VERSION
ENV SETUPTOOLS_SCM_PRETEND_VERSION=${SETUPTOOLS_SCM_PRETEND_VERSION}

RUN apt-get update \
    && apt-get install -y --no-install-recommends ffmpeg curl unzip \
    && curl -fsSL https://deno.land/install.sh | DENO_INSTALL=/usr/local sh \
    && apt-get purge -y curl unzip && apt-get autoremove -y \
    && rm -rf /var/lib/apt/lists/*

COPY --from=ghcr.io/astral-sh/uv:latest /uv /usr/local/bin/uv

WORKDIR /app
COPY pyproject.toml .python-version README.md uv.lock ./
COPY src/ src/
COPY tests/ tests/

RUN uv sync --frozen

ENTRYPOINT ["uv", "run", "spot2yoto"]
