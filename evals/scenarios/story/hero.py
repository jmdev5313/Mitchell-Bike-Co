"""The hero story: Emma's upgraded wheels need a different cassette than her bike's catalog model."""

from evals import hero
from evals.common import Scenario

SCENARIO = Scenario(
    key="hero",
    group="story",
    title="Upgraded wheels need a different cassette (the hero story)",
    play=hero.play,
)
