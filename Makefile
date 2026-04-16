.PHONY: setup install test test-unit lint format typecheck health clean

setup: install
	@echo "Setup complete. Copy .env.example to .env and fill in credentials."

install:
	python -m venv .venv
	. .venv/bin/activate && pip install --upgrade pip && pip install -r requirements.txt

test: test-unit

test-unit:
	pytest tests/unit -v --cov=src --cov-report=term-missing

lint:
	ruff check src tests cli.py

format:
	black src tests cli.py scripts
	ruff check --fix src tests cli.py

typecheck:
	mypy src/core/auth.py src/core/client.py src/config/

health:
	python cli.py health

clean:
	find . -type d -name __pycache__ -exec rm -rf {} +
	find . -type f -name "*.pyc" -delete
	rm -rf .pytest_cache .mypy_cache .ruff_cache htmlcov
