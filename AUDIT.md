# Open-source readiness audit

Audited on 3 October 2026 at commit `1707c7d`. Last updated on 4 October 2026 at commit `add5e43` (branch `phase-2-3`).

**Verdict: not ready for an open-source launch, but the list of blockers is now short.** What remains is a licence, a sandbox, a valid benchmark comparison, and a release.

## How to read this

| Status | Meaning |
|---|---|
| Done | Implemented and verified by a test, a live run, CI or a direct check |
| Partial | Exists but incomplete, verified only narrowly, or undocumented |
| Missing | Not implemented, or never tested |

Statuses come from checks run on the repo (file presence, a scan of git history, a wheel build, shell experiments, the pilot benchmark, CI results) and from what the tests and live runs established. When an item is fixed, change its status here and add a row to the change log.

## Summary

| Category | Done | Partial | Missing | Total |
|---|---|---|---|---|
| A. Secrets and authentication | 7 | 3 | 1 | 11 |
| B. Command execution safety | 9 | 0 | 4 | 13 |
| C. Data handling and privacy | 3 | 2 | 1 | 6 |
| D. Prompt injection and trust | 3 | 1 | 2 | 6 |
| E. Loop correctness and robustness | 8 | 0 | 4 | 12 |
| F. Context management | 5 | 6 | 1 | 12 |
| G. Model and API integration | 5 | 3 | 2 | 10 |
| H. Cost control | 4 | 3 | 0 | 7 |
| I. CLI and product design | 9 | 1 | 1 | 11 |
| J. Configuration | 2 | 1 | 1 | 4 |
| K. Cross-platform | 6 | 1 | 1 | 8 |
| L. Testing and quality | 4 | 1 | 3 | 8 |
| M. Benchmark and evidence | 4 | 1 | 6 | 11 |
| N. Documentation | 3 | 3 | 2 | 8 |
| O. Licensing and legal | 2 | 3 | 2 | 7 |
| P. Repository and release | 3 | 1 | 4 | 8 |
| Q. Observability | 6 | 0 | 1 | 7 |
| R. Community | 3 | 0 | 1 | 4 |
| **Total** | **86** | **30** | **37** | **153** |

At the first audit the totals were 54 done, 32 partial and 67 missing.

## Launch blockers, in order

| # | Blocker | Items | Needs |
|---|---|---|---|
| 1 | No LICENSE file; without one the code is all-rights-reserved | O1 | A decision on which licence |
| 2 | The agent runs commands with the user's full permissions and can read secret files on disk | A6, A7, B4, B5, B6, B11 | A sandbox, most simply a Docker mode |
| 3 | No valid benchmark comparison; the one baseline run ended in an API refusal | M4, M5, M6 | A fairer baseline, then paid runs |
| 4 | The work is on an unmerged branch; no tag or release | P1, P2 | A decision to merge and tag |
| 5 | No live run outside Windows; macOS untested | K2 | A Linux or macOS machine with an API key |
| 6 | Only one model has been run | G4 | Paid runs on a second model |

Resolved since the first audit: README, CI and lint, clean shutdown on Ctrl+C, progress output, transcripts auto-ignored by git, other secrets hidden from the agent.

## Change log

| Date | Items | Change |
|---|---|---|
| 3 Oct 2026 | A5, A9 fixed; A6, A8 mitigated | Secret-looking environment variables are removed from the agent's commands; known secret values and common key formats are redacted from command output; `harness doctor` added; `run` warns about a `.env` in the working folder. |
| 3 Oct 2026 | B2, B8, B9, B12, C1 fixed; N7 partly | Command output goes to a file, so background jobs no longer stall a turn and a command printing over 10 MB is killed; `git push` is refused without `--allow-push`; `SAFETY.md` added. |
| 4 Oct 2026 | **B7 was wrong and is now fixed** | The first audit marked the timeout kill as done. It was not: on Windows the kill did not reach processes started by Git Bash, and a test's runaway command filled the disk. Commands now run in a job object and every descendant is ended; tests check that the children are dead. |
| 4 Oct 2026 | C2, E2, E6, E7, G10, H6, I2, I3, I7, I8, I10, J4, K6, K7, L2, L5, L8, N2, N8, O3, Q5, Q6, R1, R3, R4 fixed; G4, K2, L6 partly | Session folder ignores itself in git; clean shutdown; extra tool calls reported; refusal category recorded; SDK version bounded; progress with running cost; new flags and `sessions`; config validation; `.gitattributes`; CI on Linux and Windows for Python 3.12 and 3.13; ruff; README, CHANGELOG, CONTRIBUTING, SECURITY, templates; cost at the serving model's prices. |

---

## A. Secrets and authentication

| # | Check | Status | Note |
|---|---|---|---|
| A1 | API key read from environment or `.env` | Done | `harness/env.py`, tested |
| A2 | `.env` ignored by git; `.env.example` committed | Done | Verified with `git check-ignore` |
| A3 | No key in git history | Done | Scanned all branches: 0 matches |
| A4 | Key hidden from the agent's commands | Done | Tested |
| A5 | Other secrets hidden from the agent's commands | Done | Secret-looking variables are removed; `--pass-env NAME` opts one back in; tested |
| A6 | Agent cannot read a `.env` in its working folder | Partial | Still readable. Its values are redacted from command output, and `run` and `doctor` warn. Needs a sandbox to close |
| A7 | Agent cannot read `~/.ssh`, `~/.aws`, git credentials | Missing | Needs a sandbox (B4) |
| A8 | Secrets never written to transcripts | Partial | Removed variables' values, `.env` values and common key formats are redacted. A secret in any other file or format is not |
| A9 | Credential check before a run | Done | `harness doctor`; uses free token counting; verified live |
| A10 | `.env` does not override the real environment | Done | Tested |
| A11 | Other auth methods (profiles, Bedrock, Vertex) | Partial | The SDK supports profiles; never tried |

## B. Command execution safety

| # | Check | Status | Note |
|---|---|---|---|
| B1 | Destructive-command blocklist | Done | Tested |
| B2 | Blocklist limits stated to users | Done | `SAFETY.md`; `harness run --help` points to it |
| B3 | Approve-each-command mode | Done | `--confirm`; the default is unattended |
| B4 | OS sandbox or container | Missing | None; `SAFETY.md` tells users to supply their own |
| B5 | Writes confined to the working folder | Missing | Needs B4 |
| B6 | Network egress control | Missing | Needs B4 |
| B7 | Timeout kills the command and everything it started | Done | Windows: job object, tested by checking the children stop. Linux: process group, passes in CI. See the change log: this was wrongly marked done before |
| B8 | Background jobs do not stall a turn | Done | Tested. On Windows they are ended when the run ends; on Linux and macOS they are not |
| B9 | Cap on captured output size | Done | Killed past 10 MB; at most the cap is read into memory; tested |
| B10 | Interactive commands cannot hang | Done | stdin is closed |
| B11 | CPU, disk and process limits | Missing | Needs B4 |
| B12 | Guard on `git push` and force-push | Done | Refused without `--allow-push`; tested |
| B13 | Heredoc data not scanned; shell-fed heredocs scanned | Done | Tested |

## C. Data handling and privacy

| # | Check | Status | Note |
|---|---|---|---|
| C1 | Users told that file contents and output go to Anthropic | Done | `SAFETY.md` and README |
| C2 | `.ctx/` auto-ignored in the target repo | Done | The harness writes `.ctx/.gitignore`; tested |
| C3 | Secret redaction in stored transcripts | Partial | Command output is redacted before it is stored (A8); the model's own replies are not |
| C4 | No telemetry | Done | None exists |
| C5 | Retention or cleanup command for sessions | Missing | Sessions accumulate forever |
| C6 | Fallback to another model disclosed | Partial | In `SAFETY.md`; recorded per turn; cannot be turned off |

## D. Prompt injection and trust

| # | Check | Status | Note |
|---|---|---|---|
| D1 | Command output marked as untrusted | Missing | Output arrives as plain user-role text beside the task |
| D2 | Model-written notes cannot act as instructions | Partial | One prompt line only |
| D3 | Output cannot forge block headers | Done | Tested |
| D4 | Task and user messages cannot be edited | Done | Tested |
| D5 | Rollback note cannot be edited | Done | Kept outside the file |
| D6 | Injection test cases | Missing | None |

## E. Loop correctness and robustness

| # | Check | Status | Note |
|---|---|---|---|
| E1 | Step, call, cost and time limits | Done | Each tested |
| E2 | Ctrl+C or crash still closes the session | Done | `finish` event and `usage.json` are written; tested for both |
| E3 | API failure closes the session cleanly | Done | Tested and seen live |
| E4 | Command from a cut-off reply never runs | Done | Tested |
| E5 | Invalid tool input is re-prompted | Done | Tested |
| E6 | Extra tool calls in one reply handled | Done | The first runs; the model is told how many were ignored; tested |
| E7 | Refusal handled and explained | Done | Category and explanation are recorded and shown; tested |
| E8 | Unknown stop reasons end the run as an error | Done | Tested |
| E9 | Resume a session | Missing | Out of scope so far |
| E10 | Follow-up user messages | Missing | One task per run |
| E11 | Repeated-command loop detection | Missing | Only the caps. A naive check would misfire on the benchmark, where the same command legitimately repeats |
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
| G4 | Model selectable | Partial | `--model` exists and warns; only `claude-opus-5-5` has been run |
| G5 | Retries with backoff | Done | Tested with fakes; not seen live |
| G6 | Bash tool used as documented | Partial | No tool result is ever returned; works live, undocumented |
| G7 | Other providers or local models | Missing | Anthropic only |
| G8 | Reasoning summaries captured | Done | Seen live |
| G9 | One-hour cache option | Missing | Five-minute only |
| G10 | SDK version bounded | Done | `anthropic>=1.8,<2` |

## H. Cost control

| # | Check | Status | Note |
|---|---|---|---|
| H1 | Per-run dollar cap | Done | Tested |
| H2 | Benchmark spend ceiling | Done | Tested |
| H3 | Prices correct for the serving model | Partial | Each call is charged at the serving model's prices; an unknown model is flagged. Two fallback models' cache-read rates are assumed, not checked |
| H4 | Cap cannot be overshot | Partial | Checked before each call, so it can overshoot by one call |
| H5 | Summary calls charged to the run | Done | Tested |
| H6 | Running cost visible during a run | Done | On every progress line |
| H7 | `usage.json` hand-checked against the transcript | Partial | Summed once informally |

## I. CLI and product design

| # | Check | Status | Note |
|---|---|---|---|
| I1 | `run`, `log`, `undo`, `bench`, `report` | Done | |
| I2 | Progress output during a run | Done | One line per turn and per edit; `--quiet` turns it off; tested |
| I3 | `--model`, `--effort`, `--timeout` flags | Done | Tested |
| I4 | Safe default mode | Partial | Runs unattended by default |
| I5 | Meaningful exit codes | Done | 0 finished, 1 otherwise, 2 bad input or no client |
| I6 | Session inspection | Done | `harness log` |
| I7 | List sessions | Done | `harness sessions`; tested |
| I8 | Help text | Done | Every flag has help; `run` carries the safety note |
| I9 | UTF-8 output on Windows | Done | |
| I10 | Task from a file or stdin | Done | `--task-file PATH` or `-`; tested |
| I11 | Name checked on PyPI; clear positioning | Missing | `clm-harness` and the generic `harness` command are unchecked |

## J. Configuration

| # | Check | Status | Note |
|---|---|---|---|
| J1 | All defaults in one place | Done | `Config` |
| J2 | Config file or environment overrides | Missing | Flags only |
| J3 | Sensible default budget | Partial | 32,000 is the experiment setting, not a practical default |
| J4 | Config validated | Done | Rejected with the field named; tested |

## K. Cross-platform

| # | Check | Status | Note |
|---|---|---|---|
| K1 | Windows with Git Bash | Done | Tested and run live |
| K2 | Linux and macOS | Partial | The full test suite passes on Linux in CI. No live run on Linux; macOS untested |
| K3 | Bash discovery with override | Done | `HARNESS_BASH` |
| K4 | `python3` stub detection | Done | |
| K5 | Paths with spaces | Done | Tested |
| K6 | `.gitattributes` for line endings | Done | LF everywhere |
| K7 | Python versions | Done | 3.12 and 3.13 in CI |
| K8 | WSL | Missing | Untested |

## L. Testing and quality

| # | Check | Status | Note |
|---|---|---|---|
| L1 | Test suite passes | Done | 267 tests, about 50 s |
| L2 | Tests skip cleanly without bash | Done | Tests that run commands are skipped |
| L3 | Coverage measured | Missing | |
| L4 | Scripted live smoke test | Missing | Done by hand each time |
| L5 | CI | Done | Linux and Windows, Python 3.12 and 3.13; first run green |
| L6 | Lint, format, type check | Partial | ruff lint in CI; no formatter or type checker |
| L7 | Fuzz or property tests for the parser | Missing | |
| L8 | Tests for the non-Windows branches | Done | They run on Linux in CI |

## M. Benchmark and evidence

| # | Check | Status | Note |
|---|---|---|---|
| M1 | Deterministic generators, sizing checked | Done | Tested |
| M2 | Exact-match scorer | Done | Tested |
| M3 | Model-managed pilot, key-value | Done | 24/24 correct, $1.08, one run |
| M4 | Baseline pilot, key-value | Missing | Ended in an API refusal on turn 5 ($1.38, 0/24); invalid. The category was not recorded then; it is now (E7) |
| M5 | Fair baseline | Partial | It must retype each batch (about 6,300 output tokens) and cannot clear those commands |
| M6 | Full 12-run matrix | Missing | On hold until M4 is understood |
| M7 | Ledger task run live | Missing | |
| M8 | Multiple seeds and spread | Missing | |
| M9 | A realistic coding-task evaluation | Missing | Both tasks are synthetic |
| M10 | Claims limited to what was measured | Done | README states the limits |
| M11 | `RESULTS.md` | Missing | |

## N. Documentation

| # | Check | Status | Note |
|---|---|---|---|
| N1 | Plan, spec and agent guide | Done | `PLAN.md`, `IMPLEMENTATION.md`, `AGENTS.md` |
| N2 | README | Done | Install, use, how it works, what has been measured |
| N3 | Spec matches the code | Partial | Some pseudo-code predates later changes |
| N4 | Architecture diagram | Missing | |
| N5 | Docstrings on public functions | Partial | Present on most; uneven |
| N6 | Example session walkthrough | Missing | |
| N7 | Threat model | Partial | `SAFETY.md` lists protections and gaps; no attacker-by-attacker analysis |
| N8 | Changelog | Done | `CHANGELOG.md` |

## O. Licensing and legal

| # | Check | Status | Note |
|---|---|---|---|
| O1 | LICENSE | Missing | README says so plainly |
| O2 | Clean of the paper's non-commercial code | Partial | Reimplemented from the design in our own wording; not independently reviewed |
| O3 | Attribution for the paper and `pi-clm` | Done | README acknowledgements |
| O4 | Dependency licences checked | Partial | Two direct dependencies; not audited |
| O5 | Trademark use ("Claude") | Partial | Descriptive use only; not reviewed |
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
| Q5 | Schema version in the transcript | Done | `schema` in the `start` event |
| Q6 | Refusal details recorded | Done | In the `reply` event and the final status |
| Q7 | Fallback model recorded per turn | Done | |

## R. Community

| # | Check | Status | Note |
|---|---|---|---|
| R1 | CONTRIBUTING | Done | |
| R2 | Code of conduct | Missing | Needs a contact address to be chosen |
| R3 | SECURITY policy | Done | |
| R4 | Issue and PR templates | Done | |

---

## Evidence

| Check | Result |
|---|---|
| Key-like strings in git history, all branches (3 Oct) | 0 |
| `.env` ever committed | No |
| Wheel build (3 Oct) | 24 files, including the 3 prompt files |
| `sleep 6 & echo started` | Before: returned after the sleep ended. Now: returns at once |
| Command printing 30 MB (3 Oct) | Was held whole in memory. Now killed past 10 MB |
| Timed-out command's children on Windows (4 Oct) | Before: survived; three orphaned `yes` processes wrote 77 GB of temp files. Now: a heartbeat loop stops within a second of the kill |
| `harness doctor` (3 Oct) | All checks passed against the live API at no cost |
| CI run 37177829380 (4 Oct) | Success on Ubuntu and Windows, Python 3.12 and 3.13 |
| Test suite (4 Oct) | 267 passed; lint clean |

## Pilot benchmark, for items M3 to M5

One key-value run per mode, seed 1, about 99,000 tokens of input against a 29,952-token limit.

| Mode | Status | Accuracy | Cost | Model calls | Notes |
|---|---|---|---|---|---|
| Model-managed | finished | 24/24 | $1.08 | 74 | 25 edits, none refused, no rollback |
| Baseline | refusal | 0/24 | $1.38 | 5 | Retyped each batch by hand; compacted on every turn; the API refused the fifth request |

This is not a valid comparison. The baseline cannot clear the long commands it retypes, and the cause of the refusal is unknown.
