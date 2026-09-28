FROM ghcr.io/astral-sh/uv:0.12.19 AS uv

FROM python:3.12-slim

RUN apt-get update \
    && apt-get install -y --no-install-recommends libatomic1 \
    && rm -rf /var/lib/apt/lists/*

COPY --from=uv /uv /uvx /bin/

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PYTHONPATH=/app/src \
    UV_PROJECT_ENVIRONMENT=/opt/venv \
    UV_LINK_MODE=copy

WORKDIR /app

COPY pyproject.toml uv.lock ./
RUN uv sync --locked --all-groups --no-install-project

COPY . .

RUN addgroup --system slideai \
    && adduser --system --ingroup slideai --home /home/slideai slideai \
    && mkdir -p /var/lib/slideai/files /home/slideai/.cache/uv \
    && chown -R slideai:slideai /opt/venv /var/lib/slideai /home/slideai

ENV HOME=/home/slideai UV_CACHE_DIR=/home/slideai/.cache/uv
USER slideai

EXPOSE 8000
CMD ["uv", "run", "uvicorn", "slideai.api.main:app", "--host", "0.0.0.0", "--port", "8000"]
