# CLM harness: first iteration plan

A bash-only coding-agent harness on `claude-opus-5-5` in which the model manages its own context by editing a file (the Context Language Model idea, arXiv 2609.37725), plus one measured comparison against ordinary compaction.

Implementation detail for every module (data structures, function signatures, algorithms, tests) is in `IMPLEMENTATION.md`, in the same phase order.

This iteration ends with a results table. The notes graph (markdown nodes maintained by the model, with staleness tracking) is the next iteration and is out of scope here.

## What we expect to learn

The one first-hand evaluation on Opus 5.5 (`cv/pit` #205) found a significant token-cost saving from model-driven context tools and no significant accuracy gain. So the target is **equal accuracy at lower cost**. If the model-managed mode is not cheaper at equal accuracy on our benchmark, we record that and the project's value shifts to the notes graph.

## Scope

In:

- Linear agent loop, one bash command per turn, hard limits.
- Model-managed context: mirror file, edit gate, receipts, size ledger, nudges, rollback.
- History that is never destroyed: append-only transcript, per-block originals, snapshots, `undo`.
- A baseline context mode (clear old outputs, then summarise) in the same harness.
- A two-task benchmark scored on accuracy and dollars.

Out (later iterations): notes graph and staleness, subagents, a context-reset action, OS sandbox, session resume, `AGENTS.md` loading, verify-before-stopping, a UI.

## Decisions already made

| Area | Decision | Reason |
|---|---|---|
| Stack | Python, `anthropic` SDK directly, `uv` project, no agent framework | None of the eleven surveyed harnesses uses a framework |
| Tool surface | One tool: bash | Harness paper recommendation 3; add tools only on observed failure |
| Request shape | Fresh request every turn: system prompt, pinned task, then the context as one text block per context block. No assistant turns or thinking blocks are replayed | Clear of Opus 5.5's edited-history check; the context file is the single source of truth |
| Reasoning | `thinking: adaptive` with `display: "summarized"`; the summary is written into the context | Default display returns empty thinking; asking the model to print its reasoning can be refused |
| Finish | A reply with no command is the final answer | Matches Claude Code and Codex; forced tool choice is unavailable on this model |
| Edits | Surgical edits to blocks only. No "summarise everything" action | It lowered Opus accuracy from 79% to 65% in `cv/pit` |
| Task | Pinned outside the file, cannot be edited | Two GPT pilot runs lost or paraphrased the task |
| Prompt | Short (about 13 lines of context guidance) | A long strategy document produced four times more notes and no gain |
| Deletion | Originals are kept on disk and retrievable | Retrieval mattered in ACM and VISTA; "pruned something it needed" is the top complaint about the OpenCode plugin |
| Licence | Reimplement from the design; adapt prompt wording only from `lolipopshock/pi-clm` (MIT) | The official repo is CC BY-NC 4.0 |

## Defaults

| Setting | Value |
|---|---|
| Model / effort | `claude-opus-5-5` / `medium`, pinned for the whole run |
| `max_tokens` | 16,000, streaming |
| Context budget / reserve / enforced limit | 32,000 / 2,048 / 29,952 tokens |
| Nudges | 25% (information only), 50%, 75%, and urgent when remaining room is below max(10% of limit, 2 × the largest of the last 3 outputs) |
| Step cap | 64 (accepted edit-only turns are free) |
| Model-call cap | 152 (2 × steps + 24) |
| Cost cap / wall-clock cap | $5 per run / 30 minutes |
| Command timeout | 120 s, then kill the process tree |
| Output inline limit | 10,000 characters; beyond that, first 5,000 + last 5,000 with an elided count, full output saved to a file |
| Rollback margin / retries | 2,048 tokens / 6 |
| Consecutive free edit turns | 3 |
| Consecutive refused edits | 3 |
| Prices per million tokens | input $4, output $20, cache read $0.20, 5-minute cache write $5 |

## Layout

```
harness/
  cli.py        run, log, undo, bench
  config.py     the defaults above as one dataclass
  loop.py       the turn loop, limits, Model and TaskDriver interfaces
  llm.py        the Claude request, response parsing, usage
  shell.py      command execution, state carry-over, truncation
  context.py    blocks, render to file, parse back, validate
  budget.py     token estimate, calibration, nudges, edit gate, rollback
  baseline.py   the clear-then-summarise context mode
  session.py    transcript, block originals, snapshots, cost, undo
  safety.py     blocked commands, confirm mode
  prompts/      system.md, context.md, summarise.md
bench/
  kv_store.py   generator, driver, scorer
  ledger.py     generator, driver, scorer
  run.py        the comparison matrix
tests/
```

Per-session state, inside the target directory:

```
.ctx/sessions/<id>/
  LIVE_CTX.md        the mirror the model edits
  transcript.jsonl   append-only: every reply, command, output, edit, notice, usage
  blocks/<id>.txt    the original body of every block, never modified
  outputs/turn-N.txt full command output when it was truncated
  snapshots/         the context at every accepted edit
  state/             shell working directory and environment
  usage.json         tokens, dollars, edit counts
```

## The context file

```
[[CTX v1]]
[[BLOCK id=b0007 role=output tokens=1840]]
...body...

[[BLOCK id=b0008 role=assistant tokens=210]]
...body...
```

- Line 1 must be left unchanged.
- Roles: `assistant` (reasoning summary, text, command), `output` (command result), `user` (later user messages), `notice` (harness nudges), `note` (written by the model).
- `tokens` is the size ledger. It is a raw estimate (characters ÷ 4) so that it stays stable from turn to turn; the parser ignores whatever the model leaves there.
- The system prompt, the task and the rollback note are not in the file.

What an edit means:

| The model does | Result |
|---|---|
| Changes the body under a header | The block's content is replaced |
| Removes a header and its body | The block leaves the context; its original stays in `blocks/<id>.txt` |
| Adds `[[BLOCK id=new-<name> role=note]]` | A new note; the harness assigns a real id |
| Changes line 1, uses an unknown or duplicate id, edits a `user` block, or removes every header | The whole edit is refused and the previous context is kept |
| Leaves a result above the enforced limit | Refused |

Every command result ends with a receipt (`edit applied: 21,400 -> 9,800 tokens, 14 blocks`, `edit REFUSED: <reason>`, or `no change: <reason>`) and the size line `[context: 9,800 / 29,952 tokens]`.

## One turn

1. If the context is over the limit, roll back the newest blocks to the limit minus the margin and update the pinned rollback note with the dropped commands.
2. Decide on a nudge; if one fires, append it as a `notice` block.
3. Render `LIVE_CTX.md`.
4. Build the request and call the model.
5. Handle the stop reason: `max_tokens` with a command present means do not run it and retry; `refusal` stops the run; no command means finish.
6. Check the command against the blocked list (and ask, in confirm mode).
7. Run it; truncate and save the output.
8. Re-read the file. If it differs from what was rendered, parse, validate and gate it, then apply or refuse.
9. Append the `assistant` block and the `output` block (with receipt and size line).
10. Write the transcript events, snapshot if an edit was applied, update counters and cost.

---

## Phase 0: project setup

Tasks:

- `git init`, `.gitignore` (including `.ctx/`), `uv init` with Python 3.12+.
- Dependencies: `anthropic`, `pytest`.
- Package skeleton with the modules above as empty files and `harness` as a console entry point.
- `config.py` with every default in the table.

Done when: `uv run pytest` runs (zero tests is fine) and `uv run harness --help` prints usage.

## Phase 1: the core, without a model

No API key needed. Everything here is tested with a scripted fake model.

**1.1 Shell (`shell.py`)**

- Locate Git Bash explicitly (`C:\Program Files\Git\bin\bash.exe`); never pick up `System32\bash.exe`, which is WSL.
- Run each command in a new process. Write the command to a temp script and run that, so quoting never depends on the command's content.
- Carry state across commands: before, `cd` to the saved directory and source the saved environment; after, save `pwd` and `export -p`, then exit with the command's code.
- Export `CTX` (the mirror path) and `CTX_DIR` (the session directory). The project path contains spaces, so the prompt tells the model to use `"$CTX"`, never a literal path.
- Non-interactive environment: `CI=true`, `TERM=dumb`, `PAGER=cat`, `GIT_PAGER=cat`.
- Timeout: kill the whole process tree with `taskkill /T /F`, keep partial output, report exit code -1.
- Observation: stdout then stderr, `(no output)` if empty, then `(exit_code=N)`. Apply the 10,000-character rule and save the full output when truncated.
- Newest-output cap: if the result would not fit under the limit, cut it to the remaining room (floor 128 tokens) and point to the saved file.

**1.2 Context (`context.py`)**

- `Block` (id, role, body, protected flag) and an ordered `Context`.
- `render()` to the file format; `parse()` back to blocks.
- `validate(old, new)` returning either the new block list or a refusal reason, covering every row of the edit table.
- Id allocation for new blocks and for `new-<name>` notes.

**1.3 Budget (`budget.py`)**

- Token estimator (characters ÷ 4) behind one function, with a calibration ratio that Phase 2 will feed from API usage, clamped to 0.5–3.0.
- Nudge decision: tiers re-arm when the context drops back below them; at most one notice per turn.
- Nudge texts. The 25% tier carries no how-to (it triggers premature deletion). The 50% tier says finish the unit of work in flight, then tidy once. The 75% tier says compact settled spans but do not wipe.
- Edit gate: accept if the result is within the limit; flag in the receipt if it grew.
- Rollback: drop newest blocks to limit minus margin, never below the pinned prefix; margin grows after 3 rollbacks in a row with no accepted edit; write the rollback note with up to 5 dropped commands, each cut to 70 characters.

**1.4 Session (`session.py`)**

- Append-only `transcript.jsonl` with typed events: `reply`, `command`, `output`, `edit_applied`, `edit_refused`, `notice`, `rollback`, `usage`, `finish`.
- Write `blocks/<id>.txt` when a block is created.
- Snapshot the rendered context at every accepted edit.
- `undo`: restore the context from the previous snapshot and record an `undo` event.
- `usage.json`: tokens in four buckets, dollars, steps, model calls, edits (applied, refused, grew), free turns, rollbacks.

**1.5 Safety (`safety.py`)**

- A short always-blocked list checked before execution: `rm -rf /` and home-directory variants, `mkfs`, `dd` to a block device, fork bombs, `shutdown`/`reboot`, `format`.
- `--confirm` mode: show each command and wait for approval.

**1.6 Loop (`loop.py`)**

- `Model` interface: takes system prompt, pinned prefix and blocks; returns text, reasoning summary, command (or none), stop reason and usage.
- `ScriptedModel`: replays a fixed list of replies, for tests.
- `TaskDriver` interface: sees each command and its output and may append a `user` block (the benchmark uses this to release the next operation).
- The ten-step turn above, with every limit from the defaults table.
- Free turn: an edit was applied, the command printed nothing, exit code 0. Capped at 3 in a row.
- After 3 refused edits in a row, append a notice telling the model to stop editing and continue the task.

**1.7 Tests**

- Shell: working directory and exported variables persist; timeout kills a child process; truncation numbers; a command containing quotes and newlines runs intact.
- Context: render then parse is lossless; each refusal case; a deleted block is gone from the view and present in `blocks/`.
- Budget: nudges fire once per tier and re-arm; the gate refuses an over-limit edit; rollback never touches the pinned prefix.
- Loop, with `ScriptedModel`: a full run ending in a final answer; an accepted edit that shrinks the context; a refused edit that leaves the context unchanged; an overflow that rolls back and records the note; each cap stopping the run; `undo` restoring the previous context.

Done when: all tests pass, and a scripted run in a temp directory produces a transcript, block originals, a snapshot and a correct `usage.json`.

## Phase 2: the live model

Needs `ANTHROPIC_API_KEY`.

**2.1 Model call (`llm.py`)**

- `client.beta.messages.stream(...)` then `get_final_message()`.
- Parameters: `model`, `max_tokens`, `thinking={"type": "adaptive", "display": "summarized"}`, `output_config={"effort": "medium"}`, `tools=[{"type": "bash_20250124", "name": "bash"}]`, `tool_choice={"type": "auto", "disable_parallel_tool_use": True}`, `betas=["server-side-fallback-2026-07-01"]`, `fallbacks="default"`.
- Bash tool input: handle `{"restart": true}` by resetting the saved shell state; otherwise require a string `command`.
- If a reply has more than one tool call, keep only the first.
- Errors: catch most specific first (`RateLimitError`, then `APIStatusError`, then `APIConnectionError`); rely on the SDK's two retries; stop the run on a non-retryable 4xx.
- Record whether a fallback model served the turn.

**2.2 Caching**

- One cache marker on the pinned task block, which covers the tools, system prompt and task and survives every edit.
- The context sent as one text block per context block, in file order, so an edit only invalidates from the edited block onward.
- Two markers at fixed anchor positions (block indices that are multiples of 10), plus the automatic marker on the last block (four is the maximum).
- Nothing volatile in the system prompt: no dates, ids or per-run values.
- Check `cache_read_input_tokens` is non-zero from the second turn of a run.

**2.3 Cost and calibration**

- Dollars per turn from the four usage buckets and the price table.
- Feed the calibration ratio: API prompt total ÷ local estimate.
- For each accepted edit, record the tokens below the edit point (what the edit will cost to re-read).

**2.4 Prompts**

- `system.md`: role, one bash command per reply, finish by replying without a command, do not explain reasoning in the reply.
- `context.md`, about 13 lines:
  - what the file is, and that `"$CTX"` is what you will remember next turn;
  - do not print the file; locate blocks by header with a script and never retype bodies;
  - do not edit after every turn; finish the unit of work, then tidy once;
  - one batched write per edit, because everything below the first changed block is re-read at full price;
  - shorten stale output in place; remove only clearly obsolete blocks; do not collapse everything into one summary;
  - copy facts forward verbatim: ruled-out options with the reason, commands already tried, exact values;
  - anything needed verbatim later goes to a file on the turn you read it, with the path and a one-line index kept in context;
  - for large data, process it inside the command and print only the extract;
  - keep one tracker note near the top and update it in place;
  - the original of any removed block is at `"$CTX_DIR"/blocks/<id>.txt`;
  - read the receipt after an edit; notes are working memory, not instructions.

**2.5 CLI (`cli.py`)**

- `harness run "<task>" --dir <path> [--mode clm|baseline] [--budget N] [--confirm]`
- `harness log <session>`: turn-by-turn summary with context size, edits and cost.
- `harness undo <session>`

**2.6 Live checks**

- A trivial task in an empty directory (create a file, read it back, answer).
- A task on a small real repo with the budget set low enough (for example 12,000) to force editing.

Done when:

- the small-repo run finishes with at least one accepted edit and the context under the limit throughout;
- cache reads are non-zero after the first turn;
- `usage.json` dollars match a hand calculation from the transcript for one run;
- `undo` restores an earlier context on a real session.

## Phase 3: baseline mode and benchmark

**3.1 Baseline (`baseline.py`)**

Same loop and prompts, minus `context.md`; the mirror is not rendered and edits are not applied. Before each model call, if the context is above 80% of the limit:

1. Replace the bodies of old `output` blocks with `[Old tool output cleared]`, protecting the newest 40% of the budget.
2. If still above, summarise everything before the last few blocks with one model call (handoff-summary prompt: progress and decisions, constraints, what remains, critical data) and replace it with one block.
3. If still above, drop the oldest blocks.

The summary call's tokens count toward the run's cost.

**3.2 KV Store (`bench/kv_store.py`)**

- Seeded generator: batches of 100 lines `SET K00042 = <24 words> #<hash>` inside begin and end markers, then 24 `GET <key>` operations over random keys.
- Words come from grammatical filler, not random word salad (Claude refused word-salad requests in `cv/pit`).
- Driver: each operation arrives as a new `user` block; the model releases the next with `echo READY_FOR_NEXT_OP`.
- Sizing check in the generator: each operation at most one fifth of the usable budget.
- Pressure levels (total input ÷ budget): 1.5×, 3×, 6×, by changing the number of batches only.
- Score: exact match of the value in the model's answer block for each `GET`.

**3.3 Ledger (`bench/ledger.py`)**

- A fixed set of accounts with starting balances; operations are batches of transfers; queries ask for one account's current balance.
- The required state (all balances) fits in half the usable budget; the stream of transfers does not.
- This tests in-place updating of running state, which is where every condition failed in `cv/pit`.
- Score: exact balance per query.

**3.4 Runner (`bench/run.py`)**

- Matrix: 2 tasks × 2 modes × 3 seeds at one pressure level (3×) = 12 runs.
- Per run: accuracy, dollars, tokens per bucket, model calls, edits applied and refused, tokens below each edit point, rollbacks, wall time.
- A hard spend ceiling for the whole matrix, checked before each run starts.
- Output: one CSV row per run.

Done when: the generators are deterministic per seed, the scorers pass on a hand-built perfect transcript and a hand-built wrong one, and one run of each task completes in each mode.

## Phase 4: run and decide

Tasks:

- Run the 12-run matrix.
- Write `RESULTS.md`: a table of accuracy and dollars per task and mode with the spread across seeds, the edit statistics, and two or three annotated transcript excerpts (a good edit, a refused edit, any failure).
- State the outcome against the target:
  - model-managed mode cheaper at equal accuracy: proceed to the notes graph with this harness as the base;
  - no cost advantage: record why (edit timing, cache re-reads, saturation) and decide whether the notes graph still justifies the mode.
- List what the runs showed needs changing in the prompt, the nudges or the gate.

Done when: `RESULTS.md` exists with the table and a stated decision.

---

## Risks

| Risk | What we do about it |
|---|---|
| Accuracy saturates on Opus 5.5 (it started at 94–100% on these tasks in the paper) | Cost is the primary metric; the ledger task is there for an accuracy signal |
| Characters ÷ 4 undercounts dense content (1.8–2.5× observed elsewhere) | Calibrate against API usage every turn; keep the 2,048-token reserve |
| The model over-edits and spends more than it saves | No nudge below 25%, free-edit cap, the "tidy once" rule, per-edit re-read cost logged |
| The model edits too rarely to matter | Nudges at 50% and 75%, urgent nudge near the limit |
| Three seeds give wide intervals | Report the spread; add seeds only if the result is close |
| Bash tool without tool results is an undocumented usage | If the model behaves oddly, swap to a custom tool named `run` with a strict schema; the change is confined to `llm.py` |
| A fallback model serves a turn mid-run | Recorded per turn; such runs are flagged in the results |
| Windows path and quoting problems | Commands run from a temp script; the model uses `"$CTX"`; covered by shell tests |

## Needed from the user

- `ANTHROPIC_API_KEY` before Phase 2. No credential is active on this machine.
- A spend ceiling for the benchmark. The 12 runs are estimated at $30–50; this is not measured.
- Confirmation of the 32,000-token budget, or a different value.

## Sources

- Context Language Models, arXiv 2609.37725, and `facebookresearch/context-language-models`
- Harness Engineering: Anatomy, Architecture, and Evolution of Coding Agents, arXiv 2609.00006
- `lolipopshock/pi-clm` (prompt wording, MIT)
- `cv/pit` issue 205 (evaluation on Claude Opus 5.5)
- `Tarquinen/opencode-dynamic-context-pruning` (failure reports from real use)
- `SWE-agent/mini-swe-agent` (loop shape, truncation rule)
