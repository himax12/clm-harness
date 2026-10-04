# Working on this repo

A bash-only coding-agent harness in which Claude manages its own context by editing a file (the Context Language Model idea, arXiv 2609.37725), plus a baseline compaction mode and a benchmark that compares the two.

`PLAN.md` says what is being built and why. `IMPLEMENTATION.md` says how each module works and records every deviation and every finding from live runs. Read the relevant section before changing a module. `SAFETY.md` states what the harness protects against and what it does not; keep it true when you change `safety.py`, `redact.py`, `shell.py` or `sandbox.py`. `AUDIT.md` is the open-source readiness checklist; update an item's status when you fix it. `LAUNCH.md` is the wider launch checklist (going public, packaging, visibility, other models and agents) and the architecture review; keep its statuses current the same way.

## Commands

```
uv sync                         install
uv run pytest -q                all tests (about 75 s; shell tests run real bash, sandbox tests real Docker)
uv run pytest tests/test_context.py -q
uv run ruff check .             lint (also run in CI)
uv run harness setup            save the API key in the user's settings folder; spends nothing
uv run harness doctor           check the shell and the API credential; spends nothing
uv run harness run "<task>" --dir <folder> [--mode clm|baseline] [--budget N] [--max-cost D]
                                [--sandbox docker] [--allow-net]
uv run harness sessions --dir <folder>
uv run harness log <session-dir>
uv run harness undo <session-dir>
uv run harness bench --ceiling <dollars> [--tasks kv,ledger] [--modes clm,baseline] [--seeds 1,2,3]
uv run harness report <results.csv>
```

`harness run` and `harness bench` call the Claude API and cost money. Everything else is free.

## Layout

```
clm_harness/
  config.py     every default, in one frozen dataclass; the price table
  shell.py      runs a command in Git Bash; state carry-over, timeout, truncation
  context.py    blocks, the context file format, edit validation, receipts
  budget.py     token estimate and calibration, notices, rollback
  session.py    transcript, block originals, snapshots, undo, cost
  safety.py     always-blocked commands, confirm mode
  loop.py       the turn loop; Model and TaskDriver interfaces; ScriptedModel
  llm.py        the Claude request and response parsing (the only SDK import)
  baseline.py   clear-then-summarise compaction, the comparison mode
  env.py        loads .env; the user's settings folder
  redact.py     hides secret variables from commands; redacts secrets in output
  sandbox.py    runs the commands in a Docker container (`--sandbox docker`)
  cli.py        the commands above
  prompts/      system.md, context.md, summarise.md
  bench/        key-value and ledger streams, driver, scorer, run matrix
tests/          one file per module
```

Session data is written to `<workdir>/.ctx/sessions/<id>/` and benchmark output to `bench_out/`. Both are ignored by git.

## Rules that are easy to break

- **Never read, print or commit `.env`.** It holds the API key. The harness loads it itself. Commands the agent runs do not inherit secret-looking variables, and known secret values are redacted from command output before it is stored or sent (`clm_harness/redact.py`); keep both in place.
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
- **A test that starts a process must be bounded.** It has to end by itself within seconds even if the harness fails to kill it. Never use an endless generator such as `yes`: an earlier test did, the kill did not reach it on Windows, and three orphans wrote 77 GB of temp files. Check that the children are dead, not only that the call returned.
- **Kill by job object on Windows, not by parent link.** `taskkill /T` does not reliably reach processes Git Bash starts. `Shell` puts each command in a job object and ends the whole job; `Shell.close()` ends anything still running. Call `close()` on any `Shell` you create outside `loop.run`.
- **In the sandbox, a path in a script is the path inside the container.** `Shell._inside` maps a host path to `/work/...` or `/session/...`; use it for anything written into `run.sh`. The container gets the working folder, the session folder and nothing else: do not add a mount, a capability or an environment variable without updating `SAFETY.md`. The sandbox tests need a Docker engine running Linux containers and are skipped without one.
- **`llm.py` and nothing else imports `anthropic`.** The loop depends on the `Model` interface.
- **No agent framework and no embeddings.** Raw SDK calls and plain files.

## Conventions

- Python 3.10+, standard library plus `anthropic`; `pytest` for tests.
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

The notes graph (markdown nodes maintained across sessions, with staleness tracking), subagents, session resume, a sandbox that needs no Docker (bubblewrap, Seatbelt) and loading this file into the harness's own agent. These are later iterations.

## Editing files in this repo from a shell

Do not patch source files with a script passed through a shell heredoc when the patch contains backslash escapes such as `\n`: they have been silently turned into real newlines more than once, breaking the file. Use an editor or a direct file-edit tool.
