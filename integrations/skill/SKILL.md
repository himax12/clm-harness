---
name: clm-harness
description: Hand a long, self-contained coding or research task to clm-harness, a separate agent that manages its own context, so the task does not fill yours. Use when a task means reading many files or running many commands and you only need the result.
---

# clm-harness

clm-harness is a separate coding agent. It works in one folder with shell commands and keeps its own context small by editing it as it goes. Use it to keep long, mechanical work out of your own context.

## When to use it

- Reading or summarising a large part of a codebase when you only need the summary.
- A long search, audit or refactor whose steps you do not need to see.
- Any task you can state completely in one message.

Do not use it for a task that needs this conversation's context, for a quick lookup you can do yourself, or when the user has not agreed to the cost: it is billed to the user's Anthropic API key.

## How to call it

If the `run_task` tool from the `clm-harness` MCP server is available, call it with:

- `task`: everything the agent needs. It cannot see this conversation.
- `dir`: the absolute path of the folder to work in.
- `max_cost`: a dollar limit. Start low; one dollar is the default.

It runs in a Docker sandbox by default, with no network. Set `sandbox` to false only if the user agrees, and `allow_net` only if the task needs to download something.

Without the MCP server, run the command and read the JSON it prints:

```
clm-harness run "<task>" --dir <absolute folder> --sandbox docker --max-cost 1 --json --quiet
```

## What comes back

A JSON object with `status`, `answer`, `dollars` and `session_dir`. Only `finished` is a success. For any other status, tell the user what it was; do not retry without asking, because each attempt costs money. `session_dir` holds the full record, and `clm-harness log <session_dir>` prints it turn by turn.
