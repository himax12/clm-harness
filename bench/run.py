from __future__ import annotations

import csv
import json
import time
from pathlib import Path
from typing import Callable

from harness.baseline import make_compactor
from harness.config import Config
from harness.loop import Model, run

from . import kv_store, ledger
from .common import StreamDriver, check_sizing, score, sized_for

TASKS = {"kv": kv_store, "ledger": ledger}
COLUMNS = [
    "task", "mode", "seed", "pressure", "ops", "status", "accuracy", "dollars",
    "input", "output", "cache_read", "cache_write", "model_calls", "steps",
    "edits_applied", "edits_refused", "reread_tokens", "rollbacks", "seconds",
    "served_by_fallback", "session",
]


def bench_config(mode: str, max_cost: float) -> Config:
    # A stream of ~50-100 operations needs far more turns than an ordinary task.
    return Config(mode=mode, max_steps=400, max_cost_usd=max_cost, max_wall_seconds=3_600)


def run_one(task: str, mode: str, seed: int, pressure: float, out_dir: Path,
            make_model: Callable[[Config], Model], max_cost: float) -> dict:
    module = TASKS[task]
    cfg = bench_config(mode, max_cost)
    ops = sized_for(module.generate, seed, pressure, cfg.budget_tokens)
    check_sizing(ops, cfg.limit)

    workdir = out_dir / "runs" / f"{task}-{mode}-{seed}"
    workdir.mkdir(parents=True, exist_ok=True)
    model = make_model(cfg)
    summarise = getattr(model, "summarise", None)
    compactor = make_compactor(summarise) if mode == "baseline" else None

    started = time.monotonic()
    result = run(module.TASK, workdir, cfg, model, driver=StreamDriver(ops), compactor=compactor)
    seconds = time.monotonic() - started

    stats = json.loads((result.session_dir / "usage.json").read_text())
    transcript = result.session_dir / "transcript.jsonl"
    fallback = any(
        json.loads(line).get("served_by") not in ("", None, cfg.model)
        for line in transcript.read_text(encoding="utf-8").splitlines()
        if '"type": "reply"' in line
    )
    return {
        "task": task, "mode": mode, "seed": seed, "pressure": pressure, "ops": len(ops),
        "status": result.status, "accuracy": round(score(ops, transcript), 4),
        "dollars": round(result.dollars, 4),
        "input": result.usage.input, "output": result.usage.output,
        "cache_read": result.usage.cache_read, "cache_write": result.usage.cache_write,
        "model_calls": stats.get("model_calls", 0), "steps": stats.get("steps", 0),
        "edits_applied": stats.get("edits_applied", 0),
        "edits_refused": stats.get("edits_refused", 0),
        "reread_tokens": stats.get("reread_tokens", 0),
        "rollbacks": stats.get("rollbacks", 0), "seconds": round(seconds, 1),
        "served_by_fallback": fallback, "session": result.session_dir.name,
    }


def run_matrix(tasks: list[str], modes: list[str], seeds: list[int], pressure: float,
               ceiling_usd: float, out_dir: Path, make_model: Callable[[Config], Model],
               max_cost_per_run: float = 8.0) -> list[dict]:
    """Run every (task, mode, seed). Stops before a run that could breach the spend ceiling."""
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    csv_path = out_dir / "results.csv"
    rows: list[dict] = []
    spent = 0.0
    with csv_path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=COLUMNS)
        writer.writeheader()
        for task in tasks:
            for mode in modes:
                for seed in seeds:
                    if spent + max_cost_per_run > ceiling_usd:
                        print(f"skipped {task}/{mode}/{seed}: spend ceiling "
                              f"(${spent:.2f} of ${ceiling_usd:.2f} used)")
                        continue
                    row = run_one(task, mode, seed, pressure, out_dir, make_model,
                                  max_cost_per_run)
                    spent += row["dollars"]
                    rows.append(row)
                    writer.writerow(row)
                    f.flush()
                    print(f"{task}/{mode}/{seed}: {row['status']}, accuracy "
                          f"{row['accuracy']:.0%}, ${row['dollars']:.2f}")
    return rows


def report(csv_path: Path) -> str:
    """Per task and mode: mean and range of accuracy and dollars, and edit statistics."""
    with Path(csv_path).open(encoding="utf-8") as f:
        rows = list(csv.DictReader(f))
    groups: dict[tuple[str, str], list[dict]] = {}
    for r in rows:
        groups.setdefault((r["task"], r["mode"]), []).append(r)

    def stat(rs: list[dict], col: str) -> str:
        xs = [float(r[col]) for r in rs]
        return f"{sum(xs) / len(xs):.2f} ({min(xs):.2f}-{max(xs):.2f})"

    lines = ["task    mode      runs  accuracy            dollars             edits  rollbacks"]
    for (task, mode), rs in sorted(groups.items()):
        edits = sum(int(r["edits_applied"]) for r in rs) / len(rs)
        rollbacks = sum(int(r["rollbacks"]) for r in rs) / len(rs)
        lines.append(f"{task:<7} {mode:<9} {len(rs):<5} {stat(rs, 'accuracy'):<19} "
                     f"{stat(rs, 'dollars'):<19} {edits:<6.1f} {rollbacks:.1f}")
    return "\n".join(lines)
