# Contributing

Thanks for looking. This is a small experimental project; issues and focused pull requests are welcome.

## Before you start

- Read [AGENTS.md](AGENTS.md). It lists the layout and the rules that are easy to break, most of which protect prompt caching, the edit guarantees or the user's secrets.
- For anything larger than a bug fix, open an issue first so the approach can be agreed.
- [AUDIT.md](AUDIT.md) lists known gaps. Picking one up is a good first contribution; say which item you are taking.

## Setup

```
uv sync
uv run pytest -q
uv run ruff check .
```

The tests run real bash commands. On Windows they need Git for Windows; without bash they are skipped. No test calls the Anthropic API, and none should: use `ScriptedModel` or a fake client.

## Making a change

1. Work on a branch.
2. Add or change a test with every behaviour change.
3. Keep `SAFETY.md` true if you touch `safety.py`, `redact.py` or `shell.py`.
4. If you learn something from a live run, record it in `IMPLEMENTATION.md` with what you measured.
5. Run the tests and the linter before opening a pull request.

A change to the request, the prompts or the loop can alter how the model behaves and what a run costs. Say so in the pull request, and say whether you ran it live. Do not commit benchmark results you did not produce.

## Tests that run commands

A test that starts a process must be bounded: it has to end by itself within seconds even if the harness fails to kill it. Never use an endless generator such as `yes` in a test.

## Reporting security problems

See [SECURITY.md](SECURITY.md).
