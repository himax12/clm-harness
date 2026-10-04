# Media

Everything here shows real output. Nothing was typed in by hand.

| File | What it shows | Where the content comes from |
|---|---|---|
| `replay.gif`, `replay.mp4` | An animated replay of one run: the log on the left, context size on the right | The transcript of session `20261003T150804-d740`, a live run on 3 October 2026 (`claude-opus-5-5`, 12,000-token budget, $0.60). The lines are the output of `harness log`, shown one at a time. It is a replay, not a recording of the run as it happened: the real run took several minutes. |
| `context-size.png` | Context size at each turn of the same run, against the limit | `context_tokens` of each `reply` event and `after_tokens` of each `edit_applied` event in that transcript |
| `session-log.png` | The full turn-by-turn log of the same run | `harness log 20261003T150804-d740` |
| `sandbox.png` | What commands see inside `--sandbox docker` | Six commands run through the harness's own `Shell` with the sandbox on, in a throwaway project that held a `.env` file, on Windows 11 with Docker 29.7.2 |
| `doctor.png` | The setup check | `harness doctor --offline` in the same throwaway project |

The terminal pictures are the captured text rendered in a terminal-style frame and photographed with headless Chrome. Colours were added for reading; the text is unchanged, except that long lines are cut at the right edge in the replay.

The task in the recorded run was: "Read every Python file under harness/ in full and write SUMMARY.md in this directory with one short paragraph per module".
