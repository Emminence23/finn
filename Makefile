.PHONY: setup api web seed snapshot test lint fmt check

setup:            ## install all dependencies
	cd backend && uv sync
	cd frontend && npm install

api:              ## run the backend on :8000
	cd backend && uv run uvicorn app.main:app --reload --port 8000

web:              ## run the frontend on :3000
	cd frontend && npm run dev

snapshot:         ## refresh fixtures from live sources (NSE, Yahoo, screener)
	cd backend && uv run python -m app.ingest.snapshot all

seed:             ## load fixtures into SQLite
	cd backend && uv run python -m app.ingest.seed

test:
	cd backend && uv run pytest -q

lint:
	cd backend && uv run ruff check . && uv run ruff format --check .
	cd frontend && npm run lint

fmt:
	cd backend && uv run ruff check --fix . && uv run ruff format .

check: lint test  ## what CI runs
	cd frontend && npm run build
