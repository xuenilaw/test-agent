# Collaboration Protocol: Codex (implementer) ↔ Claude (reviewer)

The project owner (the user) decides scope and priorities. Codex writes the code.
Claude reviews it and gives feedback. The two agents never talk directly: they
communicate through review files in `docs/reviews/`, and the user carries
messages between sessions.

## Roles

| Who | Does | Does not |
| --- | --- | --- |
| User | Picks the next task, answers open questions, approves merges/commits | — |
| Codex | Implements one task at a time, writes tests, fills in the handoff | Start the next workflow step without the user's go-ahead |
| Claude | Reviews the diff, runs tests, writes findings with severity | Rewrite Codex's code (small suggested snippets are fine) |

## The loop

1. **Task**: the user gives Codex a task, e.g. "Restructure folders per review 2026-10-13".
2. **Implement**: Codex makes the change on a branch (`codex/<topic>`) or as uncommitted changes.
3. **Handoff**: Codex creates or updates `docs/reviews/<YYYY-MM-DD>-<topic>.md` with the
   *Handoff* section (template below).
4. **Review**: the user asks Claude to review that file. Claude reads the diff, runs the
   tests, and appends a *Review* section.
5. **Fix**: Codex addresses every `MUST` finding and replies inline under each one
   (`Fixed in <file>` or `Disagree: <reason>`). Repeat 4–5 until there are no open `MUST`s.
6. **Close**: Claude marks the file `Status: APPROVED`. The user commits.

One file per task keeps the full conversation for that task in one place.
That file is the project's review history, which is also useful evidence for the WBS report.

## Severity levels

- **MUST**: bug, wrong behavior, broken test, secret leaked, workflow step violated. Blocks approval.
- **SHOULD**: design or maintainability issue. Fix now, or record why not.
- **NIT**: style or naming. Optional.
- **QUESTION**: the reviewer needs information. It does not block unless the answer reveals a MUST.

## Definition of done (checked in every review)

- `uv run python -m unittest discover -s tests -v` passes. The output is pasted into the handoff.
- New behavior has at least one test, including a negative test (input that must be rejected).
- Tests don't depend on a live LLM or the internet. Use fixtures and fakes.
- No secrets in code, logs, or artifacts. `.env` stays untracked.
- An LLM output is never trusted directly: it is schema-validated and rule-checked before use.
- The README is updated when commands or file locations change.
- The change maps to a box in the workflow diagram (`docs/workflow.png` when added).

## Project principles

- **Deterministic first, agent second.** Use a Python rule when the check can be expressed
  as one. Use an agent only for genuinely fuzzy judgments, and log its reasoning.
- **Never relax a test to make it pass.** Thresholds, cities, and expected values come from
  the test case or a confirmed amendment, never from the model.
- **Every run is reproducible from its artifact folder.** Save inputs, model output,
  and the verdict for each case.
- **Statuses are distinct:** `VALIDATED` (plan OK) ≠ `PASSED` (test ran and passed).
  `FAILED` means the app is wrong. `BLOCKED` means the test could not run.
- **Small steps.** Each task should be reviewable in one sitting (roughly < 400 changed lines,
  excluding moves).

## Handoff template (Codex writes)

```markdown
# <Topic>
Status: IN REVIEW            <!-- IN PROGRESS | IN REVIEW | CHANGES REQUESTED | APPROVED -->
Workflow step(s): <e.g. 1b Translate>

## Handoff (Codex)
### Goal
### What changed
- `path/file.py`: one line per file
### How to verify
<commands>
### Test output
<pasted output>
### Known limitations / open questions
```

## Review template (Claude writes)

```markdown
## Review round N (Claude, YYYY-MM-DD)
Verdict: CHANGES REQUESTED | APPROVED
Verified: <commands run and result>

1. **MUST** `path/file.py:42` What is wrong. Why it matters. Suggested fix.
   > Codex: Fixed / Disagree: ...
2. **SHOULD** ...
```
