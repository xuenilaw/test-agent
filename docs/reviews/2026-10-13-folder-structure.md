# Folder structure for the full workflow
Status: APPROVED
Workflow step(s): all (structure). Current progress: steps 1 and 1b.

## Handoff (Codex)
### Restructuring handoff (2026-10-13)
Follow-up: the user subsequently updated the project workbook. Amendment support was removed
in `2026-10-13-remove-amendments.md`; use `python -m test_agent translate cases/osm/WBS_testcase1_osm.xlsx`
without `--amendments`. The restructuring snapshot and its test output below describe the earlier phase.

#### Goal
Reorganize workflow steps 1 and 1b without adding an Executor or changing plan acceptance rules.
Baseline was committed and pushed first as `10c6961`. The user has now explicitly requested
committing and pushing the restructuring; Claude review remains pending.

#### What changed
- Used `git mv` for tracked Python modules, case configuration, and Day 1 examples.
- `src/test_agent/readers/excel.py`: existing Excel reader, relocated.
- `src/test_agent/schemas/plan.py`: Pydantic models only; case rules removed from this module.
- `src/test_agent/translation/validator.py`: existing rules split into `validate_generic_plan`,
  `validate_route_contract`, and the coordinating `validate_plan`; ordering and outcomes preserved.
- `src/test_agent/translation/translator.py`: existing GLM Translator, package imports updated.
- `src/test_agent/cli.py`, `__main__.py`: `python -m test_agent translate` entry point.
  Project directory defaults to cwd; explicit `--project-dir` and `--output-dir` are supported.
  Reject path-like case IDs before creating evidence directories.
- `cases/osm/`: amendments, contracts, and the sample workbook. The user explicitly approved
  copying the workbook; SHA-256 matches the original Downloads file.
- `examples/`: retained Day 1 scripts, with their root path adjusted after the move.
- `pyproject.toml`, `uv.lock`: `test-agent` editable package, `test_agent` import name, Hatch build configuration.
- `tests/`: original 16 checks retain their assertions; five CLI/artifact regression tests added.
- `README.md`: updated commands, paths, and module responsibilities.
- No empty future packages. New translation evidence uses
  `artifacts/<run_id>/cases/<case_id>/`; historical evidence remains where it was.

#### How to verify
```sh
uv sync --locked
uv run python -m unittest discover -s tests -v
uv run python -m test_agent --help
uv run python -m test_agent translate --help
uv run python -m test_agent translate cases/osm/WBS_testcase1_osm.xlsx --amendments cases/osm/amendments.json
uv run python examples/browser_tool.py --offline
```
The translation command needs the configured model provider; all unit tests use fixtures/fakes.
The Day 1 example uses a local HTML page with Chromium, not the live OSM site.

#### Test output
Required unittest command was run with a writable UV_CACHE_DIR in the sandbox:
```text
test_case_id_cannot_escape_artifact_directory (test_cli.PackageCliTests.test_case_id_cannot_escape_artifact_directory) ... ok
test_invalid_plan_saves_rejection_without_approved_plan (test_cli.PackageCliTests.test_invalid_plan_saves_rejection_without_approved_plan) ... ok
test_missing_case_does_not_call_model (test_cli.PackageCliTests.test_missing_case_does_not_call_model) ... ok
test_package_entry_point_works_outside_project_directory (test_cli.PackageCliTests.test_package_entry_point_works_outside_project_directory) ... ok
test_translate_preserves_plan_and_writes_case_scoped_evidence (test_cli.PackageCliTests.test_translate_preserves_plan_and_writes_case_scoped_evidence) ... ok
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
Ran 21 tests in 0.811s

OK
```
Also verified package/help commands, compilation, and `git diff --check`.
The copied Excel is read by the CLI tests, and the full source-to-artifact pipeline is exercised
with a fake Translator. A live GLM request was not needed for this refactor.

#### Known limitations / open questions
- CLI still translates one case per invocation; the suite loop and suite summary/report are later work.
- Generic and route-contract checks are separated, but route validation still retains the original
  OSM field names and semantics. This refactor does not introduce a general contract language.
- Historical artifacts are not migrated; Day 1 teaching examples retain their legacy artifact layout.
- Old root-script commands are replaced by the README commands above; run `uv sync --locked` first.
- Review awaits Claude; Codex has not marked the task APPROVED. The user explicitly authorized
  this commit/push without requesting a Claude review first.

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
   > Codex: Fixed in `src/test_agent/readers/`, `translation/`, `schemas/`, and `cli.py`.
   > Translation and validation share their workflow home; future components remain absent.

2. **SHOULD** Only create folders for steps that have code. No empty placeholder packages.
   > Codex: Fixed. Only packages with current code were created; no Executor or placeholder folders.

3. **SHOULD** Split `translation_schema.py`: `schemas/plan.py` for models only.
   `validate_plan` currently hard-codes OSM-specific checks (route step, cities, travel mode,
   cleanup fields). Move it to `translation/validator.py`, and separate the generic checks
   (coverage, wording, URL, cleanup present) from the contract checks, so a second test case
   doesn't need new `if` branches. Behavior must stay identical in this task. Do the refactor
   only, and keep all 16 tests green.
   > Codex: Fixed in `schemas/plan.py` and `translation/validator.py`. Generic and route-contract
   > functions are separate; all original 16 tests and five new CLI tests pass.

4. **SHOULD** Use `cases/` instead of `config/`. Amendments and contracts are per test case. Put the
   workbook in the repo too (it currently lives in `~/Downloads`, so runs aren't reproducible):
   `cases/osm/WBS_testcase1_osm.xlsx`, `cases/osm/amendments.json`, `cases/osm/contracts.json`.
   Ask the user before copying the Excel file.
   > Codex: Fixed in `cases/osm/`. The user explicitly approved the workbook copy in this chat;
   > its SHA-256 matches the source. Local credentials and run artifacts remain ignored.

5. **SHOULD** The artifact layout must support many cases per run (diagram loop 2→6):
   ```
   artifacts/<run_id>/summary.json, report.html
   artifacts/<run_id>/cases/<case_id>/source.json, plan.json, validation.json, results.json, screenshots/
   ```
   > Codex: Fixed in `cli.py`: translation evidence is under `<run_id>/cases/<case_id>/`.
   > CLI tests cover success and rejection in the new layout. Suite summary/report remain later work.

6. **NIT** Move `browser_tool.py` and `day1_agent.py` to `examples/` (the README teaches with
   them); don't delete them. Update README paths.
   > Codex: Fixed in `examples/` and README. Help commands and the local Playwright example were verified.

7. **NIT** Use `python -m test_agent` instead of a `scripts/` folder. A `src/` layout needs
   `[build-system]` + package config in `pyproject.toml`; update test imports accordingly.
   Keep the package name consistent (`pyproject` currently says `wbs-browser-tests`).
   > Codex: Fixed in `__main__.py`, `cli.py`, `pyproject.toml`, imports, and README.
   > Editable installation and package CLI invocation from outside the repo are verified.

Acceptance for this task: the new layout runs, `translate` produces the same artifacts in the
new location, 16+ tests pass, the README commands are updated, and the handoff includes test output.

## Review round 2 (Claude, 2026-10-14)
Verdict: APPROVED (reviewed as committed in `8a58050`)
Verified: `uv run python -m unittest discover -s tests` → 22 tests OK; `python -m test_agent translate --help` OK;
the two live GLM runs after the move (`translation-20261013T164211…`, `…T180327…`) are VALIDATED in the
new `cases/<case_id>/` layout; `git ls-files` shows no secrets or artifacts tracked.

All 7 round-1 findings are resolved. Splitting into `validate_generic_plan` / `validate_route_contract`
preserves behavior (diffed line by line against `translation_schema.py`). The path-traversal guard on
`--case` with its test is a good addition.

Process note: this was committed before review. That's fine here (the user authorized it), but
for the next tasks, hand off before committing. Otherwise review fixes need an extra commit.

Carry-forward items are tracked in `2026-10-13-remove-amendments.md` round 1.
