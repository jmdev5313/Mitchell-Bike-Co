"""What every eval shares: checks, the report of one run, and recording a turn."""

import sqlite3
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from datetime import date

from agents.runtime import AgentRuntime, TurnResult


@dataclass
class Check:
    name: str
    passed: bool
    detail: str = ""
    required: bool = True


@dataclass
class Report:
    runtime: str
    model: str | None
    conversation_id: str
    checks: list[Check] = field(default_factory=list)
    turns: list[dict] = field(default_factory=list)
    usage: dict[str, int] = field(default_factory=dict)
    cost_usd: float | None = None

    @property
    def passed(self) -> bool:
        return all(c.passed for c in self.checks if c.required)

    def add(self, name: str, passed: bool, detail: str = "", required: bool = True) -> bool:
        self.checks.append(Check(name, bool(passed), detail, required))
        return bool(passed)


def record_turn(report: Report, result: TurnResult) -> None:
    report.turns.append({
        "reply": result.reply,
        "stop_reason": result.stop_reason,
        "tools": [c.name + (" (refused)" if c.is_error else "") for c in result.tool_calls],
        "progress": result.progress,
    })
    for key, value in result.usage.items():
        report.usage[key] = report.usage.get(key, 0) + value


def date_mentions(day: date) -> list[str]:
    """Ways a message might write `day`: 2026-11-18, November 18, Nov 18, 18 November."""
    return [
        day.isoformat(),
        f"{day:%B} {day.day}", f"{day:%b} {day.day}",
        f"{day.day} {day:%B}", f"{day.day} {day:%b}",
    ]


@dataclass(frozen=True)
class Scenario:
    """One eval: how to play it against an open runtime, and any state to set up first."""

    key: str
    group: str
    title: str
    play: Callable[[AgentRuntime, sqlite3.Connection, "Report", date], Awaitable[None]]
    setup: Callable[[sqlite3.Connection, date], None] | None = None
