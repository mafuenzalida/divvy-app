.PHONY: dev test lint

dev:
	uvicorn main:app --reload --port 8000

test:
	pytest tests/ -q

lint:
	ruff check app db.py main.py tests
