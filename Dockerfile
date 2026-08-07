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

# This is an application runtime image, not a preconfigured Gaia product.
# Deployments must provide their own API or Worker command and application factory.
CMD ["gaia", "--help"]
