COMPOSE = docker compose -f docker-compose.dev.yml

.PHONY: dev down logs migrate shell-api shell-db lint test

## Start the full dev stack (builds images if needed)
dev:
	@if [ ! -f .env.compose ]; then \
		cp .env.compose.example .env.compose; \
		echo "Created .env.compose from .env.compose.example — review before running"; \
	fi
	$(COMPOSE) up --build

## Stop all dev services and remove containers
down:
	$(COMPOSE) down

## Follow logs for all services (pass s=<service> to filter, e.g. make logs s=api)
logs:
	$(COMPOSE) logs -f $(s)

## Run Alembic migrations (one-shot, same as the migrate init container)
migrate:
	$(COMPOSE) run --rm migrate

## Open a shell in the API container
shell-api:
	$(COMPOSE) exec api bash

## Open a psql session in the postgres container
shell-db:
	$(COMPOSE) exec postgres psql -U postgres price_tracker

## Run ruff linter inside the api container
lint:
	$(COMPOSE) exec api ruff check app tests

## Run the pytest suite inside the api container
test:
	$(COMPOSE) exec api pytest
