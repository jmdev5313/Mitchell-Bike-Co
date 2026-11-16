.PHONY: help db seed reset test servers demo agent agent-check api web evals

help:
	@echo "make db      Create the SQLite database from shop/schema.sql"
	@echo "make seed    Load seed data into the database"
	@echo "make reset   Delete, rebuild, and seed the database"
	@echo "make test    Run unit tests"
	@echo "make servers Run the three MCP servers over HTTP (ports 8101-8103)"
	@echo "make demo    Run the hero story through the MCP servers"
	@echo "make agent   Chat with the Agent as the Mechanic (uses your API key)"
	@echo "make agent-check  Run the hero story against the real model and check the outcome (spends tokens)"
	@echo "make api     Run the API on http://127.0.0.1:8000 (docs at /docs)"
	@echo "make web     Run the frontend (not built yet)"
	@echo "make evals   Run the eval suite (not built yet)"

db:
	uv run python -m shop.db init

seed:
	uv run python -m shop.seed

reset:
	uv run python -m shop.seed --reset

test:
	uv run pytest

servers:
	uv run python -m mcp_servers.catalog --http & \
	uv run python -m mcp_servers.work_orders --http & \
	uv run python -m mcp_servers.procurement --http & \
	wait

demo:
	uv run python -m demo.hero

agent:
	uv run python -m agents.cli $(ARGS)

agent-check:
	uv run python -m evals.hero $(ARGS)

api:
	uv run uvicorn api.app:app --reload --port 8000

web:
	@echo "Not built yet: M6 (web)"

evals:
	@echo "Not built yet: M5 (evals)"
