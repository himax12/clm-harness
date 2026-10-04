# Changelog

Notable changes to this project. Versions follow [semantic versioning](https://semver.org/); nothing has been released yet.

## Unreleased

### Added

- Agent loop: one bash command per turn, with step, model-call, cost and wall-clock limits.
- Model-managed context: the context file, whole-edit validation, receipts, a per-block size ledger, notices at 25%, 50% and 75% of the limit, and rollback on overflow.
- History: append-only transcript, block originals, snapshots, `harness undo`.
- Claude integration: one request block per context block, prompt caching, reasoning summaries, retries, cost tracking at the serving model's prices.
- Baseline mode: clear old outputs, then summarise, then drop.
- Benchmark: key-value and ledger streams, exact-match scorer, run matrix with a spend ceiling.
- Commands: `run`, `doctor`, `sessions`, `log`, `undo`, `bench`, `report`.
- Safety: blocked destructive commands, `git push` refused without `--allow-push`, secret variables removed from the agent's environment, secrets redacted from stored output, a 10 MB output cap, `--confirm`.
- Per-turn progress output; `--quiet` turns it off.
- `--model`, `--effort`, `--timeout`, `--task-file`.
- `.ctx/` ignores itself in git.
- Configuration is validated when it is built.
- CI on Linux and Windows; ruff lint.
- MIT licence.
- One-line installers: `install.sh` for macOS, Linux and WSL, and `install.ps1` for Windows. They install uv if needed, then the harness as a uv tool.
- `harness setup` saves the API key in the user's settings folder, where an installed copy finds it.
- `harness doctor` reports the system, says what to install when something is missing, and no longer fails for a missing bash when Docker can run the sandbox.
- `harness run` stops with a clear message when there is no shell to run commands in.
- CI runs the tests on macOS and runs the installer on Linux, macOS and Windows.
- A second command name, `clm-harness`.
- Python 3.10 and 3.11 are supported and tested.
- A publish workflow for PyPI, a Dependabot configuration, a citation file and a feature-request template.
- `LAUNCH.md` (launch checklist and architecture review) and `TODO.md` (the ordered work list).
- Sandbox: `--sandbox docker` runs the agent's commands in a container that sees only the working folder, with no network (`--allow-net` turns it on), no host environment, dropped capabilities and limits on memory, CPU and processes. `--sandbox-image` chooses the image.

### Changed

- The code is now one importable package, `clm_harness`, with the benchmark at `clm_harness.bench`. The old top-level names `harness` and `bench` are gone. The `harness` command is unchanged.

### Fixed

- Prompt cache missed on every turn because request blocks ended in whitespace, which the API trims from the final block.
- On Windows a timed-out command's child processes survived the kill. Commands now run in a job object, and everything they start is ended on timeout and at the end of the run.
- A background job held the turn open until it exited.
- A command with large output was buffered whole in memory.
- Ctrl+C or a harness error left a session without a `finish` event or `usage.json`.
- The safety check refused notes that merely mentioned a blocked command.
- Extra tool calls in one reply were dropped without telling the model.
- The refusal category was not recorded.
