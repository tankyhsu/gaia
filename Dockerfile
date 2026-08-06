FROM ghcr.io/astral-sh/uv:0.8.14 AS uv

FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    PATH="/app/.venv/bin:${PATH}"

COPY --from=uv /uv /uvx /bin/

WORKDIR /app
COPY . .
RUN uv sync --frozen --no-dev \
    --extra postgres \
    --extra redis \
    --extra temporal \
    --extra langfuse \
    --extra guardrails

USER 65532:65532
EXPOSE 8000

CMD ["uvicorn", "examples.controlled_task.app:create_app", "--factory", "--host", "0.0.0.0", "--port", "8000"]
