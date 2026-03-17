FROM python:3.13-slim

WORKDIR /app

COPY --from=ghcr.io/astral-sh/uv:latest /uv /usr/local/bin/uv

COPY pyproject.toml .
RUN uv sync --no-dev --no-install-project

RUN apt-get update && apt-get install -y --no-install-recommends curl && rm -rf /var/lib/apt/lists/*

COPY src/ src/

RUN uv sync --no-dev

EXPOSE 8000

CMD ["uv", "run", "uvicorn", "shared.main:app", "--host", "0.0.0.0", "--port", "8000"]
