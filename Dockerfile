FROM python:3.13-slim AS base

WORKDIR /app

# Install uv
COPY --from=ghcr.io/astral-sh/uv:latest /uv /usr/local/bin/uv

# Pre-install deps; README.md is included because hatchling reads it from pyproject metadata.
COPY pyproject.toml uv.lock README.md .python-version* ./
RUN uv sync --no-dev --frozen

# Copy source
COPY src/ ./src/

# Run as non-root user
USER root

CMD ["uv", "run", "python", "-m", "main_bot"]