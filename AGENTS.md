# WBS Test Agent: Agent Instructions

This project uses two AI agents. **Codex implements**, **Claude reviews**, and the user decides.
Before starting any task, read `docs/collaboration.md` and follow its loop, templates,
and definition of done.

- Look in `docs/reviews/` for open review files (`Status:` is not `APPROVED`).
  Address every open `MUST` finding before starting new work.
- After each task, write the *Handoff* section in `docs/reviews/<YYYY-MM-DD>-<topic>.md`.
- Run `uv run python -m unittest discover -s tests -v` before handing off.
- Don't commit unless the user asks.
- Language and explanation preferences are in `../AGENTS.md`.
