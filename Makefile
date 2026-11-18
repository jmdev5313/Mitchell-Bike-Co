.PHONY: help db seed reset sample photo test servers demo agent agent-check api web evals record

help:
	@echo "make db      Create the SQLite database from shop/schema.sql"
	@echo "make seed    Load seed data into the database"
	@echo "make reset   Delete, rebuild, and seed the database"
	@echo "make sample  Add a quoted hero work order and print its Customer token (ARGS=--done: ready to pay)"
	@echo "make photo SRC=data/photos/raw/<file>  Make the hero photo (1200px JPEG, metadata stripped) from a raw image (macOS)"
	@echo "make test    Run unit tests"
	@echo "make servers Run the three MCP servers over HTTP (ports 8101-8103)"
	@echo "make demo    Run the hero story through the MCP servers"
	@echo "make agent   Chat with the Agent as the Mechanic (uses your API key)"
	@echo "make agent-check  Run the hero story against the real model and check the outcome (spends tokens)"
	@echo "make api     Run the API on http://127.0.0.1:8000 (docs at /docs)"
	@echo "make web     Run the frontend (not built yet)"
	@echo "make record  Record a real run of the Agent on each story, for the hosted demo to replay (spends tokens; ARGS=\"--only <key>\")"
	@echo "make evals   Run the eval suite against the real model, 3 runs per scenario (spends tokens; ARGS=\"--only <key or group> --runs 1\", or --list)"

db:
	uv run python -m shop.db init

seed:
	uv run python -m shop.seed

reset:
	uv run python -m shop.seed --reset

sample:
	uv run python -m demo.sample $(ARGS)

# The hero story's illustrative photo. sips (built into macOS) resizes and re-encodes it, which
# also drops the raw file's metadata. The raw original stays in data/photos/raw/ (gitignored).
photo:
	@test -n "$(SRC)" || (echo "Usage: make photo SRC=data/photos/raw/<file>"; exit 1)
	mkdir -p web/static/img
	sips -Z 1200 -s format jpeg -s formatOptions 80 "$(SRC)" --out web/static/img/hero-cassette.jpg
	@echo "Wrote web/static/img/hero-cassette.jpg. It's shown as an illustrative, AI-generated photo."

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
	uv run python -m evals.suite $(ARGS)

record:
	uv run python -m demo.record $(ARGS)
