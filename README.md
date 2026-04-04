# Price Tracker

A price tracking service built with FastAPI, async SQLAlchemy, and Redis.

## Prerequisites

- Python 3.12+
- [uv](https://docs.astral.sh/uv/) package manager
- Docker and Docker Compose (for local infrastructure)

## Local Setup

### 1. Clone and install dependencies

```bash
git clone <repo-url>
cd price-tracker
uv sync --dev
```

### 2. Start infrastructure

```bash
docker compose up -d postgres redis
```

### 3. Configure environment

```bash
cp .env.example .env
# Edit .env with your values (defaults work with docker compose)
```

### 4. Run the application

```bash
uv run uvicorn app.main:app --reload
```

The API is available at `http://localhost:8000`.
OpenAPI docs at `http://localhost:8000/docs`.

### 5. Run tests

```bash
uv run pytest -v
```

### 6. Lint and type-check

```bash
uv run ruff check .
uv run mypy app
```

## Docker (full stack)

```bash
cp .env.example .env
docker compose up --build
```

## Project Structure

```
app/
  main.py        # FastAPI application
  config.py      # Settings from environment
  database.py    # Async SQLAlchemy engine + session
  models/        # ORM models
  routers/       # API route handlers
tests/           # pytest test suite
```
