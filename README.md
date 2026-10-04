# clm-harness

A small coding-agent harness in which the model manages its own context window.

Most agent harnesses decide what the model remembers: when the context fills up, the harness summarises or drops old turns. Here the context is mirrored to a file, and the model edits that file with ordinary shell commands. It prunes a file dump once it has taken notes, shortens stale output, and keeps a tracker of what it has done. The harness checks each edit, keeps the originals on disk, and can undo it.

This is an implementation of the idea in [Context Language Models](https://arxiv.org/abs/2609.37725) (Shao et al., 2026), written from the paper's design for Anthropic's hosted API.

> **Status: experimental.** It works and is tested, but it is not ready for unattended use on anything you care about. By default the agent runs shell commands with your permissions; `--sandbox docker` runs them in a container instead. Read [SAFETY.md](SAFETY.md) first.

## What it does

- Runs one bash command per turn in a loop, with limits on steps, cost and time.
- Mirrors the model's context to a file it can edit; each edit is applied whole or refused whole, with a receipt.
- Shows the model its context size on every result and warns it as the limit approaches.
- Keeps an append-only transcript, the original of every block, and a snapshot at each edit.
- Can run the agent's commands in a Docker container that sees only the project folder and has no network (`--sandbox docker`).
- Includes an ordinary compaction mode (`--mode baseline`) and a benchmark for comparing the two.

## Requirements

- Python 3.12 or newer and [uv](https://docs.astral.sh/uv/)
- Bash. On Windows, install [Git for Windows](https://git-scm.com/download/win).
- An Anthropic API key with credit. Each run is billed.
- Optional: Docker, for the sandbox.

Development and all live runs so far have been on Windows 11 with Git Bash. The test suite also runs on Linux in CI. macOS is untested, and no live run has been made outside Windows.

## Install

```
git clone https://github.com/himax12/clm-harness
cd clm-harness
uv sync
```

Put your key in a `.env` file in the project folder (it is ignored by git):

```
ANTHROPIC_API_KEY=sk-ant-...
```

Check the setup. This spends nothing:

```
uv run harness doctor
```

## Use

```
uv run harness run "add a --verbose flag to cli.py and a test for it" --dir path/to/repo
```

The agent works in `--dir`. Progress is printed one line per turn, and the final answer at the end.

| Command | What it does |
|---|---|
| `harness run "<task>" --dir <folder>` | Run a task. `--task-file` reads the task from a file or stdin. |
| `harness doctor` | Check bash, the scripting tool and the API key. Free. |
| `harness sessions --dir <folder>` | List recorded sessions with status and cost. |
| `harness log <session>` | Turn-by-turn view: command, context size, edits. |
| `harness undo <session>` | Restore the context from before the last edit. |
| `harness bench --ceiling <dollars>` | Run the benchmark (costs money). |
| `harness report <results.csv>` | Summarise benchmark results. |

Useful flags for `run`:

| Flag | Default | Meaning |
|---|---|---|
| `--mode clm\|baseline` | `clm` | Model-managed context, or ordinary compaction |
| `--budget N` | 32000 | Context budget in tokens |
| `--max-cost D` | 5 | Stop the run at this many dollars |
| `--max-steps N` | 64 | Commands the agent may run |
| `--timeout S` | 120 | Seconds before a command is killed |
| `--effort` | `medium` | Reasoning effort |
| `--confirm` | off | Approve every command before it runs |
| `--allow-push` | off | Let the agent run `git push` |
| `--pass-env NAME` | none | Let the agent's commands see a secret-looking variable |
| `--sandbox none\|docker` | `none` | `docker`: run commands in a container that sees only `--dir` |
| `--allow-net` | off | Give the sandbox network access |
| `--sandbox-image NAME` | built on first use | Container image for the sandbox |

To run a task in the sandbox:

```
uv run harness run "fix the failing test" --dir path/to/repo --sandbox docker
```

The project appears at `/work` inside the container. A task that needs to download packages also needs `--allow-net`.

## How it works

Each turn the harness sends the model a fresh request: a fixed system prompt, the task, and the context file, one block per turn record.

```
[[CTX v1]]
[[BLOCK id=b0007 role=output tokens=1840]]
...command output...

[[BLOCK id=b0008 role=assistant tokens=210]]
...reasoning and the command it ran...
```

The model replies with one bash command. The file is available to that command as `"$CTX"`. After the command runs, the harness compares the file to what it wrote:

- unchanged: nothing happens;
- a valid edit (a body replaced, a block removed, a note added): it becomes the new context;
- an invalid edit (a damaged header, an unknown block id, a changed user message, growth past the limit): it is refused as a whole and the previous context is kept.

Either way the model gets a receipt on its next turn. The original text of every block stays in the session folder, so the model can read back anything it removed.

The task and the user's messages cannot be edited. If the context still overflows, the harness drops the newest turns and tells the model which commands caused it.

More detail: [PLAN.md](PLAN.md) for the design and reasoning, [IMPLEMENTATION.md](IMPLEMENTATION.md) for each module and the findings from live runs.

## What has been measured

Very little so far, and nothing that supports a general claim.

- On a 23-turn task under a 12,000-token budget, the model applied 13 context edits, none were refused, and the context stayed under the limit.
- On one run of a synthetic key-value task (about 99,000 tokens of input through a 29,952-token limit), the model-managed mode answered 24 of 24 questions correctly for $1.08.
- The one baseline run of the same task ended early in an API refusal and is not a valid comparison.

A proper comparison across tasks and seeds has not been run. [AUDIT.md](AUDIT.md) tracks this and everything else that is unfinished.

## Cost

A run costs what its API calls cost. Editing the context is not free: everything after an edited block is re-sent at the cache-write price. `--max-cost` stops a run at a dollar limit, and `harness log` shows what each edit cost in re-read tokens.

## Development

```
uv run pytest -q        tests; shell tests run real bash commands
uv run ruff check .     lint
```

[AGENTS.md](AGENTS.md) describes the layout and the rules that are easy to break. [CONTRIBUTING.md](CONTRIBUTING.md) covers how to propose a change.

## Acknowledgements

- Rulin Shao and co-authors for [Context Language Models](https://arxiv.org/abs/2609.37725). This project reimplements the paper's idea and does not use code from the official repository.
- [lolipopshock/pi-clm](https://github.com/lolipopshock/pi-clm) (MIT), whose strategy notes informed the wording of the context-management prompt.
- [mini-swe-agent](https://github.com/SWE-agent/mini-swe-agent) for the loop shape and the output-truncation rule.
- Barbaste et al., [Harness Engineering](https://arxiv.org/abs/2609.00006), for the survey of how existing harnesses are built.

## Licence

[MIT](LICENSE).
