FROM python:3.11-slim

RUN apt-get update \
    && apt-get install -y --no-install-recommends ffmpeg \
    && rm -rf /var/lib/apt/lists/*

COPY --from=ghcr.io/astral-sh/uv:latest /uv /usr/local/bin/uv

WORKDIR /app
COPY pyproject.toml .python-version ./
COPY src/ src/

RUN uv sync --no-dev \
    && uv pip install spotdl

ENTRYPOINT ["uv", "run", "spot2yoto"]
