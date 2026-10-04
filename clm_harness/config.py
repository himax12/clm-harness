from __future__ import annotations

from dataclasses import dataclass

# Dollars per million tokens. `cache_write` is the 5-minute rate (1.25 x input).
# Input, output and the cache-read rates for Opus 5.5, Sonnet 5.5 and Fable 5.1 are
# Anthropic's published figures. The Opus 5 and Opus 4.8 cache-read rates are the usual
# 0.1 x input and have not been checked; they only matter on a fallback turn.
# Haiku 4.5: input and output are published; its cache-read rate is the same assumption.
# It is priced here but cannot be run yet: it rejects the `effort` setting and adaptive
# thinking that the request in llm.py sends.
MODEL_PRICES = {
    "claude-haiku-4-5": {"input": 1.0, "output": 5.0, "cache_read": 0.10, "cache_write": 1.25},
    "claude-opus-5-5": {"input": 4.0, "output": 20.0, "cache_read": 0.20, "cache_write": 5.0},
    "claude-sonnet-5-5": {"input": 2.0, "output": 10.0, "cache_read": 0.20, "cache_write": 2.5},
    "claude-fable-5-1": {"input": 10.0, "output": 50.0, "cache_read": 0.25, "cache_write": 12.5},
    "claude-opus-5": {"input": 5.0, "output": 25.0, "cache_read": 0.50, "cache_write": 6.25},
    "claude-opus-4-8": {"input": 5.0, "output": 25.0, "cache_read": 0.50, "cache_write": 6.25},
}
PRICES = MODEL_PRICES["claude-opus-5-5"]
TESTED_MODELS = ("claude-opus-5-5",)  # the only model the request shape has been run against
SANDBOX_IMAGE = "clm-harness-sandbox:1"  # bump the tag when the Dockerfile in sandbox.py changes


def prices_for(model: str | None) -> tuple[dict[str, float], bool]:
    """The price table for a model, and whether it is a known one.

    An unknown model is priced as Opus 5.5 so that cost limits still work; the
    caller is told the figure is a guess.
    """
    if model in MODEL_PRICES:
        return MODEL_PRICES[model], True
    return PRICES, not model


@dataclass(frozen=True)
class Config:
    model: str = "claude-opus-5-5"
    effort: str = "medium"
    max_tokens: int = 16_000
    mode: str = "clm"  # "clm" | "baseline"
    budget_tokens: int = 32_000
    reserve_tokens: int = 2_048
    nudge_tiers: tuple[float, ...] = (0.25, 0.50, 0.75)
    max_steps: int = 64
    max_cost_usd: float = 5.0
    max_wall_seconds: int = 1_800
    command_timeout: int = 120
    inline_chars: int = 10_000
    head_chars: int = 5_000
    tail_chars: int = 5_000
    rollback_margin: int = 2_048
    max_rollbacks: int = 6
    max_free_edits_in_row: int = 3
    max_refused_edits_in_row: int = 3
    max_output_bytes: int = 10_000_000  # a command printing more than this is killed
    confirm: bool = False
    allow_push: bool = False  # `git push` is refused unless this is set
    # Secret-looking environment variables the agent's commands may see after all.
    env_passthrough: tuple[str, ...] = ()
    sandbox: str = "none"  # "none": commands run on the host | "docker": in a container
    sandbox_image: str = SANDBOX_IMAGE  # the default is built on first use
    sandbox_network: bool = False  # the container has no network unless this is set
    sandbox_memory: str = "2g"
    sandbox_cpus: float = 2.0
    sandbox_pids: int = 512

    def __post_init__(self) -> None:
        problems = []
        if self.sandbox not in ("none", "docker"):
            problems.append(f"sandbox must be none or docker, not {self.sandbox!r}")
        if self.sandbox_cpus <= 0 or self.sandbox_pids <= 0:
            problems.append("sandbox_cpus and sandbox_pids must be positive")
        if self.mode not in ("clm", "baseline"):
            problems.append(f"mode must be clm or baseline, not {self.mode!r}")
        if self.effort not in ("low", "medium", "high", "xhigh", "max"):
            problems.append(f"effort must be low, medium, high, xhigh or max, not {self.effort!r}")
        if self.budget_tokens - self.reserve_tokens < 2_000:
            problems.append(
                f"budget_tokens ({self.budget_tokens}) must exceed reserve_tokens "
                f"({self.reserve_tokens}) by at least 2,000"
            )
        for name in ("max_tokens", "max_steps", "command_timeout", "max_output_bytes",
                     "inline_chars", "max_rollbacks"):
            if getattr(self, name) <= 0:
                problems.append(f"{name} must be positive")
        if self.max_cost_usd <= 0:
            problems.append("max_cost_usd must be positive")
        if self.max_wall_seconds < 0:
            problems.append("max_wall_seconds must not be negative")
        if self.head_chars + self.tail_chars > self.inline_chars:
            problems.append("head_chars + tail_chars must not exceed inline_chars")
        if any(not 0 < t < 1 for t in self.nudge_tiers):
            problems.append("nudge_tiers must each be between 0 and 1")
        if problems:
            raise ValueError("invalid configuration: " + "; ".join(problems))

    @property
    def limit(self) -> int:
        """The enforced context limit: the budget minus the reserve."""
        return self.budget_tokens - self.reserve_tokens

    @property
    def lm_call_cap(self) -> int:
        return 2 * self.max_steps + 24
