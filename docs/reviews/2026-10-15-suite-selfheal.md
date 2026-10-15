# Task: suite loop for 3 cases, layer case support, locator cache + limited self-healing
Status: APPROVED
Workflow step(s): 2 / 6 (case loop), 3 (locator resolution + self-healing). Plan Day 3.
Assigned: Codex · Reviewer: Claude · Brief written 2026-10-15

## Context and schedule
The project is behind schedule; the goal is to **complete the plan**. Keep this task to what's listed and
don't polish beyond it. One handoff for Part A, one for Part B; the reviewer reviews once per part and only blocks on MUST.
Hand off before committing.

Principle (unchanged): use the LLM only where needed. Python decides; models observe or propose, and Python verifies.

The workbook `cases/osm/WBS_testcase1_osm.xlsx` now has 3 cases (edited by the user):
| Case | Topic | Designed outcome |
| --- | --- | --- |
| OSM-001 | Car route Hamburg → Berlin, duration < 180 min | PASSED |
| OSM-002 | Car route Hamburg → **Munich**, duration < 180 min | **FAILED at step 5** (real duration ≈ 7–8 h) |
| OSM-003 | Open the layers panel, check the 8 listed layers, select a layer, check it is selected; cleanup back to Standard and close | PASSED |

### Two input issues the user must fix in Excel first (human-owned; Codex must not edit the workbook)
- **OSM-003 typo:** Actions step 3 and Expected step 3 say `Trackstack Topo`, but the real OSM layer (and Expected step 2's
  own list) is `Tracestrack Topo`. With the typo, the test would correctly report BLOCKED/SELECTION_MISMATCH,
  but for the wrong reason. The user corrects the workbook; Codex starts Part A after that.
- Optional: post-action "Set the **may** layer back…" → "map". This is cosmetic; the Translator keeps it verbatim either way.

---

## Part A: suite loop + OSM-002 + OSM-003

### A1. Suite command (diagram steps 2 → 6)
```sh
uv run python -m test_agent suite cases/osm/WBS_testcase1_osm.xlsx --locators cases/osm/locators.json [--reuse] [--skip-vision]
```
- Reads **all** case IDs from the workbook (new reader function; keep `read_case` as is), in workbook order.
- For each case: translate (GLM) → if VALIDATED, run → collect results. A case whose translation is REJECTED is
  recorded as BLOCKED (`TRANSLATION_REJECTED`, with the validation errors) and the suite continues.
- `--reuse`: reuse the newest VALIDATED translation for a case if the workbook text, contract and vocabulary are
  unchanged (the loader's existing staleness checks); otherwise translate again. This saves GLM calls during
  repeatability runs (Day 6).
- One fresh browser context per case (isolation); cleanup per case as now.
- Output: `artifacts/suite-<id>/summary.json` + per-case folders (reusing the existing `run`/`translation` layouts
  or linking to them). `summary.json`: per case status, reason, durations, translation folder, run folder; totals.
- **Designed outcome (for the demo and repeatability, not a test verdict):** add an optional `"designed_outcome"`
  (`PASSED`/`FAILED`) per case in `contracts.json`. The summary shows `outcome_as_designed: true/false` next to the real
  status. It never changes a case status. OSM-002 FAILED → `outcome_as_designed: true`.
- Exit code: 0 if all cases PASSED, else 1 (the test result). Print a short table.

### A2. OSM-002 (route to Munich)
- Add the OSM-002 route contract (origin Hamburg, destination Munich, limit 180, the same step numbers, the vision check on
  step 4 with `min_confidence` 0.90, `designed_outcome: FAILED`).
- **MUST, city names:** OSM map labels are German. Calibration already showed the model reads `München`. With
  `destination: "Munich"`, `endpoint_matches("München", "Munich")` fails, which gives a **false vision FAILED at step 4** and
  the case fails for the wrong reason. Add optional `origin_aliases` / `destination_aliases` to the route contract
  (OSM-002: `["München"]`). Use them in both the vision comparison and the DOM `route_connects` check, as exact
  matches only (no fuzzy). Test: observation `München` + destination `Munich` with alias → PASSED; without alias → FAILED.
- Expected live result: steps 1–4 PASSED (vision reads Hamburg → München), **step 5 FAILED** with the parsed duration
  (≥ 180) in the reason.

### A3. OSM-003 (map layers): a second contract type
- `contracts.json` entries get a `"type"`: `"route"` (existing, the default for old entries) or `"layer"`. Use a pydantic
  discriminated union. Route-specific validation runs only for `route`.
- Layer contract (example; the step numbers come from the workbook):
  ```json
  "OSM-003": {"type": "layer", "panel_step": 2, "select_step": 3,
              "expected_options": ["Standard", "CyclOSM", "Cycle Map", "Transport Map", "Tracestrack Topo",
                                   "Humanitarian", "Shortbread", "MapTiler OMT"],
              "selected_layer": "Tracestrack Topo", "default_layer": "Standard",
              "designed_outcome": "PASSED"}
  ```
  Layer validator rules (deterministic, like the route ones): the select step selects exactly `selected_layer`; the panel step
  checks all `expected_options`; the select step checks the selected layer; cleanup selects `default_layer` and closes the panel.
- Vocabulary: add targets such as `layers control`, `map layers panel`, `map layer selector`, `layers panel close button`
  (descriptions plus hints). Keep the existing route targets.
- Locators: inspect the live OSM layers panel and add entries (allowed strategies only). Layer choice is a radio/label
  control, so reuse the existing `select` handling with `selection_aliases` if the labels differ.
- **New check kind `options_present`:** the expected value is a list of option labels; it PASSES only if every expected label is
  present in the panel (report missing and extra labels in `actual`). Extend `Assertion` so `value` may be a list of
  strings for this kind only.
- Step 3 "the map display changes to Tracestrack Topo": check in the DOM, with `selected` = the Tracestrack Topo radio
  checked. If OSM exposes the active layer in the URL (the `layers=` parameter), record it in `actual` as extra evidence.
  **No vision check for layers:** that would be a new visual check kind and would need its own calibration set
  (agreed rule). Record "layer tiles not visually verified" as a known limitation.
- Precondition "Standard Map Layer (default) is selected": record the observed default selection in `actual` before
  step 1 actions if cheap; otherwise keep it as text (as now). Don't build a general precondition checker.

### Part A acceptance
- [ ] The user fixed the Excel typo before Part A started (note it in the handoff).
- [ ] Offline tests: suite loop with 3 fake cases (one translation REJECTED → BLOCKED and the suite continues), `--reuse`
      hit/miss, aliases, layer contract validation (positive and negative), `options_present` (missing/extra).
- [ ] Live: **one** suite run for all 3 cases (OSM courtesy). Expected: OSM-001 PASSED, OSM-002 FAILED at step 5,
      OSM-003 PASSED, and all three `outcome_as_designed: true`. Paste the summary table. If a result differs, report it honestly.
- [ ] README (Chinese): `suite`, `--reuse`, contract types, `designed_outcome` vs. status.

---

## Part B: locator cache + limited self-healing (diagram step 3)

### B1. Resolution order
`locators.json` (human) → `locators.cache.json` (machine, same folder) → **self-heal**. A cached locator is used only if it
still resolves to exactly one visible element; otherwise heal again.

### B2. Self-heal (limited)
- Trigger only on `NO_LOCATOR` or `LOCATOR_COUNT` with count 0, and only for targets **declared in `vocabulary.json`**.
- Input to the Planner (GLM, text only, no tools): the target name, its vocabulary description, and the page's ARIA
  snapshot (`page.locator("body").aria_snapshot()`, truncated to a fixed size). Never send cookies, page HTML, or the plan's expected values.
- Output: one JSON proposal using the allowed strategies **without `css`** (`role`+name, `label`, `placeholder`, `text`,
  `test_id`), plus a one-line rationale.
- Python validates: schema, strategy allow-list, **exactly one visible match**. Then it performs the action/check as normal.
- **Max 1 heal attempt per target per case.** A failed heal → BLOCKED with code `HEAL_FAILED` (+ the proposal and the match count).
- A successful heal is written to `locators.cache.json` with provenance (target, locator, case, run id, model, timestamp,
  snapshot hash) and used by later cases in the same suite and by later runs. **Never write to `locators.json`.**
- Results mark it: the action/check entry gets `"healed": true`, plus `locator_source`: `human` | `cache` | `healed`.
  The suite summary counts heals.
- Healing finds elements only; it can never change actions, values, expected results or statuses.

### B3. Part B acceptance
- [ ] Offline tests (fake Planner): heal success → action PASSED, cache written, second resolution uses the cache without a model call;
      ambiguous proposal (2 matches) → HEAL_FAILED; a `css` proposal rejected; undeclared target → no heal; stale cache → heal again.
- [ ] Live demonstration, **once**: copy `locators.json` to a temp file without the `layers control` entry, run OSM-003
      with it, and show `locator_source: healed` and the cache entry. (This is also the first Day 5 fault-injection scenario.)
- [ ] README: resolution order, cache file, limits.

## Out of scope (later tasks)
Clef via OpenRouter (next, small), Day 5 fault-injection switches and the vision click fallback, Day 6 HTML report.

---

## Handoff (Codex)
<!-- Part A, then Part B. Template in docs/collaboration.md -->

### Part A handoff — 2026-10-15 (Codex)
Goal: workbook-order suite loop, exact city aliases, and DOM layer-case support (workflow 2/6).

What changed:
- `suite.py`, `cli.py`, `readers/excel.py`: all-case loop, stale-plan-safe reuse, isolated execution, timings, diagnostic designed outcomes, summary and exit status.
- `schemas/contracts.py`, `plan_loader.py`: route/layer discriminated contracts, legacy route defaults.
- `schemas/plan.py`, `translation/translator.py`, `translation/validator.py`: options_present, layer invariants, explicit selected operator guidance, exact declared city aliases in route checks.
- `tools/dom.py`, `verification/checks.py`, `verification/vision.py`: label-based radio groups, options/missing/extra evidence, layer URL evidence, exact aliases for DOM and blind vision comparisons.
- `cases/osm/{contracts,locators,vocabulary}.json`: contracts and semantic targets for all three cases. Workbook corrected by the user before work; Codex did not edit it.
- `tests/test_suite.py`, `tests/fixtures/fake_layers.html`: fake suite rejection/continuation, reuse, designed failure, exact alias, layer validation and browser evidence tests. README has Chinese commands/explanations.

How to verify:
```sh
uv run python -m unittest discover -s tests -v
uv run python -m test_agent suite cases/osm/WBS_testcase1_osm.xlsx --locators cases/osm/locators.json --reuse --headed
```
Live evidence (one browser suite, no repeated suite visits):
`artifacts/suite-20261015T084012127337Z/summary.json`

| Case | Actual | As designed | Reason |
|---|---|---|---|
| OSM-001 | BLOCKED | false | Vision confidence 0.85 < unchanged 0.90; later DOM duration still ran |
| OSM-002 | BLOCKED | false | Translation route check used München; original validator required Munich |
| OSM-003 | PASSED | true | All eight options, selected Tracestrack Topo, cleanup passed |

The first translation-only attempt (`suite-20261015T083604767711Z`) rejected all three missing selected-check operators and made no browser visits. Tightened prompt/schema descriptions; did not infer missing operators.
After the live suite exposed the alias gate inconsistency, fixed the gate and added regression coverage. Translated and executed ONLY OSM-002 once (not another suite):
`artifacts/translation-20261015T084143589101Z/cases/OSM-002`.
Follow-up evidence: `artifacts/run-20261015T084215186969Z/cases/OSM-002/results.json` — **FAILED at step 5**, Duration 456 minutes is not less than 180 minutes; route_geometry_verified=True.

Known limitations: full three-case designed-outcome acceptance is not yet achieved (OSM-001 vision BLOCKED). No threshold/requirements changed and no repeated attempts to obtain a favourable vision answer. Layer tile appearance is not visually verified; preconditions remain source text. This task exceeds the protocol's approximate 400-line preference because the brief explicitly combines the suite, contract union, layer support, tests and live evidence; Part A/B have separate handoffs. No commits made.

Test output (complete; UV_CACHE_DIR=/private/tmp/wbs-uv-cache, local Chromium enabled):
```text
test_arithmetic_and_threshold_replay (test_calibration.CalibrationTests.test_arithmetic_and_threshold_replay) ... ok
test_bad_labels_rejected (test_calibration.CalibrationTests.test_bad_labels_rejected) ... ok
test_capture_excludes_overlay_and_never_overwrites_frozen_set (test_calibration.CalibrationTests.test_capture_excludes_overlay_and_never_overwrites_frozen_set) ... ok
test_offline_run_counts_error_and_saves_report (test_calibration.CalibrationTests.test_offline_run_counts_error_and_saves_report) ... ok
test_pure_decision_threshold_boundary_and_no_mutation (test_calibration.CalibrationTests.test_pure_decision_threshold_boundary_and_no_mutation) ... ok
test_absent_sidecar_does_not_apply_osm_project_contract (test_cli.PackageCliTests.test_absent_sidecar_does_not_apply_osm_project_contract) ... ok
test_case_id_cannot_escape_artifact_directory (test_cli.PackageCliTests.test_case_id_cannot_escape_artifact_directory) ... ok
test_explicit_missing_contract_path_rejected_before_model_call (test_cli.PackageCliTests.test_explicit_missing_contract_path_rejected_before_model_call) ... ok
test_invalid_plan_saves_rejection_without_approved_plan (test_cli.PackageCliTests.test_invalid_plan_saves_rejection_without_approved_plan) ... ok
test_malformed_contract_rejected_before_model_call (test_cli.PackageCliTests.test_malformed_contract_rejected_before_model_call) ... ok
test_malformed_vocabulary_rejected_before_model_call (test_cli.PackageCliTests.test_malformed_vocabulary_rejected_before_model_call) ... ok
test_missing_case_does_not_call_model (test_cli.PackageCliTests.test_missing_case_does_not_call_model) ... ok
test_package_entry_point_works_outside_project_directory (test_cli.PackageCliTests.test_package_entry_point_works_outside_project_directory) ... ok
test_removed_amendment_option_is_rejected (test_cli.PackageCliTests.test_removed_amendment_option_is_rejected) ... ok
test_sidecar_without_selected_case_reports_no_contract (test_cli.PackageCliTests.test_sidecar_without_selected_case_reports_no_contract) ... ok
test_translate_preserves_plan_and_writes_case_scoped_evidence (test_cli.PackageCliTests.test_translate_preserves_plan_and_writes_case_scoped_evidence) ... ok
test_unknown_action_check_and_cleanup_targets_rejected_during_translation (test_cli.PackageCliTests.test_unknown_action_check_and_cleanup_targets_rejected_during_translation) ... ok
test_ambiguous_locator_reports_count (test_executor.BrowserExecutorTests.test_ambiguous_locator_reports_count) ... ok
test_delayed_form_initialization_waits_before_filling (test_executor.BrowserExecutorTests.test_delayed_form_initialization_waits_before_filling) ... ok
test_duration_failure_and_cleanup (test_executor.BrowserExecutorTests.test_duration_failure_and_cleanup) ... ok
test_exact_three_hours_fails (test_executor.BrowserExecutorTests.test_exact_three_hours_fails) ... ok
test_form_not_ready_reports_lazy_fetch_http_status (test_executor.BrowserExecutorTests.test_form_not_ready_reports_lazy_fetch_http_status) ... ok
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
test_contract_only_change_new_validated_folder_old_untouched (test_revalidate.RevalidateTests.test_contract_only_change_new_validated_folder_old_untouched) ... ok
test_modified_plan_still_rejected_against_current_contract (test_revalidate.RevalidateTests.test_modified_plan_still_rejected_against_current_contract) ... ok
test_workbook_change_rejected_without_approved_plan (test_revalidate.RevalidateTests.test_workbook_change_rejected_without_approved_plan) ... ok
test_layer_selected_cleanup_and_options_missing_extra (test_suite.LayerBrowserTests.test_layer_selected_cleanup_and_options_missing_extra) ... ok
test_case_ids_order_and_reuse_hit_miss (test_suite.SuiteTests.test_case_ids_order_and_reuse_hit_miss) ... ok
test_city_alias_is_exact_and_used_by_vision (test_suite.SuiteTests.test_city_alias_is_exact_and_used_by_vision) ... ok
test_designed_failure_remains_failed_and_reuse_skips_translation (test_suite.SuiteTests.test_designed_failure_remains_failed_and_reuse_skips_translation) ... ok
test_dom_route_uses_city_alias (test_suite.SuiteTests.test_dom_route_uses_city_alias) ... ok
test_layer_contract_positive_and_negative (test_suite.SuiteTests.test_layer_contract_positive_and_negative) ... ok
test_plan_route_check_accepts_only_declared_city_alias (test_suite.SuiteTests.test_plan_route_check_accepts_only_declared_city_alias) ... ok
test_three_cases_rejected_middle_continues_and_designed_status_stays_real (test_suite.SuiteTests.test_three_cases_rejected_middle_continues_and_designed_status_stays_real) ... ok
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
test_default_provider_runs_only_declared_checks_after_dom_pass (test_vision.VisionRunnerTests.test_default_provider_runs_only_declared_checks_after_dom_pass) ... ok
test_precedence_crop_reasons_and_cleanup (test_vision.VisionRunnerTests.test_precedence_crop_reasons_and_cleanup) ... ok
test_skip_vision_cli_continues_duration_but_never_passes (test_vision.VisionRunnerTests.test_skip_vision_cli_continues_duration_but_never_passes) ... ok
test_claude_native_image_and_output_budget (test_vision.VisionTests.test_claude_native_image_and_output_budget) ... ok
test_config_error_never_uses_glm_key (test_vision.VisionTests.test_config_error_never_uses_glm_key) ... ok
test_contract_change_stales_saved_plan (test_vision.VisionTests.test_contract_change_stales_saved_plan) ... ok
test_contract_rejects_invalid_or_missing_confidence_and_unknown_kind (test_vision.VisionTests.test_contract_rejects_invalid_or_missing_confidence_and_unknown_kind) ... ok
test_each_transport_error_code_is_safe_and_saved (test_vision.VisionTests.test_each_transport_error_code_is_safe_and_saved) ... ok
test_invalid_json_schema_and_skip_have_saved_response (test_vision.VisionTests.test_invalid_json_schema_and_skip_have_saved_response) ... ok
test_judgment_programming_error_is_internal_not_network (test_vision.VisionTests.test_judgment_programming_error_is_internal_not_network) ... ok
test_qualified_requirement_retains_country (test_vision.VisionTests.test_qualified_requirement_retains_country) ... ok
test_reason_rows_and_strict_rules (test_vision.VisionTests.test_reason_rows_and_strict_rules) ... ok
test_sdk_sends_image_and_records_usage (test_vision.VisionTests.test_sdk_sends_image_and_records_usage) ... ok
test_thinking_prefix_parsed_but_never_logged (test_vision.VisionTests.test_thinking_prefix_parsed_but_never_logged) ... ok
test_declared_targets_do_not_require_existing_locators (test_vocabulary.VocabularyTests.test_declared_targets_do_not_require_existing_locators) ... ok
test_loader_rejects_changed_vocabulary_and_unknown_saved_target (test_vocabulary.VocabularyTests.test_loader_rejects_changed_vocabulary_and_unknown_saved_target) ... ok
test_translator_receives_suite_catalog_and_hints (test_vocabulary.VocabularyTests.test_translator_receives_suite_catalog_and_hints) ... ok

----------------------------------------------------------------------
Ran 78 tests in 15.608s

OK
```

### Part B handoff — 2026-10-15 (Codex)
Goal: human locator → verified machine cache → one GLM locator proposal per declared target/case (workflow 3).

What changed:
- `planning/locator.py`: tool-free GLM Agent via existing Agents SDK/OPENAI_* settings; strict proposal schema excludes CSS, actions and expected values. ARIA snapshot limit is 16000 characters.
- `tools/healing.py`: human first; cache rechecked for exactly one visible match; healing triggered only for NO_LOCATOR or zero matches and canonical vocabulary targets. One attempt per target/case, HEAL_FAILED details on rejection; atomic separate cache with provenance. No writes to human locator files.
- `tools/dom.py`: shared fixed locator builder, preserving existing human locator strategies.
- `runner.py`, `verification/checks.py`, `schemas/results.py`, `suite.py`: healed/source evidence for actions and DOM checks, successful heal counts, input/proposal and resolved locator artifacts (including cache hits). Existing app assertions still determine results.
- `.gitignore`, README: machine cache ignored, Chinese usage/limits/evidence explanation.
- `tests/test_healing.py`: fake Planner tests for success/persistent reuse, ambiguous/zero counts, CSS/extra field rejection, undeclared and ambiguous-human no-call behavior, stale cache and broken human locator, truncated snapshot, sanitized provider failure, actual action/check evidence, remaining steps NOT_RUN, unchanged human file.

How to verify (from project root):
```sh
uv run python -m unittest discover -s tests -v
uv run python -m test_agent suite cases/osm/WBS_testcase1_osm.xlsx --locators cases/osm/locators.json --reuse --headed
```
For the isolated live demo (already run once; no need for reviewer to revisit OSM):
```sh
uv run python -m test_agent run artifacts/suite-20261015T084012127337Z/translation-20261015T084044092832Z/cases/OSM-003 --locators artifacts/selfheal-demo-20261015/locators.json --output-dir artifacts/selfheal-demo-20261015 --headed
```
The temporary human file is a copy missing only layers control. Its sibling cache now exists, so repeating this command uses the cache. Offline tests prove cache reuse without a second model call; no second live demo was made.

Live demonstration evidence:
- `artifacts/selfheal-demo-20261015/run-20261015T084627427058Z/cases/OSM-003/results.json`: **PASSED**, locator_heals=1, both cleanup actions PASSED.
- Step 2 click layers control: status=PASSED, healed=true, locator_source=healed.
- `artifacts/selfheal-demo-20261015/locators.cache.json`: role=link, name=Layers, match count=1, model=glm-4.7, case=OSM-003, run id/timestamp/snapshot SHA-256/rationale present.
- Same run's `locator-heals.json` and `locator-input-<hash>.json`: actual proposal/verification and truncated Planner input. `resolved-locators.json` was added after this single live run; its generated contents are verified by offline runner tests (not claimed present in the earlier live artifact).
- `git diff --check` clean. `.env` and machine cache ignored; no credentials read into logs. No commit/push performed.

Known limitations / review focus:
- Unique visible matching verifies a locator's shape and uniqueness, not full semantic correctness. Subsequent assertions remain necessary. Page ARIA content is untrusted; the Planner has no tools and cannot propose executable code.
- A stale human locator waits for the existing normal locator timeout before cache/healing; this preserves lazy-DOM handling but adds delay in a fault case. No general retry loop or locator migration is included.
- Suite status stays based on actual results. OSM-001's 0.85 confidence block remains unresolved; it is not converted to a pass. Full expected suite demonstration is still not achieved. Clef via OpenRouter remains the next separate task per the brief and has not been implemented here.
- Part A and Part B are ready for Claude review. Changes remain uncommitted.

Test output (complete; UV_CACHE_DIR=/private/tmp/wbs-uv-cache, local Chromium enabled):
```text
test_arithmetic_and_threshold_replay (test_calibration.CalibrationTests.test_arithmetic_and_threshold_replay) ... ok
test_bad_labels_rejected (test_calibration.CalibrationTests.test_bad_labels_rejected) ... ok
test_capture_excludes_overlay_and_never_overwrites_frozen_set (test_calibration.CalibrationTests.test_capture_excludes_overlay_and_never_overwrites_frozen_set) ... ok
test_offline_run_counts_error_and_saves_report (test_calibration.CalibrationTests.test_offline_run_counts_error_and_saves_report) ... ok
test_pure_decision_threshold_boundary_and_no_mutation (test_calibration.CalibrationTests.test_pure_decision_threshold_boundary_and_no_mutation) ... ok
test_absent_sidecar_does_not_apply_osm_project_contract (test_cli.PackageCliTests.test_absent_sidecar_does_not_apply_osm_project_contract) ... ok
test_case_id_cannot_escape_artifact_directory (test_cli.PackageCliTests.test_case_id_cannot_escape_artifact_directory) ... ok
test_explicit_missing_contract_path_rejected_before_model_call (test_cli.PackageCliTests.test_explicit_missing_contract_path_rejected_before_model_call) ... ok
test_invalid_plan_saves_rejection_without_approved_plan (test_cli.PackageCliTests.test_invalid_plan_saves_rejection_without_approved_plan) ... ok
test_malformed_contract_rejected_before_model_call (test_cli.PackageCliTests.test_malformed_contract_rejected_before_model_call) ... ok
test_malformed_vocabulary_rejected_before_model_call (test_cli.PackageCliTests.test_malformed_vocabulary_rejected_before_model_call) ... ok
test_missing_case_does_not_call_model (test_cli.PackageCliTests.test_missing_case_does_not_call_model) ... ok
test_package_entry_point_works_outside_project_directory (test_cli.PackageCliTests.test_package_entry_point_works_outside_project_directory) ... ok
test_removed_amendment_option_is_rejected (test_cli.PackageCliTests.test_removed_amendment_option_is_rejected) ... ok
test_sidecar_without_selected_case_reports_no_contract (test_cli.PackageCliTests.test_sidecar_without_selected_case_reports_no_contract) ... ok
test_translate_preserves_plan_and_writes_case_scoped_evidence (test_cli.PackageCliTests.test_translate_preserves_plan_and_writes_case_scoped_evidence) ... ok
test_unknown_action_check_and_cleanup_targets_rejected_during_translation (test_cli.PackageCliTests.test_unknown_action_check_and_cleanup_targets_rejected_during_translation) ... ok
test_ambiguous_locator_reports_count (test_executor.BrowserExecutorTests.test_ambiguous_locator_reports_count) ... ok
test_delayed_form_initialization_waits_before_filling (test_executor.BrowserExecutorTests.test_delayed_form_initialization_waits_before_filling) ... ok
test_duration_failure_and_cleanup (test_executor.BrowserExecutorTests.test_duration_failure_and_cleanup) ... ok
test_exact_three_hours_fails (test_executor.BrowserExecutorTests.test_exact_three_hours_fails) ... ok
test_form_not_ready_reports_lazy_fetch_http_status (test_executor.BrowserExecutorTests.test_form_not_ready_reports_lazy_fetch_http_status) ... ok
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
test_ambiguous_proposal_blocks_once_and_remaining_steps_not_run (test_healing.HealingTests.test_ambiguous_proposal_blocks_once_and_remaining_steps_not_run) ... ok
test_css_and_extra_fields_rejected_and_zero_match_blocked (test_healing.HealingTests.test_css_and_extra_fields_rejected_and_zero_match_blocked) ... ok
test_heal_cache_reuse_and_check_metadata (test_healing.HealingTests.test_heal_cache_reuse_and_check_metadata) ... ok
test_runner_action_heals_then_next_run_uses_cache (test_healing.HealingTests.test_runner_action_heals_then_next_run_uses_cache) ... ok
test_snapshot_truncated_and_provider_exception_sanitized (test_healing.HealingTests.test_snapshot_truncated_and_provider_exception_sanitized) ... ok
test_stale_cache_and_broken_human_locator_heal_again (test_healing.HealingTests.test_stale_cache_and_broken_human_locator_heal_again) ... ok
test_undeclared_and_ambiguous_human_targets_never_call_planner (test_healing.HealingTests.test_undeclared_and_ambiguous_human_targets_never_call_planner) ... ok
test_contract_only_change_new_validated_folder_old_untouched (test_revalidate.RevalidateTests.test_contract_only_change_new_validated_folder_old_untouched) ... ok
test_modified_plan_still_rejected_against_current_contract (test_revalidate.RevalidateTests.test_modified_plan_still_rejected_against_current_contract) ... ok
test_workbook_change_rejected_without_approved_plan (test_revalidate.RevalidateTests.test_workbook_change_rejected_without_approved_plan) ... ok
test_layer_selected_cleanup_and_options_missing_extra (test_suite.LayerBrowserTests.test_layer_selected_cleanup_and_options_missing_extra) ... ok
test_case_ids_order_and_reuse_hit_miss (test_suite.SuiteTests.test_case_ids_order_and_reuse_hit_miss) ... ok
test_city_alias_is_exact_and_used_by_vision (test_suite.SuiteTests.test_city_alias_is_exact_and_used_by_vision) ... ok
test_designed_failure_remains_failed_and_reuse_skips_translation (test_suite.SuiteTests.test_designed_failure_remains_failed_and_reuse_skips_translation) ... ok
test_dom_route_uses_city_alias (test_suite.SuiteTests.test_dom_route_uses_city_alias) ... ok
test_layer_contract_positive_and_negative (test_suite.SuiteTests.test_layer_contract_positive_and_negative) ... ok
test_plan_route_check_accepts_only_declared_city_alias (test_suite.SuiteTests.test_plan_route_check_accepts_only_declared_city_alias) ... ok
test_three_cases_rejected_middle_continues_and_designed_status_stays_real (test_suite.SuiteTests.test_three_cases_rejected_middle_continues_and_designed_status_stays_real) ... ok
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
test_default_provider_runs_only_declared_checks_after_dom_pass (test_vision.VisionRunnerTests.test_default_provider_runs_only_declared_checks_after_dom_pass) ... ok
test_precedence_crop_reasons_and_cleanup (test_vision.VisionRunnerTests.test_precedence_crop_reasons_and_cleanup) ... ok
test_skip_vision_cli_continues_duration_but_never_passes (test_vision.VisionRunnerTests.test_skip_vision_cli_continues_duration_but_never_passes) ... ok
test_claude_native_image_and_output_budget (test_vision.VisionTests.test_claude_native_image_and_output_budget) ... ok
test_config_error_never_uses_glm_key (test_vision.VisionTests.test_config_error_never_uses_glm_key) ... ok
test_contract_change_stales_saved_plan (test_vision.VisionTests.test_contract_change_stales_saved_plan) ... ok
test_contract_rejects_invalid_or_missing_confidence_and_unknown_kind (test_vision.VisionTests.test_contract_rejects_invalid_or_missing_confidence_and_unknown_kind) ... ok
test_each_transport_error_code_is_safe_and_saved (test_vision.VisionTests.test_each_transport_error_code_is_safe_and_saved) ... ok
test_invalid_json_schema_and_skip_have_saved_response (test_vision.VisionTests.test_invalid_json_schema_and_skip_have_saved_response) ... ok
test_judgment_programming_error_is_internal_not_network (test_vision.VisionTests.test_judgment_programming_error_is_internal_not_network) ... ok
test_qualified_requirement_retains_country (test_vision.VisionTests.test_qualified_requirement_retains_country) ... ok
test_reason_rows_and_strict_rules (test_vision.VisionTests.test_reason_rows_and_strict_rules) ... ok
test_sdk_sends_image_and_records_usage (test_vision.VisionTests.test_sdk_sends_image_and_records_usage) ... ok
test_thinking_prefix_parsed_but_never_logged (test_vision.VisionTests.test_thinking_prefix_parsed_but_never_logged) ... ok
test_declared_targets_do_not_require_existing_locators (test_vocabulary.VocabularyTests.test_declared_targets_do_not_require_existing_locators) ... ok
test_loader_rejects_changed_vocabulary_and_unknown_saved_target (test_vocabulary.VocabularyTests.test_loader_rejects_changed_vocabulary_and_unknown_saved_target) ... ok
test_translator_receives_suite_catalog_and_hints (test_vocabulary.VocabularyTests.test_translator_receives_suite_catalog_and_hints) ... ok

----------------------------------------------------------------------
Ran 85 tests in 20.667s

OK
```

## Review (Claude, 2026-10-15), Parts A and B
Verified: 85 tests OK; the live suite summary, the OSM-002 rerun and the self-heal demo artifacts were inspected (no extra OSM visits).

**Part A: APPROVED.** The suite loop continues after a rejected case, `--reuse` relies on the loader's staleness checks,
`designed_outcome` is diagnostic only, the contract union works, and the aliases are exact. Live: OSM-003 PASSED (8 options,
Tracestrack Topo selected, cleanup PASSED); OSM-002 rerun **FAILED at step 5 (456 min)** with `route_geometry_verified=true`
(the München alias works). Both match the design. OSM-001 BLOCKED at vision confidence 0.85 < 0.90: see the user decision below.

**Part B: CHANGES REQUESTED (1 MUST, small).**

1. **MUST** `tools/healing.py` + `verification/checks.py:25` + `tools/dom.py:129`: **healing can hide a real application failure.**
   The `HealingResolver` is used for *every* resolve, including **check targets** and the **submit-effect target**.
   Scenario: OSM ignores Enter, so `route` (`#directions_route`) has 0 matches. That should be `SUBMIT_NO_EFFECT`, but instead
   it triggers a heal: the Planner proposes some other visible element containing "route"/"Directions", it matches once, and
   the step continues and may PASS. The same applies to a `visible` check on a missing element (the app is broken → a heal
   finds a lookalike → PASSED). This is the known risk of self-healing tests: they must never "heal away" the bug they are
   supposed to detect.
   Fix: **heal only targets of actions** (`perform` for click/fill/select/press). Resolutions for checks
   (`verify`), `submit_effect_target`, cleanup verification reads and `capture_map` must use the plain human/cache
   resolution with **no Planner call**, so a missing element stays BLOCKED/FAILED as before. (Using a cache entry for a
   check target is also off: a check should only use human-reviewed locators.) Tests: route never appears →
   `SUBMIT_NO_EFFECT` with the Planner not called; a `visible` check on a missing element → no heal, not PASSED;
   the action heal still works (layers control).
   > Codex: Fixed in `tools/healing.py` and `tools/dom.py`: default `resolve` now uses human-reviewed locators only; only action-target `resolve_action` can use cache/Planner. Existing `verify`, submit-effect resolution, cleanup verification reads and `capture_map` remain on the human-only path. Added four regressions in `tests/test_healing.py`, including cache lookalikes and a prior action heal; action healing/cache reuse still pass.

2. **NIT** `suite.py` `reusable_plan` globs `**/translation-*` over all artifacts, and gets slower as artifacts grow. Acceptable for now.

**User decision (OSM-001 vision threshold), not a code finding:** with the current blind pipeline, OSM-001 got 0.85 live.
Options: (a) keep 0.90, so OSM-001 is often BLOCKED ("unable to determine") and goes to human review; honest, but the demo shows
BLOCKED; (b) return to **0.85**. That was the user's own value *before* any calibration data (not chosen after seeing results),
and replay of the blind reports at 0.85 shows **0 false PASS on both frozen sets** (original: missed PASS 2/10; hold-out: 0).
The reviewer finds (b) defensible if it's stated as such in the report. Change it only in `contracts.json` + `revalidate`.

Commit: Parts A and B touch the same files, so commit them together **after** MUST 1 is fixed (a small change).

## Follow-up handoff (Codex, 2026-10-15) — Review MUST 1
### Goal
Prevent locator healing from replacing evidence that an application failed to produce (workflow 3 / verification).

### What changed
- `src/test_agent/tools/healing.py`: human-only default resolution; action-only cache/healing method. Clear previous resolution metadata before every observation so prior action healing cannot be reported as a successful check.
- `src/test_agent/tools/dom.py`: base action-resolution entry point; only click/fill/select/press targets in `perform` use it. Submission effects continue to use default resolution. `verification/checks.py`, cleanup verification reads and `capture_map` already call default resolution, so no call-site changes were needed there.
- `tests/test_healing.py`: updated positive coverage to exercise actual actions; new negative tests ensure missing visible checks ignore caches, prior healed actions cannot alter subsequent verification reads, missing routes remain SUBMIT_NO_EFFECT without a Planner call, and screenshot targets ignore caches/healing. Existing action/cache/ambiguity tests retained.
- README: Chinese explanation of action-only repair and human-only verification.

### Threshold decision and revalidation
The user explicitly selected **Keep 0.90** in this turn. Both route contracts already contain 0.90, so no contract or threshold edit was necessary. OSM-003 has no vision check. Revalidated all three saved plans through the existing `revalidate` command; each wrote a new VALIDATED artifact, without model/browser calls or modifying the original folders. This is plan validation, not a new application PASS verdict; OSM-001 may still be BLOCKED at confidence 0.85.

Revalidation command (one invocation per source folder below):
```sh
uv run python -m test_agent revalidate <existing-validated-case-folder>
```
Complete revalidation output:
```text
Case: OSM-001 Source: /Users/xuenilaw/Documents/myProject/WBS/artifacts/suite-20261015T084012127337Z/translation-20261015T084012171413Z/cases/OSM-001
{
  "status": "VALIDATED",
  "browser_executed": false,
  "model_called": false,
  "errors": [],
  "output_directory": "/Users/xuenilaw/Documents/myProject/WBS/artifacts/translation-20261015T090320482735Z/cases/OSM-001",
  "validation_scope": "schema, unchanged source coverage, current contract and vocabulary; not full semantic equivalence",
  "contract_applied": true,
  "vocabulary_applied": true
}
Case: OSM-002 Source: /Users/xuenilaw/Documents/myProject/WBS/artifacts/translation-20261015T084143589101Z/cases/OSM-002
{
  "status": "VALIDATED",
  "browser_executed": false,
  "model_called": false,
  "errors": [],
  "output_directory": "/Users/xuenilaw/Documents/myProject/WBS/artifacts/translation-20261015T090320506650Z/cases/OSM-002",
  "validation_scope": "schema, unchanged source coverage, current contract and vocabulary; not full semantic equivalence",
  "contract_applied": true,
  "vocabulary_applied": true
}
Case: OSM-003 Source: /Users/xuenilaw/Documents/myProject/WBS/artifacts/suite-20261015T084012127337Z/translation-20261015T084044092832Z/cases/OSM-003
{
  "status": "VALIDATED",
  "browser_executed": false,
  "model_called": false,
  "errors": [],
  "output_directory": "/Users/xuenilaw/Documents/myProject/WBS/artifacts/translation-20261015T090320524371Z/cases/OSM-003",
  "validation_scope": "schema, unchanged source coverage, current contract and vocabulary; not full semantic equivalence",
  "contract_applied": true,
  "vocabulary_applied": true
}
```

### How to verify
```sh
uv run python -m unittest discover -s tests -v
uv run python -m test_agent suite cases/osm/WBS_testcase1_osm.xlsx --locators cases/osm/locators.json --reuse --headed
```
The suite command is for the user's manual test; no additional OSM visits were made for this fix.

### Test output
Required command: `uv run python -m unittest discover -s tests -v` (UV_CACHE_DIR=/private/tmp/wbs-uv-cache; local Chromium).
```text
test_arithmetic_and_threshold_replay (test_calibration.CalibrationTests.test_arithmetic_and_threshold_replay) ... ok
test_bad_labels_rejected (test_calibration.CalibrationTests.test_bad_labels_rejected) ... ok
test_capture_excludes_overlay_and_never_overwrites_frozen_set (test_calibration.CalibrationTests.test_capture_excludes_overlay_and_never_overwrites_frozen_set) ... ok
test_offline_run_counts_error_and_saves_report (test_calibration.CalibrationTests.test_offline_run_counts_error_and_saves_report) ... ok
test_pure_decision_threshold_boundary_and_no_mutation (test_calibration.CalibrationTests.test_pure_decision_threshold_boundary_and_no_mutation) ... ok
test_absent_sidecar_does_not_apply_osm_project_contract (test_cli.PackageCliTests.test_absent_sidecar_does_not_apply_osm_project_contract) ... ok
test_case_id_cannot_escape_artifact_directory (test_cli.PackageCliTests.test_case_id_cannot_escape_artifact_directory) ... ok
test_explicit_missing_contract_path_rejected_before_model_call (test_cli.PackageCliTests.test_explicit_missing_contract_path_rejected_before_model_call) ... ok
test_invalid_plan_saves_rejection_without_approved_plan (test_cli.PackageCliTests.test_invalid_plan_saves_rejection_without_approved_plan) ... ok
test_malformed_contract_rejected_before_model_call (test_cli.PackageCliTests.test_malformed_contract_rejected_before_model_call) ... ok
test_malformed_vocabulary_rejected_before_model_call (test_cli.PackageCliTests.test_malformed_vocabulary_rejected_before_model_call) ... ok
test_missing_case_does_not_call_model (test_cli.PackageCliTests.test_missing_case_does_not_call_model) ... ok
test_package_entry_point_works_outside_project_directory (test_cli.PackageCliTests.test_package_entry_point_works_outside_project_directory) ... ok
test_removed_amendment_option_is_rejected (test_cli.PackageCliTests.test_removed_amendment_option_is_rejected) ... ok
test_sidecar_without_selected_case_reports_no_contract (test_cli.PackageCliTests.test_sidecar_without_selected_case_reports_no_contract) ... ok
test_translate_preserves_plan_and_writes_case_scoped_evidence (test_cli.PackageCliTests.test_translate_preserves_plan_and_writes_case_scoped_evidence) ... ok
test_unknown_action_check_and_cleanup_targets_rejected_during_translation (test_cli.PackageCliTests.test_unknown_action_check_and_cleanup_targets_rejected_during_translation) ... ok
test_ambiguous_locator_reports_count (test_executor.BrowserExecutorTests.test_ambiguous_locator_reports_count) ... ok
test_delayed_form_initialization_waits_before_filling (test_executor.BrowserExecutorTests.test_delayed_form_initialization_waits_before_filling) ... ok
test_duration_failure_and_cleanup (test_executor.BrowserExecutorTests.test_duration_failure_and_cleanup) ... ok
test_exact_three_hours_fails (test_executor.BrowserExecutorTests.test_exact_three_hours_fails) ... ok
test_form_not_ready_reports_lazy_fetch_http_status (test_executor.BrowserExecutorTests.test_form_not_ready_reports_lazy_fetch_http_status) ... ok
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
test_action_heal_cache_reuse_and_metadata (test_healing.HealingTests.test_action_heal_cache_reuse_and_metadata) ... ok
test_ambiguous_proposal_blocks_once_and_remaining_steps_not_run (test_healing.HealingTests.test_ambiguous_proposal_blocks_once_and_remaining_steps_not_run) ... ok
test_css_and_extra_fields_rejected_and_zero_match_blocked (test_healing.HealingTests.test_css_and_extra_fields_rejected_and_zero_match_blocked) ... ok
test_map_capture_ignores_cache_and_never_heals (test_healing.HealingTests.test_map_capture_ignores_cache_and_never_heals) ... ok
test_missing_visible_check_ignores_cache_and_never_heals (test_healing.HealingTests.test_missing_visible_check_ignores_cache_and_never_heals) ... ok
test_prior_action_heal_cannot_change_later_check_or_verification_read (test_healing.HealingTests.test_prior_action_heal_cannot_change_later_check_or_verification_read) ... ok
test_runner_action_heals_then_next_run_uses_cache (test_healing.HealingTests.test_runner_action_heals_then_next_run_uses_cache) ... ok
test_snapshot_truncated_and_provider_exception_sanitized (test_healing.HealingTests.test_snapshot_truncated_and_provider_exception_sanitized) ... ok
test_stale_cache_and_broken_human_locator_heal_again (test_healing.HealingTests.test_stale_cache_and_broken_human_locator_heal_again) ... ok
test_submit_no_effect_ignores_cache_and_never_heals (test_healing.HealingTests.test_submit_no_effect_ignores_cache_and_never_heals) ... ok
test_undeclared_and_ambiguous_human_targets_never_call_planner (test_healing.HealingTests.test_undeclared_and_ambiguous_human_targets_never_call_planner) ... ok
test_contract_only_change_new_validated_folder_old_untouched (test_revalidate.RevalidateTests.test_contract_only_change_new_validated_folder_old_untouched) ... ok
test_modified_plan_still_rejected_against_current_contract (test_revalidate.RevalidateTests.test_modified_plan_still_rejected_against_current_contract) ... ok
test_workbook_change_rejected_without_approved_plan (test_revalidate.RevalidateTests.test_workbook_change_rejected_without_approved_plan) ... ok
test_layer_selected_cleanup_and_options_missing_extra (test_suite.LayerBrowserTests.test_layer_selected_cleanup_and_options_missing_extra) ... ok
test_case_ids_order_and_reuse_hit_miss (test_suite.SuiteTests.test_case_ids_order_and_reuse_hit_miss) ... ok
test_city_alias_is_exact_and_used_by_vision (test_suite.SuiteTests.test_city_alias_is_exact_and_used_by_vision) ... ok
test_designed_failure_remains_failed_and_reuse_skips_translation (test_suite.SuiteTests.test_designed_failure_remains_failed_and_reuse_skips_translation) ... ok
test_dom_route_uses_city_alias (test_suite.SuiteTests.test_dom_route_uses_city_alias) ... ok
test_layer_contract_positive_and_negative (test_suite.SuiteTests.test_layer_contract_positive_and_negative) ... ok
test_plan_route_check_accepts_only_declared_city_alias (test_suite.SuiteTests.test_plan_route_check_accepts_only_declared_city_alias) ... ok
test_three_cases_rejected_middle_continues_and_designed_status_stays_real (test_suite.SuiteTests.test_three_cases_rejected_middle_continues_and_designed_status_stays_real) ... ok
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
test_default_provider_runs_only_declared_checks_after_dom_pass (test_vision.VisionRunnerTests.test_default_provider_runs_only_declared_checks_after_dom_pass) ... ok
test_precedence_crop_reasons_and_cleanup (test_vision.VisionRunnerTests.test_precedence_crop_reasons_and_cleanup) ... ok
test_skip_vision_cli_continues_duration_but_never_passes (test_vision.VisionRunnerTests.test_skip_vision_cli_continues_duration_but_never_passes) ... ok
test_claude_native_image_and_output_budget (test_vision.VisionTests.test_claude_native_image_and_output_budget) ... ok
test_config_error_never_uses_glm_key (test_vision.VisionTests.test_config_error_never_uses_glm_key) ... ok
test_contract_change_stales_saved_plan (test_vision.VisionTests.test_contract_change_stales_saved_plan) ... ok
test_contract_rejects_invalid_or_missing_confidence_and_unknown_kind (test_vision.VisionTests.test_contract_rejects_invalid_or_missing_confidence_and_unknown_kind) ... ok
test_each_transport_error_code_is_safe_and_saved (test_vision.VisionTests.test_each_transport_error_code_is_safe_and_saved) ... ok
test_invalid_json_schema_and_skip_have_saved_response (test_vision.VisionTests.test_invalid_json_schema_and_skip_have_saved_response) ... ok
test_judgment_programming_error_is_internal_not_network (test_vision.VisionTests.test_judgment_programming_error_is_internal_not_network) ... ok
test_qualified_requirement_retains_country (test_vision.VisionTests.test_qualified_requirement_retains_country) ... ok
test_reason_rows_and_strict_rules (test_vision.VisionTests.test_reason_rows_and_strict_rules) ... ok
test_sdk_sends_image_and_records_usage (test_vision.VisionTests.test_sdk_sends_image_and_records_usage) ... ok
test_thinking_prefix_parsed_but_never_logged (test_vision.VisionTests.test_thinking_prefix_parsed_but_never_logged) ... ok
test_declared_targets_do_not_require_existing_locators (test_vocabulary.VocabularyTests.test_declared_targets_do_not_require_existing_locators) ... ok
test_loader_rejects_changed_vocabulary_and_unknown_saved_target (test_vocabulary.VocabularyTests.test_loader_rejects_changed_vocabulary_and_unknown_saved_target) ... ok
test_translator_receives_suite_catalog_and_hints (test_vocabulary.VocabularyTests.test_translator_receives_suite_catalog_and_hints) ... ok

----------------------------------------------------------------------
Ran 89 tests in 23.213s

OK
```

### Known limitations / open questions
Only action targets can use machine locators, including cleanup actions. A healed action does not authorize the same locator for subsequent assertions: those still require human-reviewed configuration. Full semantic correctness of an action proposal remains subject to subsequent assertions/review. Threshold remains 0.90 by explicit user choice; the prior OSM-001 vision block is not claimed resolved. NIT 2 (artifact glob growth) remains deferred as accepted in review. No commits or pushes performed; ready for Claude re-review.

## Re-review (Claude, 2026-10-15)
Verdict: **APPROVED. Commit Parts A and B together and push.**
Verified: 89 tests OK. Wiring checked: `perform()` is the only caller of `resolve_action` (heal + cache); `resolve()` is
human-only and used by checks (`checks.py:25,65,66`), the submit effect (`dom.py:133`), `capture_map` and cleanup reads
(`runner.py:157`). A missing route after Enter stays `SUBMIT_NO_EFFECT` with no Planner call (test added). Threshold 0.90
kept by the user; the 3 plans were revalidated by command (no model/browser). MUST 1 is resolved; NIT 2 is deferred as agreed.
