# Open-source readiness audit

Audited on 3 October 2026 at commit `1707c7d` (branch `phase-2-3`).

**Verdict: not ready for an open-source launch.** The core works and is well tested, but the project has no licence, no README, no CI and no sandbox; it exposes other secrets to the agent; and the one baseline benchmark run was invalid.

## How to read this

| Status | Meaning |
|---|---|
| Done | Implemented and verified by a test, a live run or a direct check |
| Partial | Exists but incomplete, verified only narrowly, or undocumented |
| Missing | Not implemented, or never tested |

Statuses come from checks run on the repo on the audit date (file presence, a scan of git history, a wheel build, two shell experiments, the pilot benchmark results) and from what the tests and live runs had already established. When an item is fixed, change its status here and note the commit.

## Changes since the audit

| Date | Items | Change |
|---|---|---|
| 3 Oct 2026 | A5, A9 fixed; A6, A8 mitigated | Secret-looking environment variables are removed from the agent's commands; known secret values and common key formats are redacted from command output; `harness doctor` added; `run` warns about a `.env` in the working folder. |
| 3 Oct 2026 | B2, B8, B9, B12 fixed; C1 fixed; N7 partly | Command output goes to a file, so background jobs no longer stall a turn and a command printing over 10 MB is killed; `git push` is refused without `--allow-push`; `SAFETY.md` added. |

The summary counts below include these changes.

## Summary

| Category | Done | Partial | Missing | Total |
|---|---|---|---|---|
| A. Secrets and authentication | 7 | 3 | 1 | 11 |
| B. Command execution safety | 9 | 0 | 4 | 13 |
| C. Data handling and privacy | 2 | 1 | 3 | 6 |
| D. Prompt injection and trust | 3 | 1 | 2 | 6 |
| E. Loop correctness and robustness | 5 | 2 | 5 | 12 |
| F. Context management | 5 | 6 | 1 | 12 |
| G. Model and API integration | 4 | 3 | 3 | 10 |
| H. Cost control | 3 | 3 | 1 | 7 |
| I. CLI and product design | 4 | 2 | 5 | 11 |
| J. Configuration | 1 | 1 | 2 | 4 |
| K. Cross-platform | 4 | 1 | 3 | 8 |
| L. Testing and quality | 1 | 1 | 6 | 8 |
| M. Benchmark and evidence | 4 | 1 | 6 | 11 |
| N. Documentation | 1 | 3 | 4 | 8 |
| O. Licensing and legal | 1 | 3 | 3 | 7 |
| P. Repository and release | 3 | 1 | 4 | 8 |
| Q. Observability | 4 | 0 | 3 | 7 |
| R. Community | 0 | 0 | 4 | 4 |
| **Total** | **61** | **32** | **60** | **153** |

## Launch blockers, in order

| # | Blocker | Items |
|---|---|---|
| 1 | No LICENSE file; without one the code is all-rights-reserved | O1 |
| 2 | No README with install, quickstart and a safety warning | N2 |
| 3 | The agent runs arbitrary commands with the user's full permissions and can read secret files on disk | A6, A7, B4, B5 |
| 4 | Session folders are not auto-ignored in target repos, so transcripts can be committed by accident | C2 |
| 5 | The baseline benchmark run ended in an API refusal, so there is no valid comparison | M4, M5 |
| 6 | No CI, lint or type checks | L5, L6 |
| 7 | Only Windows is tested | K2 |
| 8 | Ctrl+C leaves a session unfinished | E2 |
| 9 | The model is hardcoded, and the price table is correct for that one model only | G4, H3 |
| 10 | No progress output during a run | I2 |

---

## A. Secrets and authentication

| # | Check | Status | Note |
|---|---|---|---|
| A1 | API key read from environment or `.env` | Done | `harness/env.py`, tested |
| A2 | `.env` ignored by git; `.env.example` committed | Done | Verified with `git check-ignore` |
| A3 | No key in git history | Done | Scanned all branches: 0 matches |
| A4 | Key hidden from the agent's commands | Done | `ANTHROPIC_*` stripped; tested |
| A5 | Other secrets hidden from the agent's commands | Done | Secret-looking variables (`*TOKEN*`, `*SECRET*`, `*PASSWORD*`, `*_KEY`, `*_AUTH_*` and similar) are removed; `--pass-env NAME` opts one back in; tested |
| A6 | Agent cannot read a `.env` in its working folder | Partial | Still readable. Mitigated: its values are redacted from command output, and `run` and `doctor` warn when one is present. Needs a sandbox to close |
| A7 | Agent cannot read `~/.ssh`, `~/.aws`, git credentials | Missing | No file confinement; needs a sandbox (B4, B5) |
| A8 | Secrets never written to transcripts | Partial | Removed variables' values, `.env` values and common key formats are redacted before output is stored or sent. A secret in any other file or format is not |
| A9 | Credential check before a run (`harness doctor`) | Done | Checks shell, scripting tool, credential and API access via free token counting; verified live |
| A10 | `.env` does not override the real environment | Done | Tested |
| A11 | Other auth methods (profiles, Bedrock, Vertex) | Partial | The SDK supports profiles; never tried |

## B. Command execution safety

| # | Check | Status | Note |
|---|---|---|---|
| B1 | Destructive-command blocklist | Done | `rm -rf /`, `mkfs`, `dd`, fork bomb, shutdown; tested |
| B2 | Blocklist limits stated to users | Done | `SAFETY.md` lists what is and is not protected; `harness run --help` points to it |
| B3 | Approve-each-command mode | Done | `--confirm`; the default is unattended |
| B4 | OS sandbox or container | Missing | None; `SAFETY.md` tells users to supply their own |
| B5 | Writes confined to the working folder | Missing | The agent can write anywhere; needs B4 |
| B6 | Network egress control | Missing | Unrestricted; needs B4 |
| B7 | Timeout with process-tree kill | Done | Tested on Windows |
| B8 | Background jobs do not stall a turn | Done | Output goes to a file and the harness waits on bash alone; `sleep 6 &` now returns at once; tested. Background jobs are not cleaned up when the run ends |
| B9 | Cap on captured output size | Done | A command printing more than 10 MB is killed; at most the cap is read into memory, as head and tail; tested |
| B10 | Interactive commands cannot hang | Done | stdin is closed |
| B11 | CPU, disk and process limits | Missing | None; needs B4 |
| B12 | Guard on `git push` and force-push | Done | `git push` in any form is refused unless the run is started with `--allow-push`; tested |
| B13 | Heredoc data not scanned; shell-fed heredocs scanned | Done | Tested |

## C. Data handling and privacy

| # | Check | Status | Note |
|---|---|---|---|
| C1 | Users told that file contents and output go to Anthropic | Done | `SAFETY.md`, "Where your data goes" |
| C2 | `.ctx/` auto-ignored in the target repo | Missing | Only ignored in this repo; the harness should write `.ctx/.gitignore` |
| C3 | Secret redaction in stored transcripts | Missing | None |
| C4 | No telemetry | Done | None exists |
| C5 | Retention or cleanup command for sessions | Missing | Sessions accumulate forever |
| C6 | Fallback to another model disclosed | Partial | On by default; recorded per turn; not documented for users |

## D. Prompt injection and trust

| # | Check | Status | Note |
|---|---|---|---|
| D1 | Command output marked as untrusted | Missing | Output arrives as plain user-role text beside the task |
| D2 | Model-written notes cannot act as instructions | Partial | One prompt line only |
| D3 | Output cannot forge block headers | Done | Header-like lines are escaped; tested |
| D4 | Task and user messages cannot be edited | Done | Tested |
| D5 | Rollback note cannot be edited | Done | Kept outside the file |
| D6 | Injection test cases | Missing | None |

## E. Loop correctness and robustness

| # | Check | Status | Note |
|---|---|---|---|
| E1 | Step, call, cost and time limits | Done | Each tested |
| E2 | Ctrl+C or crash still closes the session | Missing | No `try/finally`; no `finish` event or `usage.json` |
| E3 | API failure closes the session cleanly | Done | Tested and seen live |
| E4 | Command from a cut-off reply never runs | Done | Tested |
| E5 | Invalid tool input is re-prompted | Done | Tested |
| E6 | Extra tool calls in one reply handled | Partial | The first is kept; the rest are dropped silently and the model is not told |
| E7 | Refusal handled and explained | Partial | The run stops; the refusal category is not recorded (hit in the pilot) |
| E8 | Unknown stop reasons end the run as an error | Done | Tested |
| E9 | Resume a session | Missing | Out of scope so far |
| E10 | Follow-up user messages | Missing | One task per run |
| E11 | Repeated-command loop detection | Missing | Only the caps |
| E12 | Verify-before-finish guard | Missing | Planned for a later iteration |

## F. Context management

| # | Check | Status | Note |
|---|---|---|---|
| F1 | File format, parsing, whole-edit validation | Done | 20+ tests; 38 edits applied live, 0 refused |
| F2 | Receipt after every edit | Done | Tested and seen live |
| F3 | Per-block size ledger and size line | Done | |
| F4 | Notice thresholds | Partial | They work; tuned on a single run |
| F5 | Rollback with pinned note | Partial | Tested; never triggered live |
| F6 | Originals archive | Done | The model used it live to recover a pruned block |
| F7 | Undo | Partial | Works on a real session; no practical use until resume exists |
| F8 | Edit cost recorded | Done | `reread_tokens` is logged; not shown to the model |
| F9 | Cache-aware edit gate | Missing | Planned; edits near the top re-send everything |
| F10 | Token estimate accuracy | Partial | Within about 2% on one English and code run; other content untested |
| F11 | Snapshot storage bounded | Partial | A full copy of the context per edit |
| F12 | Whole-context wipe prevented | Partial | "No headers" is refused; deleting every non-user block is allowed |

## G. Model and API integration

| # | Check | Status | Note |
|---|---|---|---|
| G1 | Request accepted by the live API | Done | Three live tasks |
| G2 | Prompt caching works | Done | 86 to 96% cache reads on turns without an edit |
| G3 | No dependence on beta features | Partial | Uses a beta endpoint and the fallback beta header |
| G4 | Model selectable | Missing | Hardcoded to `claude-opus-5-5`; no `--model` |
| G5 | Retries with backoff | Done | Tested with fakes; not seen live |
| G6 | Bash tool used as documented | Partial | No tool result is ever returned; works live, undocumented |
| G7 | Other providers or local models | Missing | Anthropic only |
| G8 | Reasoning summaries captured | Done | Seen live |
| G9 | One-hour cache option | Missing | Five-minute only |
| G10 | SDK version bounded | Partial | `anthropic>=1.0` with no upper bound; the lock file pins 1.11 |

## H. Cost control

| # | Check | Status | Note |
|---|---|---|---|
| H1 | Per-run dollar cap | Done | Tested |
| H2 | Benchmark spend ceiling | Done | Tested |
| H3 | Prices correct for the serving model | Partial | One hardcoded table; wrong on a fallback turn |
| H4 | Cap cannot be overshot | Partial | Checked before each call, so it can overshoot by one call |
| H5 | Summary calls charged to the run | Done | Tested |
| H6 | Running cost visible during a run | Missing | Only at the end |
| H7 | `usage.json` hand-checked against the transcript | Partial | Summed once informally; the planned check was not done |

## I. CLI and product design

| # | Check | Status | Note |
|---|---|---|---|
| I1 | `run`, `log`, `undo`, `bench`, `report` | Done | |
| I2 | Progress output during a run | Missing | Silent for minutes |
| I3 | `--model`, `--effort`, `--timeout` flags | Missing | |
| I4 | Safe default mode | Partial | Runs unattended by default |
| I5 | Meaningful exit codes | Done | 0 finished, 1 otherwise, 2 no client |
| I6 | Session inspection | Done | `harness log` |
| I7 | List sessions | Missing | The folder must be found by hand |
| I8 | Help text | Partial | Present; thin on `run` |
| I9 | UTF-8 output on Windows | Done | |
| I10 | Task from a file or stdin | Missing | Argument only |
| I11 | Name checked on PyPI; clear positioning | Missing | `clm-harness` and the generic `harness` command are unchecked |

## J. Configuration

| # | Check | Status | Note |
|---|---|---|---|
| J1 | All defaults in one place | Done | `Config` |
| J2 | Config file or environment overrides | Missing | Flags only |
| J3 | Sensible default budget | Partial | 32,000 is the experiment setting, not a practical default |
| J4 | Config validated | Missing | A budget below the reserve is accepted |

## K. Cross-platform

| # | Check | Status | Note |
|---|---|---|---|
| K1 | Windows with Git Bash | Done | Tested and run live |
| K2 | Linux and macOS | Missing | Code paths exist; never run |
| K3 | Bash discovery with override | Done | `HARNESS_BASH` |
| K4 | `python3` stub detection | Done | |
| K5 | Paths with spaces | Done | Tested |
| K6 | `.gitattributes` for line endings | Missing | Git warns on every commit |
| K7 | Python versions | Partial | Runs on 3.12; 3.13 and 3.14 untested |
| K8 | WSL | Missing | Untested |

## L. Testing and quality

| # | Check | Status | Note |
|---|---|---|---|
| L1 | Test suite passes | Done | 170 tests, about 45 s |
| L2 | Tests skip cleanly without bash | Partial | Shell tests assume Git Bash |
| L3 | Coverage measured | Missing | |
| L4 | Scripted live smoke test | Missing | Done by hand each time |
| L5 | CI | Missing | No workflows |
| L6 | Lint, format, type check | Missing | No config |
| L7 | Fuzz or property tests for the parser | Missing | |
| L8 | Tests for the non-Windows branches | Missing | |

## M. Benchmark and evidence

| # | Check | Status | Note |
|---|---|---|---|
| M1 | Deterministic generators, sizing checked | Done | Tested |
| M2 | Exact-match scorer | Done | Tested |
| M3 | Model-managed pilot, key-value | Done | 24/24 correct, $1.08, one run |
| M4 | Baseline pilot, key-value | Missing | Ended in an API refusal on turn 5 ($1.38, 0/24); invalid, cause unknown |
| M5 | Fair baseline | Partial | It must retype each batch (about 6,300 output tokens) and cannot clear those commands |
| M6 | Full 12-run matrix | Missing | On hold until M4 is understood |
| M7 | Ledger task run live | Missing | |
| M8 | Multiple seeds and spread | Missing | |
| M9 | A realistic coding-task evaluation | Missing | Both tasks are synthetic |
| M10 | Claims limited to what was measured | Done | |
| M11 | `RESULTS.md` | Missing | |

## N. Documentation

| # | Check | Status | Note |
|---|---|---|---|
| N1 | Plan, spec and agent guide | Done | `PLAN.md`, `IMPLEMENTATION.md`, `AGENTS.md` |
| N2 | README | Missing | |
| N3 | Spec matches the code | Partial | Some pseudo-code predates later changes |
| N4 | Architecture diagram | Missing | |
| N5 | Docstrings on public functions | Partial | Present on most; uneven |
| N6 | Example session walkthrough | Missing | |
| N7 | Threat model | Partial | `SAFETY.md` lists protections and gaps; no attacker-by-attacker analysis |
| N8 | Changelog | Missing | |

## O. Licensing and legal

| # | Check | Status | Note |
|---|---|---|---|
| O1 | LICENSE | Missing | |
| O2 | Clean of the paper's non-commercial code | Partial | Reimplemented from the design in our own wording; not independently reviewed |
| O3 | Attribution for the paper and `pi-clm` | Missing | No NOTICE or citations in the repo |
| O4 | Dependency licences checked | Partial | Two direct dependencies; not audited |
| O5 | Trademark use ("Claude") | Partial | In the description; needs a nominative-use check |
| O6 | Benchmark data is original | Done | Generated from our own word lists |
| O7 | Citation file | Missing | |

## P. Repository and release

| # | Check | Status | Note |
|---|---|---|---|
| P1 | Clean default branch | Partial | `main` has 1 commit; the rest sit on an unmerged branch |
| P2 | Version tags and releases | Missing | 0 tags |
| P3 | Package builds with prompts included | Done | Wheel built; 3 prompt files present |
| P4 | Publish workflow | Missing | |
| P5 | Lock file committed | Done | `uv.lock` |
| P6 | Ignore rules | Done | `.ctx/`, `.env`, `bench_out/` |
| P7 | Branch protection | Missing | |
| P8 | Dependency update and audit | Missing | |

## Q. Observability

| # | Check | Status | Note |
|---|---|---|---|
| Q1 | Typed event transcript | Done | |
| Q2 | Usage and cost file | Done | |
| Q3 | Turn-by-turn log command | Done | |
| Q4 | Request dump or debug flag | Missing | |
| Q5 | Schema version in the transcript | Missing | |
| Q6 | Refusal details recorded | Missing | |
| Q7 | Fallback model recorded per turn | Done | |

## R. Community

| # | Check | Status | Note |
|---|---|---|---|
| R1 | CONTRIBUTING | Missing | |
| R2 | Code of conduct | Missing | |
| R3 | SECURITY policy | Missing | |
| R4 | Issue and PR templates | Missing | |

---

## Evidence gathered for this audit

| Check | Result |
|---|---|
| Standard files present | None of README, LICENSE, NOTICE, CONTRIBUTING, CODE_OF_CONDUCT, SECURITY, CHANGELOG, `.gitattributes`, CI workflows, pre-commit config |
| Key-like strings in git history, all branches | 0 |
| `.env` ever committed | No |
| Lint or type-check configuration in `pyproject.toml` | None |
| Wheel build | 24 files, including the 3 prompt files |
| `sleep 8 & echo started` | Returned after 8.2 s, not immediately |
| Command printing 30 MB | Completed in 1.2 s with all 30,000,000 characters held in memory |
| Secret-looking variables passed to the agent's commands | At least one non-Anthropic `*_TOKEN` variable in the audit shell |
| Interrupt handling in `loop.py` and `cli.py` | No `KeyboardInterrupt` or `finally` handling |
| Code size | 1,845 lines in `harness/` and `bench/`, 1,340 lines of tests |
| Repo | Private; default branch `main`; 0 tags |

## Pilot benchmark, for items M3 to M5

One key-value run per mode, seed 1, about 99,000 tokens of input against a 29,952-token limit.

| Mode | Status | Accuracy | Cost | Model calls | Notes |
|---|---|---|---|---|---|
| Model-managed | finished | 24/24 | $1.08 | 74 | 25 edits, none refused, no rollback |
| Baseline | refusal | 0/24 | $1.38 | 5 | Retyped each batch by hand; compacted on every turn; the API refused the fifth request |

This is not a valid comparison. The refusal category was not recorded, and the baseline cannot clear the long commands it retypes.
