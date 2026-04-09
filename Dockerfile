# ---------- Dev stage ----------
# Used by docker-compose.dev.yml: mounts source, runs uvicorn --reload.
# The venv lives at /venv (outside /app) so the source volume mount
# does not shadow the installed packages.
FROM python:3.12-slim AS dev

WORKDIR /app

COPY --from=ghcr.io/astral-sh/uv:latest /uv /usr/local/bin/uv

ENV UV_PROJECT_ENVIRONMENT=/venv
ENV PATH="/venv/bin:$PATH"
ENV PYTHONUNBUFFERED=1

# Install all deps including dev extras
COPY pyproject.toml ./
RUN uv sync --all-extras --no-install-project

# Source is mounted at runtime via volume — no COPY here
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", "--reload"]

# ---------- Build stage ----------
FROM python:3.12-slim AS builder

WORKDIR /build

COPY --from=ghcr.io/astral-sh/uv:latest /uv /usr/local/bin/uv

# Build venv at the production path so script shebangs are correct
ENV UV_PROJECT_ENVIRONMENT=/home/appuser/app/.venv

COPY pyproject.toml ./
RUN uv sync --no-dev --no-install-project

COPY . .
RUN uv sync --no-dev

# ---------- Production stage ----------
FROM python:3.12-slim AS production

RUN groupadd --gid 1000 appuser && \
    useradd --uid 1000 --gid 1000 --create-home appuser

WORKDIR /home/appuser/app

COPY --from=builder /home/appuser/app/.venv .venv
COPY --from=builder /build/app ./app

ENV PATH="/home/appuser/app/.venv/bin:$PATH"
ENV PYTHONUNBUFFERED=1

USER appuser

EXPOSE 8000

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
