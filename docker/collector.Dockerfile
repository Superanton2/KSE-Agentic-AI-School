# Live Telegram collector (read-only). Build: docker compose build collector
FROM python:3.12-slim-bookworm

COPY --from=ghcr.io/astral-sh/uv:0.11.16 /uv /usr/local/bin/uv

ENV UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    UV_PROJECT_ENVIRONMENT=/opt/venv \
    PATH="/opt/venv/bin:$PATH" \
    PYTHONUNBUFFERED=1 \
    DATA_DIR=/app/data \
    REPORTS_DIR=/app/reports \
    TG_SESSION_PATH=/session/airalert.session

WORKDIR /app
COPY pyproject.toml uv.lock README.md ./
RUN uv sync --frozen --no-dev --no-install-project
COPY src ./src
RUN uv sync --frozen --no-dev && rm /usr/local/bin/uv

# Non-root; the uid/gid are overridden at runtime to match the owner of the mounted session file.
RUN useradd --system --uid 10001 --home-dir /nonexistent --shell /usr/sbin/nologin collector
USER collector

HEALTHCHECK --interval=60s --timeout=10s --start-period=120s --retries=3 \
    CMD ["airalert", "healthcheck"]
ENTRYPOINT ["airalert"]
CMD ["tg-live"]
