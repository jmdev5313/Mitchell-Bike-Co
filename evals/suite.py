"""The eval suite: scenarios played against the real model, judged by what ends up in the shop.

Each run of a scenario starts from a fresh copy of the seed data in its own database,
plays one or more Mechanic turns (acting out the Mechanic's sends and the Customer's
answers in between), and then reads the shop's state: work order lines, the quote,
drafted messages, orders, refusals. Required checks decide whether a run passes;
advisory checks are noted. Each scenario runs several times, so the result is a pass
rate, and the whole suite is saved to evals/results/suite-<time>.json.

It spends real tokens. Run: make evals   (ARGS="--only stock-wheels --runs 1", or --list)
"""

import argparse
import asyncio
import importlib
import json
import os
import pkgutil
import sys
from collections.abc import Callable
from dataclasses import asdict
from datetime import date, datetime, timezone
from pathlib import Path

from agents import config
from agents.runtime import AgentRuntime, open_agent
from evals.common import Report, Scenario
from evals.pricing import cost_usd
from shop import db, seed

RUN_DB = Path(os.environ.get("EVAL_DB_PATH", "data/eval.db"))
RESULTS_DIR = Path("evals/results")
LATEST = Path("evals/latest.json")  # committed: the newest full-suite pass rates, for the front door and README
GROUPS = ("story", "compatibility", "diagnosis", "guardrails", "procurement")


def discover() -> list[Scenario]:
    """Every SCENARIO under evals/scenarios/<group>/, in group order."""
    import evals.scenarios as package

    found = []
    for info in pkgutil.walk_packages(package.__path__, package.__name__ + "."):
        module = importlib.import_module(info.name)
        if isinstance(getattr(module, "SCENARIO", None), Scenario):
            found.append(module.SCENARIO)
    return sorted(found, key=lambda s: (GROUPS.index(s.group) if s.group in GROUPS else len(GROUPS), s.key))


def fresh_database(path: Path = RUN_DB) -> Path:
    path.unlink(missing_ok=True)
    conn = db.connect(db.init(path))
    seed.load(conn)
    conn.close()
    os.environ["DB_PATH"] = str(path)  # the MCP servers the runtime starts read it
    return path


async def run_once(scenario: Scenario, make_agent: Callable[[], AgentRuntime], today: date) -> Report:
    """One run of a scenario, on whatever database DB_PATH points at."""
    conn = db.connect()
    if scenario.setup:
        scenario.setup(conn, today)
    agent = make_agent()
    report = None
    try:
        async with agent:
            report = Report(agent.name, getattr(agent, "model", None), agent.conversation_id)
            await scenario.play(agent, conn, report, today)
    except Exception as e:  # a crash is a failed run, with the reason kept
        report = report or Report(getattr(agent, "name", "?"), getattr(agent, "model", None), "")
        report.add("ran without an error", False, f"{type(e).__name__}: {e}")
    if report.conversation_id:
        refused = conn.execute(
            "SELECT COUNT(*) FROM audit_log WHERE conversation_id = ? AND result_summary LIKE 'refused:%'",
            (report.conversation_id,),
        ).fetchone()[0]
        report.add("tool calls the shop refused", True, f"{refused} refused", required=False)
    conn.close()
    if report.model:
        report.cost_usd = cost_usd(report.model, report.usage)
    return report


def summarize(scenario: Scenario, reports: list[Report]) -> dict:
    checks: dict[str, dict] = {}
    for report in reports:
        for c in report.checks:
            entry = checks.setdefault(c.name, {"required": c.required, "passed": 0, "runs": 0, "failures": []})
            entry["runs"] += 1
            entry["passed"] += c.passed
            if not c.passed and c.detail:
                entry["failures"].append(c.detail[:300])
    return {
        "key": scenario.key, "group": scenario.group, "title": scenario.title,
        "runs": len(reports), "passed_runs": sum(r.passed for r in reports),
        "cost_usd": round(sum(r.cost_usd or 0 for r in reports), 4),
        "checks": checks,
        "reports": [{**asdict(r), "passed": r.passed} for r in reports],
    }


async def run_suite(scenarios: list[Scenario], runs: int, make_agent: Callable[[], AgentRuntime],
                    today: date | None = None, fresh: Callable[[], object] = fresh_database) -> dict:
    today = today or date.today()
    results = []
    for scenario in scenarios:
        reports = []
        for i in range(runs):
            fresh()
            print(f"  {scenario.key} run {i + 1} of {runs}…", flush=True)
            reports.append(await run_once(scenario, make_agent, today))
        results.append(summarize(scenario, reports))
    models = {r["model"] for s in results for r in s["reports"] if r["model"]}
    return {
        "suite": True,
        "ran_at": datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ"),
        "today": today.isoformat(),
        "model": ", ".join(sorted(models)) or None,
        "runs_per_scenario": runs,
        "passed_runs": sum(s["passed_runs"] for s in results),
        "total_runs": sum(s["runs"] for s in results),
        "cost_usd": round(sum(s["cost_usd"] for s in results), 4),
        "scenarios": results,
    }


def print_summary(result: dict) -> None:
    print(f"\nEval suite on {result['model']}: {result['runs_per_scenario']} run(s) per scenario\n")
    for s in result["scenarios"]:
        print(f"  {s['passed_runs']}/{s['runs']}  {s['group']:<13} {s['title']}")
        for name, c in s["checks"].items():
            if c["required"] and c["passed"] < c["runs"]:
                print(f"         failed {c['runs'] - c['passed']}x: {name}" + (f"  ({c['failures'][0]})" if c["failures"] else ""))
    print(f"\n{result['passed_runs']} of {result['total_runs']} runs passed. Estimated cost ${result['cost_usd']:.2f}")


def save(result: dict) -> Path:
    RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    path = RESULTS_DIR / f"suite-{result['ran_at']}.json"
    path.write_text(json.dumps(result, indent=2, default=str))
    return path


def compact(result: dict) -> dict:
    """The pass rates without the transcripts: small enough to commit and show on the site."""
    keep = ("ran_at", "model", "runs_per_scenario", "passed_runs", "total_runs", "cost_usd")
    return {**{k: result[k] for k in keep}, "scenarios": [
        {k: s[k] for k in ("key", "group", "title", "passed_runs", "runs")} for s in result["scenarios"]]}


def write_latest(result: dict, path: Path = LATEST) -> Path:
    path.write_text(json.dumps(compact(result), indent=2) + "\n")
    return path


def markdown_table(latest: dict) -> str:
    """The README's results table, from evals/latest.json."""
    rows = [f"| {s['title']} | {s['group']} | {s['passed_runs']}/{s['runs']} |" for s in latest["scenarios"]]
    day = latest["ran_at"][:8]
    return "\n".join([
        "| Scenario | Group | Passed |", "| --- | --- | --- |", *rows, "",
        f"{latest['passed_runs']} of {latest['total_runs']} runs passed on {latest['model']}, "
        f"{latest['runs_per_scenario']} runs per scenario, {day[:4]}-{day[4:6]}-{day[6:]}. "
        f"Estimated cost of the whole suite: ${latest['cost_usd']:.2f}.",
    ])


async def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(description="Run the eval suite against the real model (spends tokens).")
    parser.add_argument("--runtime", default="anthropic")
    parser.add_argument("--runs", type=int, default=3, help="runs per scenario (default 3)")
    parser.add_argument("--only", nargs="*", default=None, help="scenario keys or groups to run")
    parser.add_argument("--list", action="store_true", help="list the scenarios and stop")
    parser.add_argument("--table", action="store_true", help="print the README results table from evals/latest.json")
    args = parser.parse_args(argv)
    if args.table:
        print(markdown_table(json.loads(LATEST.read_text())))
        return 0

    scenarios = discover()
    if args.only:
        scenarios = [s for s in scenarios if s.key in args.only or s.group in args.only]
    if args.list or not scenarios:
        for s in scenarios:
            print(f"{s.key:<20} {s.group:<13} {s.title}")
        return 0 if scenarios else 1

    config.load_env()
    result = await run_suite(scenarios, args.runs, lambda: open_agent(args.runtime))
    print_summary(result)
    print(f"Saved {save(result)}")
    if not args.only:  # only a full run speaks for the whole suite
        print(f"Updated {write_latest(result)}")
    return 0 if result["passed_runs"] == result["total_runs"] else 1


if __name__ == "__main__":
    sys.exit(asyncio.run(main(sys.argv[1:])))
