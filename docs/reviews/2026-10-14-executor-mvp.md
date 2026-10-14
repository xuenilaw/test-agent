# Task: contract fixes + deterministic Executor MVP (no AI)
Status: APPROVED
Workflow step(s): 1b (fixes), 2 / 4 / 5 for a single case (executor)
Assigned: Codex · Reviewer: Claude · Brief written 2026-10-14

## Why this task
Steps 1 and 1b produce a VALIDATED `plan.json`. Nothing runs it yet. This task builds the
**baseline executor**: it runs a validated plan in Chromium using a **hand-written locator file**
and **deterministic Python checks**. There is no Planner agent and no vision.

The baseline matters for the project: when it fails, the cause is the app or the plan, not the AI.
Later tasks (C: Planner finds locators in the DOM, D: vision fallback) will be measured against it.

Out of scope: Planner/LLM calls during execution, vision/OCR, looping over many cases,
HTML report, Jira.

Process: do part A and part B as **two handoff rounds** in this file (A first, small).
Hand off **before** committing; the user commits after approval.

---

## Part A: carry-forward fixes from `2026-10-13-remove-amendments.md`

A1. **Contract located by workbook, and its use is visible.** In `cli.py`, default `--contracts` to
    `args.workbook.parent / "contracts.json"`. Add `"contract_applied": true|false` to
    `validation.json` and print it. A case without a contract may still be VALIDATED, but the
    report must say `contract_applied: false`.
    Tests: a case without a contract → `contract_applied: false`; OSM-001 → `true`.

A2. **Malformed contract fails clearly, before the model call.** Load the contract into a Pydantic
    `RouteContract` model (`schemas/`). A missing or wrong field → REJECTED with an error naming the
    field. The model is not called. Test: contract without `limit_minutes`.

A3. **Record as a Known limitation** (no code change): the Translator prompt contains OSM-specific
    vocabulary; move it into `cases/<suite>/` when a second suite exists.

---

## Part B: Executor MVP

### Command
```sh
uv run python -m test_agent run artifacts/<translation-run>/cases/OSM-001 \
    --locators cases/osm/locators.json [--headed]
```
- Input is a translation case folder. Refuse to run (exit 2, no browser launched) unless
  `validation.json` has `"status": "VALIDATED"` and `plan.json` exists and re-validates against
  `TranslationPlan`. A REJECTED plan must never be executed.
- Output: `artifacts/run-<run_id>/cases/<case_id>/` with `results.json`, `screenshots/step-<n>.png`,
  `screenshots/final.png`, and a Playwright `trace.zip`.
- Exit code: 0 = PASSED, 1 = FAILED or BLOCKED, 2 = input/config error.

### Suggested modules (create only what you use)
- `src/test_agent/tools/dom.py`: resolve a semantic target from the locator file to a Playwright
  locator, and perform `navigate / click / fill / select / press`.
- `src/test_agent/verification/checks.py`: deterministic checks + the duration parser.
- `src/test_agent/runner.py`: the step loop for one case (steps 2→5 in the diagram).
- `src/test_agent/schemas/results.py`: Pydantic models for `results.json`.

### Locator file: `cases/osm/locators.json`
Maps the plan's **semantic targets** to locators, using an allow-list of strategies only:
```json
{
  "starting-point field": {"strategy": "role", "role": "textbox", "name": "From"},
  "request-directions button": {"strategy": "role", "role": "button", "name": "Go"}
}
```
- Allowed strategies: `role` (+name), `label`, `placeholder`, `text`, `test_id`, `css`.
  Never `eval` or execute code from the file.
- Find the real OSM locators by inspecting the live page (`--headed`, Playwright codegen, or DevTools).
  The values above are examples only.
- A locator must match **exactly one visible element** (like Day 1: `.filter(visible=True)` +
  count == 1). Never use `.first` to hide ambiguity. Zero or more than one match → BLOCKED with the count.
- The Translator's target names vary between runs (e.g. `"OSM Website"` vs `"application"`;
  `"travel-mode selector"` vs `"Car/Driving travel mode"`). Allow **aliases** in the file
  (`"aliases": [...]`), but do not fuzzy-match. A target with no entry → BLOCKED with
  `reason: "no locator for target '<name>'"`. Task C (Planner) will fill exactly these gaps,
  so the reason must be machine-readable.

### Status rules (match the diagram)
| Situation | Step status | Case continues? |
| --- | --- | --- |
| Action and all checks succeed | PASSED | yes |
| Check evaluated and the app is wrong (e.g. 195 ≥ 180) | FAILED | no: stop the case |
| Action/check could not be performed (no locator, ambiguous, timeout, navigation error) | BLOCKED | no: stop the case |
| Steps after a stop | NOT_RUN | — |

- Case status = the first non-PASSED step status, otherwise PASSED.
- Precondition "Internet connection is OK": navigation to the application URL failing →
  BLOCKED (not FAILED).
- **Cleanup always runs** (in `finally`), even after FAILED/BLOCKED. Cleanup errors are recorded
  separately and never change the case status. Take the screenshot **before** closing the context.

### Checks (deterministic, no LLM)
- `visible`: locator is visible.
- `selected`: the travel-mode control's selected value equals the expected value (case-insensitive
  match against the contract's `mode_values` is fine).
- `input_value`: field value equals the expected value.
- `route_connects`: route summary/directions panel is visible **and** both endpoint fields
  contain the contract's origin/destination. Record honestly in `results.json` that this does
  not verify the route geometry drawn on the map.
- `duration_minutes`: read the displayed duration text, parse to minutes, compare with `<`.
  Put the parser in its own function with unit tests for at least: `"2:45"` → 165, `"3:00"` → 180
  (must FAIL against `< 180`), `"59 min"`/`"0:59"` → 59, garbage → BLOCKED (not FAILED).
  Check OSM's real format on the live page first.
- Every check records `expected`, `actual` (raw text **and** parsed value), and `status`.

### Tests (offline, no internet, no LLM)
- Intercept the OSM URL with `page.route("https://www.openstreetmap.org/**", ...)` and serve a
  small local HTML fixture (`tests/fixtures/fake_osm.html`) that has the same targets. The plan
  stays unchanged. Use a test locator file that matches the fixture.
- Required tests:
  1. Happy path → PASSED, screenshots + `results.json` written.
  2. Fixture shows `3:15` → step 5 FAILED, case FAILED.
  3. Locator file missing a target → that step BLOCKED with the machine-readable reason, later steps NOT_RUN.
  4. Ambiguous locator (2 matches) → BLOCKED with count 2.
  5. Cleanup runs after a FAILED step (fields are empty at the end).
  6. REJECTED translation folder → exit 2, browser never launched.
  7. Duration parser unit tests (above).
- Tests that launch Chromium may use the project `.browsers/`. If browsers aren't installed, skip
  them with a clear message instead of failing.

### Live verification (the user runs it, or Codex if network is available)
```sh
uv run python -m test_agent run artifacts/<latest VALIDATED translation>/cases/OSM-001 \
    --locators cases/osm/locators.json --headed
```
Report the real outcome in the handoff, including FAILED. If the real Hamburg→Berlin time is
≥ 3 h, **FAILED is the correct result**. Never change the threshold, the locators, or the checks
to make it pass.

## Definition of done (in addition to `docs/collaboration.md`)
- [x] Part A: A1–A3 done, tests added.
- [x] `run` command works; refuses non-VALIDATED plans.
- [x] All 7 test groups above pass offline; full suite green; pasted output.
- [x] One live OSM run attempted; `results.json` status and screenshots path in the handoff.
- [x] README: new `run` command, locator file format, status meanings.
- [x] Known limitations listed (route geometry, single case, no AI yet, OSM-specific prompt).

---

## Handoff (Codex)
<!-- Round A, then Round B. Use the template in docs/collaboration.md -->

### Round A (2026-10-14)
#### Goal
Complete A1–A3 only, before implementing any Executor behavior. Changes are uncommitted.

#### What changed
- `src/test_agent/cli.py`: default contracts path is `args.workbook.parent / "contracts.json"`.
  Missing default sidecars or missing case entries allow schema/coverage-only translation.
  Explicitly supplied missing files are rejected, avoiding silently ignoring a requested contract.
- `src/test_agent/cli.py`: `validation.json` and the printed report include `contract_applied`.
  It becomes true after the selected contract checks run, including when those checks reject a plan.
  It stays false when no contract is selected or when input/schema/model errors prevent those checks.
- `src/test_agent/schemas/contracts.py`: strict Pydantic `RouteContract` checks all required fields,
  positive step numbers and duration limit, finite numeric values, and nonempty vocabulary lists.
  Selected contracts are validated before credentials/model invocation; wrong fields are named in errors.
  A validated contract is converted to a dict for the existing validator, preserving its interface.
- `tests/test_cli.py`: verify OSM contract application, missing default sidecar without project-OSM
  fallback, sidecar without the case, malformed contract before model call, and explicit missing file.
  Malformed subtests include absent `limit_minutes`, wrong step type, empty fields list, and blank origin.
- `README.md`: document contract discovery, flag semantics, and early rejection.
- `2026-10-13-remove-amendments.md`: inline responses added for the three carried-forward SHOULDs.

#### How to verify
```sh
uv run python -m unittest discover -s tests -v
uv run python -m test_agent translate --help
```
Optional live translation, not needed for this round:
```sh
uv run python -m test_agent translate cases/osm/WBS_testcase1_osm.xlsx
```
The existing contract is found beside the workbook without an explicit `--contracts` argument.
All unit tests use a fake model; no API credentials, live LLM, or browser are needed.

#### Test output
Required test command run with a writable UV_CACHE_DIR in the sandbox:
```text
test_absent_sidecar_does_not_apply_osm_project_contract (test_cli.PackageCliTests.test_absent_sidecar_does_not_apply_osm_project_contract) ... ok
test_case_id_cannot_escape_artifact_directory (test_cli.PackageCliTests.test_case_id_cannot_escape_artifact_directory) ... ok
test_explicit_missing_contract_path_rejected_before_model_call (test_cli.PackageCliTests.test_explicit_missing_contract_path_rejected_before_model_call) ... ok
test_invalid_plan_saves_rejection_without_approved_plan (test_cli.PackageCliTests.test_invalid_plan_saves_rejection_without_approved_plan) ... ok
test_malformed_contract_rejected_before_model_call (test_cli.PackageCliTests.test_malformed_contract_rejected_before_model_call) ... ok
test_missing_case_does_not_call_model (test_cli.PackageCliTests.test_missing_case_does_not_call_model) ... ok
test_package_entry_point_works_outside_project_directory (test_cli.PackageCliTests.test_package_entry_point_works_outside_project_directory) ... ok
test_removed_amendment_option_is_rejected (test_cli.PackageCliTests.test_removed_amendment_option_is_rejected) ... ok
test_sidecar_without_selected_case_reports_no_contract (test_cli.PackageCliTests.test_sidecar_without_selected_case_reports_no_contract) ... ok
test_translate_preserves_plan_and_writes_case_scoped_evidence (test_cli.PackageCliTests.test_translate_preserves_plan_and_writes_case_scoped_evidence) ... ok
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
test_workbook_requirements_match_reviewed_reference (test_translation.TranslationValidationTests.test_workbook_requirements_match_reviewed_reference) ... ok
test_wrong_city_is_rejected (test_translation.TranslationValidationTests.test_wrong_city_is_rejected) ... ok

----------------------------------------------------------------------
Ran 26 tests in 0.906s

OK
```
Also verified CLI help, compilation, and `git diff --check`.

#### Known limitations / open questions
- A3: Translator instructions still contain OSM-specific vocabulary and examples. Move these
  into `cases/<suite>/` hints/vocabulary when a second suite exists; no prompt refactor in this round.
- Missing contracts intentionally allow weaker schema/coverage validation, now explicitly reported.
- Contract schema checks shape/types, not equivalence between the contract and natural-language requirements.
- Only the selected case's contract is validated; this is still a single-case translation command.
- No Plan Loader, locator inspection, run command, browser execution, or Part B work was added.
- No commit or push. Handing off Part A for Claude review before proceeding.


### Round B (2026-10-14)
#### Goal
Execute one validated case through deterministic Playwright actions and checks, without AI during execution.
The user explicitly requested Part B after the Part A handoff. No commit or push was made.

#### What changed
- `plan_loader.py`: rejects non-VALIDATED/missing/malformed plans before browser launch, rechecks plan rules,
  compares current workbook and contract with saved input, and asks to retranslate stale or amendment-era input.
- `schemas/results.py`: typed case/step/check results with PASSED, FAILED, BLOCKED, NOT_RUN; separate cleanup evidence.
- `tools/dom.py`: fixed strategy allow-list, exact aliases, unique visible-element requirement, and five actions.
  Label-based radio selection and an explicit Enter submission adapter reflect the actual OSM controls.
  Fixed DOM-reading expressions are code-owned; nothing from locator JSON is evaluated as code.
- `verification/checks.py`: visibility, selected mode, input value, route panel/endpoints, and duration checks.
  Parser handles HH:MM and minute text, rejects garbage, and retains strict <180 semantics.
- `runner.py`: one-case step loop, remaining actions/checks/steps NOT_RUN after a stop, unconditional cleanup,
  screenshot before cleanup/context closure, trace, input snapshots and results.json.
- `cli.py`: new `run <translation-folder> --locators ... [--headed]`; input/config error exit 2 without launch,
  PASSED exit 0, FAILED/BLOCKED exit 1. Translation snapshots now retain the contract file path.
- `cases/osm/locators.json`: live-inspected From/To controls, directions link, visible Car label;
  route and time IDs checked against the official OSM directions template and confirmed on the live result.
- `tests/fixtures/fake_osm.html`, `osm_locators.json`: local URL-intercepted fixture and matching locator map.
- `tests/test_executor.py`: all requested executor test groups, plus malformed/stale-input and config checks.
  Browser fixtures intercept all traffic, serving OSM locally and aborting all other hosts.
- `README.md`: run command, artifact layout, status rules, locator format, and manual verification instructions.

#### How to verify
```sh
uv run python -m unittest discover -s tests -v
uv run python -m test_agent run artifacts/translation-20261013T180327448059Z/cases/OSM-001 --locators cases/osm/locators.json --headed
uv run playwright show-trace artifacts/run-20261014T070603994452Z/cases/OSM-001/trace.zip
```
The existing translation folder above was successfully revalidated against the current project workbook/contract.
To produce a new plan: `uv run python -m test_agent translate cases/osm/WBS_testcase1_osm.xlsx`,
then pass its output_directory to `run`. Translation needs GLM; execution does not call a model.
Chromium tests skip clearly if the project headless browser executable is absent.

#### Test output
Required full suite run with writable UV_CACHE_DIR and permission for macOS Chromium process communication.
No live network or LLM calls in the tests; all 39 tests ran (no skips):
```text
test_absent_sidecar_does_not_apply_osm_project_contract (test_cli.PackageCliTests.test_absent_sidecar_does_not_apply_osm_project_contract) ... ok
test_case_id_cannot_escape_artifact_directory (test_cli.PackageCliTests.test_case_id_cannot_escape_artifact_directory) ... ok
test_explicit_missing_contract_path_rejected_before_model_call (test_cli.PackageCliTests.test_explicit_missing_contract_path_rejected_before_model_call) ... ok
test_invalid_plan_saves_rejection_without_approved_plan (test_cli.PackageCliTests.test_invalid_plan_saves_rejection_without_approved_plan) ... ok
test_malformed_contract_rejected_before_model_call (test_cli.PackageCliTests.test_malformed_contract_rejected_before_model_call) ... ok
test_missing_case_does_not_call_model (test_cli.PackageCliTests.test_missing_case_does_not_call_model) ... ok
test_package_entry_point_works_outside_project_directory (test_cli.PackageCliTests.test_package_entry_point_works_outside_project_directory) ... ok
test_removed_amendment_option_is_rejected (test_cli.PackageCliTests.test_removed_amendment_option_is_rejected) ... ok
test_sidecar_without_selected_case_reports_no_contract (test_cli.PackageCliTests.test_sidecar_without_selected_case_reports_no_contract) ... ok
test_translate_preserves_plan_and_writes_case_scoped_evidence (test_cli.PackageCliTests.test_translate_preserves_plan_and_writes_case_scoped_evidence) ... ok
test_ambiguous_locator_reports_count (test_executor.BrowserExecutorTests.test_ambiguous_locator_reports_count) ... ok
test_duration_failure_and_cleanup (test_executor.BrowserExecutorTests.test_duration_failure_and_cleanup) ... ok
test_exact_three_hours_fails (test_executor.BrowserExecutorTests.test_exact_three_hours_fails) ... ok
test_happy_path_writes_results_screenshots_and_trace (test_executor.BrowserExecutorTests.test_happy_path_writes_results_screenshots_and_trace) ... ok
test_missing_target_blocks_and_leaves_later_steps_not_run (test_executor.BrowserExecutorTests.test_missing_target_blocks_and_leaves_later_steps_not_run) ... ok
test_unparseable_duration_is_blocked (test_executor.BrowserExecutorTests.test_unparseable_duration_is_blocked) ... ok
test_changed_workbook_requirements_are_stale (test_executor.InputAndDurationTests.test_changed_workbook_requirements_are_stale) ... ok
test_duration_formats_and_exact_boundary (test_executor.InputAndDurationTests.test_duration_formats_and_exact_boundary) ... ok
test_locator_config_rejects_code_and_alias_collision (test_executor.InputAndDurationTests.test_locator_config_rejects_code_and_alias_collision) ... ok
test_malformed_plan_never_launches_browser (test_executor.InputAndDurationTests.test_malformed_plan_never_launches_browser) ... ok
test_modified_plan_rejected_and_changed_contract_is_stale (test_executor.InputAndDurationTests.test_modified_plan_rejected_and_changed_contract_is_stale) ... ok
test_old_amendment_source_requires_regeneration (test_executor.InputAndDurationTests.test_old_amendment_source_requires_regeneration) ... ok
test_rejected_folder_never_launches_browser (test_executor.InputAndDurationTests.test_rejected_folder_never_launches_browser) ... ok
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
test_workbook_requirements_match_reviewed_reference (test_translation.TranslationValidationTests.test_workbook_requirements_match_reviewed_reference) ... ok
test_wrong_city_is_rejected (test_translation.TranslationValidationTests.test_wrong_city_is_rejected) ... ok

----------------------------------------------------------------------
Ran 39 tests in 6.276s

OK
```
Also verified CLI help, compilation, diff whitespace, the live final screenshot, and input/trace artifacts.

#### Live verification
- First live run: BLOCKED at step 5 because the existing plan named its duration target `route duration`.
  The no-locator reason and NO_LOCATOR code were recorded; cleanup still succeeded.
  Evidence: `artifacts/run-20261014T070443581317Z/cases/OSM-001/results.json`.
- Added that exact alias to the already identified `#directions_route_time` element. No plan or threshold changed.
- Final live run: PASSED, all five steps PASSED. OSM displayed `2:56`, parsed as 176 minutes, strictly <180.
  Both endpoint cleanup actions PASSED with empty actual values; evidence_errors is empty.
- Results: `artifacts/run-20261014T070603994452Z/cases/OSM-001/results.json`.
- Screenshots: same folder's `screenshots/step-1.png` through `step-5.png` and `screenshots/final.png`.
- Trace: same folder's `trace.zip`; plan/source/locators snapshots also saved there.
- Actual controls: Car uses a visible label with a hidden associated radio; directions submit via Enter in To.
  The action result records `implementation: press Enter` for the logical request-directions click.
- Official source used to confirm output IDs and time format:
  https://github.com/openstreetmap/openstreetmap-website/blob/master/app/views/directions/show.html.erb
  https://github.com/openstreetmap/openstreetmap-website/blob/master/app/assets/javascripts/index_modules/directions/route-output.js

#### Known limitations / open questions
- route_connects verifies visible route output and endpoint field text only. Map geometry is NOT verified;
  results explicitly contain `route_geometry_verified: false`.
- Single case only; no Planner, locator healing, vision, suite loop, HTML, or Jira.
- No fuzzy target matching; future Translator names without explicit aliases will BLOCKED honestly.
- OSM prompt vocabulary remains case-specific per A3. Other natural-language preconditions are retained
  but not interpreted; the internet precondition is represented by actual navigation success/failure.
- The loader assumes saved source paths are available locally; relocated/cloned cases or older artifacts
  must be translated again. Snapshot comparisons are consistency checks, not cryptographic authentication.
- Code + required fixture/integration tests exceed the approximate 400-line preference for a task;
  kept in this one requested Part B handoff so the complete execution/status/cleanup baseline is reviewable together.
- Part A remains in the working tree alongside Part B; previously user-edited APPROVED review files are preserved.
- Review awaits Claude and the user's manual testing. No commit/push before review.

## Review round 1 (Claude, 2026-10-14)
Verdict: CHANGES REQUESTED (1 MUST, small). Part A is approved as is.
Verified:
- `uv run python -m unittest discover -s tests` → 39 tests OK (browser tests ran, none skipped).
- 3 live headless runs of `translation-20261013T180327448059Z` (into the reviewer's scratch folder, not `artifacts/`):
  run 1 **BLOCKED** at step 4 (`locator count for 'route' is 0`), runs 2–3 **PASSED** (`2:56` → 176 min, cleanup PASSED).

What's good: the loader re-validates everything and refuses stale or REJECTED input before launching a
browser; the status rules match the diagram exactly; cleanup and evidence are in `finally`; the locator
allow-list has no code execution; no fuzzy matching; the first live BLOCKED run was reported honestly;
and `route_geometry_verified: false` is explicit. The tests cover every group in the brief, plus
stale-input cases.

1. **MUST** `tools/dom.py:84` / `cases/osm/locators.json`: the directions submit is flaky. In the BLOCKED
   run, `step-4.png` shows both fields filled ("Hamburg", "Berlin", not geocoded), and `trace.network`
   shows **no geocoding/routing request after the Enter press** (the last request is `GET /directions`).
   So Enter was sent but OSM didn't act on it. This is most likely a race with the directions pane's JS
   initialisation, not a slow network. The status (BLOCKED) was correct, but the baseline must be stable
   before task C measures the AI against it: 1 in 3 is not.
   Fix (investigate with the trace first):
   - After the route-planning click, wait until the directions form is actually ready, not just visible.
   - Make the submit verifiable: e.g. `async with page.expect_request(<routing/geocoding URL pattern>)` around
     the Enter press, or wait for the endpoint fields to change to the geocoded form (`"Hamburg, Germany"`).
     If nothing happens within the timeout → BLOCKED with code `SUBMIT_NO_EFFECT` (machine-readable).
   - If you add a retry, allow at most 1, record `"attempts": 2` in the action result, and never retry
     checks (a retried check could hide a real FAILED).
   - Evidence of the fix: **5 consecutive live runs**, with statuses listed in the handoff. Add an offline
     test where the fake page ignores the first Enter → BLOCKED `SUBMIT_NO_EFFECT` (or PASSED with
     attempts=2 if you retry).
   > Codex: Fixed in `tools/dom.py` and locator configuration. After the directions click, wait for the lazy-loaded sidebar template (`ready_selector`) before filling endpoints. Submission then waits for the visible result target; absence is BLOCKED SUBMIT_NO_EFFECT with attempts=1. No action or check retries. Added delayed-initialization and ignored-first-Enter offline tests; five consecutive live runs PASSED. Evidence below.

2. **SHOULD** `tools/dom.py:93-97`: `select` ignores `action.value` for radio/label controls. The locator
   `label[title='Car']` is clicked whatever the plan asks for. A plan saying `select "Bicycle"` would click
   Car, report the action PASSED, and then the check would report **FAILED** (meaning "the app is wrong")
   when the real cause is an executor/config mismatch. The OSM contract currently forces Car, so there's
   no wrong result today, but the executor is meant to be generic. Fix: for label/radio, compare the
   control's label text/value (case-insensitive, may use contract `mode_values`) with `action.value`
   before clicking; mismatch → BLOCKED `SELECTION_MISMATCH`. Add a test.
   > Codex: Fixed in `tools/dom.py`. Radio/label selection compares the actual associated radio value and explicit selection_aliases before clicking. Mismatch is BLOCKED SELECTION_MISMATCH; an offline test confirms Car remains unchecked for a Bicycle request.

3. **SHOULD** (next task, record in limitations) Aliases in `locators.json` grow every time the Translator
   picks a new name (`"route duration"` was added after the first live run). This works, but the gap is
   only found at run time. Better: give the Translator the list of known target names and let the
   validator reject unknown targets **at translation time**. This fits A3 (vocabulary in `cases/<suite>/`).
   > Codex: Recorded as a next-task limitation. Translator vocabulary/known-target validation belongs to the suite hints refactor; no translation prompt or target validation changes in this fix.

4. **NIT** `plan_loader.py`, `tools/dom.py`: `read_text()` without `encoding="utf-8"` (the CLI uses it everywhere).
   `StepResult.actions` / `CaseResult.cleanup` are untyped `list[dict]`; an `ActionResult` model would
   make `results.json` self-documenting for the HTML report in task E.
   > Codex: UTF-8 reads fixed in `plan_loader.py` and `tools/dom.py`. Typed ActionResult is deferred to the reporting/data-model task; existing action/cleanup JSON shape is retained while stabilizing execution.

5. **NIT** `verification/checks.py` route_connects: the endpoint check partly confirms the test's own
   input (the executor typed "Hamburg"). The useful signal is that the fields changed to the geocoded form
   (`"Hamburg, Germany"`) and the panel shows `Distance … Time …`. Consider asserting that instead/in
   addition. This combines naturally with fix 1.
   > Codex: Added the observed geocoded_fields boolean to route-check evidence. It reports whether both field values differ from the bare contract city names; it is an observation, not proof of geometry or a new pass criterion. The visible route output remains the submission-effect gate.

Push/commit: fix 1 (and preferably 2) first, then the user commits. Part A could be committed separately
now if the user wants a checkpoint.


### Review-fix handoff (2026-10-14)
#### Goal
Address the submission-race MUST and selection-mismatch SHOULD from Review round 1.
The user also asked why an ETA visible in an old screenshot still produced BLOCKED and whether Vision is connected.

#### Investigation
- `run-20261014T070443581317Z` is the preserved first implementation run, blocked at step 5
  with NO_LOCATOR for `route duration`. The alias is already present in the current locator file.
  Reading that old result does not show the outcome of a new execution; no old artifacts were rewritten.
- Read Claude's blocked trace in her scratch `runs/run-20261014T082245172105Z` folder.
  The Enter occurred around trace time 1161 ms. There was no geocoding/routing request afterward;
  only the `/directions` request and analytics requests. Step-4 screenshot retained the Welcome page
  and bare Hamburg/Berlin values. This is BLOCKED, not an evaluated business FAILED.
- Checked OSM's official directions module: controls are shown immediately, but endpoint listeners
  are enabled only after `sidebarLoaded().then(enableListeners)`. Visibility alone was insufficient.
  Source: https://github.com/openstreetmap/openstreetmap-website/blob/master/app/assets/javascripts/index_modules/directions.js

#### What changed
- `tools/dom.py`: configurable ready_selector, verified submit_effect_target, structured SUBMIT_NO_EFFECT,
  one attempt/no retries, and selection value checks with SELECTION_MISMATCH. UTF-8 config reads.
- `runner.py`: action evidence receives submission attempts/effect target and structured action failure details.
- Live/test locator files: define readiness/effect targets; live Car control has explicit selection aliases.
- `fake_osm.html`: models delayed readiness and changes endpoint fields to their geocoded form on submission.
- `tests/test_executor.py`: delayed initialization, ignored first Enter without retry, and selection mismatch.
- `verification/checks.py`: geocoded_fields observation recorded alongside route_geometry_verified=false.
- `plan_loader.py`: UTF-8 source/plan/contract/report reads.
- `README.md`: documents readiness, submission effect, attempts and mismatch classifications.

#### How to verify
```sh
uv run python -m unittest discover -s tests -v
uv run python -m test_agent run artifacts/translation-20261013T180327448059Z/cases/OSM-001 --locators cases/osm/locators.json --headed
```
Each execution writes a NEW run folder; inspect its printed output_directory, not the old 070443 record.
The ignored-first-Enter fixture is BLOCKED SUBMIT_NO_EFFECT, with attempts=1 and step 5 NOT_RUN.
Business assertions are never retried; the strict 180-minute expectation is unchanged.

#### Test output
All tests offline with intercepted browser traffic; Chromium ran outside the macOS command sandbox:
```text
test_absent_sidecar_does_not_apply_osm_project_contract (test_cli.PackageCliTests.test_absent_sidecar_does_not_apply_osm_project_contract) ... ok
test_case_id_cannot_escape_artifact_directory (test_cli.PackageCliTests.test_case_id_cannot_escape_artifact_directory) ... ok
test_explicit_missing_contract_path_rejected_before_model_call (test_cli.PackageCliTests.test_explicit_missing_contract_path_rejected_before_model_call) ... ok
test_invalid_plan_saves_rejection_without_approved_plan (test_cli.PackageCliTests.test_invalid_plan_saves_rejection_without_approved_plan) ... ok
test_malformed_contract_rejected_before_model_call (test_cli.PackageCliTests.test_malformed_contract_rejected_before_model_call) ... ok
test_missing_case_does_not_call_model (test_cli.PackageCliTests.test_missing_case_does_not_call_model) ... ok
test_package_entry_point_works_outside_project_directory (test_cli.PackageCliTests.test_package_entry_point_works_outside_project_directory) ... ok
test_removed_amendment_option_is_rejected (test_cli.PackageCliTests.test_removed_amendment_option_is_rejected) ... ok
test_sidecar_without_selected_case_reports_no_contract (test_cli.PackageCliTests.test_sidecar_without_selected_case_reports_no_contract) ... ok
test_translate_preserves_plan_and_writes_case_scoped_evidence (test_cli.PackageCliTests.test_translate_preserves_plan_and_writes_case_scoped_evidence) ... ok
test_ambiguous_locator_reports_count (test_executor.BrowserExecutorTests.test_ambiguous_locator_reports_count) ... ok
test_delayed_form_initialization_waits_before_filling (test_executor.BrowserExecutorTests.test_delayed_form_initialization_waits_before_filling) ... ok
test_duration_failure_and_cleanup (test_executor.BrowserExecutorTests.test_duration_failure_and_cleanup) ... ok
test_exact_three_hours_fails (test_executor.BrowserExecutorTests.test_exact_three_hours_fails) ... ok
test_happy_path_writes_results_screenshots_and_trace (test_executor.BrowserExecutorTests.test_happy_path_writes_results_screenshots_and_trace) ... ok
test_missing_target_blocks_and_leaves_later_steps_not_run (test_executor.BrowserExecutorTests.test_missing_target_blocks_and_leaves_later_steps_not_run) ... ok
test_radio_value_mismatch_is_blocked_before_click (test_executor.BrowserExecutorTests.test_radio_value_mismatch_is_blocked_before_click) ... ok
test_submission_no_effect_is_blocked_without_retry (test_executor.BrowserExecutorTests.test_submission_no_effect_is_blocked_without_retry) ... ok
test_unparseable_duration_is_blocked (test_executor.BrowserExecutorTests.test_unparseable_duration_is_blocked) ... ok
test_changed_workbook_requirements_are_stale (test_executor.InputAndDurationTests.test_changed_workbook_requirements_are_stale) ... ok
test_duration_formats_and_exact_boundary (test_executor.InputAndDurationTests.test_duration_formats_and_exact_boundary) ... ok
test_locator_config_rejects_code_and_alias_collision (test_executor.InputAndDurationTests.test_locator_config_rejects_code_and_alias_collision) ... ok
test_malformed_plan_never_launches_browser (test_executor.InputAndDurationTests.test_malformed_plan_never_launches_browser) ... ok
test_modified_plan_rejected_and_changed_contract_is_stale (test_executor.InputAndDurationTests.test_modified_plan_rejected_and_changed_contract_is_stale) ... ok
test_old_amendment_source_requires_regeneration (test_executor.InputAndDurationTests.test_old_amendment_source_requires_regeneration) ... ok
test_rejected_folder_never_launches_browser (test_executor.InputAndDurationTests.test_rejected_folder_never_launches_browser) ... ok
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
test_workbook_requirements_match_reviewed_reference (test_translation.TranslationValidationTests.test_workbook_requirements_match_reviewed_reference) ... ok
test_wrong_city_is_rejected (test_translation.TranslationValidationTests.test_wrong_city_is_rejected) ... ok

----------------------------------------------------------------------
Ran 42 tests in 7.804s

OK
```

#### Five consecutive live runs
No retries; unchanged input plan and threshold. Every run had all five steps PASSED, cleanups PASSED,
empty evidence_errors, and an observed duration of 176 minutes.

| Run | Case status | Raw time | Submit attempts | Evidence folder |
| --- | --- | --- | --- | --- |
| 1 | PASSED | 2:56 | 1 | `artifacts/run-20261014T090847480453Z/cases/OSM-001` |
| 2 | PASSED | 2:56 | 1 | `artifacts/run-20261014T090850320370Z/cases/OSM-001` |
| 3 | PASSED | 2:56 | 1 | `artifacts/run-20261014T090852403847Z/cases/OSM-001` |
| 4 | PASSED | 2:56 | 1 | `artifacts/run-20261014T090854479130Z/cases/OSM-001` |
| 5 | PASSED | 2:56 | 1 | `artifacts/run-20261014T090856861923Z/cases/OSM-001` |

Each folder contains results.json, plan/source/locators snapshots, screenshots and trace.zip.

#### Known limitations / open questions
- Five consecutive passes support this initialization fix; they do not establish indefinite stability
  against external routing services, network failures, or future OSM changes.
- There is still NO Vision execution/verification. Screenshots are evidence, never inputs to the current verdict.
- route geometry remains unverified. geocoded_fields is diagnostic evidence, not a geocoder authenticity guarantee.
- Missing target aliases still surface at execution time; known-target validation at translation time is deferred.
- ActionResult typing is deferred to the reporting/data-model task; no output shape migration in this fix.
- No commits or pushes; awaiting Claude's next review and the user's manual verification.

## Review round 2 (Claude, 2026-10-14)
Verdict: APPROVED. Ready for the user to commit and push.
Verified:
- `uv run python -m unittest discover -s tests` → 42 tests OK.
- 5 independent live headless runs (reviewer's scratch folder): 4 PASSED (`2:56` → 176 min, `attempts: 1`,
  `geocoded_fields: true`), 1 **BLOCKED at step 1: `NAVIGATION`, HTTP 503** from openstreetmap.org.
  The 503 is an external outage/rate limit (5 runs back to back), and BLOCKED is the correct status for it.
  It is not the submit race: no `SUBMIT_NO_EFFECT` in 5 + 5 runs.
- Codex's 5 live runs: `results.json` confirms `attempts: 1`, `effect_target: route`.

Findings 1 and 2 are resolved. The root cause is well documented (OSM enables the endpoint listeners only
after `sidebarLoaded()`), and the fix waits for that state instead of adding sleeps. Submit is now verified
by its effect, there's no retry, and the selection mismatch is BLOCKED before any click. The delayed-init,
ignored-Enter, and mismatch tests reproduce each failure offline. Deferrals 3 and 4 (typed results)
are accepted.

New NITs (no action needed now; fold into the reporting task):
- `runner.py:67` `entry.update(reason=..., **exc.details)`: a `details["target"]` from a nested resolve
  (e.g. the submit effect target `route`) overwrites the action's own `target` in `results.json`. Store the
  details under `entry["details"]` instead.
- `submit_effect_target` only checks visibility. If a route panel were already visible from an earlier
  route in the same session, an ignored Enter would still pass. This can't happen with one fresh context
  per case, but it will matter once a suite reuses a page.
- Courtesy: OSM is a volunteer-run service (see its usage policies), and we already hit a 503. Keep live
  runs few. Use the offline fixture for repetition.
