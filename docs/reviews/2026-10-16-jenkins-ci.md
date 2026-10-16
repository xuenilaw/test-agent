# Task: audit.csv + Docker/Jenkins CI pipeline, with a step-by-step learning guide
Status: APPROVED (code); first real Jenkins build pending after push
Workflow step(s): CI/CD (trigger + artifacts); prepares diagram steps 8–10 (audit agent, approval, Jira = next task)
Assigned: Codex · Reviewer: Claude · Brief written 2026-10-16

## Context and user decisions (2026-10-16)
- The user wants to **learn** Docker + Jenkins CI/CD. **Teaching is part of the deliverable:** a step-by-step guide the user follows themselves,
  with an explanation of *why* at each step, linked to testing concepts where useful. The user is a test engineer, new to Jenkins internals.
- Jenkins runs locally in **Docker Desktop** (the user had Jenkins before; it isn't running now).
- The Excel file is kept **in git**; a push of a changed workbook triggers the pipeline (Poll SCM; a local Jenkins can't receive GitHub webhooks).
- **No Slack.** Human-in-the-loop will use the **Jenkins approval (`input`) step** in the next task. The user has a free Jira account (next task).
- The HTML report is **downloaded** from Jenkins (no HTML Publisher, because Jenkins' default CSP breaks inline CSS/images).
- Next task (not this one): audit agent reads `audit.csv` → ticket suggestions → Jenkins approval → Jira.
Principles unchanged. Hand off before committing.

---

## Part A: `audit.csv` (deterministic, no LLM)
Machine-readable log for the audit agent (the HTML stays for humans). It also opens in Excel.
- Written automatically at the end of `suite` and `repeat` into the same folder; also `python -m test_agent audit <suite-or-repeat-folder>`
  to build it from existing artifacts.
- **One row per action, check and cleanup action** (and one row per case with the case status), with these columns:
  `row_id` (stable, e.g. `R0007`), `run_id`, `repeat_index`, `case_id`, `case_name`, `case_status`, `designed_outcome`, `outcome_as_designed`, `step`,
  `row_type` (case/action/check/cleanup), `kind_or_action`, `target`, `status`, `reason_code`, `reason` (one line, truncated),
  `expected`, `actual` (short human-readable, as in the HTML), `locator_source`, `healed`, `vision_provider`, `vision_model`, `min_confidence`,
  `vision_min_selected_probability`, `borderline` (Yes/No), `faults`, `duration_s`, `screenshot` (relative path), `results_json` (relative path).
- Standard CSV (UTF-8, header row, RFC 4180 quoting). **Formula-injection safety:** prefix any cell starting with `=`, `+`, `-`, `@` with `'`,
  because Excel could execute it (the cells contain text from Excel, the page and models).
- Tests: rows for PASSED/FAILED/BLOCKED/NOT_RUN, a healed row, a vision-click row, a borderline row, stable row ids, a formula-injection cell neutralized, multi-run repeat.

## Part B: Docker + Jenkins pipeline
### Files (in the repo)
- `ci/jenkins/Dockerfile`: the Jenkins LTS controller image plus the Docker CLI (so pipelines can start containers).
- `ci/jenkins/plugins.txt`: preinstalled plugins (pipeline, git, docker-workflow, credentials-binding, and anything else required), with pinned versions where practical.
- `ci/docker-compose.yml`: runs the controller with a persistent `jenkins_home` volume, port bound to **127.0.0.1:8080 only**, and the Docker socket mounted.
  The guide must state plainly that mounting the Docker socket gives Jenkins full control of Docker on the Mac. That's fine for local learning,
  not for a shared or production server.
- `Jenkinsfile` (repo root), declarative:
  - **Agent:** `docker { image 'mcr.microsoft.com/playwright/python:<tag>' }`, with the tag **matching the Playwright version in `uv.lock`** (the browser must
    match the Python package; explain this in the guide). Install `uv` inside the agent in a reproducible way.
  - **Trigger:** `pollSCM('H/5 * * * *')`.
  - **Stages:** Setup (`uv sync --locked`) → Unit tests (`uv run python -m unittest discover -s tests`) → Test suite
    (`uv run python -m test_agent suite cases/osm/WBS_testcase1_osm.xlsx --locators cases/osm/locators.json`).
    The CI workspace has no `artifacts/`, so the suite **translates from Excel with GLM on every build**. That's the real "push Excel → get report" flow. Explain this.
  - **Exit codes → build result** (teach this distinction): suite exit 0 → SUCCESS; exit 1 (a test FAILED/BLOCKED) → **UNSTABLE** (tests found
    problems, but the pipeline worked); exit 2 or a crash → **FAILURE** (the pipeline itself broke). Unit-test failure → FAILURE.
  - **Secrets:** Jenkins **credentials** (Secret text) for `OPENAI_API_KEY`, `OPENAI_BASE_URL`, `OPENAI_MODEL`, `OPENROUTER_API_KEY`,
    `ANTHROPIC_API_KEY`, bound with `withCredentials` only in the stage that needs them. No `.env` in CI, never `echo` a secret, no `set -x` around them.
    `VISION_PROVIDER=clef`, `VISION_MODEL=cloudflare/clef` are set as plain environment variables in the Jenkinsfile.
  - **Post (always):** `archiveArtifacts` for `artifacts/suite-*/**` (report.html, audit.csv, summary.json, screenshots, results) so the user can download them
    from the build page, even when the build is UNSTABLE.
  - If the repo is private, document adding a GitHub token credential for checkout.
- **Linux rendering check:** in the container, map screenshots differ slightly from macOS. After the first green CI build, compare the OSM-001 Clef
  probabilities with the Mac runs and report them (Berlin was 0.856–0.870 against 0.85 on the Mac, so it may flip to BLOCKED). Report it; don't tune.

### What Codex can and can't verify
Codex can't click through the Jenkins UI. Codex must verify everything possible from the terminal and say exactly what is verified vs. left for the user:
- `docker compose -f ci/docker-compose.yml config`, building the controller image, starting it and checking it answers on 127.0.0.1:8080, then stopping it.
- **Simulate the pipeline's agent:** run the Jenkinsfile's stages' commands inside the same Playwright image with `docker run` (mount the repo; unit tests;
  a `suite` run with `--skip-vision`, and with the user's permission one full run using local credentials passed as env vars, never written to disk).
- Validate the Jenkinsfile syntax if possible (e.g. via the running controller's linter endpoint), or state that it wasn't.

## Part C: small report wording fix
In the HTML report (display only; `results.json` unchanged), show `locator_source` as: `human` → **"locator file"**, `cache` → "cache",
`healed` → "healed (GLM)", `vision` → "vision (Claude)". Add a one-line legend under the steps table. Also use the same display values in `audit.csv`'s
`locator_source` column? **No:** keep the raw values in the CSV (machine-readable) and document them in the guide.

## Part D: the learning guide, `docs/ci/jenkins-guide.md`
In **Chinese** (like the README), with English technical terms. Numbered steps; each step has **what to do**, **why**, **what you should see**
(a checkpoint), and **if it goes wrong**. At minimum:
1. Concepts in 5 minutes: controller vs. agent, pipeline/stage/step, workspace, artifact, credential, trigger, and the build results
   SUCCESS/UNSTABLE/FAILURE, mapped to testing ideas (e.g. UNSTABLE = "tests ran and found defects").
2. Start Jenkins with `docker compose` and unlock it (where the initial admin password is and the command to print it).
3. Plugins (already preinstalled) and creating the admin user.
4. Add the credentials (screens and field names), and explain why not `.env`.
5. Create the Pipeline job "from SCM" (repo URL, branch, Jenkinsfile path); Poll SCM.
6. First build: read the stage view and the console log; where to download report.html and audit.csv.
7. Trigger by changing the Excel file and pushing; watch Poll SCM pick it up.
8. A deliberate failure exercise: e.g. push a wrong locator in a branch, or use a `--fault`, and observe UNSTABLE + the evidence. Then revert.
9. Stop/start Jenkins, where data lives (the volume), and a clean reset.
10. Troubleshooting: port in use, the Docker socket permission, Playwright version mismatch, missing credentials, OSM 503.
Keep commands copy-pasteable. The user will follow it step by step and report back; Codex then helps interactively.

## Acceptance
- [ ] Part A tests green; `audit.csv` generated for an existing repeat folder (no new runs) and pasted (first ~10 rows).
- [ ] Part B files added; terminal verification results listed (what passed, what's left for the user).
- [ ] Part C: report regenerated (no new runs), legend visible.
- [ ] Part D guide complete; the README links to it.
- [ ] Full test suite output pasted. Hand off without committing.

## Out of scope (next task)
Audit agent (LLM reads audit.csv, analysis + ticket suggestions with cited row ids validated by Python), the Jenkins approval step, and Jira ticket creation.

---

## Handoff (Codex)

### Goal and scope
Implement Parts A–D together: deterministic audit evidence, local Docker/Jenkins pipeline, human-friendly locator wording and a Chinese learning guide. Prior approved collapsible-step changes were already uncommitted at the start and are preserved. No audit agent, input approval or Jira integration added.

### What changed
- `src/test_agent/audit.py`: UTF-8 / RFC 4180 CSV, exact requested columns, one case/action/check/cleanup row, deterministic sequential row IDs, repeat indexes, raw locator sources, existing reason codes, relative evidence paths, short human-readable expected/actual, provider/model/threshold/probability and borderline flags. Whitespace is normalized before formula-prefix detection; cells beginning =/+/-/@ receive an apostrophe. Existing JSON is read-only. Missing results still produce a case row; outside-artifact paths are not linked.
- `src/test_agent/cli.py`, `suite.py`, `repeatability.py`: `audit <folder>` command plus automatic suite/repeat CSV generation. Repeat children and aggregate each have their own CSV. No API calls in offline audit/report commands.
- `src/test_agent/reporting.py`: locator file / cache / healed (GLM) / vision (Claude) labels with a legend under each step table. Technical JSON and CSV retain raw machine values.
- `Jenkinsfile`: Declarative Playwright 1.63.0 agent, matching uv.lock; pinned uv 0.12.17; fresh checkout/workspace per build; Setup → Unit tests → Test suite; Poll SCM H/5; five credentials scoped to suite stage; plain Clef configuration; suite exit result mapping; post always artifact archive; concurrency disabled, timeout and build retention.
- `ci/suite_result.py`: completed results map to SUCCESS/UNSTABLE; crash/input failure/missing or inconsistent evidence maps to FAILURE. This is necessary because a Python crash can also return exit 1. Setup cleans the workspace, so the checker requires exactly one suite folder with final summary, HTML and CSV.
- `ci/jenkins/Dockerfile`, `plugins.txt`, `ci/docker-compose.yml`: pinned Jenkins LTS 2.580.1 / JDK21, Docker CLI 29.7.2 and direct plugin versions. Local controller with persistent volume, socket mount, and only 127.0.0.1:8080 published. Guide states the root/socket authority explicitly. Transitive plugin dependencies are resolved by Jenkins plugin manager, not fully locked.
- `docs/ci/jenkins-guide.md`: Chinese numbered guide with action/why/checkpoint/troubleshooting, private GitHub checkout credentials, five model credentials, fresh GLM translation every build, artifact download/CSP, fault exercise on a separate branch, polling scope, native Jenkins conflict, stop/start/reset and Linux calibration check. README links to it and documents audit CLI/raw CSV values.
- `tests/test_audit.py`, `tests/test_ci.py`: audit rows/statuses, healing/click/borderline, stable IDs, repeats, CSV round-trip and formula safety, missing/outside evidence, CLI rejection, raw/display wording; CI exit/evidence classification.
- `tests/browser_support.py` and five existing browser test modules: respect PLAYWRIGHT_BROWSERS_PATH in skip detection. Initial Linux check exposed 35 silent skips from Mac-only `.browsers` detection. Fixed rather than accepting the partial test run; final Linux execution includes browser tests.

### How to verify / learning handoff
```sh
uv run python -m unittest discover -s tests -v
uv run python -m test_agent audit artifacts/repeat-20261015T120006438910Z
uv run python -m test_agent report artifacts/repeat-20261015T120006438910Z
docker compose -f ci/docker-compose.yml config
docker compose -f ci/docker-compose.yml build
```
Audit/report regeneration also performed for the three existing suite-* children. Existing repeat CSV has 123 rows, including 9 case rows. SHA-256 checks protect all 70 pre-existing JSON files in that repeat tree; no changes to original verdicts or thresholds. New live Linux verification is separate under `artifacts/ci-linux-20261016/`.
Offline report render: 0 HTTP requests, body/viewport 1280, locator labels visible in `ci-locator-step.png` with step 4 opened; the legend itself is captured in `ci-locator-legend.png`. Screenshot and `ci-locator-render-check.json` are in the saved repeat folder.

### Environment findings and verification boundaries
- Docker Desktop 4.88.1 / Engine 29.7.2 Linux arm64 is available. Compose configuration validates and the controller image builds successfully.
- Docker's normal credential helper hung on public pulls. Downloads/build succeeded using a temporary anonymous Docker config under /private/tmp; user config/keychain were not modified.
- Homebrew Jenkins (PID 836 at inspection) already listens on Mac 127.0.0.1:8080. The HTTP 200 there belongs to the old service, not our controller. It was not stopped. A disposable Compose override on 8081 was tried.
- Docker normal container starts stalled in Created state, including a no-network Java probe. Normal docker run / Compose runtime verification therefore could not finish. Cancelled owned clients and removed only the disposable verification containers/network/volume; n8n and Homebrew Jenkins untouched. No Docker restart/prune performed.
- Alternative isolated BuildKit runtime verifies the same images without normal container startup. Jenkins started, answered HTTP 200 at 127.0.0.1:8080 **inside that runtime**, and its real Declarative `Converter.scriptToPipelineDef` validated the current Jenkinsfile. Server stopped on exit. This is parser verification, not an end-to-end SCM/credential/job execution.
- Controller evidence: `artifacts/ci-linux-20261016/controller/verification.txt` records HTTP 200, WBS_JENKINSFILE_VALIDATED and Docker CLI 29.7.2. No initial admin password printed or exported.
- Linux Playwright image matches lock: v1.63.0-noble, digest `sha256:72bd171a9ffc2b4b59532aaa6210e21014d07093120dc25528870c0b840da1f0`. Setup commands execute in that image. Final Linux unit output is in `artifacts/ci-linux-20261016/unit/unit-tests.log`.
- User explicitly authorized one full live Linux suite using credentials as environment variables. BuildKit secret-env mounts supply the local keys without .env, key values in command arguments, Dockerfile ENV, or exported files. Skip-vision and full-suite results follow below.
- Left for user after review/push: resolve which Jenkins installation owns 8080; run Compose normally after Docker startup is healthy; unlock/create admin; configure credentials and SCM job; exercise Poll SCM and download artifacts; verify SUCCESS/UNSTABLE/FAILURE in a real job. Jenkins UI was not used by Codex.

### Existing CSV sample (header + first 10 rows)
```csv
row_id,run_id,repeat_index,case_id,case_name,case_status,designed_outcome,outcome_as_designed,step,row_type,kind_or_action,target,status,reason_code,reason,expected,actual,locator_source,healed,vision_provider,vision_model,min_confidence,vision_min_selected_probability,borderline,faults,duration_s,screenshot,results_json
R0001,run-20261015T120006500256Z,1,OSM-001,Destination ETA check,PASSED,PASSED,Yes,,case,,,PASSED,,,PASSED,PASSED,,No,,,,,No,none,5.119,,suite-20261015T120006439175Z/run-20261015T120006500256Z/cases/OSM-001/results.json
R0002,run-20261015T120006500256Z,1,OSM-001,Destination ETA check,PASSED,PASSED,Yes,1,action,navigate,OSM Website,PASSED,,,navigate OSM Website → https://www.openstreetmap.org/,PASSED,,No,,,,,No,none,,suite-20261015T120006439175Z/run-20261015T120006500256Z/cases/OSM-001/screenshots/step-1.png,suite-20261015T120006439175Z/run-20261015T120006500256Z/cases/OSM-001/results.json
R0003,run-20261015T120006500256Z,1,OSM-001,Destination ETA check,PASSED,PASSED,Yes,1,check,visible,OSM Website,PASSED,,,visible,visible ✓,human,No,,,,,No,none,,suite-20261015T120006439175Z/run-20261015T120006500256Z/cases/OSM-001/screenshots/step-1.png,suite-20261015T120006439175Z/run-20261015T120006500256Z/cases/OSM-001/results.json
R0004,run-20261015T120006500256Z,1,OSM-001,Destination ETA check,PASSED,PASSED,Yes,2,action,click,route-planning control,PASSED,,,click route-planning control,PASSED,human,No,,,,,No,none,,suite-20261015T120006439175Z/run-20261015T120006500256Z/cases/OSM-001/screenshots/step-2.png,suite-20261015T120006439175Z/run-20261015T120006500256Z/cases/OSM-001/results.json
R0005,run-20261015T120006500256Z,1,OSM-001,Destination ETA check,PASSED,PASSED,Yes,2,check,visible,starting-point field,PASSED,,,visible,visible ✓,human,No,,,,,No,none,,suite-20261015T120006439175Z/run-20261015T120006500256Z/cases/OSM-001/screenshots/step-2.png,suite-20261015T120006439175Z/run-20261015T120006500256Z/cases/OSM-001/results.json
R0006,run-20261015T120006500256Z,1,OSM-001,Destination ETA check,PASSED,PASSED,Yes,2,check,visible,destination field,PASSED,,,visible,visible ✓,human,No,,,,,No,none,,suite-20261015T120006439175Z/run-20261015T120006500256Z/cases/OSM-001/screenshots/step-2.png,suite-20261015T120006439175Z/run-20261015T120006500256Z/cases/OSM-001/results.json
R0007,run-20261015T120006500256Z,1,OSM-001,Destination ETA check,PASSED,PASSED,Yes,3,action,select,travel-mode selector,PASSED,,,select travel-mode selector → Car,PASSED,human,No,,,,,No,none,,suite-20261015T120006439175Z/run-20261015T120006500256Z/cases/OSM-001/screenshots/step-3.png,suite-20261015T120006439175Z/run-20261015T120006500256Z/cases/OSM-001/results.json
R0008,run-20261015T120006500256Z,1,OSM-001,Destination ETA check,PASSED,PASSED,Yes,3,check,selected,travel-mode selector,PASSED,,,Car,car ✓,human,No,,,,,No,none,,suite-20261015T120006439175Z/run-20261015T120006500256Z/cases/OSM-001/screenshots/step-3.png,suite-20261015T120006439175Z/run-20261015T120006500256Z/cases/OSM-001/results.json
R0009,run-20261015T120006500256Z,1,OSM-001,Destination ETA check,PASSED,PASSED,Yes,4,action,fill,starting-point field,PASSED,,,fill starting-point field → Hamburg,PASSED,human,No,,,,,No,none,,suite-20261015T120006439175Z/run-20261015T120006500256Z/cases/OSM-001/screenshots/step-4.png,suite-20261015T120006439175Z/run-20261015T120006500256Z/cases/OSM-001/results.json
R0010,run-20261015T120006500256Z,1,OSM-001,Destination ETA check,PASSED,PASSED,Yes,4,action,fill,destination field,PASSED,,,fill destination field → Berlin,PASSED,human,No,,,,,No,none,,suite-20261015T120006439175Z/run-20261015T120006500256Z/cases/OSM-001/screenshots/step-4.png,suite-20261015T120006439175Z/run-20261015T120006500256Z/cases/OSM-001/results.json
```


### Live Linux checks (one skip-vision + one authorized full run)
Normal docker run remained blocked; these execute inside the matching Playwright image via BuildKit RUN instead. The clean source copy excludes .env, Mac .venv/.browsers, cached plans and locator cache. No --reuse, no retries, no threshold changes. Tests/Setup run without model credentials; each suite RUN receives keys only through secret environment mounts. The uncommitted source copy has no .git, so simulation Git metadata may be unavailable; the real SCM job records its checkout commit.

| Check | Result / evidence |
| --- | --- |
| Linux Setup + Unit tests | `uv==0.12.17`, `uv sync --locked`; 136 tests, all passed, **0 skipped**, 38.049 s. `artifacts/ci-linux-20261016/unit/unit-tests.log` |
| Skip-vision suite | exit 1 → UNSTABLE by the real `ci/suite_result.py`; OSM-001 BLOCKED (VISION_SKIPPED), OSM-002 BLOCKED (GLM TRANSLATION_REJECTED), OSM-003 PASSED. Fresh GLM translation for all 3. `skip/suite-20261016T103245113583Z/summary.json`, HTML, audit.csv |
| Full suite (exactly once, user authorized) | exit 1 → UNSTABLE; OSM-001 PASSED, OSM-002 FAILED, OSM-003 PASSED. Fresh GLM translation, all 3 reused=false. `full/suite-20261016T103434475366Z/summary.json`, HTML, audit.csv |
| OSM-001 full vision | Clef/cloudflare/clef, threshold 0.85; selected start Hamburg **0.9172**, end Berlin **0.8842**, continuous line **0.9722**. Route check PASSED. Saved Mac Berlin range was 0.856–0.870; Linux observation is above it, not borderline under the display's 0.03 band. |
| OSM-002 full vision + duration | Route picture BLOCKED: Hamburg 0.5296, München 0.6247, line continuous 0.7345. Duration **456 min**, fails <180. Overall case FAILED as designed; route geometry remains unverified. |
| Secrets | Byte scan of exported Linux evidence found none of the configured API-key values. No .env modified or included. |

The skip run's GLM rejection concerned “Munich or München” spelling ambiguity. The full run independently translated it successfully. Both first results are retained: this exposes translation variability under fresh CI translation, not a reason to bypass validation or retry until green. A future Translator review can address it separately.

This is a single Linux/Mac observation with maps captured at different times, not controlled calibration or proof that Linux is more accurate. Existing calibration caveats remain. A real Jenkins job still needs its first build / SCM / credentials / archive / Poll SCM checks and a follow-up probability comparison.

Reproduction evidence (no secrets) is saved in `artifacts/ci-linux-20261016/verification/`: build-time verification Dockerfiles, parser init script and current-source SHA-256 manifest. Linux console logs and exit-code.txt are in skip/ and full/. No Linux live reruns were made after the one full run.

### Acceptance and remaining work
- [x] A: CSV tests pass; saved repeat/children exported without new runs; header + 10 rows pasted above.
- [x] B: repository files added, Compose config and image build passed, real parser/startup and Linux commands checked in isolated build runtimes. Normal Compose/docker run startup remains an explicit environment limitation; no claim of a real Jenkins job execution.
- [x] C: saved reports regenerated; locator legend rendered offline; original JSON unchanged.
- [x] D: complete Chinese guide linked from README. Includes known 8080 conflict and user checkpoints.
- [x] Full local test output below; Linux full output below. No commit or push.

### Full local test output
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
test_suite_preflights_faults_and_only_injects_matching_cases (test_day5.FaultInputTests.test_suite_preflights_faults_and_only_injects_matching_cases) ... Executing <Task finished name='Task-317' coro=<FaultInputTests.test_suite_preflights_faults_and_only_injects_matching_cases() done, defined at /Users/xuenilaw/Documents/myProject/WBS/tests/test_day5.py:39> result=None created at /opt/homebrew/Cellar/python@3.14/3.14.8/Frameworks/Python.framework/Versions/3.14/lib/python3.14/asyncio/runners.py:110> took 0.114 seconds
ok
test_unknown_fault_exit_two_before_browser (test_day5.FaultInputTests.test_unknown_fault_exit_two_before_browser) ... ok
test_borderline_pass_is_display_only_and_readable_numbers_remain (test_day6.Day6Tests.test_borderline_pass_is_display_only_and_readable_numbers_remain) ... ok
test_clef_route_configuration_uses_separate_claude_for_clicks (test_day6.Day6Tests.test_clef_route_configuration_uses_separate_claude_for_clicks) ... ok
test_collapsed_step_keeps_borderline_badge_and_cleanup_empty_is_not_run (test_day6.Day6Tests.test_collapsed_step_keeps_borderline_badge_and_cleanup_empty_is_not_run) ... ok
test_missing_provider_entry_rejects_before_browser (test_day6.Day6Tests.test_missing_provider_entry_rejects_before_browser) ... ok
test_missing_screenshot_or_outside_asset_does_not_break_or_link_report (test_day6.Day6Tests.test_missing_screenshot_or_outside_asset_does_not_break_or_link_report) ... ok
test_per_provider_thresholds_validate_without_hidden_default (test_day6.Day6Tests.test_per_provider_thresholds_validate_without_hidden_default) ... ok
test_readability_summary_page_type_and_human_formatting (test_day6.Day6Tests.test_readability_summary_page_type_and_human_formatting) ... ok
test_repeat_analysis_reports_status_and_step_differences_and_probability_spread (test_day6.Day6Tests.test_repeat_analysis_reports_status_and_step_differences_and_probability_spread) ... ok
test_repeat_never_translates_and_writes_html_json (test_day6.Day6Tests.test_repeat_never_translates_and_writes_html_json) ... Executing <Task finished name='Task-359' coro=<Day6Tests.test_repeat_never_translates_and_writes_html_json() done, defined at /Users/xuenilaw/Documents/myProject/WBS/tests/test_day6.py:255> result=None created at /opt/homebrew/Cellar/python@3.14/3.14.8/Frameworks/Python.framework/Versions/3.14/lib/python3.14/asyncio/runners.py:110> took 0.384 seconds
ok
test_report_escapes_all_untrusted_text_and_embeds_offline_thumbnails (test_day6.Day6Tests.test_report_escapes_all_untrusted_text_and_embeds_offline_thumbnails) ... ok
test_saved_clef_replay_point85_zero_false_and_missed_pass_both_sets (test_day6.Day6Tests.test_saved_clef_replay_point85_zero_false_and_missed_pass_both_sets) ... ok
test_steps_and_cleanup_are_collapsed_with_safe_short_summaries (test_day6.Day6Tests.test_steps_and_cleanup_are_collapsed_with_safe_short_summaries) ... ok
test_ambiguous_locator_reports_count (test_executor.BrowserExecutorTests.test_ambiguous_locator_reports_count) ... ok
test_delayed_form_initialization_waits_before_filling (test_executor.BrowserExecutorTests.test_delayed_form_initialization_waits_before_filling) ... ok
test_duration_failure_and_cleanup (test_executor.BrowserExecutorTests.test_duration_failure_and_cleanup) ... Executing <Task pending name='Task-408' coro=<Page._on_route() running at /Users/xuenilaw/Documents/myProject/WBS/.venv/lib/python3.14/site-packages/playwright/_impl/_page.py:310> wait_for=<Task pending name='Task-409' coro=<run_case.<locals>.intercept() running at /Users/xuenilaw/Documents/myProject/WBS/src/test_agent/runner.py:111> cb=[Task.task_wakeup()] created at /opt/homebrew/Cellar/python@3.14/3.14.8/Frameworks/Python.framework/Versions/3.14/lib/python3.14/asyncio/tasks.py:742> cb=[AsyncIOEventEmitter._emit_run.<locals>.callback() at /Users/xuenilaw/Documents/myProject/WBS/.venv/lib/python3.14/site-packages/pyee/asyncio.py:97] created at /Users/xuenilaw/Documents/myProject/WBS/.venv/lib/python3.14/site-packages/playwright/_impl/_page.py:228> took 0.106 seconds
ok
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
Ran 136 tests in 51.304s

OK
```

### Full Linux unit test output
```text
........correct.png 1/2: PASSED
correct.png 2/2: BLOCKED
wrong.png 1/2: FAILED
wrong.png 2/2: FAILED
..........hamburg-berlin.png 1/1: PASSED
..........................................Executing <Task finished name='Task-359' coro=<Day6Tests.test_repeat_never_translates_and_writes_html_json() done, defined at /work/tests/test_day6.py:255> result=None created at /usr/lib/python3.12/asyncio/runners.py:100> took 0.241 seconds
............................................................................
----------------------------------------------------------------------
Ran 136 tests in 38.049s

OK
```

`git diff --check`: clean. Parts A–D ready for Claude review with the runtime limitations above.

## Review (Claude, 2026-10-16), Parts A–D
Verdict: **APPROVED. Commit and push** (the job checks out from GitHub, so it can't see uncommitted files), then **Build Now** once.
Verified:
- Local tests OK (136). Linux unit run: 136, 0 skipped. Codex found and fixed 35 browser tests that were silently skipped on Linux: a good catch.
- Read `Jenkinsfile`, `ci/suite_result.py`, `ci/docker-compose.yml`: correct stage order, credentials only in the suite stage, `set +x`, `test ! -f .env`,
  `deleteDir()` before checkout, SUCCESS/UNSTABLE/FAILURE mapping guarded against "crash with exit 1", port on 127.0.0.1 only, socket risk documented.
- **Live state checked by the reviewer:** container `wbs-ci-jenkins-1` is up on 127.0.0.1:8080, and job `test-agent` exists (GitHub `xuenilaw/test-agent`,
  `*/main`, `Jenkinsfile`) with **0 builds so far**. The guide covers push-before-build and "Build Now once to register Poll SCM" (sections 0 and 5).
- `audit.csv` sample: columns, stable row ids, raw `locator_source`, relative paths, as specified. HTML legend shows "locator file".
- Linux live run: OSM-001 PASSED (Berlin 0.884, not borderline), OSM-002 FAILED (456 min), OSM-003 PASSED → UNSTABLE, as designed.

Findings:
1. **SHOULD (put in the next task):** **fresh GLM translation makes CI noisy.** In the Linux skip-vision run, OSM-002 was `TRANSLATION_REJECTED`
   ("Munich or München" ambiguity); the full run translated fine. With translation on every build, a build can turn UNSTABLE for a reason
   unrelated to the app. Fix: add a suite hint in `cases/osm/vocabulary.json` ("München is the German name of Munich; the workbook city is
   authoritative; this is not an ambiguity"), plus a regression test with the rejected wording. The audit agent must classify
   `TRANSLATION_REJECTED` as **test infrastructure**, never as an app bug. Longer term: reuse a validated plan when the Excel is unchanged.
2. **Watch on the first build:** the controller runs in a container and starts the agent through the host Docker socket. The docker-workflow plugin normally
   shares the workspace (`--volumes-from`), but if the Setup stage sees an empty workspace or "Jenkinsfile not found" inside the agent, this is the
   cause. Add it to the guide's troubleshooting if it happens.
3. **NIT:** transitive plugin versions aren't locked (documented). Fine for local learning.

Acceptance still open (user + Codex, after push): first real build number + result (expected **UNSTABLE**: OSM-002 FAILED by design), artifacts
downloadable, Poll SCM visible after the first build, and one Excel push picked up.
