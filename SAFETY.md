# Safety

This harness lets a language model run shell commands on your machine. Read this before pointing it at anything you care about.

## In one paragraph

By default the agent runs unattended, with your user's permissions, in the folder you give it. The harness refuses a short list of destructive commands and keeps secrets out of the agent's environment and out of stored output. Without the sandbox, that is all: a command can still read, write or delete any file your user can, and can use the network. With `--sandbox docker` the commands run in a container that sees only the working folder and has no network.

## The sandbox

`harness run ... --sandbox docker` runs every command in a Docker container that lives for the run and is removed when it ends. It needs Docker running Linux containers; `harness doctor` says whether that is so. The first use builds a small image (about 335 MB).

| In the sandbox | Detail |
|---|---|
| Files | Only the working folder (at `/work`) and the run's session folder are visible. Your home folder, SSH keys, cloud credentials and other projects are not. |
| `.env` files | A `.env` file at the top of the working folder reads as empty. One in a subfolder is still readable. |
| Network | None. `--allow-net` turns it on, for all destinations. |
| Environment | None of your environment variables are passed in. `--pass-env NAME` passes one. |
| Limits | 2 GB of memory, 2 CPUs, 512 processes, 1 GB for `/tmp`. |
| Privileges | All Linux capabilities are dropped and privilege escalation is disabled. On Linux and macOS the commands run as your user, on Windows as the container's root. |
| Lifetime | Everything the agent started ends with the run. A container whose harness died is removed by itself 15 minutes after the run's time limit. |

What the sandbox does not do:

- **It does not limit writes to the working folder.** The agent can still delete or fill it. Work on a copy, or commit first.
- **It does not filter the network.** It is off or on; there is no list of allowed hosts.
- **It is only as strong as Docker.** A container shares the host's kernel. It stops mistakes and ordinary attacks, not a kernel exploit.
- **It does not stop prompt injection.** It limits what an injected instruction can reach.
- **It has had little use.** Its tests pass on Windows with Docker Desktop and on Linux in CI. macOS is untried, and no live model run has used it yet.

Some tools the project needs may be missing from the default image. `--sandbox-image NAME` uses another image; it must contain `bash`.

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

## What it does not do without the sandbox

- **It does not confine file access.** The agent can read `~/.ssh`, cloud credentials, browser data, or a `.env` in the working folder, and can write outside the working folder.
- **It does not restrict the network.** A command can download and run code, or send data out.
- **The blocked list is a floor.** It matches a few obvious command shapes. The same damage can be done another way, for example through a script.
- **Redaction only catches what it knows.** A secret in some other file or format, or one that is encoded before printing, is not recognised.
- **It does not limit CPU, memory, disk or the number of processes.**
- **On Linux and macOS it does not clean up background jobs.** A process the agent starts with `&` can outlive the run there. On Windows every process a command starts is ended when the run ends.
- **It does not defend against prompt injection.** Text the agent reads from files, command output or the web arrives in its context alongside your task, and could contain instructions.

## How to run it safely

1. Use `--sandbox docker` whenever the task or the repo is not fully trusted, and whenever you leave it unattended.
2. Give it a scratch copy of a repo, not your only copy. Commit or back up first.
3. Use `--confirm` the first few times, and for any task that touches things outside the working folder.
4. Keep `.env` files and other secrets out of the working folder. `harness doctor --dir <folder>` and `harness run` warn when they find one.
5. Set `--max-cost` to what you are willing to spend on the run.

## Where your data goes

- **To Anthropic.** Everything in the agent's context is sent to the Claude API on every turn: your task, the commands it runs, their output, and the contents of any file it reads. A refused request may be retried on another Anthropic model.
- **To disk.** Each run writes a full record to `<working folder>/.ctx/sessions/<id>/`: every reply, command and output, in plain text. Nothing there is deleted automatically. The folder contains its own ignore file, so git does not pick it up.
- **Nowhere else.** The harness has no telemetry and makes no other network calls.

## Where your API key is kept

`harness setup` writes the key as plain text to `.env` in your user settings folder: `~/.config/clm-harness/` on macOS and Linux, `%APPDATA%\clm-harness\` on Windows. On macOS and Linux the file is readable by your user only. It is not encrypted and not stored in the system keychain. The key is never passed to the agent's commands, and its value is redacted from command output.

## Reporting a problem

If you find a way to make the harness run a command it should refuse, or to leak a secret it should redact, please open an issue with the command and what happened. Leave real secrets out of the report.
