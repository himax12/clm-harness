# Launch audit

Written on 4 October 2026 against `main` at `ed36e2b` plus pull request #4.

`AUDIT.md` asks whether the code is safe and correct enough to publish. This document asks a wider question: what has to be true for an open-source launch to go well. It covers making the repository public, packaging, visibility, evidence, support for other models and other agents, and a review of the architecture.

Updated the same day for the `release-0.1` branch: the package rename, Python 3.10 and 3.11, the publish workflow, and the README and community files.

Statuses use the same words as `AUDIT.md`: **Done**, **Partial**, **Missing**. Where a row says "checked", it was checked on the date above. Facts about other vendors come from their public documentation and have not been tested here.

## Verdict

The code is in better shape than the project around it. Three things are missing, and they matter more than anything else in this document:

1. **No evidence that the idea helps.** There is one successful run of the model-managed mode and no valid baseline to compare it with.
2. **Nothing to install.** There is no release, no package on PyPI, and the repository is private.
3. **One model, one provider.** Only `claude-opus-5-5` has been run, and the request cannot work anywhere else as written.

A sensible path is a quiet public release first (labelled experimental), then the announcement once there is a fair benchmark and a second provider.

## Do these first

| # | Action | Why now | Needs |
|---|---|---|---|
| 1 | Decide what to do about the personal Gmail address in 13 commits | It becomes public with the repository, and rewriting history after that is disruptive | Your decision |
| 2 | Rename the importable packages `harness` and `bench` | Both are generic top-level names that will collide with other packages; renaming after a release breaks users | A code change |
| 3 | Merge pull request #4 | The README media and current audit are in it | Your click |
| 4 | Run a fair benchmark comparison | It is the claim the project rests on | A fixed baseline, then money |
| 5 | Add a portable request mode and run one non-Claude model | Unlocks DeepSeek, Kimi, Qwen, GLM and MiniMax with little code | A code change, a key for one of them |
| 6 | Tag `v0.1.0` and publish to PyPI | People install from PyPI, not from a clone | A PyPI account |
| 7 | Decide whether the sandbox is the default | The safe mode is opt-in today | Your decision |
| 8 | Set the repository's topics, social image, Discussions and security features | Cheap, and they affect who finds the project | Ten minutes in settings |
| 9 | Add badges, a one-minute quickstart, a comparison and an FAQ to the README | First impressions | Writing |
| 10 | Announce | Last, once 4 to 6 are done | A launch post |

---

## Checklist

### GP. Going public

| # | Check | Status | Note |
|---|---|---|---|
| GP1 | No secrets in git history | Partial | Scanned on 3 October: 0 matches. GitGuardian passes on every pull request. Scan once more just before the switch |
| GP2 | No personal data in commit metadata | Missing | 13 commits are authored with a personal Gmail address; 4 use GitHub's no-reply address. Either accept it or rewrite history before going public, and set the no-reply address for future commits |
| GP3 | No local-only refs on the remote | Done | Checked: the remote has `main`, one feature branch and pull-request refs. The editor's checkpoint commits were never pushed |
| GP4 | Licence | Done | MIT |
| GP5 | Internal documents read well to an outsider | Partial | `PLAN.md`, `IMPLEMENTATION.md` and `AUDIT.md` are candid, which is good, but they mention local paths and a disk incident. Read them once as a stranger would |
| GP6 | No session transcripts or benchmark output committed | Done | `.ctx/` and `bench_out/` are ignored |
| GP7 | Repository is public | Missing | Private today |
| GP8 | `main` is protected | Done | Pull request and four CI jobs required |
| GP9 | Secret scanning, push protection and Dependabot alerts | Missing | Dependabot alerts are off (checked). All three are free once the repository is public |
| GP10 | Merged branches cleaned up | Partial | `sandbox-and-licence` remains; automatic deletion on merge is off |

### PK. Packaging and release

| # | Check | Status | Note |
|---|---|---|---|
| PK1 | Package name available and reserved | Partial | `clm-harness` is free on PyPI (checked). It is not reserved until something is published |
| PK2 | Import names are unlikely to collide | Done | One top-level package, `clm_harness`, with the benchmark inside it |
| PK3 | Command name is unlikely to collide | Done | `harness` and `clm-harness` both work |
| PK4 | Version tag and release notes | Missing | No tags, no releases |
| PK5 | Publish workflow | Partial | The workflow exists. The trusted publisher still has to be registered on PyPI |
| PK6 | Install without cloning | Partial | One-line installers for all three systems install from GitHub with uv, with no clone and no Python needed. They need the repository to be public. PyPI is still to come |
| PK7 | Python versions as wide as the code allows | Done | 3.10 to 3.13. The suite passes on all four |
| PK8 | Sandbox image easy to get | Partial | Built on first use, which needs network and about a minute. Publishing it to GitHub's container registry would remove that step |
| PK9 | Wheel contains prompts and licence | Done | Checked by building it |
| PK10 | Changelog | Done | |

### VS. Visibility

| # | Check | Status | Note |
|---|---|---|---|
| VS1 | Repository description | Done | |
| VS2 | Topics | Missing | None set. Suggested: `ai-agents`, `coding-agent`, `llm`, `claude`, `context-management`, `context-engineering`, `agent-harness`, `anthropic` |
| VS3 | Social preview image | Missing | Shown when the link is shared. The context-size chart would do |
| VS4 | Demo at the top of the README | Done | In pull request #4 |
| VS5 | Badges: CI, licence, PyPI, Python | Partial | CI, licence and Python are in. The PyPI badge waits for the first release |
| VS6 | Who it is for, and how it differs | Done | A section and a comparison table in the README |
| VS7 | Working in under a minute | Partial | One install command, then `harness setup` and `harness doctor`. Works once the repository is public |
| VS8 | Launch post | Missing | The story is strong: the idea, the cache bug that cost every turn, the 77 GB incident, what was measured and what was not |
| VS9 | Channels chosen | Missing | English: Show HN, r/LocalLLaMA, r/ClaudeAI, X, LinkedIn, dev.to. Chinese: a `README.zh-CN.md`, V2EX, Juejin, Zhihu, and a Gitee mirror |
| VS10 | Paper authors and `pi-clm` author told | Missing | A courtesy, and they may link to it |
| VS11 | Listed where people look | Missing | Awesome lists for agents and for Claude Code; the paper's implementations list |
| VS12 | Discussions enabled | Missing | Off (checked) |
| VS13 | Starter issues | Missing | The small open items in `AUDIT.md` are ready-made |
| VS14 | Video hosted where it plays | Partial | The MP4 is in the repository, has dead time at the end, and does not play inline on GitHub |
| VS15 | Claims limited to what was measured | Done | The README is careful |

### EV. Evidence

| # | Check | Status | Note |
|---|---|---|---|
| EV1 | A valid comparison of the two modes | Missing | The baseline pilot ended in a refusal |
| EV2 | A fair baseline | Partial | It must retype each batch and cannot clear those commands |
| EV3 | More than one seed, with spread | Missing | |
| EV4 | A realistic coding task | Missing | Both benchmark tasks are synthetic. A small set of real bug-fix tasks would persuade more people than either |
| EV5 | Results on a second model | Missing | |
| EV6 | Cost per task reported next to accuracy | Partial | Recorded per run; not summarised |
| EV7 | One command reproduces the numbers | Partial | `harness bench` exists; no `RESULTS.md` |
| EV8 | A live run in the sandbox | Missing | Tested with scripted replies only |

### MP. Models and providers

Today the request in `llm.py` uses five things only Anthropic's own API accepts: the beta endpoint with the fallback header, `fallbacks`, adaptive thinking with summaries, the `effort` setting, and Anthropic's built-in bash tool type. Any other endpoint is likely to reject it, including the ones that advertise Anthropic compatibility.

| Target | Route | What is in the way | Effort |
|---|---|---|---|
| Other Claude models | `--model` | Untested. Haiku 4.5 is priced but rejects the `effort` setting and adaptive thinking that the request sends | Small |
| Bedrock, Vertex, Foundry | The SDK's other clients | The beta features may be unavailable there | Medium |
| DeepSeek, Kimi, Qwen, GLM, MiniMax | Their Anthropic-compatible endpoints, by setting a base URL | The five features above | Small to medium |
| OpenAI models, including the Codex models | A second adapter on OpenAI's API | Does not exist | Medium |
| OpenRouter, Ollama, vLLM, LM Studio, Hermes models | The same second adapter with a base URL | Does not exist | Small once the adapter exists |

| # | Check | Status | Note |
|---|---|---|---|
| MP1 | A portable request mode | Missing | An ordinary tool definition for bash, no beta features, thinking and cache markers optional |
| MP2 | Base URL and key name configurable | Missing | The SDK reads `ANTHROPIC_BASE_URL` itself, but `doctor` and the messages assume Anthropic |
| MP3 | Adapter chosen by provider, not hard-wired | Missing | `cli.py` calls `_claude` directly |
| MP4 | An OpenAI-compatible adapter | Missing | |
| MP5 | Prices per provider, or supplied by the user | Missing | An unknown model is charged at Opus rates, which would overstate a cheap model's cost many times over |
| MP6 | Cost of a context edit measured per provider | Missing | The design assumes Anthropic's cache markers. OpenAI and DeepSeek cache a repeated prefix automatically, so an edit should behave similarly, but it has to be measured |
| MP7 | Token estimate checked on non-English text | Missing | Characters divided by four is far off for Chinese |
| MP8 | A behaviour bar for each model | Missing | The idea depends on the model editing a file without breaking it. Record the refused-edit rate per model and state a minimum |
| MP9 | Tested-models table in the README | Missing | |
| MP10 | `doctor` checks the chosen provider | Missing | It checks Anthropic only |

### EC. Other agents and tools

There are two kinds of support. A host can hand a whole task to this harness (delegate), which works for any agent that accepts MCP servers. Or a plug-in can bring model-managed context into the host itself (native). An earlier version of this section said native support was impossible because a host owns its context window. That was wrong: Hermes Agent has a context engine plug-in slot, and opencode has a hook that edits the messages before each request. Codex CLI has neither; its hooks cannot change history. `integrations/README.md` has the details.

| # | Check | Status | Note |
|---|---|---|---|
| EC1 | `AGENTS.md` at the root | Done | Read by Codex CLI and other agents working on the repository |
| EC2 | Machine-readable result | Done | `harness run --json` |
| EC3 | Stable exit codes | Done | 0, 1 and 2 |
| EC4 | An MCP server exposing one "run a task" tool | Done | `harness mcp`: one tool, `run_task`, sandboxed by default, with a cost ceiling. Called once from a live Codex CLI session |
| EC5 | An agent skill describing when to call it | Done | `integrations/skill/SKILL.md` |
| EC6 | A documented Python entry point | Partial | `clm_harness.loop.run` works but is not documented as public |
| EC7 | Approval through a callback, not the keyboard | Missing | `--confirm` calls `input()`, which cannot work when another program is the caller |
| EC8 | Hermes models as the model | Missing | Covered by MP4 |
| EC9 | Native plug-in for Hermes Agent | Partial | `integrations/hermes/clm`. One short live session on one model worked. No long session, and nothing on a model that keeps its thinking |
| EC10 | Native plug-in for opencode | Partial | `integrations/opencode/clm.ts`. One short live session on one model worked, with the cache intact before the edit. The hook it uses is experimental |
| EC11 | Native support in Codex CLI | Missing | Blocked upstream: hooks cannot edit history |

### DC. Documentation and community

| # | Check | Status | Note |
|---|---|---|---|
| DC1 | Code of conduct | Missing | Needs a contact address |
| DC2 | Citation file | Done | `CITATION.cff`, citing the paper as well |
| DC3 | Architecture diagram | Missing | |
| DC4 | A walkthrough of one session | Partial | The media show one; no written version |
| DC5 | FAQ and troubleshooting | Done | A Questions section in the README |
| DC6 | Roadmap | Partial | This file and `AUDIT.md` |
| DC7 | Feature-request template | Done |  |
| DC8 | Dependency updates | Done | Dependabot configuration for Python packages and GitHub Actions |

---

## Architecture review

### What holds up

- **Every turn is a fresh, self-contained request.** There is no conversation state on the provider's side and no tool results to pair up. This is why the idea can move to another provider at all.
- **An edit is applied whole or refused whole,** with a receipt. The model can damage the file and the context survives.
- **History is append-only.** Originals, snapshots and the transcript are never rewritten.
- **The loop depends on an interface, not on the SDK.** `ScriptedModel` lets 287 tests run without an API call.
- **The rules that protect caching are written down and tested.**
- **The sandbox is a narrow boundary:** two mounts, no network, no host environment.

### Findings

| # | Finding | Where | Why it matters | Change | Effort |
|---|---|---|---|---|---|
| AR1 | The model adapter imports from the loop | `llm.py` imports `ModelReply` and `PROMPTS` from `loop.py` | A second adapter has to do the same, and the loop cannot be changed freely | Move `ModelReply`, `Model`, `Usage` and prompt loading into their own modules | Small |
| AR2 | One function runs the whole turn | `_turns` in `loop.py` is about 230 lines with nine counters | Hard to test in parts; every new feature lands in the same function | A run-state object and one function per phase: limits, request, reply handling, command, edit, record | Medium |
| AR3 | Run state lives only in memory | Context, estimator, notice state and counters | No resume; a crash or an API error loses the run; `undo` has little use | Write the state each turn, or make the transcript complete enough to replay | Medium |
| AR4 | The request is Anthropic-only | `llm.py`, `_base` and `reply` | Blocks every other provider, including the compatible ones | Capability flags per provider; a portable mode | Small to medium |
| AR5 | The provider is not one object | `summarise` is outside the interface; `cli.py` builds the model itself (`doctor` used to import `anthropic` directly; fixed in 0.1.0) | Adding a provider means touching several files | One provider object: reply, summarise, credential check, prices, capabilities | Medium |
| AR6 | Prices and model names live in the global config | `config.py` | Wrong costs for any other model, and the cost limit then stops runs at the wrong point | Prices belong to the provider; allow a user-supplied table | Small |
| AR7 | Two ways of running commands in one class | `Shell` branches on the sandbox; Windows job code sits in the same file | A third backend would make it hard to follow | An executor interface: host, Docker, later bubblewrap and Seatbelt | Medium |
| AR8 | Generic package names | `harness`, `bench` | Collisions after install | Done in 0.1.0: one package, `clm_harness` | Done |
| AR9 | Configuration is flags only | `Config`, `cli.py` | Sandbox limits and several settings cannot be changed without editing code | A config file and environment overrides | Small |
| AR10 | A full copy of the context is stored at every edit | `Session.snapshot` | Storage grows with the square of the run length | Store only the blocks that changed; the originals are already kept | Small |
| AR11 | One token estimate for all text | `Estimator` | The limit is enforced with it; it will be wrong for Chinese and for other tokenizers | Use the provider's token count where one exists | Small |
| AR12 | Command output shares a message with the task | `build_content` | Text from a file or web page sits beside the user's instructions | Mark output as untrusted; add injection tests | Medium |
| AR13 | Approval is tied to the keyboard | `safety.confirm` | Cannot be embedded in another program | An approval callback, like the progress callback | Small |
| AR14 | The safe mode is opt-in | `Config.sandbox` | By default the only protection is a short blocked list | Default to the sandbox when Docker is available, and say so when it is not | Small |
| AR15 | The baseline is a weak comparison | `baseline.py` | Any result against it will be questioned | Fix the retyping problem; move its constants into `Config` | Medium |
| AR16 | Windows quirks leak into the prompt | `load_system` | The model is told about Git Bash paths | The sandbox removes the problem; another reason for AR14 | None |
| AR17 | The model may delete every block that is not a user message | `apply_edit` | One bad edit can erase its working memory | Refuse an edit that removes more than a set share at once | Small |
| AR18 | No type checker | The whole package | The interfaces are already written as protocols | Add one to CI | Small |

One design choice is not a finding but should be stated to users: the agent runs one command per reply. That keeps the context file consistent between commands, and it costs one model call per command.

### Target shape

```
cli ──> run loop ──> provider   (Claude, Anthropic-compatible, OpenAI-compatible)
           │   └───> executor   (host, Docker, later bubblewrap or Seatbelt)
           ├───────> context    (blocks, edit validation, budget)
           └───────> session    (transcript, originals, state for resume)
```

The loop would know four interfaces and nothing about any vendor or operating system.

### Order of work

1. Rename the packages (AR8). It is the only change that gets harder after a release.
2. Separate the types from the loop, make the provider one object, and add the portable mode (AR1, AR4, AR5, AR6). This is what opens other models.
3. Split out the executor (AR7) and make the sandbox the default (AR14).
4. Break up the turn function and persist run state (AR2, AR3). This is what makes resume possible.
5. The small items, in any order.

## Suggested releases

| Release | Contents | Announce? |
|---|---|---|
| 0.1.0 | Renamed package, PyPI, public repository, settings and README done | No. Public, labelled experimental |
| 0.2.0 | Portable mode, one Anthropic-compatible provider run live, fair benchmark with results | Yes |
| 0.3.0 | OpenAI-compatible adapter, MCP server, resume | A second, smaller announcement |

## Sources for facts about other vendors

- [Using the Anthropic API with DeepSeek](https://api-docs.deepseek.com/guides/anthropic_api/)
- [Guide to models compatible with Claude Code: DeepSeek, Qwen, MiniMax, Kimi, GLM](https://github.com/Alorse/cc-compatible-models)
- [Kimi's Anthropic-compatible endpoint](https://github.com/MoonshotAI/Kimi-K2/issues/129)
- [OpenAI: Prompt Caching 201](https://developers.openai.com/cookbook/examples/prompt_caching_201)
- [Hermes Agent](https://github.com/nousresearch/hermes-agent) and [its documentation](https://hermes-agent.nousresearch.com/docs/)
