# Translator canonical target vocabulary
Status: APPROVED
Workflow step(s): 1b Translate (Executor review SHOULD 3)

## Handoff (Codex)
### Goal
Give the Translator known target names and reject naming mismatches during translation.
The approved Executor baseline was committed/pushed first as `dd60cda`.
This vocabulary change is separate and uncommitted for review.

### What changed
- `cases/osm/vocabulary.json`: canonical target names, semantic descriptions and suite-specific hints.
  Independent of locator entries so declared targets may later be resolved by a Planner.
- `schemas/vocabulary.py`: strict TargetVocabulary schema; malformed configuration fails before the model call.
- `translation/translator.py`: receives catalog/hints; instructs exact canonical names for all actions,
  checks and cleanup. OSM-specific prompt controls moved to suite hints.
- `translation/validator.py`: optional known-target validation; UNKNOWN_TARGET rejects undeclared names.
  A runtime alias such as route duration is intentionally rejected in a newly translated plan.
- `cli.py`: discovers vocabulary.json beside the workbook, supports --vocabulary, passes vocabulary to GLM,
  saves the vocabulary/path snapshot, reports vocabulary_applied and retains rejected candidates.
- `plan_loader.py`: revalidates vocabulary consistency and saved targets before browser launch for new artifacts.
  Legacy artifacts without vocabulary metadata retain their old behavior.
- `tests/`: model input payload, canonical-name success, unknown action/check/cleanup targets, invalid vocabulary,
  loader rejection of altered vocabulary/targets, and independence from DOM mappings.
- `tests/fixtures/osm_translation.json`: reviewed reference plan now uses canonical selected-check target.
- `README.md`: documents new configuration and the distinction between UNKNOWN_TARGET and NO_LOCATOR.

### How to verify
```sh
uv run python -m unittest discover -s tests -v
uv run python -m test_agent translate cases/osm/WBS_testcase1_osm.xlsx
uv run python -m test_agent run artifacts/translation-20261014T093803952939Z/cases/OSM-001 --locators cases/osm/locators.json --headed
```
Only the optional translation command uses GLM. The unit tests use mocks/fixtures, intercept browser traffic,
and require the same installed project Chromium as the Executor tests.

### Test output
Required full suite run with writable UV_CACHE_DIR and macOS browser process access:
```text
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
test_declared_targets_do_not_require_existing_locators (test_vocabulary.VocabularyTests.test_declared_targets_do_not_require_existing_locators) ... ok
test_loader_rejects_changed_vocabulary_and_unknown_saved_target (test_vocabulary.VocabularyTests.test_loader_rejects_changed_vocabulary_and_unknown_saved_target) ... ok
test_translator_receives_suite_catalog_and_hints (test_vocabulary.VocabularyTests.test_translator_receives_suite_catalog_and_hints) ... ok

----------------------------------------------------------------------
Ran 47 tests in 7.806s

OK
```
Also verified help, compilation, and `git diff --check`.

### Live translation verification
GLM returned VALIDATED with contract_applied=true and vocabulary_applied=true; browser_executed=false.
Every action/check/cleanup target uses a declared canonical name. Step 5 uses estimated journey duration,
operator less_than and limit 180. No automatic rename, plan repair, or browser execution took place.
Evidence: `artifacts/translation-20261014T093803952939Z/cases/OSM-001/`.

### Known limitations / open questions
- No vocabulary file means optional name checks are skipped and vocabulary_applied=false is explicit.
- Name validity does not prove semantic equivalence or that a locator works on the current DOM.
- The target catalog is independent of locator mappings. A declared target may still be NO_LOCATOR at runtime;
  future Planner work can handle that gap. This task catches undeclared naming, not locator discovery.
- Runtime aliases and older plans remain compatible; retranslation enables the new checks.
- OSM route contract checks still use their original field semantics; no generic contract-language redesign.
- No Planner or Vision added. Recommend D1 vision verification next to address route_geometry_verified=false,
  after this task's review.
- No commit/push for the vocabulary change. The Executor baseline alone was pushed as requested.

## Review round 1 (Claude, 2026-10-14)
Verdict: APPROVED. Ready for the user to commit and push.
Verified:
- `uv run python -m unittest discover -s tests` → 47 tests OK.
- Codex's live translation `translation-20261014T093803952939Z`: VALIDATED, contract_applied and
  vocabulary_applied true, and all 8 targets used are canonical vocabulary keys.
- End-to-end: the reviewer ran that new plan once on live OSM → **PASSED**, all 5 steps (`2:56` → 176 min).
  So the vocabulary names and `locators.json` fit together.

Good design choices: the vocabulary (what the Translator may say) is kept separate from the locators
(how the Executor finds it), so the future Planner can fill NO_LOCATOR gaps without touching the
vocabulary. UNKNOWN_TARGET (wrong name, caught at translation time) and NO_LOCATOR (known name, not yet
mapped, caught at run time) are now distinct, machine-readable failures. The loader rejects plans whose
vocabulary changed after translation. The OSM-specific prompt lines moved into suite hints.

NITs (no action needed now):
- `translator.py` INSTRUCTIONS still contain suite-specific rules ("under 3 hours … 180", `route_connects`).
  Move them to hints when a second suite exists.
- No check that the contract's target names (`visible_fields`; the validator's hard-coded
  `"starting-point field"` / `"destination field"`) exist in the vocabulary. Renaming a vocabulary key would
  produce confusing contract errors. Add a load-time subset check with the contract-language redesign.
- Planner task (C): add a `run` pre-flight that lists vocabulary targets with no locator **before** launching
  the browser. That list is exactly the Planner's work queue.
