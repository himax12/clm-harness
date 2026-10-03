# Working on this repo

A bash-only coding-agent harness in which Claude manages its own context by editing a file (the Context Language Model idea, arXiv 2609.37725), plus a baseline compaction mode and a benchmark that compares the two.

`PLAN.md` says what is being built and why. `IMPLEMENTATION.md` says how each module works and records every deviation and every finding from live runs. Read the relevant section before changing a module.

## Commands

```
uv sync                         install
uv run pytest -q                all tests (about 45 s; shell tests run real Git Bash)
uv run pytest tests/test_context.py -q
uv run harness doctor           check the shell and the API credential; spends nothing
uv run harness run "<task>" --dir <folder> [--mode clm|baseline] [--budget N] [--max-cost D]
uv run harness log <session-dir>
uv run harness undo <session-dir>
uv run harness bench --ceiling <dollars> [--tasks kv,ledger] [--modes clm,baseline] [--seeds 1,2,3]
uv run harness report <results.csv>
```

`harness run` and `harness bench` call the Claude API and cost money. Everything else is free.

## Layout

```
harness/
  config.py     every default, in one frozen dataclass; the price table
  shell.py      runs a command in Git Bash; state carry-over, timeout, truncation
  context.py    blocks, the context file format, edit validation, receipts
  budget.py     token estimate and calibration, notices, rollback
  session.py    transcript, block originals, snapshots, undo, cost
  safety.py     always-blocked commands, confirm mode
  loop.py       the turn loop; Model and TaskDriver interfaces; ScriptedModel
  llm.py        the Claude request and response parsing (the only SDK import)
  baseline.py   clear-then-summarise compaction, the comparison mode
  env.py        loads .env
  redact.py     hides secret variables from commands; redacts secrets in output
  cli.py        the commands above
  prompts/      system.md, context.md, summarise.md
bench/          key-value and ledger streams, driver, scorer, run matrix
tests/          one file per module
```

Session data is written to `<workdir>/.ctx/sessions/<id>/` and benchmark output to `bench_out/`. Both are ignored by git.

## Rules that are easy to break

- **Never read, print or commit `.env`.** It holds the API key. The harness loads it itself. Commands the agent runs do not inherit secret-looking variables, and known secret values are redacted from command output before it is stored or sent (`harness/redact.py`); keep both in place.
- **Do not spend money without the user's say.** Run the benchmark only with an agreed `--ceiling`. Use `ScriptedModel` or a fake client for anything that can be tested without the API.
- **Nothing in a request may change between turns unless the model changed it.** Prompt caching depends on the unedited prefix being byte-identical. In particular:
  - no request block may end in whitespace (the API trims the final block, so it would never match its own cache entry on the next turn);
  - line 1 of the context file is the constant `[[CTX v1]]`;
  - the `tokens=` figure in a block header is the raw estimate, never the calibrated one;
  - nothing volatile (dates, ids, run-specific values) goes in the system prompt.
  `tests/test_llm.py` guards these. If cache reads drop, check here first.
- **An edit is applied whole or refused whole.** `apply_edit` must not mutate the context before its last step.
- **Never delete history.** The transcript, block originals and snapshots are append-only or write-once.
- **`user` blocks are protected; `input` blocks are not.** The model may edit task input fed by a driver, and rollback may drop neither.
- **`llm.py` and nothing else imports `anthropic`.** The loop depends on the `Model` interface.
- **No agent framework and no embeddings.** Raw SDK calls and plain files.

## Conventions

- Python 3.12+, standard library plus `anthropic`; `pytest` for tests.
- Write every file the shell will read with `newline="\n"`. Bash fails on CRLF.
- The project path contains spaces. Quote paths in scripts, and refer to the context file as `"$CTX"`.
- On Windows, `python3` may be a Store stub and native programs do not understand Git Bash paths such as `/tmp/x`. See `Shell.scripting_hint` and the Windows note in `load_system`.
- Add or change a test with every behaviour change. Live findings go in `IMPLEMENTATION.md` under the deviations section, with what was measured.
- Work on a branch, not on `main`. Commit only when asked.

## Checking a change

1. `uv run pytest -q` passes.
2. For a change to the request, the prompt or the loop: one cheap live run, for example
   `uv run harness run "create hello.txt containing hi, read it back, and tell me the contents" --dir <temp folder> --max-cost 0.5`,
   then `uv run harness log <session>` and confirm cache reads are non-zero from the second turn.
3. For a change that could affect results: say that the benchmark needs re-running; do not re-run it unasked.

## Out of scope for now

The notes graph (markdown nodes maintained across sessions, with staleness tracking), subagents, session resume, an OS sandbox and loading this file into the harness's own agent. These are later iterations.
