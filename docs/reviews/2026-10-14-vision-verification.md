# D1: screenshot route verification
Status: APPROVED
Workflow step(s): 4 Verify (vision)

## Handoff (Codex, initial baseline; superseded by V1–V5 below)
### Goal
Judge the visible route line and endpoints after the DOM route check. User chose Claude API first after considering GLM; Clef comparison comes later.

### What changed
- `src/test_agent/verification/vision.py`: provider protocol, Claude native Messages transport, optional GLM-compatible transport, strict observation schema, local verdict rules, saved evidence.
- `src/test_agent/runner.py`: optional injected provider; capture screenshot before cleanup, append route_geometry check, stop on visual failure/block, set geometry flag only on visual PASS.
- `src/test_agent/cli.py`: opt-in `--vision`, load local credentials, fail configuration before launch.
- `.env.example`: separate vision provider/model/key settings; never reuse GLM key for native Claude.
- `tests/test_vision.py`: offline adapter payload, malformed output, unsupported match, uncertainty, provider failure, browser evidence and cleanup tests.
- `README.md`: commands, architecture, evidence and limitations.

### How to verify
```bash
uv run python -m unittest discover -s tests -v
# Configure VISION_PROVIDER=anthropic, VISION_MODEL and ANTHROPIC_API_KEY locally first.
uv run python -m test_agent run artifacts/translation-20261014T093803952939Z/cases/OSM-001 --locators cases/osm/locators.json --headed --vision
```
Expected visual mismatch: FAILED at step 4, step 5 NOT_RUN, cleanup attempted.
Uncertain/invalid/provider error: BLOCKED, never silently passes.
Without --vision: existing deterministic run, geometry flag false.
With visual PASS but duration >=180: geometry flag true, overall FAILED.
Evidence: screenshots/route-4-0.png and vision/step-4-0/{request,response,verdict}.json.

### Known limitations / open questions
- Initial handoff lacked credentials; now one positive live OSM run passed with the user-configured Claude model (see follow-up below). Wrong/ambiguous live image calibration remains pending; offline tests do not measure model accuracy.
- Must calibrate correct/wrong/ambiguous screenshots before treating this as a reliable verifier. Self-reported confidence >=0.9 is an experimental threshold, not measured 90% accuracy. Unsupported match blocks.
- Screenshot may capture loading/unclear map tiles; expected behavior is uncertainty/BLOCKED. No retry or weakening of requirements.
- Visual PASS is a model judgment, not a coordinate/topological proof. The model must identify map endpoints and a continuous route, not merely sidebar field values.
- Claude uses a fixed official endpoint and standard-library HTTP transport (60-second timeout); GLM uses existing OpenAI SDK dependency. Neither retries automatically. Provider errors log only exception class to avoid exposing credential-bearing errors.
- Raw returned content is saved, schema checked locally; no tools, no SDK Agent loop needed for a single visual judgment.
- Records provider/model/requested model, latency and usage. No price assumptions. Clef adapter and fair repeated latency/cost/accuracy comparison deferred until account ready.
- Changes remain uncommitted for Claude review. Approved vocabulary change was already committed/pushed separately as c636018.
- Official references: [Claude vision](https://platform.claude.com/docs/en/build-with-claude/vision), [Messages API](https://platform.claude.com/docs/en/api/messages/create), [GLM-4.6V](https://docs.z.ai/guides/vlm/glm-4.6v), [OpenAI-compatible image content](https://developers.openai.com/api/reference/python/resources/chat/subresources/completions/methods/create).

### Test output
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
test_visual_verdict_controls_case_and_preserves_cleanup (test_vision.VisionRunnerTests.test_visual_verdict_controls_case_and_preserves_cleanup) ... ok
test_claude_never_uses_glm_key (test_vision.VisionTests.test_claude_never_uses_glm_key) ... ok
test_claude_sends_native_image_and_rejects_truncation (test_vision.VisionTests.test_claude_sends_native_image_and_rejects_truncation) ... ok
test_config_requires_explicit_vision_model (test_vision.VisionTests.test_config_requires_explicit_vision_model) ... ok
test_provider_error_and_bad_json_are_blocked_without_secret (test_vision.VisionTests.test_provider_error_and_bad_json_are_blocked_without_secret) ... ok
test_rules_reject_uncertainty_and_unsupported_match (test_vision.VisionTests.test_rules_reject_uncertainty_and_unsupported_match) ... ok
test_sdk_sends_image_and_records_usage (test_vision.VisionTests.test_sdk_sends_image_and_records_usage) ... ok
test_declared_targets_do_not_require_existing_locators (test_vocabulary.VocabularyTests.test_declared_targets_do_not_require_existing_locators) ... ok
test_loader_rejects_changed_vocabulary_and_unknown_saved_target (test_vocabulary.VocabularyTests.test_loader_rejects_changed_vocabulary_and_unknown_saved_target) ... ok
test_translator_receives_suite_catalog_and_hints (test_vocabulary.VocabularyTests.test_translator_receives_suite_catalog_and_hints) ... ok

----------------------------------------------------------------------
Ran 54 tests in 10.142s

OK
```

## Live-run follow-up (Codex, 2026-10-14)
User run `run-20261014T113710819314Z` reached Claude successfully: match, confidence 0.95, latency 2389ms, input/output tokens 1985/239. Python incorrectly blocked because observed city labels included country qualifiers (`Hamburg, Germany`, `Berlin, Germany`) while contract requirements were city-only.

Fixed `verification/vision.py`: compare complete city token before comma for city-only requirements; country-qualified requirements retain full comparison. No substring/fuzzy matching. Geometry flags and confidence threshold unchanged. Tests include qualified city PASS, Bremen/near-name/swapped-city BLOCKED, and preserving explicit country requirements. README documents the scope; country ambiguity cannot be resolved by a city-only contract.

One new live run `run-20261014T114118216097Z`: PASSED, route_geometry_verified=true, visual latency 2035ms, input/output tokens 1985/237, duration 2:56 =176 minutes <180. Original user run unchanged. This is positive-image evidence, not completed wrong/ambiguous-image calibration. No commits made.

### Updated required test output
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
test_visual_verdict_controls_case_and_preserves_cleanup (test_vision.VisionRunnerTests.test_visual_verdict_controls_case_and_preserves_cleanup) ... ok
test_claude_never_uses_glm_key (test_vision.VisionTests.test_claude_never_uses_glm_key) ... ok
test_claude_sends_native_image_and_rejects_truncation (test_vision.VisionTests.test_claude_sends_native_image_and_rejects_truncation) ... ok
test_config_requires_explicit_vision_model (test_vision.VisionTests.test_config_requires_explicit_vision_model) ... ok
test_provider_error_and_bad_json_are_blocked_without_secret (test_vision.VisionTests.test_provider_error_and_bad_json_are_blocked_without_secret) ... ok
test_qualified_requirement_retains_country (test_vision.VisionTests.test_qualified_requirement_retains_country) ... ok
test_rules_reject_uncertainty_and_unsupported_match (test_vision.VisionTests.test_rules_reject_uncertainty_and_unsupported_match) ... ok
test_sdk_sends_image_and_records_usage (test_vision.VisionTests.test_sdk_sends_image_and_records_usage) ... ok
test_declared_targets_do_not_require_existing_locators (test_vocabulary.VocabularyTests.test_declared_targets_do_not_require_existing_locators) ... ok
test_loader_rejects_changed_vocabulary_and_unknown_saved_target (test_vocabulary.VocabularyTests.test_loader_rejects_changed_vocabulary_and_unknown_saved_target) ... ok
test_translator_receives_suite_catalog_and_hints (test_vocabulary.VocabularyTests.test_translator_receives_suite_catalog_and_hints) ... ok

----------------------------------------------------------------------
Ran 55 tests in 9.591s

OK
```

## Review round 1 (Claude, 2026-10-14)
Verdict: CHANGES REQUESTED (1 MUST, small). The overall design is good.
Verified:
- `uv run python -m unittest discover -s tests` → 55 tests OK.
- The user's 3 vision runs: `113710` BLOCKED (city-qualifier bug, fixed since), `114118` PASSED,
  `120010` BLOCKED `Vision unavailable or invalid response: ValueError`, with **no `response.json`**.
- Reviewer probe (same `.env`, same `route-4-0.png` from `120010`, 1 provider call + 1 full
  `verify_route_image`): `stop_reason=end_turn`, single text block, verdict match 0.93 → **PASSED**.
  So `120010` was a transient failure inside `ClaudeVision.observe`, and the evidence doesn't show which one.

What's good: Python decides the verdict, not the model; uncertain/invalid output blocks and never passes;
a mismatch FAILS only above the threshold; evidence (request/response/verdict, sha256, usage, latency) is saved;
provider errors don't leak credentials; vision is opt-in (`--vision`), and the deterministic run is unchanged.

1. **MUST** `verification/vision.py` (`except Exception` → `type(exc).__name__`): failures can't be
   diagnosed. `ValueError` covers at least 4 different causes: `Incomplete vision response`
   (stop_reason ≠ end_turn, e.g. `max_tokens`/`refusal`), `Expected a single text observation`,
   `JSONDecodeError` (non-JSON body), and pydantic `ValidationError` (which subclasses ValueError).
   Network/HTTP errors are a different class again. Fix:
   - Raise a small `VisionError(code, **safe_details)` from your own checks, with codes such as `INCOMPLETE`
     (+ `stop_reason`), `NOT_SINGLE_TEXT` (+ block types), `HTTP` (+ status code only), `TIMEOUT`,
     `INVALID_JSON`, `SCHEMA`.
   - Write `response.json` with the safe metadata (stop_reason, block types, usage, HTTP status) **even
     when the call fails**. Still never write exception strings from the HTTP layer.
   - Tests: one per code, using fake transports.
   > Codex: Superseded by the user-approved V1–V5 brief; implemented in the follow-up handoff below. Safe VisionError codes and failure response.json are covered by offline fake transports.

2. **QUESTION for the user → then SHOULD**, `runner.py`: a vision BLOCKED stops the case, so step 5
   (deterministic duration) never runs. This is why the user experiences "always stuck at step 4": any
   transient provider hiccup hides the rest of the test. Proposal:
   - vision **FAILED** (confident mismatch) → stop the case, as now (the app is wrong);
   - vision **BLOCKED** (provider/uncertain) → record it, **continue** the remaining steps, and the final
     case status is BLOCKED with reason `VISION_UNAVAILABLE`/`VISION_INCONCLUSIVE`. Deterministic
     results are still collected, and the case still can't be PASSED.
   Implement after the user confirms.
   > Codex: User confirmed continuation in V4; implemented with FAILED > BLOCKED > PASSED precedence and combined reasons.

3. **SHOULD** `runner.py` screenshot input: send **only the map area** (`page.locator("#map").screenshot()`),
   not the full page. Both live responses cite the sidebar ("The sidebar fields read 'Hamburg, Germany'"),
   and `observed_origin` uses the exact sidebar text format. The prompt forbids relying on the sidebar, but
   the model still reads it, so the "geometry" verdict is partly a text-reading check. Cropping makes the
   vision check independent of the DOM check it is meant to complement. Keep the full screenshot as evidence.
   > Codex: Implemented V5 through the vision map locator-file entry; full-page and map image paths are retained.

4. **SHOULD** (can be the next task) Calibration: everything so far is positive images. Before the WBS
   report claims anything about accuracy, build a small labelled set (e.g. `cases/osm/vision_calibration/`):
   correct Hamburg→Berlin, wrong destination (Hamburg→Munich), swapped direction, empty map/no route,
   tiles still loading. Then add a command that runs each image N times and reports pass/fail/blocked
   counts, latency and tokens. This is also the fair basis for the later Claude vs. Clef comparison.
   > Codex: Deferred as allowed by the follow-up brief. Two positive live map-only runs are recorded below; labelled wrong/reversed/empty/loading calibration remains pending.

5. **NIT** `ClaudeVision` uses `urllib` instead of the official `anthropic` SDK. That's acceptable (one fewer
   dependency), but the SDK gives typed errors (`APIStatusError.status_code`, `APITimeoutError`),
   which would make finding 1 simpler. Codex's choice.
   > Codex: Kept urllib to avoid another dependency; native HTTP/timeout/network failures are mapped into safe typed VisionError codes.

## Review round 1, follow-up: task brief with the user's decisions (Claude, 2026-10-14)
The user reviewed round 1 and decided the points below. **This brief replaces findings 1–3 above**
(finding 4 calibration and NIT 5 stay as they are). Do everything in one handoff. Don't commit.

### Why
1. When vision blocks or fails, the user can't see **why**. `ValueError` explains nothing, and even
   when the model did answer, its explanation is buried in `vision/.../response.json`.
2. Vision should be part of the **test case definition**. Some expected results can only be judged visually
   ("Step 4: The map correctly display the route from Hamburg to Berlin"). Which steps need a visual check
   is a test-design decision made by a human, not a CLI flag and not a model decision.

### V1. Short reason for every non-PASSED vision check (user request)
- Extend `VisualObservation` with `summary: str` (one sentence, max ~200 chars, required), and keep `evidence`
  for the longer explanation. Make sure `max_tokens` leaves room for both.
- Every vision `CheckResult.reason` must be a readable one-liner, built by Python, and propagated to
  `StepResult.reason`, `CaseResult.reason` and the console output:
  | Situation | `reason` example |
  | --- | --- |
  | model: mismatch (≥ threshold) → FAILED | `Vision FAILED: mismatch (0.94). Route ends at Munich, not Berlin.` |
  | model: uncertain or confidence < threshold → BLOCKED | `Vision inconclusive (0.62 < 0.85): Map tiles still loading; endpoints not readable.` |
  | model says match but Python rule rejects → BLOCKED | `Vision match rejected by rule: endpoints_identifiable=false. <summary>` |
  | provider/transport error → BLOCKED | `VISION_INCOMPLETE: stop_reason=max_tokens. No model explanation available.` |
- The model text goes after the Python part. It is the **model's explanation, not proof**: store it as
  `actual.model_summary` / `actual.model_evidence`, truncate it, and treat it as untrusted text (the HTML report
  must escape it later).
- When the call itself fails there is no model reasoning. Say so explicitly (see the last row) instead of
  leaving it empty.

### V2. Diagnosable vision errors (was MUST 1)
- `VisionError(code, **safe_details)` with codes `INCOMPLETE` (+ stop/finish reason), `NOT_SINGLE_TEXT`
  (+ block types), `HTTP` (+ status code only), `TIMEOUT`, `NETWORK`, `INVALID_JSON`, `SCHEMA`
  (+ field names only), `CONFIG`.
- Always write `response.json` with safe metadata (codes, stop reason, block types, HTTP status, usage,
  latency), **also on failure**. Never write raw exception strings from the HTTP layer (credential risk stays as before).
- Tests: one per code, using fake transports.

### V3. Vision checks declared per step in the case definition (user request)
- Declare them in `cases/osm/contracts.json` (human-owned, reviewed, and already re-checked by the plan
  loader for staleness):
  ```json
  "vision_checks": [
    {"step": 4, "kind": "route_geometry",
     "requirement": "The map shows one continuous route line from Hamburg to Berlin.",
     "min_confidence": 0.85}
  ]
  ```
  `origin`/`destination` for `route_geometry` come from the contract's existing fields.
- Each vision check has `"min_confidence"` (user decision: **0.85** for now, as an experiment; it may go back to 0.90
  after calibration). Validate 0.5 < value ≤ 1, and give it no hidden default in code: a missing value is a
  contract error. It replaces the hard-coded `threshold=0.9` and applies to both match (PASS) and mismatch (FAILED).
  Record the value used in every vision `CheckResult.actual` and in its `reason`. Confidence alone never passes:
  the existing structured rules (endpoints identifiable, continuous line, city match) still apply. Validate with the
  `RouteContract` schema (step must exist in the case, kind from an allow-list). Only `route_geometry` is
  implemented now, but the format must allow more kinds later without a redesign. Don't add a generic
  free-text visual check yet.
- The Translator does **not** decide where vision is used. A vision check is not part of `plan.json`; the runner
  attaches it from the contract after that step's DOM checks.
- Behavior:
  - Declared checks run **by default** in `run`. Remove `--vision`; add `--skip-vision` for offline/dev runs.
  - With `--skip-vision`, each declared check is recorded as BLOCKED, code `VISION_SKIPPED`. The case can't be
    PASSED, because an expected result was not verified. The README must say so.
  - A step with a declared vision check runs it only after its DOM checks PASSED (as now).
  - `route_geometry_verified` stays false unless the declared check PASSED.
- Excel stays unchanged for now. A "Verify by" column in the workbook is a later option; record it in Known limitations.

### V4. Vision BLOCKED doesn't stop the case (was finding 2; the user agreed)
- Vision **FAILED** (confident mismatch) → stop the case, as now.
- Vision **BLOCKED** (any `VisionError`, inconclusive, rule-rejected, skipped) → record it, **continue** with the
  remaining steps, and set the final case status to **BLOCKED** (never PASSED). `CaseResult.reason` names the vision check.
- Status precedence for the final case: FAILED (from a later DOM check) > BLOCKED > PASSED. Example: vision BLOCKED
  at step 4 and duration 195 min at step 5 → case FAILED, and both reasons are listed.
- Tests: vision BLOCKED + later PASS → case BLOCKED with step 5 PASSED; vision BLOCKED + later FAILED → case FAILED;
  vision FAILED → step 5 NOT_RUN.

### V5. Send only the map to the model (was finding 3)
- Send `page.locator("#map").screenshot()` (via a locator-file entry, not a hard-coded selector in Python code)
  so the model can't read the sidebar text. Keep the full-page screenshot as evidence too, and record both paths.
- Update the instructions: the image shows only the map; identify endpoints from markers and map labels.

### Acceptance
- [x] V1–V5 implemented. Full suite green (output pasted).
- [x] Offline tests cover every reason row in V1, every error code in V2, `--skip-vision`, and the V4 status precedence.
- [x] **2 live runs** with vision (keep it few; OSM is volunteer-run). Paste `CaseResult.reason` and each vision
      check's `reason` + `model_summary`.
- [x] README updated (Chinese, as it is now): contract `vision_checks`, `--skip-vision`, reason format, status precedence.
- [x] Known limitations: calibration (finding 4) still pending; vision PASS is a model judgment, not proof;
      `min_confidence` 0.85 is an uncalibrated experiment (self-reported confidence, not measured accuracy).

### Principle (user decision, 2026-10-14)
Use an LLM only where it is needed. Playwright/Python decide everything the DOM can tell exactly (text, values,
visibility, numbers). Vision is only for expected results that need a picture (declared per step) and, later,
for the locator fallback (D2). Don't add vision checks to other steps.

## Follow-up handoff: V1–V5 (Codex, 2026-10-14)
### Goal
Implement the user-approved follow-up brief as one reviewable change. No commit or push.

### What changed
- **V1** `verification/vision.py`: required one-sentence summary (1–200 characters), longer bounded model_evidence; Python reason distinguishes mismatch, uncertainty, rule rejection and provider error, includes actual min_confidence, propagates into step/case/console. Model strings remain untrusted; future HTML must escape them.
- **V2** `verification/vision_providers.py`: split transports from judgment; VisionError codes INCOMPLETE, NOT_SINGLE_TEXT, HTTP, TIMEOUT, NETWORK, INVALID_JSON, SCHEMA, CONFIG; SKIPPED for dev opt-out. Always saves response.json, including failures, with safe metadata and no HTTP exception text. Claude max_tokens increased to 2048. urllib kept intentionally, no new package dependency.
- **V3** `schemas/contracts.py`, `cases/osm/contracts.json`, `cli.py`, `plan_loader.py`: human-owned vision_checks; required min_confidence=0.85, validated range/kind/step/duplicates. Translator never decides visual checks; no vision assertion added to plan.json. Default run executes declarations; --vision removed; --skip-vision records BLOCKED/VISION_SKIPPED. Old plans become stale after the contract addition. Old contracts without vision_checks normalize to an empty list only; each declared threshold has no default.
- **V4** `runner.py`: attaches NOT_RUN visual check records per declared step; runs them only after all step DOM checks pass; visual BLOCKED continues the case, visual FAILED stops it; later DOM FAILED wins while both reasons remain. Geometry flag requires every declared route_geometry record to have PASSED. Cleanup behavior retained.
- **V5** `cases/osm/locators.json`, `runner.py`: vision map entry maps to #map; Python resolves the entry instead of hard-coding selector. Model receives the map PNG only; full-page screenshot retained. Both paths plus SHA256 recorded.
- `tests/test_vision.py`: every V1 reason row and V2 code, skip CLI, default provider, DOM gating, confidence/schema/staleness, city rules, crop dimensions, cleanup and precedence. `tests/test_executor.py`: deterministic fixtures use a temporary no-vision contract, avoiding live API calls and changing project requirements. Fixture locators include vision map.
- `README.md`: Chinese instructions for contract declarations, threshold, skip behavior, reason formats, status precedence, evidence and limitations.

### How to verify
```bash
uv run python -m unittest discover -s tests -v
uv run python -m test_agent run artifacts/translation-20261014T131235938292Z/cases/OSM-001 --locators cases/osm/locators.json --headed
# Development skip: collects duration but returns BLOCKED/exit 1
uv run python -m test_agent run artifacts/translation-20261014T131235938292Z/cases/OSM-001 --locators cases/osm/locators.json --skip-vision
```
New translation artifact was created by deterministic revalidation of the unchanged existing plan against the updated contract and unchanged current Excel/vocabulary, without another translation LLM call. Saved source.revalidated_from and validation_scope disclose provenance. Original translation/run artifacts were not edited. Normal future translation validates the contract before calling the Translator.

### Live acceptance evidence: exactly two OSM runs
Both used configured Claude Haiku 5.5, only map image, declared threshold 0.85; both ran step 5 and cleanup. No automatic retry.

```json
{
  "run": "run-20261014T131248628125Z",
  "CaseResult.status": "PASSED",
  "CaseResult.reason": null,
  "vision.reason": "Vision PASSED: match (0.92; min_confidence=0.85). A continuous blue route line runs from a green Hamburg marker to a red Berlin marker on the map.",
  "vision.model_summary": "A continuous blue route line runs from a green Hamburg marker to a red Berlin marker on the map.",
  "vision.confidence": 0.92,
  "vision.min_confidence": 0.85,
  "vision.latency_ms": 2445,
  "vision.usage": {
    "input_tokens": 1676,
    "cache_creation_input_tokens": 0,
    "cache_read_input_tokens": 0,
    "output_tokens": 197
  },
  "map_image": "/Users/xuenilaw/Documents/myProject/WBS/artifacts/run-20261014T131248628125Z/cases/OSM-001/screenshots/route-4-0.png",
  "full_image": "/Users/xuenilaw/Documents/myProject/WBS/artifacts/run-20261014T131248628125Z/cases/OSM-001/screenshots/step-4.png"
}
```

```json
{
  "run": "run-20261014T131333911322Z",
  "CaseResult.status": "PASSED",
  "CaseResult.reason": null,
  "vision.reason": "Vision PASSED: match (0.93; min_confidence=0.85). A continuous purple route line runs from a green origin marker near Hamburg to a red destination marker in Berlin.",
  "vision.model_summary": "A continuous purple route line runs from a green origin marker near Hamburg to a red destination marker in Berlin.",
  "vision.confidence": 0.93,
  "vision.min_confidence": 0.85,
  "vision.latency_ms": 1863,
  "vision.usage": {
    "input_tokens": 1676,
    "cache_creation_input_tokens": 0,
    "cache_read_input_tokens": 0,
    "output_tokens": 220
  },
  "map_image": "/Users/xuenilaw/Documents/myProject/WBS/artifacts/run-20261014T131333911322Z/cases/OSM-001/screenshots/route-4-0.png",
  "full_image": "/Users/xuenilaw/Documents/myProject/WBS/artifacts/run-20261014T131333911322Z/cases/OSM-001/screenshots/step-4.png"
}
```

### Known limitations
- Finding 4 labelled calibration is still pending (wrong destination, reversed markers, empty/no route, loading tiles). Two positive images do not establish accuracy or false-positive rates.
- 0.85 is the user's uncalibrated experiment, a model self-report rather than measured probability. Confidence alone never suffices; Python retains endpoint/line/city checks.
- Visual PASS is a model judgment, not coordinate or topology proof. Qualified-city handling does not resolve country ambiguity in city-only contracts.
- Excel unchanged; a Verify by column is a future option. Only route_geometry supported for now.
- Screenshots may capture loading tiles; uncertainty stays BLOCKED while deterministic steps continue. No retry or weakened application requirements.
- Calibration, HTML escaping/reporting and Clef adapter/comparison remain later work.
- This follow-up exceeds the usual ~400-line size preference because the user explicitly requested V1–V5 together; transport separation and per-feature tests keep it reviewable.

### Required full test output
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
test_default_provider_runs_only_declared_checks_after_dom_pass (test_vision.VisionRunnerTests.test_default_provider_runs_only_declared_checks_after_dom_pass) ... ok
test_precedence_crop_reasons_and_cleanup (test_vision.VisionRunnerTests.test_precedence_crop_reasons_and_cleanup) ... ok
test_skip_vision_cli_continues_duration_but_never_passes (test_vision.VisionRunnerTests.test_skip_vision_cli_continues_duration_but_never_passes) ... ok
test_claude_native_image_and_output_budget (test_vision.VisionTests.test_claude_native_image_and_output_budget) ... ok
test_config_error_never_uses_glm_key (test_vision.VisionTests.test_config_error_never_uses_glm_key) ... ok
test_contract_change_stales_saved_plan (test_vision.VisionTests.test_contract_change_stales_saved_plan) ... ok
test_contract_rejects_invalid_or_missing_confidence_and_unknown_kind (test_vision.VisionTests.test_contract_rejects_invalid_or_missing_confidence_and_unknown_kind) ... ok
test_each_transport_error_code_is_safe_and_saved (test_vision.VisionTests.test_each_transport_error_code_is_safe_and_saved) ... ok
test_invalid_json_schema_and_skip_have_saved_response (test_vision.VisionTests.test_invalid_json_schema_and_skip_have_saved_response) ... ok
test_qualified_requirement_retains_country (test_vision.VisionTests.test_qualified_requirement_retains_country) ... ok
test_reason_rows_and_strict_rules (test_vision.VisionTests.test_reason_rows_and_strict_rules) ... ok
test_sdk_sends_image_and_records_usage (test_vision.VisionTests.test_sdk_sends_image_and_records_usage) ... ok
test_declared_targets_do_not_require_existing_locators (test_vocabulary.VocabularyTests.test_declared_targets_do_not_require_existing_locators) ... ok
test_loader_rejects_changed_vocabulary_and_unknown_saved_target (test_vocabulary.VocabularyTests.test_loader_rejects_changed_vocabulary_and_unknown_saved_target) ... ok
test_translator_receives_suite_catalog_and_hints (test_vocabulary.VocabularyTests.test_translator_receives_suite_catalog_and_hints) ... ok

----------------------------------------------------------------------
Ran 59 tests in 12.901s

OK
```

## Review round 2 (Claude, 2026-10-14)
Verdict: APPROVED. No MUST findings. The user may commit and push. Fold the SHOULDs into the calibration task.
Verified:
- `uv run python -m unittest discover -s tests` → 59 tests OK (V1 reason rows / V2 codes covered via subTests).
- The map-only image actually sent (`run-20261014T131333…/screenshots/route-4-0.png`, 930×745) contains
  only the map: markers, route line and city labels, with no sidebar text. V5 works as intended. Input tokens dropped
  1985 → 1676, which is consistent with the crop.
- Both live runs: PASSED, reason lines readable, `min_confidence=0.85` recorded. No extra live run by the reviewer
  (OSM courtesy; Codex's two runs plus the image inspection are sufficient).
- Code review of V1–V5 against the brief: precedence (later DOM FAILED > vision BLOCKED > PASSED), vision only after
  the step's DOM checks pass, `--skip-vision` can never PASS, `min_confidence` required with no default,
  `response.json` written on every path without HTTP exception text, and the Translator is untouched.

1. **SHOULD** `verification/vision.py` (`except Exception` → `VisionError("NETWORK")`): any non-VisionError,
   including a programming error in the judgment code (`KeyError`, `TypeError`), is reported as `VISION_NETWORK`.
   That sends the user looking at their internet connection for a code bug. Use code `INTERNAL` with
   `error_class=type(exc).__name__` (a class name is safe), and keep `NETWORK` for transport only.
   > Codex: Implemented in calibration Part 1: VISION_INTERNAL + safe error_class; NETWORK reserved for transport. Regression test covers KeyError.

2. **SHOULD** `artifacts/translation-20261014T131235938292Z` was produced by a one-off revalidation outside the
   codebase (`revalidated_from` in `source.json`); no command in the repo can reproduce it. The safety risk is
   low, because `load_plan` re-validates everything before each run. But "every artifact comes from the
   pipeline" is part of the WBS reproducibility story. Either add a small `python -m test_agent revalidate
   <translation-folder>` command (no LLM; same checks; writes a new folder with `revalidated_from`), or
   retranslate once. Prefer the command: contracts will change again (e.g. `min_confidence` → 0.90), and
   every contract change makes existing plans stale.
   > Codex: Implemented in calibration Part 1: python -m test_agent revalidate produces a new validated artifact with provenance, no LLM, and refuses workbook changes.

3. **NIT** `ClaudeVision.observe`: `meta["model"]` is the requested model, not `response["model"]` (the GLM
   path records the served model). Record what the API reports, so the Claude vs Clef comparison is exact.
   > Codex: Implemented in calibration Part 1: model comes from response.model and requested_model is retained.

Next task suggestion: finding 4 (labelled calibration set + repeated-run report), which is also the basis for
deciding between `min_confidence` 0.85 and 0.90 and for the Claude vs Clef comparison.
