"""Settings for the Agent, read from the environment and the project's .env file."""

import os
from pathlib import Path

PROMPTS = Path(__file__).with_name("prompts")
DEFAULT_MODEL = "claude-sonnet-5-5"
DEFAULT_EFFORT = "medium"


def load_env(path: Path = Path(".env")) -> None:
    """Load KEY=VALUE lines from .env into the environment, without overriding what is set.

    Whitespace around keys and values is stripped, so `KEY= value` works.
    """
    if not path.exists():
        return
    for line in path.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key, value = key.strip(), value.strip().strip('"').strip("'")
        if key and value and key not in os.environ:
            os.environ[key] = value


def agent_model() -> str:
    return os.environ.get("AGENT_MODEL") or DEFAULT_MODEL


def agent_effort() -> str:
    return os.environ.get("AGENT_EFFORT") or DEFAULT_EFFORT


def system_prompt() -> str:
    return (PROMPTS / "service_agent.md").read_text()
