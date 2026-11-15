"""The hero demo, run as a user would: real stdio server processes."""

import os
import subprocess
import sys


def test_demo_runs_the_hero_story(tmp_path):
    env = {**os.environ, "DEMO_DB_PATH": str(tmp_path / "demo.db")}
    result = subprocess.run(
        [sys.executable, "-m", "demo.hero"], env=env, capture_output=True, text=True, timeout=120
    )
    assert result.returncode == 0, result.stderr
    out = result.stdout
    assert "add_part -> REFUSED" in out and "does not fit this bike" in out
    assert "create_purchase_order -> REFUSED" in out and "after the customer approves" in out
    assert "is now awaiting_parts" in out
    assert "16 tool calls recorded, 2 refused" in out
    assert "Tool 'add_part' failed" not in result.stderr  # server logs are quiet in the demo
