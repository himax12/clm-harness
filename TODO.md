# To do

The ordered work list for the launch. `LAUNCH.md` explains why each item is here; the codes in brackets point to its rows. Tick an item when its "done when" is true, and update the matching status in `LAUNCH.md` or `AUDIT.md`.

**Owner:** *you* means it needs your account, your money or your decision. Everything else is a code or writing task.

## 0. Decisions (you)

Nothing below can finish without these.

- [ ] **Commit email.** Rewrite history to remove the personal Gmail address from 13 commits, or accept it being public. [GP2]
- [ ] **Sandbox default.** Should `harness run` use the sandbox whenever Docker is available? [AR14]
- [ ] **Benchmark budget.** A dollar ceiling for the comparison runs. [EV1]
- [ ] **Second provider.** Which one to run first (DeepSeek is the cheapest), and a key for it. [MP1]
- [ ] **Contact address** for the code of conduct. [DC1]

## 1. Release 0.1.0: public, installable, not announced

### Housekeeping

- [x] Merge pull request #4. Merged on 4 October 2026.
- [x] Commit `LAUNCH.md` and `TODO.md` through a pull request.
- [ ] Delete the merged branch `sandbox-and-licence` and turn on automatic deletion of merged branches. *You, in settings.* [GP10]
- [ ] Set your GitHub no-reply address as the git email for this repository. *You.* Done when a new commit shows it. [GP2]

### Code

- [x] Rename the packages `harness` and `bench` to `clm_harness` and `clm_harness.bench`. Done when the wheel has one top-level package and all tests pass. [PK2, AR8]
- [x] Add `clm-harness` as a second command name next to `harness`. [PK3]
- [x] Move the `anthropic` import out of `cli.py`'s doctor command and into `llm.py`. Done when only `llm.py` imports it. [AR5]
- [x] Add a price entry for Haiku 4.5. [MP5]
- [ ] Make Haiku 4.5 runnable: it rejects the `effort` setting and adaptive thinking that the request sends. Part of the portable request mode. [MP1]
- [x] Add Python 3.10 and 3.11 to CI; lower `requires-python` if they pass. Both pass. [PK7]
- [ ] Apply the sandbox-default decision. [AR14]
- [x] Add a publish workflow using PyPI trusted publishing, triggered by a GitHub release. [PK5]

### Setup on every system

- [x] One-line installers for macOS, Linux, WSL and Windows, built on uv. [PK6]
- [x] `harness setup` to save the key where an installed copy finds it. [VS7]
- [x] `harness doctor` says what to install on each system; bash is optional when Docker works.
- [x] macOS in CI, and the installer run on all three systems in CI. [K2 in `AUDIT.md`]
- [ ] Point the installers at PyPI once `clm-harness` is published; today they install from GitHub. [PK6]
- [ ] One live run on macOS and one on Linux. *Needs a machine and a few cents.*
- [ ] A Homebrew tap, and winget and Scoop manifests. Each needs a published release first.

### Writing

- [x] README: badges for CI, licence and Python. [VS5]
- [ ] README: the PyPI badge, once the first release is published. [VS5]
- [x] README: one paragraph on who it is for, and a short comparison with ordinary compaction, `pi-clm`, mini-swe-agent and the paper's code. [VS6]
- [ ] README: a quickstart that starts from `uvx clm-harness`. [VS7, PK6]
- [x] README: an FAQ covering cost, Windows paths, Docker not running, and refusals. [DC5]
- [x] Add `CITATION.cff`, citing the paper too. [DC2]
- [ ] Add `CODE_OF_CONDUCT.md`. Waits for the contact address. [DC1]
- [x] Add a feature-request issue template and a Dependabot configuration. [DC7, DC8]
- [x] Scan every tracked text file for personal paths, names and addresses. None found. [GP5]
- [ ] Read `PLAN.md`, `IMPLEMENTATION.md` and `AUDIT.md` once as an outsider for tone. *You.* [GP5]

### Going public (you)

Do these in this order, on one day.

- [ ] Scan the git history for secrets one last time. Done when the scan reports 0. [GP1]
- [ ] Apply the commit-email decision. [GP2]
- [ ] Create a PyPI account and register the trusted publisher for `clm-harness`. [PK1]
- [ ] Make the repository public. [GP7]
- [ ] Turn on secret scanning, push protection, Dependabot alerts and Discussions. [GP9, VS12]
- [ ] Set the topics: `ai-agents`, `coding-agent`, `llm`, `claude`, `context-management`, `context-engineering`, `agent-harness`, `anthropic`. [VS2]
- [ ] Upload a social preview image (the context-size chart). [VS3]
- [ ] Tag `v0.1.0` and publish the GitHub release. Done when `uvx clm-harness doctor` works on a clean machine. [PK4, PK6]

## 2. Release 0.2.0: the one to announce

### Other models

- [ ] Split the types out of the loop: `ModelReply`, `Model`, `Usage` and prompt loading in their own modules. [AR1]
- [ ] Make the provider one object: reply, summarise, credential check, prices, capabilities. `cli.py` picks it by name. [AR5, MP3]
- [ ] Add a portable request mode: an ordinary bash tool definition, no beta features, thinking and cache markers optional. [MP1, AR4]
- [ ] Add `--provider` and `--base-url`, and make `doctor` check the chosen provider. [MP2, MP10]
- [ ] Move prices to the provider and accept a user-supplied price table. [MP5, AR6]
- [ ] Run one live task on the chosen Anthropic-compatible provider. *Needs your key and a few cents.* Done when a session finishes and its edits are applied. [MP1]
- [ ] On that run, record the cache behaviour after an edit and the refused-edit rate. [MP6, MP8]
- [ ] Add a tested-models table to the README. [MP9]

### Evidence

- [ ] Fix the baseline so it does not have to retype each batch. [EV2, AR15]
- [ ] Run the comparison: both modes, both tasks, three seeds. *Needs the benchmark budget.* [EV1, EV3]
- [ ] Run one live task in the sandbox. *A few cents.* [EV8]
- [ ] Write `RESULTS.md`: accuracy, cost per task, spread, and the command that reproduces it. [EV6, EV7]

### Announcing (you, with drafts from me)

- [ ] Trim the dead time from the demo video and host it where it plays. [VS14]
- [ ] Write the launch post. [VS8]
- [ ] Tell the paper's authors and the `pi-clm` author before posting. [VS10]
- [ ] Open five starter issues from the small items in `AUDIT.md`. [VS13]
- [ ] Post: Show HN, r/LocalLLaMA, r/ClaudeAI, X, LinkedIn. [VS9]
- [ ] Add `README.zh-CN.md`, then post on V2EX and Juejin. Worth doing only once a Chinese provider is in the tested-models table. [VS9]
- [ ] Submit to the awesome lists for agents and for Claude Code. [VS11]

## 3. Release 0.3.0: reach and resilience

- [ ] An OpenAI-compatible adapter: OpenAI and Codex models, OpenRouter, Ollama, Hermes models. [MP4, EC8]
- [x] A `--json` flag that prints status, answer, cost and session path. [EC2]
- [ ] Approval through a callback in place of the keyboard prompt. [EC7, AR13]
- [x] An MCP server exposing one "run a task" tool, and a `SKILL.md` describing when to call it. [EC4, EC5]
- [ ] Document `run` as the public Python entry point. [EC6]
- [ ] An executor interface, with host and Docker as its two implementations. [AR7]
- [ ] Split the turn function into phases around a run-state object. [AR2]
- [ ] Save run state each turn and add `harness resume`. [AR3]
- [ ] A realistic coding-task evaluation on a small set of real bug fixes. [EV4]
- [ ] Publish the sandbox image to GitHub's container registry. [PK8]

## 3a. Other agents

See `integrations/README.md`.

- [x] A shared core for a host's own message list: one tool, edits kept as an overlay. [EC9, EC10]
- [x] Hermes Agent context engine plug-in, checked through Hermes's real loader. [EC9]
- [x] opencode plug-in, type-checked against opencode's types. [EC10]
- [x] A weekly CI job that checks both plug-ins against their hosts' current releases.
- [x] One live session in Hermes Agent with the plug-in. Done on `claude-haiku-4-5`: 3 cents. [EC9]
- [x] One live session in opencode with the plug-in. Done on `claude-haiku-4-5`: 2 cents. [EC10]
- [x] On those sessions, check prompt caching after an edit. In opencode the part before the edit was still read from cache; Hermes reports totals only. [MP6]
- [ ] A long live session in each host, long enough for the size notices and the fallback to fire, counting refused edits. [MP8]
- [ ] A live session in each host on a second model.
- [ ] Check edits to earlier assistant messages on models that keep their thinking: it may be rejected.
- [x] One live task handed over from Codex CLI through the MCP server. Done: 1 cent. [EC4]
- [ ] Publish the opencode plug-in to npm.
- [ ] Move the opencode plug-in to opencode's newer plug-in API once it is the default. [EC10]
- [ ] Native Codex support, if its hooks gain the ability to replace history. [EC11]

## 4. Small items, any time

- [ ] Store only the changed blocks in each snapshot. [AR10]
- [ ] Refuse an edit that removes more than a set share of the context at once. [AR17]
- [ ] Mark command output as untrusted and add prompt-injection tests. [AR12]
- [ ] Use the provider's token count where one exists; check the estimate on Chinese text. [AR11, MP7]
- [ ] A config file and environment overrides. [AR9]
- [ ] Add a type checker to CI. [AR18]
- [ ] An architecture diagram and a written walkthrough of one session. [DC3, DC4]
