# Task: vision follow-ups, min_confidence 0.90, and Claude calibration
Status: APPROVED
Workflow step(s): 4 (Verify: vision)
Assigned: Codex · Reviewer: Claude · Brief written 2026-10-14

## Why this task
Vision verification (D1) works on correct images, but **all evidence so far is positive images**:
we know Claude says "match" for a correct Hamburg→Berlin route, but not what it says for a wrong one.
Before the WBS report claims accuracy, and before comparing with Clef, measure Claude on a fixed,
labelled image set.

User decisions (2026-10-14):
- Raise `min_confidence` from 0.85 to **0.90** and measure Claude at that level.
- If Claude meets the acceptance bar below, the next task is the Clef comparison on the **same** image set.
- Principle unchanged: use the LLM only where needed. This task adds no vision checks to other steps.

Out of scope: the Clef adapter, vision locator fallback (D2), HTML report.

Process: **two handoff rounds** in this file (Part 1 first). Hand off before committing.

---

## Part 1: small findings from `2026-10-14-vision-verification.md` round 2, then 0.90

1.1 **`INTERNAL` error code.** In `verification/vision.py`, a non-VisionError becomes
    `VisionError("INTERNAL", error_class=type(exc).__name__)`, not `NETWORK`. Keep `NETWORK` for transport errors
    only. Test: a fake provider whose reply makes the judgment code raise `KeyError` → `VISION_INTERNAL`,
    `error_class=KeyError`.

1.2 **`revalidate` command (no LLM).**
    ```sh
    uv run python -m test_agent revalidate artifacts/<translation-folder>/cases/<case_id>
    ```
    - Reads the existing `plan.json` (+ the saved case), re-runs **all** translation checks against the
      **current** workbook, contract and vocabulary, and writes a **new** `translation-<id>/cases/<case_id>/` with
      `source.revalidated_from`, `validation.json` and `plan.json` (only if VALIDATED). Never edits the old folder.
    - Refuses if the workbook text changed (that needs a new translation, not revalidation): exit 1, REJECTED,
      clear reason.
    - It replaces the one-off script used for `translation-20261014T131235938292Z`.
    - Tests: contract-only change → VALIDATED new folder; workbook change → REJECTED; old folder untouched.

1.3 **Served model name.** `ClaudeVision` records `response["model"]` as `model`, and keeps `requested_model`.

1.4 **Switch to 0.90.** Set `"min_confidence": 0.90` in `cases/osm/contracts.json`, run `revalidate` on
    `translation-20261014T131235938292Z`, and do **one** live run with the new folder. Paste the vision `reason`.

---

## Part 2: Claude calibration

### 2.1 A fixed, labelled image set (captured once, then offline)
Folder: `cases/osm/vision_calibration/`
- `images/*.png`: **map-only** screenshots captured with the same `vision map` locator and viewport the runner
  uses, so calibration measures exactly what production sends.
- `labels.json`: one entry per image:
  ```json
  {"file": "hamburg-munich.png", "route_shown": "Hamburg -> Munich",
   "requirement": {"origin": "Hamburg", "destination": "Berlin"},
   "expected": "NOT_PASS", "ideal": "FAILED", "why": "wrong destination"}
  ```
  `expected` is `PASS` or `NOT_PASS` (the hard label). `ideal` is the best outcome: FAILED for a clear mismatch,
  BLOCKED for an unclear image.
- A small capture command or script in the repo (e.g. `python -m test_agent calibrate capture`) that drives OSM
  through the existing Playwright tools for given from/to pairs and saves map-only PNGs. Run it **once**; commit
  the images. Calibration runs never touch OSM again.

Minimum set, all judged against the requirement **Hamburg → Berlin**:
| Image | Expected | Ideal | Tests |
| --- | --- | --- | --- |
| Hamburg → Berlin (as in the real run) | PASS | PASSED | baseline |
| Hamburg → Berlin, different zoom/viewport | PASS | PASSED | robustness |
| Hamburg → Munich | NOT_PASS | FAILED | wrong destination |
| Hamburg → Potsdam | NOT_PASS | FAILED or BLOCKED | near-miss next to Berlin |
| Berlin → Hamburg (reversed) | NOT_PASS | FAILED | direction (green vs red marker) |
| Bremen → Berlin | NOT_PASS | FAILED | wrong origin |
| Map with no route (directions panel open, nothing calculated) | NOT_PASS | BLOCKED or FAILED | nothing drawn |
| Route still loading / tiles blank (screenshot taken immediately after submit) | NOT_PASS | BLOCKED | unreadable |

More images are welcome, but keep the labels honest: if a human can't judge an image, label it NOT_PASS/BLOCKED.

### 2.2 Make the decision replayable
Split the decision part of `verify_route_image` into a **pure function**
`decide(observation, requirement, min_confidence) -> (status, reason, code)`. The live path and calibration
both use it. Then the saved observations can be re-scored at other thresholds **without new model calls**.

### 2.3 Calibration command
```sh
uv run python -m test_agent calibrate run cases/osm/vision_calibration --runs 5
```
- For each image × run: call the configured provider (`VISION_PROVIDER`; Claude now, Clef later with no other
  change) through the same request/prompt/schema as production, then `decide(...)` at the contract's `min_confidence`.
- Sequential calls, no retries. Errors are counted as BLOCKED with their `VISION_*` code (they're part of reliability).
- Output: `artifacts/calibration-<id>/` with raw `responses/`, `results.json` and a short `report.md`:
  - per image: PASSED / FAILED / BLOCKED counts, confidence min/median/max, the most common `model_summary`
  - totals: **false PASS** (NOT_PASS image → PASSED), **missed PASS** (PASS image → not PASSED),
    correct-FAILED rate on clear mismatches, BLOCKED rate, error codes
  - latency p50/p95, mean input/output tokens per call, served model name
  - a **threshold table** re-scored from the same observations at 0.80 / 0.85 / 0.90 / 0.95
    (false PASS and missed PASS for each)
- Print the totals and the threshold table to the console.
- Tests (offline, fake provider): metric arithmetic, re-scoring, an error counted as BLOCKED, and labels validation
  (unknown file, bad `expected` value).

### 2.4 Live calibration (Claude)
Run `--runs 5` on the full set (~8 images × 5 = ~40 calls; ~1.7k input tokens each). Paste `report.md` into the handoff.

### 2.5 Acceptance bar for "Claude passed → go to Clef" (proposed; the user may adjust)
- **False PASS = 0** across all runs at `min_confidence` 0.90. This is a hard requirement: a wrong route must never pass.
- Correct images PASSED in **≥ 90 %** of runs (`missed PASS` ≤ 10 %).
- Clear mismatches (Munich, reversed, Bremen) end as FAILED in ≥ 80 % of runs; the rest may be BLOCKED.
- No `VISION_INTERNAL` errors.
Report the result against each line. Don't tune the prompt or labels to pass; report what happened. If something
fails, say which images and why (model summaries), and propose the change for the user to decide.

## Definition of done (in addition to `docs/collaboration.md`)
- [ ] Part 1: 1.1–1.4 done with tests; one live run at 0.90.
- [ ] Part 2: image set + labels committed; `decide()` extracted with behavior unchanged; `calibrate run` works offline with a fake provider.
- [ ] Live Claude calibration report pasted, evaluated against 2.5.
- [ ] Full suite green, output pasted. README (Chinese): `revalidate`, calibration folder, commands, how to read the report.
- [ ] Known limitations: small sample size; self-reported confidence; OSM tile appearance may change over time (images are frozen on purpose).

---

## Handoff (Codex)
<!-- Round 1 (Part 1), then Round 2 (Part 2). Use the template in docs/collaboration.md -->

## Handoff round 1: Part 1 (Codex, 2026-10-14)
### Goal
Implement 1.1–1.4 before starting calibration. No commits.
### What changed
- vision.py: unexpected judgment errors use VISION_INTERNAL + safe error_class; NETWORK remains transport-specific.
- vision_providers.py: records the served response.model separately from requested_model.
- plan_loader.py / cli.py: revalidate command reuses all source/schema/contract/vocabulary checks, permits updated sidecars but refuses changed workbook text; produces new artifacts and preserves originals, no LLM/browser.
- contracts.json: human-owned min_confidence raised to 0.90.
- tests/test_revalidate.py and tests/test_vision.py: contract-only refresh, changed workbook/altered plan rejection, immutable old artifacts, INTERNAL diagnostic and served-model checks.
- README: Chinese revalidation command and error/model explanations.
### How to verify
```bash
uv run python -m test_agent revalidate artifacts/translation-20261014T131235938292Z/cases/OSM-001
uv run python -m test_agent run artifacts/translation-20261014T135619240723Z/cases/OSM-001 --locators cases/osm/locators.json
uv run python -m unittest discover -s tests -v
```
### One live run at 0.90
{
  "run": "/Users/xuenilaw/Documents/myProject/WBS/artifacts/run-20261014T135719788528Z/cases/OSM-001",
  "case_status": "BLOCKED",
  "case_reason": "directions form is not ready",
  "vision_reasons": [
    null
  ]
}
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
test_contract_only_change_new_validated_folder_old_untouched (test_revalidate.RevalidateTests.test_contract_only_change_new_validated_folder_old_untouched) ... ok
test_modified_plan_still_rejected_against_current_contract (test_revalidate.RevalidateTests.test_modified_plan_still_rejected_against_current_contract) ... ok
test_workbook_change_rejected_without_approved_plan (test_revalidate.RevalidateTests.test_workbook_change_rejected_without_approved_plan) ... ok
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
test_declared_targets_do_not_require_existing_locators (test_vocabulary.VocabularyTests.test_declared_targets_do_not_require_existing_locators) ... ok
test_loader_rejects_changed_vocabulary_and_unknown_saved_target (test_vocabulary.VocabularyTests.test_loader_rejects_changed_vocabulary_and_unknown_saved_target) ... ok
test_translator_receives_suite_catalog_and_hints (test_vocabulary.VocabularyTests.test_translator_receives_suite_catalog_and_hints) ... ok

----------------------------------------------------------------------
Ran 63 tests in 12.913s

OK
```
### Known limitations
No calibration claims yet. Part 2 proceeds under the user's explicit instruction to hand off Part 1 then do Part 2. Changes remain uncommitted. Old 0.85 artifacts are now stale; use the new command-produced folder.

## Handoff round 2: Part 2 (Codex, 2026-10-14)
### Goal
Measure the current production verifier honestly on a frozen, labelled image set; do not tune it to pass.

### What changed
- verification/vision.py: extracted pure decide(observation, requirement, min_confidence), shared by production and calibration, with the existing decision behavior preserved.
- verification/calibration.py: strict labels validation; sequential image × run calls through the production provider/prompt/schema; saved per-call evidence and results; metrics and threshold replay; report.md and console totals.
- verification/calibration_capture.py: one-time preset capture using existing semantic Playwright tools, same default viewport/context settings; one alternate-viewport robustness example; no model calls. Refuses image overwrite. --only supports missing preset captures without redoing the set.
- tools/dom.py / runner.py / locators.json: shared capture_map handles the #map/sidebar overlap visible before a route is calculated. vision sidebar is declared in the locator file; there is no selector hard-coded in Python. Current production and calibration use identical cropping logic.
- cases/osm/vision_calibration/: 8 actual OSM PNGs, human-owned labels.json and capture.json with locator/settings/provenance hashes. PNGs are browser captures, not generated or pixel-edited images. Frozen and prepared for review, NOT committed under the user's instruction.
- tests/test_calibration.py: arithmetic, threshold replay without new calls, provider errors counted as BLOCKED, labels rejection, pure-function immutability, sidebar-clip regression and freeze guard. Existing vision/runner tests still pass.
- README: Chinese capture/run/revalidate commands, dataset and report interpretation.

### Capture inspection and corrections BEFORE model measurement
The first candidate keyboard-zoom capture did not actually zoom; replaced it with a real 1024x768 viewport sample. The initial no-route/blank #map screenshots contained the overlapping sidebar; discarded those candidates and fixed the shared region capture helper before freezing the dataset. Final set has 8 images; no labels, prompt or parser were changed after inspecting model results. Blank/loading is a controlled fault injection (tile requests aborted, screenshot immediately after Enter), not pixel editing. Default viewport remains 1280x800; the sole robustness sample intentionally differs as requested.

### How to verify
```bash
uv run python -m test_agent calibrate run cases/osm/vision_calibration --runs 5
uv run python -m unittest discover -s tests -v
# Capture is only for a NEW empty dataset folder. It accesses OSM; run uses frozen images and never accesses OSM.
uv run python -m test_agent calibrate capture <new-folder>
```
No commits or push. API calls are sequential, no retries. Exactly 40 calibration calls completed; no rerun to improve the score.

### Live report (unchanged)
Source: artifacts/calibration-20261014T142906726506Z/report.md

```markdown
# Vision calibration at 0.9

Calls: 40 | false PASS: 10 | missed PASS: 0
Correct image PASS: 100.0% | clear mismatch FAILED: 0.0% | BLOCKED: 50.0%
Error codes: {'VISION_NOT_SINGLE_TEXT': 15, 'VISION_INCONCLUSIVE': 5}
Latency p50/p95 (ms): 2462.5 / 3405.4
Mean input/output tokens per attempt: 1642.5 / 276.6
Usage reported: 40/40; missing usage contributes zero (a lower bound, not an exact bill).
Served models: ['claude-haiku-5-5']

| Image | PASSED | FAILED | BLOCKED | Confidence min/median/max | Most common model summary |
| --- | ---: | ---: | ---: | --- | --- |
| hamburg-berlin.png | 5 | 0 | 0 | 0.93/0.93/0.93 | A continuous blue route line runs from a green origin marker labeled Hamburg to a red destination marker labeled Berlin. |
| hamburg-munich.png | 0 | 0 | 5 | None/None/None | No model explanation |
| hamburg-potsdam.png | 5 | 0 | 0 | 0.9/0.9/0.93 | A continuous blue route line runs from a green origin marker at Hamburg to a red destination marker near Berlin. |
| berlin-hamburg.png | 5 | 0 | 0 | 0.9/0.93/0.93 | A continuous blue route line runs from a Hamburg marker in the northwest to a Berlin marker in the east. |
| bremen-berlin.png | 0 | 0 | 5 | None/None/None | No model explanation |
| hamburg-berlin-viewport.png | 5 | 0 | 0 | 0.9/0.9/0.9 | A continuous blue route line runs from a green marker at Hamburg to a red marker at Berlin on the map. |
| no-route.png | 0 | 0 | 5 | None/None/None | No model explanation |
| tiles-blank.png | 0 | 0 | 5 | 0.9/0.9/0.9 | The map shows only blank tiles with map controls; no route line, markers, or city labels are visible. |

| Threshold (same observations) | False PASS | Missed PASS |
| --- | ---: | ---: |
| 0.8 | 10 | 0 |
| 0.85 | 10 | 0 |
| 0.9 | 10 | 0 |
| 0.95 | 0 | 10 |

Acceptance:
- false_pass_zero: FAIL
- correct_pass_at_least_90_percent: PASS
- clear_mismatch_failed_at_least_80_percent: FAIL
- no_internal_errors: PASS

Ready for Clef comparison: False

Small fixed sample; model confidence is self-reported. Frozen tiles are not all future OSM appearances.
Model summaries are untrusted explanations, not proof. No prompt/label tuning or retries.
```

### Acceptance evaluation
- False PASS=0: **FAIL**. Potsdam near-miss and Berlin→Hamburg reversed direction each PASSED 5/5; 10 wrong-image passes in total (10/30 negative calls).
- Correct images PASSED ≥90%: **PASS**, 10/10=100%.
- Clear mismatches FAILED ≥80%: **FAIL**, 0/15=0%. Reversed direction was falsely PASSED 5/5. Munich and Bremen were BLOCKED 5/5 each by VISION_NOT_SINGLE_TEXT, not judged as FAILED.
- No VISION_INTERNAL: **PASS**, zero.
- Overall: **Claude/current verifier does not meet the proposed bar; do not describe it as production-accurate or automatically move to Clef under that gate.**

### What failed and proposals for the user to decide
1. Potsdam: summary repeatedly says the endpoint is "near Berlin" and reports match; proximity is being confused with the required destination. No prompt/threshold fix applied.
2. Reversed: summary describes a line between Hamburg and Berlin but overlooks the swapped green origin / red destination. Existing structured booleans/city names are model reports and do not independently prove direction.
3. Munich, Bremen and no-route: 15 calls returned legal thinking+text block shapes which the current adapter rejects as NOT_SINGLE_TEXT; their text observations were deliberately not used under current production rules. This measures adapter reliability too, not just model accuracy. No model explanation available for these rejected responses. Their safe response metadata and token usage are retained; private reasoning blocks are not logged.
4. Raising threshold to 0.95 replays to 0 false PASS but 10 missed PASS; changing only the threshold would reject every positive image in this sample. Do not silently adopt it.
5. Proposed next work: support exactly one text result while ignoring thinking blocks in the native Claude adapter; then, with user approval, evaluate a marker/city observation stage that identifies endpoints before comparing requirements, or compare a stronger vision model on this same frozen set. Treat these as proposed changes, not completed fixes. Any provider comparison should preserve images/labels and report both accuracy and adapter errors.

### Known limitations / outstanding evidence
- Part 1's single full Runner live attempt at 0.90 was BLOCKED before vision (directions form readiness); there is no vision reason from that attempt. The 40 Part 2 live calls measure the configured 0.90 rule independently; no extra full Runner rerun was made.
- Image set/labels are prepared but intentionally uncommitted pending review, overriding the brief's "committed" wording. They are non-ignored repo files and can be included in the later approved commit.
- Small sample; repeated calls on frozen screenshots are not independent geographical samples. Self-reported confidence is not measured accuracy. OSM tile appearance changes over time, hence frozen input images.
- No Clef adapter, D2 locator fallback, or HTML report added. Report summaries are untrusted text and must be escaped if later rendered as HTML.
- Usage is reported for all 40 calls; token averages are observed here. Generic reports show missing usage as a zero-contribution lower bound, not an exact invoice.

### Required full suite output
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
test_declared_targets_do_not_require_existing_locators (test_vocabulary.VocabularyTests.test_declared_targets_do_not_require_existing_locators) ... ok
test_loader_rejects_changed_vocabulary_and_unknown_saved_target (test_vocabulary.VocabularyTests.test_loader_rejects_changed_vocabulary_and_unknown_saved_target) ... ok
test_translator_receives_suite_catalog_and_hints (test_vocabulary.VocabularyTests.test_translator_receives_suite_catalog_and_hints) ... ok

----------------------------------------------------------------------
Ran 68 tests in 13.092s

OK
```

## Review round 1 (Claude, 2026-10-15)
Verdict: **The code is APPROVED** (Part 1 and the calibration tooling work and are honest). **The verifier is below the bar**, so
2 follow-up changes are needed before the Clef comparison. The user may commit the current state now as a checkpoint:
the calibration result is a measured finding, not a code defect.
Verified:
- `uv run python -m unittest discover -s tests` → 68 tests OK.
- Labels are fair: inspected `berlin-hamburg.png` (green start marker clearly at Berlin, red end marker at Hamburg) and
  `hamburg-potsdam.png` (red marker clearly on the "Potsdam" label, below "Berlin"). A human can judge both, so the
  10 false PASSes are real verifier errors, not label problems.
- Part 1 live run `run-20261014T135719…` BLOCKED `FORM_NOT_READY`: the trace shows **HTTP 503 on `GET /directions`**
  from OSM. That's an environment problem, and the status is correct.
- Report numbers checked against the handoff. Honest reporting and no tuning: well done. This is exactly why we calibrate.

1. **MUST** `vision_providers.py` (Claude adapter): accept `thinking`/`redacted_thinking` blocks followed by **exactly
   one** `text` block. Use the text, record only `"thinking_present": true` plus the block types, never the thinking
   content. `NOT_SINGLE_TEXT` stays for 0 or ≥2 text blocks. Right now 15/40 calls, and precisely the hard negatives
   (Munich, Bremen, no-route), are discarded, so we don't know how Claude judges them. Test: `[thinking, text]` → parsed;
   `[text, text]` → NOT_SINGLE_TEXT.
   > Codex: Fixed in vision_providers.py: accepts thinking/redacted_thinking prefix plus exactly one final text block, logs only thinking_present/block_types. Measured adapter alone first: calibration-20261015T071455682195Z (40 unchanged-image/old-prompt calls). Zero/multiple-text and no-private-thinking tests pass.

2. **MUST** (design; recommended by the reviewer, confirm with the user) **Blind observation.** Both false-PASS
   patterns look like *anchoring*: the request tells the model "Hamburg → Berlin", and it confirms what it was
   told ("red destination marker **near** Berlin"; the reversed image described as "Hamburg … to Berlin").
   Change the model's job from *judging the requirement* to *reporting what it sees*:
   - Don't send the expected cities (or the requirement text) to the model.
   - New observation fields (replacing verdict/observed_*): `start_marker_city` and `end_marker_city` (the labelled city
     at the **green** start / **red** end marker, or `"unclear"`), `start_marker_position` / `end_marker_position`
     (`on_label` | `near_other_city` | `unclear`), `route_line` (`continuous` | `broken` | `none` | `unclear`),
     `confidence`, `summary`, `evidence`.
   - **Python decides** against the contract: PASS only if start = origin, end = destination, both `on_label`,
     line continuous, and confidence ≥ `min_confidence`. A clear different city → FAILED. Anything `unclear`/`none` → BLOCKED.
     Direction is then checked by Python, not trusted to the model.
   - Keep `decide()` pure; calibration replay must still work.
   > Codex: Implemented under the user’s explicit instruction to do findings 1–4. Provider.observe now receives image bytes only; no expected cities, requirement text or filename. New blind-map-v2 schema and pure Python decide() perform contract/direction/position/line comparison. Both providers have payload-blindness tests.

3. **MUST** (method) **Hold-out images.** The 8 images have now been seen while designing fix 2, so re-measuring only
   on them can overfit. **Before** changing the prompt, capture 4–6 fresh images with the same capture command into
   `cases/osm/vision_calibration_holdout/` (e.g. Hamburg → Leipzig, Rostock → Berlin, Berlin → Hamburg at another zoom,
   Hamburg → Berlin at another zoom, Hamburg → Bernau (near Berlin, north)), label them, and commit them without
   looking at model results. Then run the calibration on **both** sets with `--runs 5` and report them separately.
   Same acceptance bar (2.5). Few OSM visits (one capture session).
   > Codex: Captured five new hold-out images in one session before prompt edits. Image/label hashes, freeze time and pre-change prompt hash are saved. No model results were used to label them. Both sets measured separately at --runs 5. Files remain uncommitted because the user explicitly prohibited commits before review.

4. **NIT** `FORM_NOT_READY` reason: when the lazy `/directions` fetch fails, include its HTTP status
   (`directions form is not ready: GET /directions → 503`), so a user sees at once that it's OSM, not the tool.
   > Codex: Fixed tools/dom.py: observe the existing clicked link’s GET response (same origin and path), attach captured HTTP status to FORM_NOT_READY; no request/retry added. Offline browser test simulates GET /directions → 503 and asserts exactly one request.

Order: 1 → re-run the original set unchanged (this measures the adapter fix alone, and the numbers go into the handoff)
→ 3 (capture hold-out) → 2 → calibrate both sets. Only then decide 0.90 vs other thresholds and the Clef step.

## Follow-up checkpoint 1 (Codex, 2026-10-15): adapter-only measurement

Finding 1 implemented first. Thinking/redacted_thinking prefixes followed by exactly one text block are accepted. Only block types and thinking_present are logged, never private thinking content. Zero or multiple text blocks are still NOT_SINGLE_TEXT. All 69 offline tests passed before measurement.

Original images, labels, prompt, schema, decision rules and threshold were unchanged for these 40 calls. Report: artifacts/calibration-20261015T071455682195Z/report.md.

```markdown
# Vision calibration at 0.9

Calls: 40 | false PASS: 9 | missed PASS: 0
Correct image PASS: 100.0% | clear mismatch FAILED: 66.7% | BLOCKED: 27.5%
Error codes: {'VISION_INCONCLUSIVE': 11}
Latency p50/p95 (ms): 2367.5 / 4647.4
Mean input/output tokens per attempt: 1642.5 / 294.2
Usage reported: 40/40; missing usage contributes zero (a lower bound, not an exact bill).
Served models: ['claude-haiku-5-5']

| Image | PASSED | FAILED | BLOCKED | Confidence min/median/max | Most common model summary |
| --- | ---: | ---: | ---: | --- | --- |
| hamburg-berlin.png | 5 | 0 | 0 | 0.93/0.93/0.93 | A continuous blue route line runs from a green origin marker labeled Hamburg to a red destination marker at Berlin. |
| hamburg-munich.png | 0 | 5 | 0 | 0.92/0.93/0.95 | The visible route runs from Hamburg to München, not to the expected destination Berlin. |
| hamburg-potsdam.png | 4 | 0 | 1 | 0.5/0.93/0.93 | A continuous blue route line runs from a green origin marker at Hamburg to a red destination marker near Berlin. |
| berlin-hamburg.png | 5 | 0 | 0 | 0.93/0.93/0.93 | A continuous blue route line runs from a Hamburg marker in the northwest to a Berlin marker in the east. |
| bremen-berlin.png | 0 | 5 | 0 | 0.9/0.9/0.9 | The continuous route runs from Bremen, not Hamburg, to Berlin, so the required origin does not match. |
| hamburg-berlin-viewport.png | 5 | 0 | 0 | 0.9/0.9/0.9 | A continuous blue route line runs from a green Hamburg marker to a red Berlin marker, matching the requirement. |
| no-route.png | 0 | 0 | 5 | 0.8/0.8/0.8 | The map shows city labels including Hamburg and Berlin, but no route line connecting them is visible. |
| tiles-blank.png | 0 | 0 | 5 | 0.9/0.9/0.95 | The map shows only blank background tiles with navigation controls; no route line, markers, or city labels are visible. |

| Threshold (same observations) | False PASS | Missed PASS |
| --- | ---: | ---: |
| 0.8 | 9 | 0 |
| 0.85 | 9 | 0 |
| 0.9 | 9 | 0 |
| 0.95 | 0 | 10 |

Acceptance:
- false_pass_zero: FAIL
- correct_pass_at_least_90_percent: PASS
- clear_mismatch_failed_at_least_80_percent: FAIL
- no_internal_errors: PASS

Ready for Clef comparison: False

Small fixed sample; model confidence is self-reported. Frozen tiles are not all future OSM appearances.
Model summaries are untrusted explanations, not proof. No prompt/label tuning or retries.
```

Next: capture and freeze hold-out before prompt edits. No commits.

## Follow-up checkpoint 2 (Codex, 2026-10-15): hold-out frozen before prompt change

Captured five new images with --profile holdout in one session: Leipzig, Rostock, reversed at 1440x900, positive at 1440x900, Bernau bei Berlin. Inspected and labelled them without model results. Frozen image/label hashes, UTC timestamp and pre-change prompt hash/schema fields are in cases/osm/vision_calibration_holdout/capture.json. Original set unchanged. No commit, following the user instruction. Blind observation has not yet been implemented at this checkpoint.

## Follow-up handoff round 1 (Codex, 2026-10-15): findings 1–4
Status: IN REVIEW
Workflow step(s): 4 Verify / vision calibration

### Goal and order followed
1. Adapter-only fix → full offline tests → 40-call original-set measurement with prompt/schema/rules/images/labels unchanged.
2. Hold-out capture: 5 new labelled images frozen and inspected BEFORE blind prompt/schema changes. Checkpoint and pre-change prompt hash saved.
3. Blind observation + Python-only comparison → offline tests → original 40 calls followed by hold-out 25 calls, separately reported.
4. FORM_NOT_READY HTTP diagnostic and final required tests. No commits or push. No model-call or action retries.

### What changed
- `verification/vision_providers.py`: legal thinking-prefix handling; exactly one final text block; no private thinking recorded. Provider API takes image bytes only; GLM and Claude payloads contain blind schema + image, without expected cities/requirement/filename.
- `verification/vision.py`: required marker city/position, line, confidence/summary/evidence fields replace verdict/observed endpoints/booleans. Prompt describes colours and visible labels, without target cities. Pure decide() owns direction and contract comparison. Both markers on_label, exact city match, continuous line, confidence >= threshold are required for PASS. Confident clear different city/broken line is FAILED; unclear/no route/near-other-city/low confidence is BLOCKED. Local request evidence retains Python-only requirements with an explicit scope marker; it is not the transmitted payload.
- `verification/calibration_capture.py` / `cli.py`: --profile holdout with five predeclared captures, including 1440x900 viewport variants. No overwrite of frozen files. Current original set unchanged.
- `cases/osm/vision_calibration_holdout/`: Leipzig, Rostock, reversed markers at new viewport, correct new viewport, Bernau near-miss. labels + actual browser PNGs + capture settings/hashes. Prepared for review, intentionally not committed.
- `tools/dom.py`: captures an existing lazy GET failure status from the clicked link’s origin/path before readiness timeout. No query/header/exception text logging, no extra request. Reason example: directions form is not ready: GET /directions → 503.
- `tests/test_vision.py`, `tests/test_calibration.py`, `tests/test_executor.py`: new blind schema cases, positive/negative/direction/unclear/no-route/broken-line rules, replay arithmetic, provider payload blindness, thinking privacy and simulated 503 behavior.
- `README.md`: Chinese description and commands for blind observations, hold-out, adapter blocks and form readiness diagnostics.

### How to verify
```bash
uv run python -m unittest discover -s tests -v
# Model calls on frozen local PNGs only; these measurements are already complete, no need to repeat for code review.
uv run python -m test_agent calibrate run cases/osm/vision_calibration --runs 5
uv run python -m test_agent calibrate run cases/osm/vision_calibration_holdout --runs 5
# Capture only when creating a NEW empty hold-out; current frozen directory will refuse overwrite.
uv run python -m test_agent calibrate capture <new-empty-folder> --profile holdout
```

### Stage comparisons (threshold remains 0.90)
| Stage | Calls | False PASS | Correct image PASS | Clear mismatch FAILED | Verdict |
| --- | ---: | ---: | ---: | ---: | --- |
| Previous baseline, anchored + strict single block | 40 | 10 | 100% | 0% | Below bar |
| Finding 1 adapter only, anchored unchanged | 40 | 9 | 100% | 66.7% | Below bar |
| Blind observation, original set | 40 | 0 | 70% | 60% | Below bar |
| Blind observation, fresh hold-out | 25 | 0 | 100% | 33.3% | Below bar |

No INTERNAL errors in any new measurement. After adapter fix there were no NOT_SINGLE_TEXT errors. The two blind reports have only VISION_INCONCLUSIVE codes, not parser/transport failures. Three stage reports are preserved separately; original/baseline artifacts were not edited. Total calls for this follow-up: 105. The prompt/schema changed exactly once, after hold-out freeze; no post-result tuning.

### Adapter only (finding 1) — complete live report

Source: artifacts/calibration-20261015T071455682195Z/report.md

```markdown
# Vision calibration at 0.9

Calls: 40 | false PASS: 9 | missed PASS: 0
Correct image PASS: 100.0% | clear mismatch FAILED: 66.7% | BLOCKED: 27.5%
Error codes: {'VISION_INCONCLUSIVE': 11}
Latency p50/p95 (ms): 2367.5 / 4647.4
Mean input/output tokens per attempt: 1642.5 / 294.2
Usage reported: 40/40; missing usage contributes zero (a lower bound, not an exact bill).
Served models: ['claude-haiku-5-5']

| Image | PASSED | FAILED | BLOCKED | Confidence min/median/max | Most common model summary |
| --- | ---: | ---: | ---: | --- | --- |
| hamburg-berlin.png | 5 | 0 | 0 | 0.93/0.93/0.93 | A continuous blue route line runs from a green origin marker labeled Hamburg to a red destination marker at Berlin. |
| hamburg-munich.png | 0 | 5 | 0 | 0.92/0.93/0.95 | The visible route runs from Hamburg to München, not to the expected destination Berlin. |
| hamburg-potsdam.png | 4 | 0 | 1 | 0.5/0.93/0.93 | A continuous blue route line runs from a green origin marker at Hamburg to a red destination marker near Berlin. |
| berlin-hamburg.png | 5 | 0 | 0 | 0.93/0.93/0.93 | A continuous blue route line runs from a Hamburg marker in the northwest to a Berlin marker in the east. |
| bremen-berlin.png | 0 | 5 | 0 | 0.9/0.9/0.9 | The continuous route runs from Bremen, not Hamburg, to Berlin, so the required origin does not match. |
| hamburg-berlin-viewport.png | 5 | 0 | 0 | 0.9/0.9/0.9 | A continuous blue route line runs from a green Hamburg marker to a red Berlin marker, matching the requirement. |
| no-route.png | 0 | 0 | 5 | 0.8/0.8/0.8 | The map shows city labels including Hamburg and Berlin, but no route line connecting them is visible. |
| tiles-blank.png | 0 | 0 | 5 | 0.9/0.9/0.95 | The map shows only blank background tiles with navigation controls; no route line, markers, or city labels are visible. |

| Threshold (same observations) | False PASS | Missed PASS |
| --- | ---: | ---: |
| 0.8 | 9 | 0 |
| 0.85 | 9 | 0 |
| 0.9 | 9 | 0 |
| 0.95 | 0 | 10 |

Acceptance:
- false_pass_zero: FAIL
- correct_pass_at_least_90_percent: PASS
- clear_mismatch_failed_at_least_80_percent: FAIL
- no_internal_errors: PASS

Ready for Clef comparison: False

Small fixed sample; model confidence is self-reported. Frozen tiles are not all future OSM appearances.
Model summaries are untrusted explanations, not proof. No prompt/label tuning or retries.
```

### Blind observation: original set — complete live report

Source: artifacts/calibration-20261015T072050441635Z/report.md

```markdown
# Vision calibration at 0.9

Calls: 40 | false PASS: 0 | missed PASS: 3
Correct image PASS: 70.0% | clear mismatch FAILED: 60.0% | BLOCKED: 60.0%
Error codes: {'VISION_INCONCLUSIVE': 24}
Latency p50/p95 (ms): 2054.5 / 5098.3
Mean input/output tokens per attempt: 1689.5 / 326.2
Usage reported: 40/40; missing usage contributes zero (a lower bound, not an exact bill).
Served models: ['claude-haiku-5-5']

| Image | PASSED | FAILED | BLOCKED | Confidence min/median/max | Most common model summary |
| --- | ---: | ---: | ---: | --- | --- |
| hamburg-berlin.png | 5 | 0 | 0 | 0.9/0.9/0.9 | The green start marker sits on Hamburg and the red end marker sits on Berlin, joined by a continuous blue route line. |
| hamburg-munich.png | 0 | 5 | 0 | 0.9/0.9/0.9 | Green start marker sits on Hamburg; red end marker sits on München, joined by a continuous blue route line. |
| hamburg-potsdam.png | 0 | 0 | 5 | 0.6/0.6/0.8 | Green start marker sits on Hamburg; red end marker sits just northwest of Potsdam label, near Berlin-Potsdam area, with a continuous blue route between them. |
| berlin-hamburg.png | 0 | 1 | 4 | 0.85/0.85/0.9 | Green start marker is at Berlin and red end marker is at Hamburg, joined by a continuous blue route line. |
| bremen-berlin.png | 0 | 3 | 2 | 0.85/0.9/0.9 | Green start marker sits at Bremen and red end marker at Berlin, joined by a continuous purple route passing Hannover and Magdeburg. |
| hamburg-berlin-viewport.png | 2 | 0 | 3 | 0.8/0.85/0.9 | Green start marker sits on Hamburg and red end marker sits on Berlin, joined by a continuous blue route line. |
| no-route.png | 0 | 0 | 5 | 0.8/0.85/0.9 | No green start or red end marker is visible on this map of central Europe, and no route line appears. |
| tiles-blank.png | 0 | 0 | 5 | 0.95/0.95/0.95 | The map shows only blank tiles with map controls and attribution; no green start marker, red end marker, labels, or route are visible. |

| Threshold (same observations) | False PASS | Missed PASS |
| --- | ---: | ---: |
| 0.8 | 0 | 0 |
| 0.85 | 0 | 2 |
| 0.9 | 0 | 3 |
| 0.95 | 0 | 10 |

Acceptance:
- false_pass_zero: PASS
- correct_pass_at_least_90_percent: FAIL
- clear_mismatch_failed_at_least_80_percent: FAIL
- no_internal_errors: PASS

Ready for Clef comparison: False

Small fixed sample; model confidence is self-reported. Frozen tiles are not all future OSM appearances.
Model summaries are untrusted explanations, not proof. No prompt/label tuning or retries.
```

### Blind observation: hold-out — complete live report

Source: artifacts/calibration-20261015T072233121599Z/report.md

```markdown
# Vision calibration at 0.9

Calls: 25 | false PASS: 0 | missed PASS: 0
Correct image PASS: 100.0% | clear mismatch FAILED: 33.3% | BLOCKED: 60.0%
Error codes: {'VISION_INCONCLUSIVE': 15}
Latency p50/p95 (ms): 1859.0 / 5264.4
Mean input/output tokens per attempt: 1839.4 / 333.1
Usage reported: 25/25; missing usage contributes zero (a lower bound, not an exact bill).
Served models: ['claude-haiku-5-5']

| Image | PASSED | FAILED | BLOCKED | Confidence min/median/max | Most common model summary |
| --- | ---: | ---: | ---: | --- | --- |
| hamburg-leipzig.png | 0 | 0 | 5 | 0.85/0.85/0.85 | Green start marker is on Hamburg and red end marker is on Leipzig, joined by a continuous blue route through Hannover area. |
| rostock-berlin.png | 0 | 5 | 0 | 0.9/0.9/0.9 | Green start marker sits on Rostock; red end marker sits on Berlin, joined by a continuous purple route line. |
| berlin-hamburg-wide.png | 0 | 0 | 5 | 0.8/0.85/0.85 | The green start marker sits on Berlin and the red end marker on Hamburg, joined by a continuous blue route line. |
| hamburg-berlin-wide.png | 5 | 0 | 0 | 0.9/0.9/0.9 | Green start marker sits on Hamburg and red end marker sits on Berlin, joined by a continuous blue route line. |
| hamburg-bernau.png | 0 | 0 | 5 | 0.6/0.8/0.8 | Green start marker sits on Hamburg; red end marker lies in the Berlin area, about 50 px northeast of the Berlin label. |

| Threshold (same observations) | False PASS | Missed PASS |
| --- | ---: | ---: |
| 0.8 | 0 | 0 |
| 0.85 | 0 | 0 |
| 0.9 | 0 | 0 |
| 0.95 | 0 | 5 |

Acceptance:
- false_pass_zero: PASS
- correct_pass_at_least_90_percent: PASS
- clear_mismatch_failed_at_least_80_percent: FAIL
- no_internal_errors: PASS

Ready for Clef comparison: False

Small fixed sample; model confidence is self-reported. Frozen tiles are not all future OSM appearances.
Model summaries are untrusted explanations, not proof. No prompt/label tuning or retries.
```

### Findings from blind observations
- Original positive viewport: 3/5 were BLOCKED at confidence 0.80–0.85; standard positive was PASSED 5/5. This explains the 70% positive rate, not a wrong city reading.
- Original reversed route: model observed green Berlin/red Hamburg correctly, but confidence was often 0.85, so Python BLOCKED 4/5 and FAILED 1/5. Bremen similarly had 2/5 below threshold. Munich FAILED 5/5.
- Hold-out Leipzig and reversed route: reported the correct endpoint cities/colours but confidence 0.80–0.85 led to BLOCKED 5/5 each. Rostock FAILED 5/5. Correct fresh viewport PASSED 5/5.
- Potsdam and Bernau near-misses were BLOCKED, never PASSED. No-route/blank cases remained BLOCKED. Frozen labels/hashes are unchanged (verified after all measurements).

### Threshold/Clef decision for the user
At the requested 0.90, BOTH sets still fail the full acceptance bar, so the automatic "Claude passed → Clef" gate is not met. Keep the contract unchanged at 0.90.

Replay at 0.80 (zero new calls) meets all four proposed metrics on both sets, with zero false PASS, 100% correct positives and 100% clear-mismatch FAILED. At 0.85, original positive PASS is only 80% (below bar), although hold-out meets the bar. This suggests evaluating 0.80 as the next user-approved experiment rather than another prompt edit. It is post-hoc threshold selection on a small sample, NOT production-accuracy evidence. Do not silently adopt it or claim a clean untouched hold-out after using it to select a threshold. A further frozen validation set would be appropriate for confirming a chosen threshold.

### Known limitations
- Hold-out image files are uncommitted under the explicit user instruction. Hash freeze/checkpoint substitutes for the brief's requested pre-change commit until review; history documents the ordering, but the Git checkpoint is still pending.
- Marker/city observations can still be wrong. Python compares reports, not coordinates; sample confidence is self-reported. Two fixed sets and repeated responses do not establish production safety.
- Legacy anchored observations are a different schema. Their reports and threshold tables remain frozen; current pure replay uses blind-map-v2 observations. Each saved request includes its instructions and schema for audit.
- No Clef adapter, D2 fallback or HTML report added. No production threshold change. No new live full Runner run requested or made in this follow-up; 503 diagnostics tested offline, as the prior failure was already traced to OSM.

### Required final test output
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
test_translator_receives_suite_catalog_and_hints (test_vocabulary.VocabularyTests.test_translator_receives_suite_catalog_and_hints) ... Executing <Task finished name='Task-353' coro=<VocabularyTests.test_translator_receives_suite_catalog_and_hints() done, defined at /Users/xuenilaw/Documents/myProject/WBS/tests/test_vocabulary.py:21> result=None created at /opt/homebrew/Cellar/python@3.14/3.14.8/Frameworks/Python.framework/Versions/3.14/lib/python3.14/asyncio/runners.py:110> took 0.112 seconds
ok

----------------------------------------------------------------------
Ran 70 tests in 17.812s

OK
```

## Review round 2 (Claude, 2026-10-15)
Verdict: **APPROVED. Ready to commit and push.** The calibration loop is closed for this project phase.
Verified: 70 tests OK; `observe(image)` takes image bytes only (no cities/requirement/filename reach the model);
`decide()` is pure and owns direction and city comparison; frozen labels/hashes are unchanged; the order
(adapter → measure → hold-out freeze → blind → measure) was followed, and 3 stage reports are preserved.

Decision (reviewer recommendation, user accepted given the schedule):
- **The hard rule is met:** 0 false PASS on the original set (40 calls) and the fresh hold-out (25 calls) at 0.90.
  A wrong route never passed. This was the safety requirement.
- The remaining shortfall is **wrong routes ending as BLOCKED instead of FAILED** (confidence 0.80–0.85). That is the
  safe direction: BLOCKED = "unable to determine" (the Day 4 plan item), so a human reviews it in the report. Record
  it as a known limitation; don't keep tuning.
- **Keep `min_confidence` at 0.90.** Don't adopt 0.80: it was chosen after seeing both sets (post-hoc) and would need a
  third frozen set to confirm. That's out of scope for the schedule.
- The Clef comparison uses this exact pipeline (blind-map-v2, both frozen sets, `--runs 5`) and is reported side by side.
