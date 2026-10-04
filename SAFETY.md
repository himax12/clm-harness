# Safety

This harness lets a language model run shell commands on your machine. Read this before pointing it at anything you care about.

## In one paragraph

By default the agent runs unattended, with your user's permissions, in the folder you give it. The harness refuses a short list of destructive commands and keeps secrets out of the agent's environment and out of stored output. It is **not a sandbox**: a command can still read, write or delete any file your user can, and can use the network.

## What the harness does

| Protection | What it covers |
|---|---|
| Blocked commands | Recursive deletion of a root or home directory, `mkfs`, `dd` to a device, fork bombs, shutdown and restart, formatting a drive. A blocked command is not run and the agent is told why. |
| No push by default | `git push` is refused unless you start the run with `--allow-push`. |
| Secrets removed from the environment | Variables whose names look secret (tokens, passwords, keys, credentials, anything `ANTHROPIC_*`) are not passed to the agent's commands. `--pass-env NAME` lets one through. |
| Secrets redacted from output | The values of those variables, the values in any `.env` file in the working folder, and common key formats are replaced with `[REDACTED]` before command output is sent to the model or written to disk. |
| Time limit | A command is killed after 120 seconds, together with everything it started. |
| Output limit | A command that prints more than 10 MB is killed the same way. |
| Run limits | Each run stops at a step, model-call, cost and wall-clock limit. |
| Approval mode | `--confirm` shows every command and waits for you to approve it. |
| No interactive input | Commands get no stdin, so a prompt cannot hang the run. |

## What it does not do

- **It does not confine file access.** The agent can read `~/.ssh`, cloud credentials, browser data, or a `.env` in the working folder, and can write outside the working folder.
- **It does not restrict the network.** A command can download and run code, or send data out.
- **The blocked list is a floor.** It matches a few obvious command shapes. The same damage can be done another way, for example through a script.
- **Redaction only catches what it knows.** A secret in some other file or format, or one that is encoded before printing, is not recognised.
- **It does not limit CPU, memory, disk or the number of processes.**
- **On Linux and macOS it does not clean up background jobs.** A process the agent starts with `&` can outlive the run there. On Windows every process a command starts is ended when the run ends.
- **It does not defend against prompt injection.** Text the agent reads from files, command output or the web arrives in its context alongside your task, and could contain instructions.

## How to run it safely

1. Run it in a container or a virtual machine when the task or the repo is not fully trusted.
2. Give it a scratch copy of a repo, not your only copy. Commit or back up first.
3. Use `--confirm` the first few times, and for any task that touches things outside the working folder.
4. Keep `.env` files and other secrets out of the working folder. `harness doctor --dir <folder>` and `harness run` warn when they find one.
5. Set `--max-cost` to what you are willing to spend on the run.

## Where your data goes

- **To Anthropic.** Everything in the agent's context is sent to the Claude API on every turn: your task, the commands it runs, their output, and the contents of any file it reads. A refused request may be retried on another Anthropic model.
- **To disk.** Each run writes a full record to `<working folder>/.ctx/sessions/<id>/`: every reply, command and output, in plain text. Nothing there is deleted automatically. The folder contains its own ignore file, so git does not pick it up.
- **Nowhere else.** The harness has no telemetry and makes no other network calls.

## Reporting a problem

If you find a way to make the harness run a command it should refuse, or to leak a secret it should redact, please open an issue with the command and what happened. Leave real secrets out of the report.
