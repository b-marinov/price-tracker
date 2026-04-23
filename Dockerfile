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

# System deps: tesseract for PDF OCR fallback + Playwright chromium deps
RUN apt-get update && apt-get install -y --no-install-recommends \
    tesseract-ocr \
    tesseract-ocr-bul \
    libglib2.0-0 \
    libnss3 \
    libnspr4 \
    libdbus-1-3 \
    libatk1.0-0 \
    libatk-bridge2.0-0 \
    libcups2 \
    libdrm2 \
    libxcomposite1 \
    libxdamage1 \
    libxfixes3 \
    libxrandr2 \
    libgbm1 \
    libxkbcommon0 \
    libpango-1.0-0 \
    libcairo2 \
    libasound2 \
    libx11-6 \
    libx11-xcb1 \
    libxcb1 \
    libxext6 \
    libxshmfence1 \
    fonts-liberation \
    wget \
    && rm -rf /var/lib/apt/lists/*

# Install all deps including dev extras
COPY pyproject.toml ./
RUN uv sync --all-extras --no-install-project

# Install Playwright chromium browser binary (system deps already installed above)
RUN /venv/bin/playwright install chromium

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
COPY --from=builder /build/alembic ./alembic
COPY --from=builder /build/alembic.ini ./alembic.ini

# Create media directory writable by appuser
RUN mkdir -p /home/appuser/app/media/images && chown -R appuser:appuser /home/appuser/app/media

ENV PATH="/home/appuser/app/.venv/bin:$PATH"
ENV PYTHONUNBUFFERED=1
ENV APP_MEDIA_DIR="/home/appuser/app/media"

USER appuser

EXPOSE 8000

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
