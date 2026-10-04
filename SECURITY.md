# Security policy

## What counts as a vulnerability

[SAFETY.md](SAFETY.md) states what the harness protects against and what it does not. The harness is not a sandbox, and the gaps listed there are known limits, not vulnerabilities.

Please report it as a security problem if you find a way to:

- make the harness run a command that the blocked list is documented to refuse;
- make a secret that should be redacted reach the model, the transcript or a saved output file;
- make the agent's commands see an environment variable the harness is documented to remove;
- make the harness leak its own API key;
- make a model's edit change something documented as protected (the task, a user message, another session's files).

## How to report

Use GitHub's private vulnerability reporting on this repository (Security tab, "Report a vulnerability"). If that is not available, open an issue that says only that you have a security report, and a maintainer will arrange a private channel.

Include the command or input, what you expected and what happened. Leave real secrets out of the report.

## What to expect

This is a small project maintained in spare time. Reports are read, and fixes are made as time allows. There is no bounty.

## Supported versions

Only the latest commit on the default branch.
