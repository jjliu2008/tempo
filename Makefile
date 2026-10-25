.PHONY: help install dev-backend dev-frontend test-backend typecheck-frontend watch-graph watch-graph-once

help:
	@echo "install             Install backend and frontend dependencies"
	@echo "dev-backend         Run the FastAPI server on :8000"
	@echo "dev-frontend        Run the Vite dev server on :5173"
	@echo "test-backend        Run backend tests"
	@echo "typecheck-frontend  Type-check the React app"
	@echo "watch-graph         Poll origin/main and refresh the graphify graph"
	@echo "watch-graph-once    Run one GitHub check + graph refresh"

install:
	cd backend && python -m venv .venv && .venv/bin/pip install -e ".[dev]"
	cd frontend && npm install

dev-backend:
	cd backend && .venv/bin/uvicorn app.main:app --reload --port 8000

dev-frontend:
	cd frontend && npm run dev

test-backend:
	cd backend && .venv/bin/pytest

typecheck-frontend:
	cd frontend && npm run typecheck

watch-graph:
	scripts/watch-github-graph.sh

watch-graph-once:
	scripts/watch-github-graph.sh --once
