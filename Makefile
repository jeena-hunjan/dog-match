# Dog Match — works in Git Bash on Windows and on Ubuntu.
# Every command goes through `uv run`, so there is no venv-activation path to differ by OS.

CONFIG ?= training/configs/baseline.yaml

.PHONY: help setup data ratings ratings-e4 train evaluate calibrate lint test test-all eval-llm up db-up db-down migrate mlflow

help:
	@echo "Targets: setup data ratings ratings-e4 train evaluate calibrate lint test test-all eval-llm up db-up db-down migrate mlflow"

setup:
	uv sync
	uv run pre-commit install

data:
	uv run python -m pipeline.build_dataset

# Real LLM calls (a few cents with Claude Haiku). Review the output before committing.
ratings:
	uv run python -m pipeline.wikipedia
	uv run python -m pipeline.ratings

# E4: rate again with the traits in reverse order, then compare the two runs.
ratings-e4:
	uv run python -m pipeline.ratings --variant b
	uv run python -m pipeline.rating_consistency

train:
	@echo "train: not implemented yet (training/train.py --config $(CONFIG))"

evaluate:
	@echo "evaluate: not implemented yet (training/evaluate.py)"

calibrate:
	@echo "calibrate: not implemented yet (training/calibrate.py)"

lint:
	uv run ruff check .
	uv run ruff format --check .
	uv run mypy app pipeline

test:
	uv run pytest -m "not slow" --cov=app

test-all:
	uv run pytest --cov=app

eval-llm:
	@echo "eval-llm: not implemented yet (eval/grounding_check.py + parsing eval)"

up:
	@echo "up: not implemented yet (needs Dockerfile and docker-compose.yml)"

db-up:
	docker compose up -d db

db-down:
	docker compose down

migrate:
	uv run alembic upgrade head

mlflow:
	@echo "mlflow: not implemented yet (install the ml group first: uv sync --group ml)"
