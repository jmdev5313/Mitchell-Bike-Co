"""What every shop MCP server shares: database access, error handling, the audit log.

Tools are plain functions whose first parameter is a database connection. The
`shop_tool` decorator opens the connection, turns shop errors into tool errors
the model can read, and writes every call to `audit_log`, so the record is the
same whichever agent runtime is calling.
"""

import argparse
import functools
import inspect
import json
import os
import sqlite3
from collections.abc import Callable
from typing import Any

from mcp.server.mcpserver import MCPServer
from mcp.server.mcpserver.exceptions import ToolError

from agents import activity
from shop import db, events
from shop.errors import NotFound, RuleViolation

SUMMARY_LIMIT = 500


def new_server(name: str, instructions: str) -> MCPServer:
    """A shop server. MCP_LOG_LEVEL (default INFO) sets how much it logs to stderr."""
    return MCPServer(name, instructions=instructions, log_level=os.environ.get("MCP_LOG_LEVEL", "INFO"))


def shop_tool(server: MCPServer) -> Callable:
    """Register `fn(conn, **args)` as a tool on `server`, with errors mapped and calls audited."""

    def decorator(fn: Callable) -> Callable:
        name = fn.__name__
        signature = inspect.signature(fn)
        params = list(signature.parameters.values())[1:]  # drop `conn`; the model never sees it

        @functools.wraps(fn)
        def tool(**kwargs: Any) -> Any:
            conn = db.connect()
            try:
                try:
                    result = fn(conn, **kwargs)
                except (NotFound, RuleViolation) as e:
                    _audit(conn, name, kwargs, f"refused: {e}")
                    _work_order_event(conn, name, kwargs, None, str(e))
                    raise ToolError(str(e)) from e
                except Exception as e:
                    _audit(conn, name, kwargs, f"error: {type(e).__name__}")
                    raise
                _audit(conn, name, kwargs, _summarize(result))
                _work_order_event(conn, name, kwargs, result, None)
                return result
            finally:
                conn.close()

        tool.__signature__ = signature.replace(parameters=params)
        server.tool()(tool)
        return fn

    return decorator


def run(server: MCPServer, default_port: int) -> None:
    """Command line entry point: stdio by default, or Streamable HTTP with --http."""
    parser = argparse.ArgumentParser(description=server.name)
    parser.add_argument("--http", action="store_true", help="serve Streamable HTTP instead of stdio")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=default_port)
    args = parser.parse_args()
    if args.http:
        server.run("streamable-http", host=args.host, port=args.port)
    else:
        server.run()


def _audit(conn: sqlite3.Connection, tool: str, args: dict, summary: str) -> None:
    with conn:
        conn.execute(
            """INSERT INTO audit_log (conversation_id, runtime, tool, args_json, result_summary)
               VALUES (?, ?, ?, ?, ?)""",
            (
                os.environ.get("CONVERSATION_ID"),
                os.environ.get("AGENT_RUNTIME"),
                tool,
                json.dumps(args, sort_keys=True, default=str),
                summary,
            ),
        )


def _work_order_event(conn: sqlite3.Connection, tool: str, args: dict, result: Any, error: str | None) -> None:
    """Add the agent's tool call to the work order's history, when it concerns one."""
    work_order_id = args.get("work_order_id")
    if work_order_id is None and isinstance(result, dict):
        work_order_id = result.get("work_order_id")
    if not isinstance(work_order_id, int) or tool.startswith(("get_", "list_")):
        return  # lookups aren't history
    if not conn.execute("SELECT 1 FROM work_orders WHERE id = ?", (work_order_id,)).fetchone():
        return
    text = error if error is not None else json.dumps(result, default=str)
    events.record(
        conn, work_order_id, "agent", f"tool:{tool}",
        activity.describe(tool, args, text, error is not None),
        {"tool": tool, "server": activity.server_for(tool)}, is_error=error is not None,
    )


def _summarize(result: Any) -> str:
    text = json.dumps(result, sort_keys=True, default=str)
    return text if len(text) <= SUMMARY_LIMIT else text[: SUMMARY_LIMIT - 3] + "..."
