# Using clm-harness from other agents

There are two ways another agent can use this project.

| | What it does | Works with |
|---|---|---|
| **Native plug-in** | Model-managed context inside the host: the host's own model lists, shortens, removes and restores blocks of its own context | Hermes Agent, opencode |
| **Delegate** | The host hands a whole task to clm-harness, which runs it with its own context | Codex CLI, and any agent that accepts MCP servers |

> **Status.** Each plug-in has been loaded through its host's real plug-in loader or types and driven with a synthetic session. **None has been used in a live session with a model yet.** Expect rough edges, and please report what you find.

## How the native plug-ins work

The host owns its message list, so the plug-ins do not use the context file that the standalone harness uses. The model gets one tool, `clm_context`:

| Action | What it does |
|---|---|
| `list` | Every block with its id, role, size and state |
| `replace` | Swap a block's text for a shorter version the model writes |
| `remove` | Take blocks out. Removing a tool call removes its result |
| `restore` | Bring back the original of anything replaced or removed |
| `show` | Print an original without restoring it |
| `tracker` | Set one short note that stays at the top |

The edits are an overlay applied to each request just before it is sent. The host's stored session is not changed, so every edit can be undone. The user's messages and the step in progress cannot be edited, and a tool result never loses the call that produced it. The rules live in one file, [`clm_harness/hostctx.py`](../clm_harness/hostctx.py), which both plug-ins use.

## Hermes Agent

A context engine plug-in. It replaces Hermes's built-in compressor: when the model has not kept the context under Hermes's threshold, the engine clears old tool output and drops old tool calls without a model call.

```
git clone https://github.com/himax12/clm-harness
cp -r clm-harness/integrations/hermes/clm ~/.hermes/plugins/clm
```

Then in `~/.hermes/config.yaml`:

```yaml
context:
  engine: "clm"
```

The plug-in is self-contained and needs nothing else installed. State is kept in `~/.hermes/clm/<session>.json`.

## opencode

A plug-in that calls the `clm-harness` command for the rules, so install clm-harness first (see the main README) and check that `clm-harness doctor` runs.

```
mkdir -p .opencode/plugins
cp clm-harness/integrations/opencode/clm.ts .opencode/plugins/clm.ts
```

Use `~/.config/opencode/plugins/` to have it in every project. State is kept in `.opencode/clm/`, which ignores itself in git. If the command is not found, set `CLM_HARNESS_BIN` to its full path; if it still fails, requests are sent unchanged.

The plug-in uses `experimental.chat.messages.transform`, which opencode marks experimental and which its newer plug-in API renames. It was written against `@opencode-ai/plugin` 1.18.

## Codex CLI and other agents: the MCP server

`clm-harness mcp` is an MCP server with one tool, `run_task`. The task runs in a Docker sandbox by default and is billed to your Anthropic API key. The calling agent sets a cost limit per task, capped at 2 dollars unless you raise `CLM_HARNESS_MCP_MAX_COST`.

**Codex CLI**

```
codex mcp add clm-harness -- clm-harness mcp
```

or in `~/.codex/config.toml`:

```toml
[mcp_servers.clm-harness]
command = "clm-harness"
args = ["mcp"]
```

**opencode** (`opencode.json`)

```json
{ "mcp": { "clm-harness": { "type": "local", "command": ["clm-harness", "mcp"] } } }
```

**Hermes Agent** (`~/.hermes/config.yaml`)

```yaml
mcp_servers:
  clm-harness:
    command: "clm-harness"
    args: ["mcp"]
```

[`skill/SKILL.md`](skill/SKILL.md) tells a host agent when to hand a task over. Copy the `skill` folder into the host's skills folder under the name `clm-harness`.

Codex cannot have a native plug-in today: its hooks can add context or block an action, but cannot change the history sent to the model.

## Checking the plug-ins against their hosts

```
# Hermes Agent: needs a clone of hermes-agent and its Python environment
python integrations/hermes/check.py <path to hermes-agent> integrations/hermes/clm

# opencode: needs Node, and clm-harness on PATH or CLM_HARNESS_BIN set
cd integrations/opencode && npm install && npm run check
```

Both drive the plug-in with a synthetic session and make no model call. CI runs them weekly and whenever this folder changes.
