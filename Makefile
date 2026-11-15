.PHONY: help db seed test servers api web evals

help:
	@echo "make db      Create the SQLite database from shop/schema.sql"
	@echo "make seed    Load seed data (not built yet)"
	@echo "make test    Run unit tests"
	@echo "make servers Run the MCP servers (not built yet)"
	@echo "make api     Run the API (not built yet)"
	@echo "make web     Run the frontend (not built yet)"
	@echo "make evals   Run the eval suite (not built yet)"

db:
	uv run python -m shop.db init

seed:
	@echo "Not built yet: day 1"

test:
	uv run pytest

servers:
	@echo "Not built yet: days 2-3"

api:
	@echo "Not built yet: day 6"

web:
	@echo "Not built yet: day 8"

evals:
	@echo "Not built yet: day 7"
