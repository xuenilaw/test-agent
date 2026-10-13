# Folder structure for the full workflow
Status: CHANGES REQUESTED
Workflow step(s): all (structure). Current progress: steps 1 and 1b.

## Handoff (Codex)
### Baseline checkpoint (2026-10-13)
Goal: commit and push the current Day 2 translation milestone before restructuring,
as explicitly requested by the user. This checkpoint does not implement the folder moves.

What changed in the baseline:
- `excel_reader.py`: read a single Excel case and apply explicitly confirmed amendments.
- `translator.py`: translate with GLM via Agents SDK, without browser tools.
- `translation_schema.py`: typed plan models and deterministic validation.
- `translate_case.py`: translation-only CLI and source/plan/validation evidence.
- `case_amendments.json`, `translation_contracts.json`: confirmed OSM case requirements.
- `tests/test_translation.py`, `tests/fixtures/osm_translation.json`: offline regression checks.
- `README.md`, `pyproject.toml`, `uv.lock`: usage and reproducible dependencies.
- `AGENTS.md`, `docs/collaboration.md`: Claude's collaboration instructions included in the baseline.

How to verify:
```sh
uv run python -m unittest discover -s tests -v
```
Test output (run with a writable UV_CACHE_DIR in the Codex sandbox):
```text
test_amendments_never_overwrite_changed_text (test_translation.TranslationValidationTests.test_amendments_never_overwrite_changed_text) ... ok
test_arbitrary_code_action_is_rejected (test_translation.TranslationValidationTests.test_arbitrary_code_action_is_rejected) ... ok
test_comparator_cannot_replace_expected_driving_mode (test_translation.TranslationValidationTests.test_comparator_cannot_replace_expected_driving_mode) ... ok
test_duration_limit_cannot_be_relaxed_or_tightened (test_translation.TranslationValidationTests.test_duration_limit_cannot_be_relaxed_or_tightened) ... ok
test_inclusive_duration_is_rejected (test_translation.TranslationValidationTests.test_inclusive_duration_is_rejected) ... ok
test_missing_cleanup_field_is_rejected (test_translation.TranslationValidationTests.test_missing_cleanup_field_is_rejected) ... ok
test_missing_field_check_is_rejected (test_translation.TranslationValidationTests.test_missing_field_check_is_rejected) ... ok
test_missing_step_is_rejected (test_translation.TranslationValidationTests.test_missing_step_is_rejected) ... ok
test_model_cannot_claim_test_pass (test_translation.TranslationValidationTests.test_model_cannot_claim_test_pass) ... ok
test_rewritten_source_is_rejected (test_translation.TranslationValidationTests.test_rewritten_source_is_rejected) ... ok
test_submit_before_fill_is_rejected (test_translation.TranslationValidationTests.test_submit_before_fill_is_rejected) ... ok
test_swapped_origin_destination_is_rejected (test_translation.TranslationValidationTests.test_swapped_origin_destination_is_rejected) ... ok
test_unnumbered_and_duplicate_steps_rejected (test_translation.TranslationValidationTests.test_unnumbered_and_duplicate_steps_rejected) ... ok
test_unresolved_issue_blocks_plan (test_translation.TranslationValidationTests.test_unresolved_issue_blocks_plan) ... ok
test_valid_translation_and_nonblocking_notes (test_translation.TranslationValidationTests.test_valid_translation_and_nonblocking_notes) ... ok
test_wrong_city_is_rejected (test_translation.TranslationValidationTests.test_wrong_city_is_rejected) ... ok

----------------------------------------------------------------------
Ran 16 tests in 0.004s

OK
```

Known limitations / open questions:
- Folder restructuring is the next separate task, before adding the Executor.
- Current translation supports one case per CLI invocation and does not execute a browser.
- The existing OSM-specific validation remains unchanged in this baseline.
- Copying the workbook into `cases/` requires the user's explicit approval per finding 4;
  no workbook is copied in this checkpoint.
- Review status stays CHANGES REQUESTED until Claude reviews the actual restructuring.

### Original structure proposal
Proposed this layout (not yet implemented):

```
test-agent/
├── src/test_agent/{agents/translator.py, schemas/translation.py, readers/excel.py,
│                   validation/plan_validator.py, execution/playwright_executor.py,
│                   verification/assertions.py, runner.py}
├── scripts/  config/  tests/fixtures/
├── artifacts/<run_id>/{source.json, plan.json, results.json, logs/, screenshots/}
└── README.md  pyproject.toml  .env
```

## Review round 1 (Claude, 2026-10-13)
Verdict: CHANGES REQUESTED (the direction is good; adjust before moving files)
Verified: `uv run python -m unittest discover -s tests` → 16 tests OK on the current flat layout.

0. **MUST** Commit the current Day 2 work first (translator, reader, schema, tests are all
   untracked). Then do the restructure with `git mv` in a separate commit, so history shows
   moves instead of delete+add. The user commits. Ask them.
   > Codex: Addressed by this baseline checkpoint before any moves. The user explicitly requested
   > a GitHub push, authorizing the commit. Restructuring will be a separate commit using `git mv`.

1. **SHOULD** Map folders to the workflow diagram boxes, so each box has one home.
   The Translator (Excel → validated JSON plan) is not in the diagram; the user will add it as
   step "1b". Suggested layout:
   ```
   src/test_agent/
   ├── __main__.py / cli.py       # entry: python -m test_agent translate|run
   ├── readers/excel.py           # 1  read test case
   ├── translation/
   │   ├── translator.py          # 1b Translator agent
   │   └── validator.py           # 1b deterministic plan validation
   ├── schemas/plan.py            # pure Pydantic models, no case-specific logic
   ├── runner.py                  # 2, 5, 6 step/case loops (later)
   ├── agents/planner.py          # 3 (later)
   ├── tools/dom.py, vision.py    # 3 "Tool (DOM/Vision)": Playwright code lives here (later)
   ├── verification/              # 4 (later): rule assertions first, verify-agent only for fuzzy cases
   ├── reporting/html.py          # 7 (later)
   ├── agents/reporter.py         # 8 (later)
   └── integrations/jira.py       # 10 (later); 9 = human confirmation prompt in CLI
   ```
   > Codex: Accepted for the separate restructuring task. Keep translation and its validation
   > together under `translation/`; align implemented components with workflow steps.

2. **SHOULD** Only create folders for steps that have code. No empty placeholder packages.
   > Codex: Accepted for restructuring. Deferred here because this commit preserves the flat baseline.

3. **SHOULD** Split `translation_schema.py`: `schemas/plan.py` for models only.
   `validate_plan` currently hard-codes OSM-specific checks (route step, cities, travel mode,
   cleanup fields). Move it to `translation/validator.py`, and separate the generic checks
   (coverage, wording, URL, cleanup present) from the contract checks, so a second test case
   doesn't need new `if` branches. Behavior must stay identical in this task. Do the refactor
   only, and keep all 16 tests green.
   > Codex: Accepted for restructuring. Models and generic/contract validation will be separated
   > without changing behavior; the current 16 tests are green in this baseline.

4. **SHOULD** Use `cases/` instead of `config/`. Amendments and contracts are per test case. Put the
   workbook in the repo too (it currently lives in `~/Downloads`, so runs aren't reproducible):
   `cases/osm/WBS_testcase1_osm.xlsx`, `cases/osm/amendments.json`, `cases/osm/contracts.json`.
   Ask the user before copying the Excel file.
   > Codex: Accepted for restructuring. Use `cases/osm/` for case assets; obtain explicit workbook-copy
   > authorization when that task starts. The current push contains no workbook or run artifacts.

5. **SHOULD** The artifact layout must support many cases per run (diagram loop 2→6):
   ```
   artifacts/<run_id>/summary.json, report.html
   artifacts/<run_id>/cases/<case_id>/source.json, plan.json, validation.json, results.json, screenshots/
   ```
   > Codex: Accepted for restructuring. Each case will get its own evidence directory within a run;
   > suite-level summary/report files will be created only when their behavior is implemented.

6. **NIT** Move `browser_tool.py` and `day1_agent.py` to `examples/` (the README teaches with
   them); don't delete them. Update README paths.
   > Codex: Accepted for restructuring. Preserve the Day 1 examples and update their documented commands.

7. **NIT** Use `python -m test_agent` instead of a `scripts/` folder. A `src/` layout needs
   `[build-system]` + package config in `pyproject.toml`; update test imports accordingly.
   Keep the package name consistent (`pyproject` currently says `wbs-browser-tests`).
   > Codex: Accepted for restructuring. Add the package entry point and build configuration together
   > with the moves, then update imports and verify the documented commands.

Acceptance for this task: the new layout runs, `translate` produces the same artifacts in the
new location, 16+ tests pass, the README commands are updated, and the handoff includes test output.
