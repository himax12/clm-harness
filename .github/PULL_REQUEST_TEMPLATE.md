**What this changes**

**Why**

**How it was checked**

- [ ] `uv run pytest -q` passes
- [ ] `uv run ruff check .` passes
- [ ] A test was added or changed for the new behaviour
- [ ] `SAFETY.md` is still true (if `safety.py`, `redact.py` or `shell.py` changed)

**Does it change model behaviour or cost?**

A change to the request, the prompts or the loop can. Say whether you ran it live and what you saw.

**Audit item**

If this closes an item in `AUDIT.md`, name it and update its status in the same pull request.
