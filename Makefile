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
	@echo "Not built yet: M1 (seed data and rules)"

test:
	uv run pytest

servers:
	@echo "Not built yet: M2 (MCP servers)"

api:
	@echo "Not built yet: M4 (API)"

web:
	@echo "Not built yet: M6 (web)"

evals:
	@echo "Not built yet: M5 (evals)"
