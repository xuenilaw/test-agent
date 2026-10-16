# Task: readable Jenkins results: JUnit, simple artifacts, in-Jenkins HTML report, tidy folders
Status: IN REVIEW
Workflow step(s): CI/CD presentation (diagram step 7 inside Jenkins)
Assigned: Codex · Reviewer: Claude · Brief written 2026-10-16

## Why (user feedback after build #4)
Build #4 is UNSTABLE as designed and **did** archive `report.html`/`audit.csv`, but under deep folders
(`artifact/suite-…/translation-…/…`). The user couldn't find them, Jenkins doesn't show the test cases line by line, and there are too many report
folders per run. Goal: a user opens the build page and immediately sees per-case/per-step results, opens the HTML report with one click, and
downloads a handful of clearly named files. Keep the learning-guide style (explain why). Hand off before committing.

## Part 1: JUnit XML (Jenkins "Test Result" page)
- Generate `junit.xml` at the end of every `suite` (and an aggregate for `repeat`), plus `python -m test_agent junit <folder>` from saved results.
- Structure: one `<testsuite>` per **test case** (name `OSM-001 – Destination ETA check`, attributes tests/failures/errors/skipped/time), one
  `<testcase>` per **source step** (`classname` = case ID, `name` = `Step n – <source action, one line>`), plus one testcase for Cleanup.
  Use one step per line rather than every action/check, so it stays readable; the actions/checks go into the step's `<system-out>`.
- Status mapping (document it in the guide; it's a testing concept):
  PASSED → no child element; FAILED → `<failure message="<short reason>">`; BLOCKED → `<error message="…">`; NOT_RUN → `<skipped message="…">`.
  A borderline vision pass stays a pass, with "(borderline)" noted in `<system-out>`. A translation-rejected case → one `<error>` testcase "Translation".
- `<system-out>`: expected/actual lines (as in the HTML), `locator_source`, the Clef probabilities, the reason code, and **relative** paths to the step screenshot and `results.json`.
- XML safety: escape properly through an XML library (no string concatenation), and strip characters that are illegal in XML 1.0.
- Jenkinsfile: `junit testResults: 'reports/junit.xml', allowEmptyResults: false` in `post { always { … } }`. The JUnit step's
  own UNSTABLE marking must agree with `ci/suite_result.py` (a FAILED/BLOCKED case → UNSTABLE; a pipeline crash → FAILURE). Explain in the guide why both exist.
- `designed_outcome` isn't representable in JUnit; OSM-002 will show red. Add the "as designed" note to the testsuite's `<properties>` and say so in the guide.
- Tests: the mapping for all 4 statuses, the translation-rejected case, escaping of a malicious step text, illegal XML characters, and the counts per testsuite.

## Part 2: simple, named artifacts
- At the end of the suite stage, copy the final outputs to a fixed `reports/` folder in the workspace:
  `report.html`, `audit.csv`, `junit.xml`, `summary.json`, and **`evidence.zip`** (everything else from the suite folder: screenshots, results, traces, translations).
- Jenkinsfile: `archiveArtifacts artifacts: 'reports/**', fingerprint: true`. Stop archiving the deep `artifacts/suite-*/**` tree.
- Make `report.html` work from the `reports/` folder: thumbnails are embedded already; full-size image/trace links should point into `evidence.zip` contents
  only when unzipped next to it, so document "unzip evidence.zip next to report.html for full-size links", or rewrite the links accordingly. Pick one and test it.

## Part 3: open the HTML report inside Jenkins
- Add the **HTML Publisher** plugin to `ci/jenkins/plugins.txt` (pinned) and in `post { always { publishHTML(...) } }`, with
  `reportDir: 'reports'`, `reportFiles: 'report.html'`, `reportName: 'Test Report'`, `keepAll: true`, `alwaysLinkToLastBuild: true`, `allowMissing: true`.
- Jenkins' default Content-Security-Policy blocks inline CSS and `data:` images. For this **local** controller only, set in `ci/docker-compose.yml`
  (`JAVA_OPTS`): `-Dhudson.model.DirectoryBrowserSupport.CSP="sandbox; default-src 'none'; img-src 'self' data:; style-src 'self' 'unsafe-inline';"`.
  Scripts stay blocked (the report has none). The guide must explain the trade-off and that a shared or production server should keep the default and use downloads.
- The guide explains the rebuild/restart needed (new plugin + JAVA_OPTS) without deleting the `jenkins_home` volume.

## Part 4: fewer folders
- Simplify the suite output layout to **one folder per suite**:
  `artifacts/suite-<id>/{report.html, audit.csv, junit.xml, summary.json, cases/<case_id>/{translation/…, run/…}}`
  instead of separate top-level `translation-*` and `run-*` folders per case. Repeat: `repeat-<id>/run-<n>/…` the same way.
  Keep `report`, `audit`, `revalidate` and `--reuse` working (reuse must still find validated plans in the new location). Old artifacts stay readable,
  or produce a clear error.
- `python -m test_agent prune --keep 10`: deletes older local `suite-*`/`repeat-*`/`run-*`/`translation-*` folders under `artifacts/`, keeping the newest N.
  It **never** touches `cases/`, the frozen calibration sets or the locator cache. It defaults to **dry-run** (lists what it would delete); `--yes` actually deletes.
- Tests: the new layout end-to-end with a fake model, reuse in the new layout, prune dry-run vs `--yes`, and protected paths untouched.

## Part 5: two small carry-overs
- `vision_click.py:89`: add `error_class` and a `VISION_CAPTURE` code for screenshot failures (from `2026-10-16-jenkins-unit-timing.md`). Test it.
- Translation noise in CI: add a suite hint to `cases/osm/vocabulary.json`: "München is the German name of Munich. The city as written in the
  workbook is authoritative; an English/German name pair is not an ambiguity." Add an offline test that the hint reaches the Translator payload.
  (Revalidate the plans after the vocabulary change.)

## Acceptance
- [x] Offline tests green (full suite output pasted).
- [x] Locally generated `reports/` from an existing suite (no new runs), with `junit.xml` pasted (one testsuite).
- [ ] After review + push: one Jenkins build where the user sees **Test Result** (cases and steps as lines, a trend chart after 2+ builds),
      a **Test Report** sidebar link rendering with styles and thumbnails, and 5 artifacts on the build page. The user reports the build number.
- [x] The guide is updated (new section: "Reading the results in Jenkins": Test Result, Test Report, artifacts, the JUnit status mapping).

---

## Handoff (Codex)

### Goal
Complete Parts 1–5: readable Jenkins case/step results, five named downloads, local HTML publication, compact suite/repeat evidence with safe retention, and the two diagnostic/translation carry-overs. No commits, push, live model calls, new live acceptance runs, or restart of the running controller.

### What changed
- `src/test_agent/junit.py`: deterministic XML export and CLI `junit`, automatic suite/repeat export. Each case has source-step testcases and Cleanup, status mapping, counts, design properties, expected/actual, locator source, Clef probabilities, reason codes and relative evidence paths. XML library escaping plus XML 1.0 character filtering. Repeat names include run labels so Jenkins does not merge repeated steps.
- `src/test_agent/artifacts.py`, `ci/prepare_reports.py`: fixed `reports/` packaging: report.html, audit.csv, junit.xml, summary.json, evidence.zip. ZIP entries preserve suite-relative evidence paths. Refuses destinations mixed with unrelated files, nested output, and HTML links outside the suite. `prune --keep N` previews top-level retention across four run types combined; `--yes` deletes. Symlink directories, calibration, cases and caches stay untouched.
- `src/test_agent/cli.py`, `suite.py`, `runner.py`, `repeatability.py`: suite-owned `cases/<id>/translation/` and `run/`; repeats use `run-<n>/`. Standalone translate/run layout stays compatible. Reuse searches both layouts and copies validated evidence into the current suite. Revalidation gets the case ID from the saved plan, so a directory named `translation` works.
- `src/test_agent/reporting.py`, `audit.py`: rebase unavailable saved machine paths only to existing files inside the current report folder; keep audit run IDs tied to the enclosing suite/run summary. Old local and relocated CI evidence stays readable.
- `Jenkinsfile`, `ci/suite_result.py`: package suite results even on an ordinary failed/blocked suite exit, publish JUnit in post always, fingerprint only reports/**, and publish Test Report. Publication is in try/finally so a missing JUnit report does not prevent archive/HTML attempts. Missing/malformed/empty XML is FAILURE; cleanup errors agree with the JUnit UNSTABLE marking while preserving saved case verdicts. Existing infrastructure failures remain FAILURE.
- `ci/jenkins/plugins.txt`, `ci/docker-compose.yml`: pinned htmlpublisher:429 and the exact requested local-only CSP; scripts stay blocked. Built image verified without restarting the running controller.
- `src/test_agent/verification/vision_click.py`: screenshot exceptions become VISION_CAPTURE with safe error_class; unexpected internal errors also carry error_class. No raw exception messages or extra retries.
- `cases/osm/vocabulary.json`: exact Munich/München hint; offline payload regression verifies it reaches the Translator.
- Tests: XML statuses/counts/translation rejection/hostile text/illegal characters/repeat aggregation; portable extracted downloads; prune preview/deletion/protected paths; fake model + real offline browser layout/reuse/revalidation; capture/internal diagnostics; CI cleanup/XML classification. Existing mock fixtures updated for copying reuse and numbered repeat runs.
- `.gitignore`, `README.md`, `docs/ci/jenkins-guide.md`: ignore generated reports; document commands/layout, all Jenkins entry points, status mapping, evidence extraction, local CSP trade-off and controller rebuild/recreate with the persistent volume retained.

### How to verify
```sh
uv run python -m unittest discover -s tests -v
uv run python -m test_agent package artifacts/suite-20261016T085446352441Z --output-dir reports
uv run python -m test_agent junit artifacts/suite-20261016T085446352441Z
uv run python -m test_agent prune --keep 10

docker compose -f ci/docker-compose.yml config
docker compose -f ci/docker-compose.yml build jenkins
```

Final verification:
- Local: 144 tests, 68.721s, OK; Linux Jenkins agent image `mcr.microsoft.com/playwright/python:v1.63.0-noble`: 144 tests, 70.236s, OK. No skips. Linux repo was read-only with an isolated /tmp venv/cache and no credentials.
- Five named files generated under `/Users/xuenilaw/Documents/myProject/WBS/reports/` from existing suite `suite-20261016T085446352441Z`; no new acceptance execution. All 19 HTML evidence links resolve after extracting evidence.zip next to the report; 44 ZIP entries; no absolute/traversal entries or .env. Unit regression covers CI paths from another machine.
- Sample case counts: OSM-001: 6 tests, 0 failures/errors/skipped; OSM-002: 6 tests, 1 failure + 1 error, 0 skipped; OSM-003: 4 tests, no failures/errors/skipped. The case is FAILED while its inconclusive vision step is an error; its duration step is a failure.
- Three saved Linux translation copies revalidated offline, preserving original artifacts. Staging only rebased source-file/sidecar paths and recorded relocated_from. New VALIDATED plans: `artifacts/translation-20261016T124921531665Z/cases/OSM-001`, `translation-20261016T124921538078Z/cases/OSM-002`, `translation-20261016T124921542874Z/cases/OSM-003`. All report model_called=false, browser_executed=false, errors=[].
- Compose parses. Controller image build succeeds; manifest confirms HTML Publisher implementation version 429. Disposable network-disabled Jenkins --version process parsed `hudson.model.DirectoryBrowserSupport.CSP = sandbox; default-src 'none'; img-src 'self' data:; style-src 'self' 'unsafe-inline';` with exit 0. Plugin release source checked: https://plugins.jenkins.io/htmlpublisher/ .
- `git diff --check`: clean.

### Known limitations / open questions
- After review and push, the user must rebuild/recreate the local controller as documented (without deleting jenkins_home), then run Jenkins once. Actual Test Result navigation, styled Test Report sidebar view, five archived downloads and later trend chart remain the live acceptance checkpoint. No claim that this has already been exercised in the running Jenkins.
- Unit tests remain verbose console output; this brief publishes JUnit for Excel acceptance case steps, not for the Python unit tests.
- Published HTML embeds thumbnails; full-size image/results/trace links require downloading and extracting evidence.zip beside report.html. The dedicated reports directory should not be used as the extraction directory when rerunning package.
- For older suites, packaging retains the old relative evidence layout; new suites use compact cases/<id>/{translation,run}. An outside-suite evidence link is rejected clearly rather than producing a broken portable package.
- Cleanup may independently make a build UNSTABLE even when its case checks passed. XML and classifier now agree; actual case status is not rewritten.
- Prune keeps N newest top-level run directories across the four prefixes combined, by directory mtime; it is opt-in and no real artifacts were pruned during this task.
- The first full run found an old reuse mock that supplied no on-disk directory. Updated the fixture to match copy-on-reuse and reran successfully. Final full logs below supersede that initial failed run.

### JUnit sample (one complete testsuite)
```xml
<testsuite name="OSM-001 – Destination ETA check" time="8.225" tests="6" failures="0" errors="0" skipped="0">
    <properties>
      <property name="designed_outcome" value="PASSED" />
      <property name="outcome_as_designed" value="Yes" />
    </properties>
    <testcase classname="OSM-001" name="Step 1 – Open Street Map">
      <system-out>Source expected: OSM is open in browser
Requested: navigate OSM Website → https://www.openstreetmap.org/ · Outcome: PASSED
locator_source: —; reason_code: —; reason: —
Expected: visible · Actual: visible ✓
locator_source: human; reason_code: —; reason: —
screenshot: run-20261016T085446427316Z/cases/OSM-001/screenshots/step-1.png
results.json: run-20261016T085446427316Z/cases/OSM-001/results.json</system-out>
    </testcase>
    <testcase classname="OSM-001" name="Step 2 – Click on Route Planning">
      <system-out>Source expected: The starting-point and destination fields are visible.
Requested: click route-planning control · Outcome: PASSED
locator_source: human; reason_code: —; reason: —
Expected: visible · Actual: visible ✓
locator_source: human; reason_code: —; reason: —
Expected: visible · Actual: visible ✓
locator_source: human; reason_code: —; reason: —
screenshot: run-20261016T085446427316Z/cases/OSM-001/screenshots/step-2.png
results.json: run-20261016T085446427316Z/cases/OSM-001/results.json</system-out>
    </testcase>
    <testcase classname="OSM-001" name="Step 3 – Select Car or driving">
      <system-out>Source expected: Car/ Driving is selected
Requested: select travel-mode selector → Car · Outcome: PASSED
locator_source: human; reason_code: —; reason: —
Expected: Car · Actual: car ✓
locator_source: human; reason_code: —; reason: —
screenshot: run-20261016T085446427316Z/cases/OSM-001/screenshots/step-3.png
results.json: run-20261016T085446427316Z/cases/OSM-001/results.json</system-out>
    </testcase>
    <testcase classname="OSM-001" name="Step 4 – Enter Hamburg as the starting point and Berlin as the destination. Request directions to start the route search.">
      <system-out>Source expected: The map correctly display the route from Hamburg to Berlin.
Requested: fill starting-point field → Hamburg · Outcome: PASSED
locator_source: human; reason_code: —; reason: —
Requested: fill destination field → Berlin · Outcome: PASSED
locator_source: human; reason_code: —; reason: —
Requested: click request-directions button · Outcome: PASSED
locator_source: human; reason_code: —; reason: —
Expected: Hamburg - Berlin · Actual: Hamburg, Germany → Berlin, Germany ✓
locator_source: human; reason_code: —; reason: —
Expected: The map shows one continuous route line from Hamburg to Berlin. · Clef: start Hamburg 0.8967, end Berlin 0.8969, line continuous 0.9553 (min 0.85)
locator_source: —; reason_code: —; reason: Clef SUCCESS: start_city Hamburg 0.8967, end_city Berlin 0.8969, line continuous 0.9553 (min 0.85)
screenshot: run-20261016T085446427316Z/cases/OSM-001/screenshots/step-4.png
results.json: run-20261016T085446427316Z/cases/OSM-001/results.json</system-out>
    </testcase>
    <testcase classname="OSM-001" name="Step 5 – Observe or check the Estimated Arrival Time (ETA)">
      <system-out>Source expected: The displayed estimated driving journey duration is under 3 hours (strictly less than 180 minutes).
Expected: duration &lt; 180 min · Actual: 2:56 = 176 min ✓
locator_source: human; reason_code: —; reason: —
screenshot: run-20261016T085446427316Z/cases/OSM-001/screenshots/step-5.png
results.json: run-20261016T085446427316Z/cases/OSM-001/results.json</system-out>
    </testcase>
    <testcase classname="OSM-001" name="Cleanup">
      <system-out>Requested: fill starting-point field →  · Outcome: PASSED; locator_source: human
Requested: fill destination field →  · Outcome: PASSED; locator_source: human
results.json: run-20261016T085446427316Z/cases/OSM-001/results.json</system-out>
    </testcase>
  </testsuite>
  
```

### Test output — local
```text
test_all_row_types_statuses_vision_healing_paths_and_formula_safety (test_audit.AuditTests.test_all_row_types_statuses_vision_healing_paths_and_formula_safety) ... ok
test_csv_prefix_and_truncation_and_invalid_cli (test_audit.AuditTests.test_csv_prefix_and_truncation_and_invalid_cli) ... ok
test_html_locator_wording_keeps_raw_csv (test_audit.AuditTests.test_html_locator_wording_keeps_raw_csv) ... ok
test_missing_results_still_exports_case_and_rejects_outside_evidence (test_audit.AuditTests.test_missing_results_still_exports_case_and_rejects_outside_evidence) ... ok
test_repeat_indexes_and_row_ids_are_stable (test_audit.AuditTests.test_repeat_indexes_and_row_ids_are_stable) ... ok
test_arithmetic_and_threshold_replay (test_calibration.CalibrationTests.test_arithmetic_and_threshold_replay) ... ok
test_bad_labels_rejected (test_calibration.CalibrationTests.test_bad_labels_rejected) ... ok
test_capture_excludes_overlay_and_never_overwrites_frozen_set (test_calibration.CalibrationTests.test_capture_excludes_overlay_and_never_overwrites_frozen_set) ... ok
test_offline_run_counts_error_and_saves_report (test_calibration.CalibrationTests.test_offline_run_counts_error_and_saves_report) ... correct.png 1/2: PASSED
correct.png 2/2: BLOCKED
wrong.png 1/2: FAILED
wrong.png 2/2: FAILED
ok
test_pure_decision_threshold_boundary_and_no_mutation (test_calibration.CalibrationTests.test_pure_decision_threshold_boundary_and_no_mutation) ... ok
test_browser_detection_respects_configured_path (test_ci.CIResultTests.test_browser_detection_respects_configured_path) ... ok
test_completed_test_outcomes_are_distinct_from_infrastructure_errors (test_ci.CIResultTests.test_completed_test_outcomes_are_distinct_from_infrastructure_errors) ... ok
test_crash_missing_partial_or_malformed_evidence_is_failure (test_ci.CIResultTests.test_crash_missing_partial_or_malformed_evidence_is_failure) ... ok
test_junit_cleanup_errors_agree_with_publisher_and_bad_xml_is_failure (test_ci.CIResultTests.test_junit_cleanup_errors_agree_with_publisher_and_bad_xml_is_failure) ... ok
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
test_screenshot_failure_has_capture_code_and_safe_error_class (test_day5.FaultInputTests.test_screenshot_failure_has_capture_code_and_safe_error_class) ... ok
test_suite_preflights_faults_and_only_injects_matching_cases (test_day5.FaultInputTests.test_suite_preflights_faults_and_only_injects_matching_cases) ... ok
test_unexpected_vision_click_error_has_safe_error_class (test_day5.FaultInputTests.test_unexpected_vision_click_error_has_safe_error_class) ... ok
test_unknown_fault_exit_two_before_browser (test_day5.FaultInputTests.test_unknown_fault_exit_two_before_browser) ... ok
test_borderline_pass_is_display_only_and_readable_numbers_remain (test_day6.Day6Tests.test_borderline_pass_is_display_only_and_readable_numbers_remain) ... ok
test_clef_route_configuration_uses_separate_claude_for_clicks (test_day6.Day6Tests.test_clef_route_configuration_uses_separate_claude_for_clicks) ... ok
test_collapsed_step_keeps_borderline_badge_and_cleanup_empty_is_not_run (test_day6.Day6Tests.test_collapsed_step_keeps_borderline_badge_and_cleanup_empty_is_not_run) ... ok
test_missing_provider_entry_rejects_before_browser (test_day6.Day6Tests.test_missing_provider_entry_rejects_before_browser) ... ok
test_missing_screenshot_or_outside_asset_does_not_break_or_link_report (test_day6.Day6Tests.test_missing_screenshot_or_outside_asset_does_not_break_or_link_report) ... ok
test_per_provider_thresholds_validate_without_hidden_default (test_day6.Day6Tests.test_per_provider_thresholds_validate_without_hidden_default) ... ok
test_readability_summary_page_type_and_human_formatting (test_day6.Day6Tests.test_readability_summary_page_type_and_human_formatting) ... ok
test_repeat_analysis_reports_status_and_step_differences_and_probability_spread (test_day6.Day6Tests.test_repeat_analysis_reports_status_and_step_differences_and_probability_spread) ... ok
test_repeat_never_translates_and_writes_html_json (test_day6.Day6Tests.test_repeat_never_translates_and_writes_html_json) ... Executing <Task finished name='Task-369' coro=<Day6Tests.test_repeat_never_translates_and_writes_html_json() done, defined at /Users/xuenilaw/Documents/myProject/WBS/tests/test_day6.py:255> result=None created at /opt/homebrew/Cellar/python@3.14/3.14.8/Frameworks/Python.framework/Versions/3.14/lib/python3.14/asyncio/runners.py:110> took 0.230 seconds
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
test_package_links_work_after_extracting_evidence_and_old_paths_rebase (test_junit.JUnitTests.test_package_links_work_after_extracting_evidence_and_old_paths_rebase) ... ok
test_prune_defaults_to_preview_and_keeps_protected_paths (test_junit.JUnitTests.test_prune_defaults_to_preview_and_keeps_protected_paths) ... ok
test_status_mapping_counts_escaping_and_diagnostic_lines (test_junit.JUnitTests.test_status_mapping_counts_escaping_and_diagnostic_lines) ... ok
test_translation_rejected_missing_evidence_and_repeat_aggregate (test_junit.JUnitTests.test_translation_rejected_missing_evidence_and_repeat_aggregate) ... ok
test_fake_translation_browser_layout_reuse_and_revalidation (test_junit.LayoutTests.test_fake_translation_browser_layout_reuse_and_revalidation) ... ok
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
Ran 144 tests in 68.721s

OK

```

### Test output — Linux Jenkins agent
```text
WARNING: Running pip as the 'root' user can result in broken permissions and conflicting behaviour with the system package manager, possibly rendering your system unusable. It is recommended to use a virtual environment instead: https://pip.pypa.io/warnings/venv. Use the --root-user-action option if you know what you are doing and want to suppress this warning.
test_all_row_types_statuses_vision_healing_paths_and_formula_safety (test_audit.AuditTests.test_all_row_types_statuses_vision_healing_paths_and_formula_safety) ... ok
test_csv_prefix_and_truncation_and_invalid_cli (test_audit.AuditTests.test_csv_prefix_and_truncation_and_invalid_cli) ... ok
test_html_locator_wording_keeps_raw_csv (test_audit.AuditTests.test_html_locator_wording_keeps_raw_csv) ... ok
test_missing_results_still_exports_case_and_rejects_outside_evidence (test_audit.AuditTests.test_missing_results_still_exports_case_and_rejects_outside_evidence) ... ok
test_repeat_indexes_and_row_ids_are_stable (test_audit.AuditTests.test_repeat_indexes_and_row_ids_are_stable) ... ok
test_arithmetic_and_threshold_replay (test_calibration.CalibrationTests.test_arithmetic_and_threshold_replay) ... ok
test_bad_labels_rejected (test_calibration.CalibrationTests.test_bad_labels_rejected) ... ok
test_capture_excludes_overlay_and_never_overwrites_frozen_set (test_calibration.CalibrationTests.test_capture_excludes_overlay_and_never_overwrites_frozen_set) ... ok
test_offline_run_counts_error_and_saves_report (test_calibration.CalibrationTests.test_offline_run_counts_error_and_saves_report) ... correct.png 1/2: PASSED
correct.png 2/2: BLOCKED
wrong.png 1/2: FAILED
wrong.png 2/2: FAILED
ok
test_pure_decision_threshold_boundary_and_no_mutation (test_calibration.CalibrationTests.test_pure_decision_threshold_boundary_and_no_mutation) ... ok
test_browser_detection_respects_configured_path (test_ci.CIResultTests.test_browser_detection_respects_configured_path) ... ok
test_completed_test_outcomes_are_distinct_from_infrastructure_errors (test_ci.CIResultTests.test_completed_test_outcomes_are_distinct_from_infrastructure_errors) ... ok
test_crash_missing_partial_or_malformed_evidence_is_failure (test_ci.CIResultTests.test_crash_missing_partial_or_malformed_evidence_is_failure) ... ok
test_junit_cleanup_errors_agree_with_publisher_and_bad_xml_is_failure (test_ci.CIResultTests.test_junit_cleanup_errors_agree_with_publisher_and_bad_xml_is_failure) ... ok
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
test_screenshot_failure_has_capture_code_and_safe_error_class (test_day5.FaultInputTests.test_screenshot_failure_has_capture_code_and_safe_error_class) ... ok
test_suite_preflights_faults_and_only_injects_matching_cases (test_day5.FaultInputTests.test_suite_preflights_faults_and_only_injects_matching_cases) ... Executing <Task finished name='Task-322' coro=<FaultInputTests.test_suite_preflights_faults_and_only_injects_matching_cases() done, defined at /work/tests/test_day5.py:74> result=None created at /usr/lib/python3.12/asyncio/runners.py:100> took 0.142 seconds
ok
test_unexpected_vision_click_error_has_safe_error_class (test_day5.FaultInputTests.test_unexpected_vision_click_error_has_safe_error_class) ... ok
test_unknown_fault_exit_two_before_browser (test_day5.FaultInputTests.test_unknown_fault_exit_two_before_browser) ... ok
test_borderline_pass_is_display_only_and_readable_numbers_remain (test_day6.Day6Tests.test_borderline_pass_is_display_only_and_readable_numbers_remain) ... ok
test_clef_route_configuration_uses_separate_claude_for_clicks (test_day6.Day6Tests.test_clef_route_configuration_uses_separate_claude_for_clicks) ... ok
test_collapsed_step_keeps_borderline_badge_and_cleanup_empty_is_not_run (test_day6.Day6Tests.test_collapsed_step_keeps_borderline_badge_and_cleanup_empty_is_not_run) ... ok
test_missing_provider_entry_rejects_before_browser (test_day6.Day6Tests.test_missing_provider_entry_rejects_before_browser) ... ok
test_missing_screenshot_or_outside_asset_does_not_break_or_link_report (test_day6.Day6Tests.test_missing_screenshot_or_outside_asset_does_not_break_or_link_report) ... ok
test_per_provider_thresholds_validate_without_hidden_default (test_day6.Day6Tests.test_per_provider_thresholds_validate_without_hidden_default) ... ok
test_readability_summary_page_type_and_human_formatting (test_day6.Day6Tests.test_readability_summary_page_type_and_human_formatting) ... ok
test_repeat_analysis_reports_status_and_step_differences_and_probability_spread (test_day6.Day6Tests.test_repeat_analysis_reports_status_and_step_differences_and_probability_spread) ... ok
test_repeat_never_translates_and_writes_html_json (test_day6.Day6Tests.test_repeat_never_translates_and_writes_html_json) ... Executing <Task finished name='Task-369' coro=<Day6Tests.test_repeat_never_translates_and_writes_html_json() done, defined at /work/tests/test_day6.py:255> result=None created at /usr/lib/python3.12/asyncio/runners.py:100> took 0.473 seconds
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
test_package_links_work_after_extracting_evidence_and_old_paths_rebase (test_junit.JUnitTests.test_package_links_work_after_extracting_evidence_and_old_paths_rebase) ... ok
test_prune_defaults_to_preview_and_keeps_protected_paths (test_junit.JUnitTests.test_prune_defaults_to_preview_and_keeps_protected_paths) ... ok
test_status_mapping_counts_escaping_and_diagnostic_lines (test_junit.JUnitTests.test_status_mapping_counts_escaping_and_diagnostic_lines) ... ok
test_translation_rejected_missing_evidence_and_repeat_aggregate (test_junit.JUnitTests.test_translation_rejected_missing_evidence_and_repeat_aggregate) ... ok
test_fake_translation_browser_layout_reuse_and_revalidation (test_junit.LayoutTests.test_fake_translation_browser_layout_reuse_and_revalidation) ... ok
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
Ran 144 tests in 70.236s

OK

```
