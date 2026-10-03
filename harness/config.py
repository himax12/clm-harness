from __future__ import annotations

from dataclasses import dataclass

# Dollars per million tokens for claude-opus-5-5.
PRICES = {"input": 4.0, "output": 20.0, "cache_read": 0.20, "cache_write": 5.0}


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
    confirm: bool = False

    @property
    def limit(self) -> int:
        """The enforced context limit: the budget minus the reserve."""
        return self.budget_tokens - self.reserve_tokens

    @property
    def lm_call_cap(self) -> int:
        return 2 * self.max_steps + 24
