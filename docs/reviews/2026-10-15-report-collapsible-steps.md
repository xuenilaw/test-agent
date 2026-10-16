# Task: collapsible steps in the HTML report
Status: APPROVED
Workflow step(s): 7 (HTML report), presentation polish
Assigned: Codex · Reviewer: Claude · Brief written 2026-10-15

## Why
The user finds the report still too long: when a case is expanded, every step is shown at once with its tables and screenshot.
The user wants one line per step, and details only on click.

## Change (`src/test_agent/reporting.py` only, plus tests and the README display note)
1. Inside an expanded case, render **each step as its own `<details>` element, collapsed by default** (no `open` attribute).
   The `<summary>` line is exactly:
   `Step <n> – <source action text, one line, truncated to ~100 chars with …> <STATUS badge>`
   e.g. `Step 4 – Enter Hamburg as the starting point and Berlin as the destination… PASSED`.
   - Keep the existing badge styles, including `PASSED (borderline)`.
   - For a **non-PASSED** step (FAILED / BLOCKED / NOT_RUN), append the short reason after the badge on the same line, truncated to
     ~120 chars, e.g. `Step 5 – Observe or check the ETA FAILED · Duration 456 minutes is not less than 180 minutes`. This is display only.
2. Everything currently shown for a step (expected text, action/check table, Clef probabilities, Technical details, screenshot) moves **inside**
   that step's `<details>`, unchanged.
3. **Cleanup** becomes one collapsed `<details>` too: `Cleanup – <n> actions <status>`.
4. The "What happened" summary, page-type note, case overview table and case-level `<details>` stay as they are.
5. Escape the summary text like everything else (the source text comes from Excel).
6. No JavaScript; no change to any result data, status or threshold.

## Tests
- Each step and the cleanup render as a `<details>` without `open`; the summary contains the step number, the (escaped) action text and the status word.
- A non-PASSED step summary contains the truncated reason; a PASSED one doesn't.
- A long action text is truncated with `…`; a malicious string in the action text is escaped.

## Verification
Regenerate the existing repeat report and its 3 child suite reports with `report` (no OSM/model calls). Attach one rendering screenshot of an expanded
case with all steps collapsed, and one with a single step opened. Full test suite output. Hand off without committing.

---

## Handoff (Codex)

### Goal
Make expanded cases easy to scan, with one collapsed disclosure per step and Cleanup. Workflow step 7; presentation only.

### What changed
- `src/test_agent/reporting.py`: each step now has a native `<details class="step">` with no `open` attribute. Summary is `Step n – <action> <status>`; whitespace is normalized and actions are shortened to at most 100 characters including `…`. Non-PASSED steps append a reason of at most 120 characters including `…`. Summary text is escaped after truncation. PASSED steps omit reasons from their summary, while full reasons remain inside.
- Existing source/expected tables, action/check tables, technical JSON, vision evidence and screenshots remain inside the matching step. A passing step containing a borderline passing check also displays the existing yellow PASSED (borderline) badge; saved step/check statuses are untouched.
- Cleanup is a collapsed `<details class="cleanup">` summarizing its action count and aggregate display status. FAILED takes priority over BLOCKED, then NOT_RUN; all successful actions display PASSED. No actions displays NOT_RUN. This aggregation does not write result data.
- `tests/test_day6.py`: two tests verify actual parsed HTML disclosure attributes, exact summary text for PASSED/FAILED/BLOCKED/NOT_RUN, whitespace normalization, truncation, malicious text escaping, omitted passing reasons, borderline badge, cleanup failure/empty states, retained evidence and unchanged result bytes.
- `README.md`: documented collapsed steps and cleanup. Top summary, page-type note, overview and case-level disclosures retain their prior behavior. No JavaScript added.

### How to verify
```sh
uv run python -m unittest discover -s tests -v
uv run python -m test_agent report artifacts/repeat-20261015T120006438910Z
# Repeat the report command for each existing suite-* child directory.
```
Regenerated the existing repeat report and all three child suite reports with `report`, without OSM or model calls. SHA-256 comparison confirmed all 69 pre-existing JSON files in that repeat folder were unchanged.

Offline Chromium inspection confirmed a case has five steps, all initially closed, plus closed Cleanup. Clicking step 4 opens exactly that step; Cleanup stays closed. 0 HTTP requests; document width 1280 equals viewport width 1280.

Rendering evidence (in `artifacts/repeat-20261015T120006438910Z/`):
- Expanded case, all steps collapsed: [collapsible-steps-closed.png](../../artifacts/repeat-20261015T120006438910Z/collapsible-steps-closed.png)
- Single step opened: [collapsible-step-open.png](../../artifacts/repeat-20261015T120006438910Z/collapsible-step-open.png)
- Machine-readable render checks: `collapsible-render-check.json`.

### Known limitations / open questions
Long summaries can wrap on narrow screens; their text is normalized to one line and shortened before HTML escaping. Full source text remains available inside the step. Cleanup status and borderline step labels are display-only. No status, threshold or execution behavior changed. No commit or push made.

### Test output
```text
test_arithmetic_and_threshold_replay (test_calibration.CalibrationTests.test_arithmetic_and_threshold_replay) ... ok
test_bad_labels_rejected (test_calibration.CalibrationTests.test_bad_labels_rejected) ... ok
test_capture_excludes_overlay_and_never_overwrites_frozen_set (test_calibration.CalibrationTests.test_capture_excludes_overlay_and_never_overwrites_frozen_set) ... ok
test_offline_run_counts_error_and_saves_report (test_calibration.CalibrationTests.test_offline_run_counts_error_and_saves_report) ... correct.png 1/2: PASSED
correct.png 2/2: BLOCKED
wrong.png 1/2: FAILED
wrong.png 2/2: FAILED
ok
test_pure_decision_threshold_boundary_and_no_mutation (test_calibration.CalibrationTests.test_pure_decision_threshold_boundary_and_no_mutation) ... ok
test_http_status_only_no_error_body_and_no_retry (test_clef_smoke.ClefSmokeTests.test_http_status_only_no_error_body_and_no_retry) ... ok
test_missing_key_blocks_without_request_and_saves_safe_output (test_clef_smoke.ClefSmokeTests.test_missing_key_blocks_without_request_and_saves_safe_output) ... ok
test_text_only_decisions_request_shape_and_metadata (test_clef_smoke.ClefSmokeTests.test_text_only_decisions_request_shape_and_metadata) ... ok
test_unknown_choice_or_missing_probabilities_rejected (test_clef_smoke.ClefSmokeTests.test_unknown_choice_or_missing_probabilities_rejected) ... ok
test_claude_uses_exact_jpeg_without_prompt_change (test_clef_vision.ClefVisionTests.test_claude_uses_exact_jpeg_without_prompt_change) ... ok
test_frozen_jpeg_integrity_calibration_and_no_overwrite (test_clef_vision.ClefVisionTests.test_frozen_jpeg_integrity_calibration_and_no_overwrite) ... hamburg-berlin.png 1/1: PASSED
ok
test_probability_decisions_and_threshold_replay (test_clef_vision.ClefVisionTests.test_probability_decisions_and_threshold_replay) ... ok
test_request_shape_and_evidence_exact_jpeg (test_clef_vision.ClefVisionTests.test_request_shape_and_evidence_exact_jpeg) ... ok
test_unknown_option_is_schema_and_click_refused (test_clef_vision.ClefVisionTests.test_unknown_option_is_schema_and_click_refused) ... ok
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
test_cost_and_cohort_alignment (test_comparison.ComparisonTests.test_cost_and_cohort_alignment) ... ok
test_different_jpeg_bytes_cannot_be_claimed_same_input (test_comparison.ComparisonTests.test_different_jpeg_bytes_cannot_be_claimed_same_input) ... ok
test_already_visible_effect_or_noncoordinate_provider_blocks (test_day5.FaultBrowserTests.test_already_visible_effect_or_noncoordinate_provider_blocks) ... ok
test_blank_tiles_unclear_blocks_but_duration_still_runs (test_day5.FaultBrowserTests.test_blank_tiles_unclear_blocks_but_duration_still_runs) ... ok
test_broken_locator_uses_private_cache_even_if_shared_cache_exists (test_day5.FaultBrowserTests.test_broken_locator_uses_private_cache_even_if_shared_cache_exists) ... ok
test_click_without_effect_blocks_and_does_not_retry (test_day5.FaultBrowserTests.test_click_without_effect_blocks_and_does_not_retry) ... ok
test_directions_503_stops_steps_and_does_not_call_vision (test_day5.FaultBrowserTests.test_directions_503_stops_steps_and_does_not_call_vision) ... ok
test_forced_vision_click_passes_with_effect_and_evidence (test_day5.FaultBrowserTests.test_forced_vision_click_passes_with_effect_and_evidence) ... ok
test_missing_declaration_or_human_effect_forbids_fallback (test_day5.FaultBrowserTests.test_missing_declaration_or_human_effect_forbids_fallback) ... ok
test_normal_resolution_then_failed_heal_can_fall_back_once (test_day5.FaultBrowserTests.test_normal_resolution_then_failed_heal_can_fall_back_once) ... ok
test_rejected_points_never_click (test_day5.FaultBrowserTests.test_rejected_points_never_click) ... ok
test_successful_human_action_never_uses_vision_and_missing_check_never_falls_back (test_day5.FaultBrowserTests.test_successful_human_action_never_uses_vision_and_missing_check_never_falls_back) ... ok
test_check_only_or_undeclared_target_rejected (test_day5.FaultInputTests.test_check_only_or_undeclared_target_rejected) ... ok
test_claude_coordinate_request_has_resize_guard_and_no_expected_values (test_day5.FaultInputTests.test_claude_coordinate_request_has_resize_guard_and_no_expected_values) ... ok
test_interception_exact_hosts_methods_and_tile_subdomains (test_day5.FaultInputTests.test_interception_exact_hosts_methods_and_tile_subdomains) ... ok
test_nonclick_actions_never_invoke_vision_fallback (test_day5.FaultInputTests.test_nonclick_actions_never_invoke_vision_fallback) ... ok
test_suite_preflights_faults_and_only_injects_matching_cases (test_day5.FaultInputTests.test_suite_preflights_faults_and_only_injects_matching_cases) ... ok
test_unknown_fault_exit_two_before_browser (test_day5.FaultInputTests.test_unknown_fault_exit_two_before_browser) ... ok
test_borderline_pass_is_display_only_and_readable_numbers_remain (test_day6.Day6Tests.test_borderline_pass_is_display_only_and_readable_numbers_remain) ... ok
test_clef_route_configuration_uses_separate_claude_for_clicks (test_day6.Day6Tests.test_clef_route_configuration_uses_separate_claude_for_clicks) ... ok
test_collapsed_step_keeps_borderline_badge_and_cleanup_empty_is_not_run (test_day6.Day6Tests.test_collapsed_step_keeps_borderline_badge_and_cleanup_empty_is_not_run) ... ok
test_missing_provider_entry_rejects_before_browser (test_day6.Day6Tests.test_missing_provider_entry_rejects_before_browser) ... ok
test_missing_screenshot_or_outside_asset_does_not_break_or_link_report (test_day6.Day6Tests.test_missing_screenshot_or_outside_asset_does_not_break_or_link_report) ... ok
test_per_provider_thresholds_validate_without_hidden_default (test_day6.Day6Tests.test_per_provider_thresholds_validate_without_hidden_default) ... ok
test_readability_summary_page_type_and_human_formatting (test_day6.Day6Tests.test_readability_summary_page_type_and_human_formatting) ... ok
test_repeat_analysis_reports_status_and_step_differences_and_probability_spread (test_day6.Day6Tests.test_repeat_analysis_reports_status_and_step_differences_and_probability_spread) ... ok
test_repeat_never_translates_and_writes_html_json (test_day6.Day6Tests.test_repeat_never_translates_and_writes_html_json) ... Executing <Task finished name='Task-359' coro=<Day6Tests.test_repeat_never_translates_and_writes_html_json() done, defined at /Users/xuenilaw/Documents/myProject/WBS/tests/test_day6.py:255> result=None created at /opt/homebrew/Cellar/python@3.14/3.14.8/Frameworks/Python.framework/Versions/3.14/lib/python3.14/asyncio/runners.py:110> took 0.225 seconds
ok
test_report_escapes_all_untrusted_text_and_embeds_offline_thumbnails (test_day6.Day6Tests.test_report_escapes_all_untrusted_text_and_embeds_offline_thumbnails) ... ok
test_saved_clef_replay_point85_zero_false_and_missed_pass_both_sets (test_day6.Day6Tests.test_saved_clef_replay_point85_zero_false_and_missed_pass_both_sets) ... ok
test_steps_and_cleanup_are_collapsed_with_safe_short_summaries (test_day6.Day6Tests.test_steps_and_cleanup_are_collapsed_with_safe_short_summaries) ... ok
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
Ran 128 tests in 34.249s

OK
```

`git diff --check`: clean. Ready for Claude review; no commit.

## Review (Claude, 2026-10-15)
Verdict: **APPROVED. Commit and push.** Verified: tests OK; `collapsible-steps-closed.png` shows one line per step ("Step n – action STATUS",
borderline badge on step 4) and a collapsed Cleanup; no result data changed (Codex's SHA-256 check).
Note for the user (not a code issue): the user's own runs (`suite-20261015T205727…`, `repeat-20261015T210458…`, etc.) used **anthropic /
claude-haiku-5-5 / 0.9**, because the local `.env` still selects Claude. Only Codex's `repeat-20261015T120006…` used Clef, through a one-off
command-line override. To use Clef by default, the user changes `VISION_PROVIDER=clef` and `VISION_MODEL=cloudflare/clef` in `.env`.
