# Implementation spec

How each part of the harness in `PLAN.md` is built: data structures, function signatures, algorithms and tests, in phase order. `PLAN.md` says what and why; this file says how.

Conventions: Python 3.12+, standard library plus `anthropic` and `pytest`. Type hints throughout. No module imports `anthropic` except `llm.py` and `baseline.py`.

---

## Phase 0: setup

### `config.py`

One frozen dataclass; every other module takes it as an argument and reads nothing from the environment.

```python
@dataclass(frozen=True)
class Config:
    model: str = "claude-opus-5-5"
    effort: str = "medium"
    max_tokens: int = 16_000
    mode: str = "clm"                    # "clm" | "baseline"
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
    def limit(self) -> int:              # enforced limit: 29,952
        return self.budget_tokens - self.reserve_tokens
    @property
    def lm_call_cap(self) -> int:        # 152
        return 2 * self.max_steps + 24
```

`PRICES = {"input": 4.0, "output": 20.0, "cache_read": 0.20, "cache_write": 5.0}` (dollars per million tokens) lives here too.

---

## Phase 1: the core, without a model

### 1.1 `shell.py`

```python
@dataclass
class CommandResult:
    output: str          # stdout and stderr merged, decoded utf-8 with errors="replace"
    exit_code: int       # -1 on timeout
    timed_out: bool
    seconds: float

class Shell:
    def __init__(self, workdir: Path, session_dir: Path, cfg: Config): ...
    def run(self, command: str) -> CommandResult: ...
    def reset(self) -> None: ...         # forget saved cwd and environment
```

**Finding bash (`find_bash`)**, in order:

1. `HARNESS_BASH` environment variable, if set.
2. `C:\Program Files\Git\bin\bash.exe`, then `C:\Program Files\Git\usr\bin\bash.exe`.
3. `shutil.which("bash")`, rejected if the path contains `System32` or `WindowsApps` (those are WSL launchers).
4. On non-Windows, `/bin/bash`.

Raise a clear error if none is found.

**Paths.** `to_posix(path)` converts `C:\a b\c` to `/c/a b/c` for use inside scripts. All paths written into scripts are double-quoted.

**Running a command.** The model's command is written verbatim to `state/user_cmd.sh`. A fixed wrapper, `state/run.sh`, is generated once per session:

```bash
STATE="<posix path to state dir>"
save_state() { pwd > "$STATE/cwd"; export -p > "$STATE/env.sh"; }
trap save_state EXIT
cd "$(cat "$STATE/cwd" 2>/dev/null)" 2>/dev/null || cd "<posix workdir>"
[ -f "$STATE/env.sh" ] && . "$STATE/env.sh"
export CTX="<posix path to LIVE_CTX.md>" CTX_DIR="<posix session dir>"
export CI=true TERM=dumb PAGER=cat GIT_PAGER=cat
. "$STATE/user_cmd.sh"
```

- The command is sourced, so `cd` and `export` persist. The `EXIT` trap saves state even when the command calls `exit`.
- Launch: `subprocess.Popen([bash, run_sh], stdout=PIPE, stderr=STDOUT, stdin=DEVNULL, creationflags=CREATE_NEW_PROCESS_GROUP)`.
- Wait with `communicate(timeout=cfg.command_timeout)`.
- On timeout: `taskkill /T /F /PID <pid>` (on POSIX, `os.killpg`), then `communicate()` again to collect partial output; return `exit_code=-1, timed_out=True`.

**Formatting the observation**

```python
def format_observation(result: CommandResult, name: str,
                       outputs_dir: Path, cfg: Config) -> str
```

1. `text = result.output.rstrip()` or `"(no output)"`.
2. If `len(text) > cfg.inline_chars`: save the full text to `outputs/turn-NNNN.txt`, then replace with first `head_chars` + `\n... [N characters elided; full output at "$CTX_DIR"/outputs/turn-NNNN.txt] ...\n` + last `tail_chars`.
3. If timed out, append `(timed out after N s; partial output shown)`.
4. Append `(exit_code=N)`.

```python
def cap_to_room(text: str, room_tokens: int, est: Estimator) -> str
```

If the text's estimate exceeds `room_tokens` (floor 128), keep head and tail halves that fit and insert the same elision marker. Called by the loop before the output block is appended.

### 1.2 `context.py`

```python
@dataclass
class Block:
    id: str              # "b0007"
    role: str            # assistant | output | user | notice | note
    body: str
    seq: int             # creation order, never reused

    @property
    def protected(self) -> bool:
        return self.role == "user"

class Context:
    pinned: str                  # the task; never in the file
    rollback_note: str | None    # never in the file
    blocks: list[Block]
    def add(self, role: str, body: str) -> Block: ...   # allocates id and seq
```

**File format**

```
[[CTX v1]]
[[BLOCK id=b0007 role=output tokens=1840]]
<body>

[[BLOCK id=b0008 role=assistant tokens=210]]
<body>
```

- Line 1 is the constant `[[CTX v1]]`. It carries no revision number, because anything that changes at the top of the request would invalidate the prompt cache on every turn.
- `tokens=` is the raw estimate (characters ÷ 4), not the calibrated one, for the same reason: a calibrated figure would change in every header each turn.
- Header regex: `^\[\[BLOCK id=([A-Za-z0-9_-]+) role=([a-z]+)(?: tokens=\d+)?\]\]\s*$` (multiline).

```python
def render(ctx: Context) -> str
def render_block(b: Block) -> str        # header + body; also used to build the request
def parse(text: str) -> list[tuple[str, str, str]]   # (id, role, body); raises ParseError
```

**Applying an edit**

```python
@dataclass
class EditResult:
    status: str              # "unchanged" | "applied" | "refused"
    reason: str              # for the receipt
    before_tokens: int
    after_tokens: int
    first_changed: int | None    # index of the first block that differs
    removed_ids: list[str]

def apply_edit(ctx: Context, rendered: str, file_text: str,
               cfg: Config, est: Estimator) -> EditResult
```

Algorithm:

1. If `file_text.strip() == rendered.strip()`: return `unchanged`.
2. Refuse if line 1 is not exactly `[[CTX v1]]`.
3. Refuse if there is no header at all, or if there is non-blank text between line 1 and the first header.
4. For each parsed block:
   - id starts with `new-`: a new `note` block (role in the header is ignored);
   - id matches an existing block: keep its original role (role in the header is ignored);
   - anything else: refuse (`unknown id`).
5. Refuse on a duplicate id.
6. Refuse if any `user` block is missing or its body differs after stripping whitespace.
7. Drop any block whose body is empty after stripping.
8. Compute `after_tokens`. Refuse if `after_tokens > cfg.limit` and `after_tokens >= before_tokens`. A shrinking edit is accepted even if the result is still over the limit; the receipt then says to compact further.
9. Commit: replace `ctx.blocks` in file order, allocating real ids for new notes. Return `applied` with `first_changed` and `removed_ids`.

Nothing is mutated before step 9, so a refusal leaves the context exactly as it was.

**Receipts** (`receipt(result) -> str`):

| Case | Text |
|---|---|
| Applied, smaller | `[context edit applied: 21,400 -> 9,800 tokens, 14 blocks]` |
| Applied, larger | `[context edit applied but it GREW: 9,800 -> 11,200 tokens. If you meant to condense, you duplicated content instead of replacing it.]` |
| Applied, still over | `[context edit applied: 34,000 -> 31,000 tokens, still over the limit. Compact further now.]` |
| Refused | `[context edit REFUSED: <reason>. Your context is unchanged.]` |
| File touched, no change | `[context file unchanged: your edit matched nothing. Headers look like [[BLOCK id=b0007 role=output tokens=N]].]` |

"File touched" means the command text contains `CTX` or the mirror's modification time changed.

### 1.3 `budget.py`

```python
class Estimator:
    ratio: float = 1.0                       # calibration, clamped to 0.5–3.0
    def raw(self, text: str) -> int          # ceil(len / 4)
    def tokens(self, text: str) -> int       # ceil(raw * ratio)
    def calibrate(self, api_prompt_total: int, raw_request: int) -> None

def context_tokens(ctx: Context, system: str, est: Estimator) -> int
    # system + pinned + rollback note + every rendered block, calibrated
```

**Nudges**

```python
class Nudger:
    fired: set[float]
    def decide(self, tokens: int, recent_outputs: list[int], cfg: Config) -> str | None
```

1. Re-arm: remove from `fired` any tier the context is now below.
2. Urgent: `need = min(max(0.10 * limit, 2 * max(recent_outputs[-3:], default=0)), 0.50 * limit)`. If `limit - tokens < need`, return the urgent text. Fires every turn while true.
3. Otherwise the highest tier in `cfg.nudge_tiers` that is crossed and not yet fired; mark it and all lower tiers fired.
4. At most one notice per turn.

Texts:

| Tier | Text |
|---|---|
| 25% | `Context is at about 25% of the limit. No action needed. Make sure your tracker records what you have already tried.` |
| 50% | `Context is at about 50% of the limit. Finish the unit of work in flight, then tidy once.` |
| 75% | `Context is at about 75% of the limit. Compact settled spans now, but do not wipe: shorten stale output in place and copy exact facts forward.` |
| Urgent | `Context is at T / L tokens and about to overflow. Compact this turn and do nothing else, or your newest turns will be rolled back.` |

**Rollback**

```python
def rollback(ctx: Context, system: str, est: Estimator, cfg: Config,
             consecutive: int) -> list[Block]
```

1. `margin = cfg.rollback_margin`; if `consecutive > 3`, `margin *= (consecutive - 3)`, capped at `0.75 * limit`.
2. Pop the newest non-`user` block until `context_tokens <= limit - margin` or no such block remains. `user` blocks are never dropped.
3. Collect the commands from the dropped `assistant` blocks: up to 5 most recent distinct ones, whitespace collapsed, cut to 70 characters.
4. Set `ctx.rollback_note`:

```
[CONTEXT LIMIT HIT, retry i/N] Your newest K blocks were rolled back and are gone.
Condense your context this turn and do nothing else.
These commands already ran and their output is what overflowed; do not re-run them
unchanged. If you need one, make it print far less (head, grep, count):
  - <command>
```

5. Return the dropped blocks (the loop logs them; their originals remain in `blocks/`).

If nothing can be dropped and the context is still over the limit, the loop stops with status `context_exhausted`.

### 1.4 `session.py`

```python
class Session:
    dir: Path
    def __init__(self, workdir: Path, cfg: Config): ...   # creates .ctx/sessions/<id>/
    def event(self, type: str, turn: int, **fields) -> None   # one JSON line, flushed
    def save_block(self, b: Block) -> None                    # blocks/<id>.txt, written once
    def snapshot(self, turn: int, blocks_before: list[Block]) -> None
    def add_usage(self, usage: Usage) -> None
    def write_usage(self) -> None
```

- Session id: UTC timestamp plus 4 random hex characters.
- Event line: `{"ts": ..., "turn": n, "type": ..., ...}`. Types: `start`, `reply`, `command`, `output`, `edit_applied`, `edit_refused`, `notice`, `rollback`, `usage`, `undo`, `finish`.
- `edit_applied` carries `before_tokens`, `after_tokens`, `first_changed`, `removed_ids` and `reread_tokens` (the tokens from `first_changed` to the end, which is what the edit costs to re-read).
- Snapshot: `snapshots/turn-NNNN.json`, the full block list as it was before the edit.

```python
@dataclass
class Usage:
    input: int = 0; output: int = 0; cache_read: int = 0; cache_write: int = 0
    def cost(self) -> float      # each bucket × PRICES / 1e6
```

`usage.json` holds the summed `Usage`, dollars, steps, model calls, edits (applied, refused, grew), free turns, rollbacks and final status.

**Undo** (`undo(session_dir)`): load the latest snapshot, keep any block created after it (higher `seq`) that still exists, write the result to `LIVE_CTX.md`, record an `undo` event. Until session resume exists, this only demonstrates that an edit is reversible; it becomes operational with resume.

### 1.5 `safety.py`

```python
def blocked(command: str) -> str | None      # the reason, or None
def confirm(command: str) -> bool            # prints the command, reads y/n
```

`blocked` checks the whitespace-collapsed command against a small regex list:

- `rm` with a recursive flag whose target is `/`, `/*`, `~`, `$HOME` or a drive root;
- `mkfs`, `dd ... of=/dev/`, a fork bomb (`:(){ :|:& };:`);
- `shutdown`, `reboot`, `format <drive>:`.

A blocked command is not run; the output block reads `[command blocked: <reason>]` and the turn costs a step.

### 1.6 `loop.py`

```python
@dataclass
class ModelReply:
    text: str
    thinking: str
    command: str | None
    restart: bool
    stop_reason: str         # tool_use | end_turn | max_tokens | refusal
    usage: Usage
    served_by: str           # model id; differs from cfg.model when a fallback ran

class Model(Protocol):
    def reply(self, system: str, ctx: Context) -> ModelReply: ...

class TaskDriver(Protocol):
    def after_command(self, command: str, observation: str) -> str | None: ...
        # return text for a new user block, or None

@dataclass
class RunResult:
    status: str    # finished | step_limit | call_limit | cost_limit | time_limit
                   # | context_exhausted | refusal | error
    answer: str
    usage: Usage

def run(task: str, workdir: Path, cfg: Config, model: Model,
        driver: TaskDriver | None = None) -> RunResult
```

Loop body, with the counters it maintains (`step`, `calls`, `free_in_row`, `refused_in_row`, `rollbacks_in_row`, `truncated_in_row`):

```
while True:
    stop if step >= max_steps, calls >= lm_call_cap, cost >= max_cost, or time is up

    if cfg.mode == "baseline": baseline.maybe_compact(ctx, ...)
    tokens = context_tokens(ctx)
    if tokens > limit:
        dropped = rollback(...)
        if nothing dropped: stop with context_exhausted
        if total rollbacks > max_rollbacks: stop with context_exhausted
        log rollback; continue

    if cfg.mode == "clm":
        notice = nudger.decide(tokens, recent_outputs)
        if notice: ctx.add("notice", notice)
        rendered = render(ctx); write LIVE_CTX.md

    reply = model.reply(system, ctx); calls += 1; add usage; calibrate

    if reply.stop_reason == "refusal": stop with refusal
    if reply.stop_reason == "max_tokens":
        truncated_in_row += 1
        if truncated_in_row > 2: stop with error
        continue                      # never run a command from a cut-off reply
    if reply.command is None and not reply.restart:
        stop with finished, answer = reply.text

    if reply.restart: shell.reset(); observation = "(shell state reset)"
    else:
        reason = safety.blocked(command)
        if reason: observation = "[command blocked: ...]"
        elif cfg.confirm and not safety.confirm(command): observation = "[command declined by user]"
        else: observation = format_observation(shell.run(command), ...)

    edit = None
    if cfg.mode == "clm":
        before = copy of ctx.blocks
        edit = apply_edit(ctx, rendered, read LIVE_CTX.md, ...)
        if edit.status == "applied": session.snapshot(turn, before); refused_in_row = 0
        if edit.status == "refused": refused_in_row += 1

    assistant = ctx.add("assistant", thinking + text + "$ " + command)
    room = limit - context_tokens(ctx)
    body = cap_to_room(observation, room) + receipt(edit) + size_line
    output = ctx.add("output", body)
    save both blocks; log events

    free = edit applied and command printed nothing and exit code 0
    if free and free_in_row < max_free_edits_in_row: free_in_row += 1
    else: step += 1; free_in_row = 0

    if refused_in_row >= max_refused_edits_in_row:
        ctx.add("notice", "Three context edits in a row were refused. Stop editing and continue the task.")
        refused_in_row = 0

    if driver:
        nxt = driver.after_command(command, observation)
        if nxt: ctx.add("user", nxt)
```

Notes:

- The edit is applied before this turn's `assistant` and `output` blocks are appended, so the model can never edit the command it is currently running.
- The size line is `[context: T / L tokens]`, written into the output block at creation and never changed afterwards.
- `ScriptedModel(replies: list[ModelReply])` returns the next reply each call, for tests.

### 1.7 Tests

| File | Cases |
|---|---|
| `test_shell.py` | `cd` then `pwd` across two commands; an exported variable persists; `exit 3` still saves state and returns 3; a sleeping child is killed on timeout; a command with quotes, `$` and newlines runs intact; truncation at 10,001 characters writes the output file and reports the elided count |
| `test_context.py` | render then parse is lossless; body replaced; block removed; `new-` note added and given a real id; each refusal (line 1 changed, no headers, stray text, unknown id, duplicate id, `user` block altered or missing, over-limit growth); a shrinking but still-over edit is accepted; a refused edit leaves `ctx.blocks` identical |
| `test_budget.py` | each tier fires once and re-arms after the context shrinks; urgent fires every turn while near the limit; no how-to in the 25% text; rollback never drops a `user` block; margin grows after three rollbacks; the rollback note lists at most 5 commands |
| `test_session.py` | events are valid JSON lines in order; `blocks/<id>.txt` holds the original after an edit; snapshot then `undo` restores the earlier blocks; cost matches a hand calculation |
| `test_loop.py` | run ends with `finished` on a reply without a command; an accepted shrinking edit changes the next request; a refused edit does not; overflow triggers rollback and sets the note; each cap returns its status; a `max_tokens` reply's command is not run; a blocked command is not run; the free-edit cap; the driver appends a `user` block |

---

## Phase 2: the live model

### 2.1 `llm.py`

```python
class ClaudeModel:
    def __init__(self, cfg: Config): self.client = anthropic.Anthropic()
    def reply(self, system: str, ctx: Context) -> ModelReply
```

**Request**

```python
with self.client.beta.messages.stream(
    model=cfg.model,
    max_tokens=cfg.max_tokens,
    betas=["server-side-fallback-2026-07-01"],
    fallbacks="default",
    thinking={"type": "adaptive", "display": "summarized"},
    output_config={"effort": cfg.effort},
    system=[{"type": "text", "text": system}],
    tools=[{"type": "bash_20250124", "name": "bash"}],
    tool_choice={"type": "auto", "disable_parallel_tool_use": True},
    cache_control={"type": "ephemeral"},
    messages=[{"role": "user", "content": build_content(ctx)}],
) as stream:
    response = stream.get_final_message()
```

**`build_content(ctx) -> list[dict]`**, one text block each, in this order:

1. The pinned task.
2. The rollback note, if any.
3. The constant line `[[CTX v1]]`.
4. One block per context block: `render_block(b)`.

So the model sees exactly the text that is in the file, headers included.

### 2.2 Cache markers

Four markers is the maximum. Placement:

| Marker | Where | Covers |
|---|---|---|
| 1 | The pinned task block | Tools, system prompt and task. Survives every edit. |
| 2, 3 | The two highest context-block indices that are multiples of 10 and at most `n - 2` | Fixed positions, so a later request finds an entry written by an earlier one |
| 4 | Automatic, on the last block (`cache_control` at the top level) | The normal turn-to-turn hit |

After an edit at block `k`, the request reads the cache up to the highest marker below `k`, and pays full price from there. Anchors at fixed multiples are used, not fractions of `n`, because a marker that moves every turn is never found again.

Checks, run in the live smoke test:

- `cache_read_input_tokens > 0` from the second turn;
- after an edit near the tail, cache reads drop only by roughly the edited tail;
- the system prompt contains nothing that varies between runs of the same configuration.

### 2.3 Response handling

- `text`: all `text` blocks joined.
- `thinking`: all non-empty `thinking` blocks joined, dropping any that reads exactly `This part of the response was interrupted before it finished.`
- Tool use: take the first `tool_use` block only. `{"restart": true}` sets `restart`; otherwise `input["command"]` must be a string, else treat the reply as having no command and append a notice `Your bash call had invalid input.`
- `stop_reason`: passed through; anything other than the four known values is treated as `error`.
- `usage`: `input_tokens`, `output_tokens`, `cache_read_input_tokens`, `cache_creation_input_tokens`.
- `served_by`: `response.model`.
- Calibration input: `api_prompt_total = input + cache_read + cache_creation`.

**Errors**, most specific first:

| Exception | Action |
|---|---|
| `anthropic.RateLimitError` | Wait and retry up to 3 more times (the SDK has already retried twice) |
| `anthropic.APIStatusError`, status ≥ 500 | Same |
| `anthropic.APIStatusError`, other | Stop the run with status `error`, record the message |
| `anthropic.APIConnectionError` | Retry up to 3 more times |

### 2.4 Prompts

`prompts/system.md` (static):

- You are a coding agent working in a directory through a bash tool.
- Each reply: at most one bash command. Commands chained with `&&` count as one.
- The shell keeps its working directory and exported variables between commands. Do not run interactive commands. Wrap anything slow in `timeout`.
- Command output arrives as text in your context, not as a tool result.
- When the task is done, reply with your final answer and no command.

`prompts/context.md` (appended in `clm` mode only; `{limit}` is filled once per run): the 11 guidance points listed in `PLAN.md` Phase 2.4, preceded by two lines stating the limit and that every command result reports the current size.

`prompts/summarise.md` (baseline only): the handoff-summary prompt.

### 2.5 `cli.py`

`argparse` with subcommands:

| Command | Behaviour |
|---|---|
| `run "<task>" --dir D [--mode] [--budget] [--confirm] [--max-steps] [--max-cost]` | Builds `Config`, runs the loop, prints the answer, status and cost |
| `log <session>` | Reads `transcript.jsonl`; one line per turn: turn, command (cut to 60 characters), context tokens, edit result, dollars |
| `undo <session>` | Calls `session.undo` |
| `bench ...` | Phase 3 |

### 2.6 Live checks

1. Empty directory, task "create hello.txt containing hi, read it back, tell me the contents". Expect `finished` in a few turns.
2. A small real repo with `--budget 12000`, a task that needs reading several files. Expect at least one `edit_applied` event and no rollback.
3. From run 2's transcript, recompute dollars by hand for three turns and compare to `usage.json`.
4. `harness undo` on run 2's session and diff the restored file against the snapshot.

---

## Phase 3: baseline mode and benchmark

### 3.1 `baseline.py`

```python
def maybe_compact(ctx: Context, system: str, est: Estimator, cfg: Config,
                  client, session: Session) -> None
```

Runs before each model call when `mode == "baseline"`. If `context_tokens > 0.80 * limit`:

1. **Clear.** Walking from oldest to newest, replace the body of each `output` block with `[Old tool output cleared]`, stopping when the remaining (newer) blocks total 40% of the budget or less. Skip blocks already cleared.
2. **Summarise**, if still above 80%. Take all non-`user` blocks except the last 6. Send them as plain text with `prompts/summarise.md` in one request (no tools, same model). Replace them with one `note` block: `[Summary of earlier work]` plus the summary. Add the call's usage to the session.
3. **Drop**, if still above the limit: remove the oldest non-`user` blocks until under.

Each stage logs a `compact` event with before and after tokens.

### 3.2 `bench/kv_store.py`

```python
def generate(seed: int, batches: int) -> list[Op]     # Op(kind, text, key, value)
class KVDriver(TaskDriver): ...
def score(ops: list[Op], transcript: Path) -> float
```

- Word list: about 2,000 common English words, shipped in the repo.
- Value: 24 words forming loosely grammatical phrases (adjective, noun, verb, repeated), followed by `#<8 hex>` derived from the key and seed.
- Batch: `<<<SET-BATCH 0003 BEGIN>>>`, 100 lines `SET K00042 = <value>`, `<<<SET-BATCH 0003 END>>>`.
- Queries: 24 `GET K00042` lines over keys drawn uniformly from all batches, after the last batch.
- Task text (pinned): the protocol. Each operation arrives as a new message. After handling it, run `echo READY_FOR_NEXT_OP`. For `GET <key>`, print `<<<ANSWER key=K>>> <value> <<<ANSWER END>>>` in the reply before releasing the next operation.
- Driver: on a command whose output's first line is `READY_FOR_NEXT_OP`, return the next operation's text; return `None` otherwise. When operations run out, return `ALL OPERATIONS DELIVERED. Reply with DONE and no command.`
- Sizing assertion in `generate`: each operation's raw estimate ≤ 0.2 × usable budget × 0.9.
- Pressure: `batches` is chosen so total raw input ÷ budget is 1.5, 3 or 6.
- Score: for each `GET`, find the `ANSWER` block for that key in the `reply` event that followed it; exact string match of the value. Accuracy = correct ÷ 24.

### 3.3 `bench/ledger.py`

- 120 accounts `A000`–`A119` with seeded starting balances, delivered in the first operation.
- Each later operation is a batch of 60 transfers: `TRANSFER A017 -> A093 : 412`.
- Every third operation is followed by a query: `BALANCE A093?`, answered as `<<<BALANCE A093>>> 7310 <<<END>>>`.
- 24 queries in total; the number of batches sets the pressure.
- Same driver protocol and release marker as KV Store.
- Sizing assertion: the full balance table's raw estimate ≤ 0.5 × usable budget × 0.9.
- Score: exact integer match per query.

### 3.4 `bench/run.py`

```python
def main(tasks, modes, seeds, pressure, ceiling_usd, out_csv)
```

- For each (task, mode, seed): fresh temp workdir, build `Config(mode=...)`, run the loop with the task's driver, score from the transcript.
- Before each run: if the sum of costs so far plus `cfg.max_cost_usd` would exceed `ceiling_usd`, stop and report which runs were skipped.
- CSV columns: task, mode, seed, pressure, status, accuracy, dollars, input, output, cache_read, cache_write, model_calls, steps, edits_applied, edits_refused, reread_tokens_total, rollbacks, seconds, served_by_fallback.

**Tests** (`tests/test_bench.py`): the same seed gives byte-identical operations; a hand-built perfect transcript scores 1.0; one with a single wrong value scores 23/24; the sizing assertions hold at all three pressure levels.

---

## Phase 4: run and decide

1. `harness bench --tasks kv,ledger --modes clm,baseline --seeds 1,2,3 --pressure 3 --ceiling <agreed amount>`.
2. `bench/report.py` reads the CSV and prints, per task and mode: mean and range of accuracy and dollars, edits per run, mean re-read tokens per edit, rollbacks.
3. Pull three transcript excerpts with `harness log`: a good edit, a refused edit, and the worst failure.
4. Write `RESULTS.md` with the table, the excerpts, the stated outcome against the target (equal accuracy at lower cost), and the list of changes the runs call for.

---

## Order of work inside each phase

- Phase 1: `config` → `shell` → `context` → `budget` → `session` → `safety` → `loop`, writing each module's tests before moving on. `loop` is last because it only wires the others together.
- Phase 2: `llm` → prompts → `cli` → live checks.
- Phase 3: `baseline` → `kv_store` → `ledger` → `run`.

## Deviations from `PLAN.md` made while writing this spec

- Line 1 of the context file is the constant `[[CTX v1]]`, with no revision number.
- The `tokens=` figure in each header is the raw estimate, not the calibrated one.
- Cache markers: one on the pinned task block and two at fixed anchor positions, not one on the system prompt and two at fractions of the block count.

All three exist to keep the prompt cache from being invalidated on every turn. `PLAN.md` has been updated to match.

Made while building Phase 1:

- Saved command output is named by turn (`outputs/turn-NNNN.txt`), not by block id, because the output block's id is not known until after the edit is applied.
- The prompt names a scripting tool that was checked to work in the shell. On Windows `python3` is often a Store stub, so the harness tries `python3`, then `python`, and falls back to `perl`.
- A body line that looks like a block header (for example when a command prints the context file) is escaped when the block is created, so it cannot be parsed as a real header later.
- An edit that leaves every block identical is reported as unchanged, not applied, so it cannot earn a free turn.
