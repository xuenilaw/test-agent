# Task: Post Actions fix + audit agent → Jenkins approval → Jira (diagram steps 8–10)
Status: APPROVED (round 7); live Jira acceptance pending
Workflow step(s): 8 (report/audit agent), 9 (human in the loop), 10 (Jira)
Assigned: Codex · Reviewer: Claude · Brief written 2026-10-16

## Context and user decisions
- Human-in-the-loop = the **Jenkins `input` approval** step (no Slack).
- Jira Cloud (free plan): site **`https://lawxueni.atlassian.net`**, project **WBS_Final_Project**, key **`WBSFP`** (a software board).
  Auth = Atlassian account email + API token, stored only as a Jenkins credential (and optionally in the local `.env` for local dry runs).
  **Never commit the email or the token.** The site URL and project key aren't secret and may live in the Jenkinsfile.
- Principle (unchanged): the LLM **drafts**, Python **validates**, a human **decides**, and Python **creates**. Nothing is created without approval.
- The user wants to learn: extend `docs/ci/jenkins-guide.md` with the new steps (Chinese, what/why/checkpoint/troubleshooting).
- **Process:** hand off before committing **and before pushing**; the reviewer reviews first.

---

## Part 0: Post Actions colour (from `2026-10-16-jenkins-junit.md`, NIT 1)
Move `junit` into `stage('Test suite') { post { always { … } } }`, so the UNSTABLE colour from OSM-002 sits on **Test suite**. The global
`post` keeps archive + publishHTML and shows green. Keep the guarantee that archive/HTML still run when `junit.xml` is missing.

## Part 1: audit agent (diagram step 8), updated 2026-10-16 with the user's request
The user wants a real **LLM analyst**, not only rule checks: it reads the **test case, the logs/results, the report data and the screenshots**, and tells the user
**what it thinks the problem is**, e.g. "software bug", "test case problem" (wrong or unrealistic expectation), "test tool / environment problem",
with an explanation, alternative causes, and a suggested next step. **The LLM does the reasoning; Python only guards against invented evidence and unsafe ticket
recommendations.**

`python -m test_agent audit-agent <suite-folder>` writes `audit_analysis.json` + `audit_analysis.md` (also copied into `reports/` and archived).

### Current user decision (2026-10-16 follow-up): Claude Haiku only
The user's latest request supersedes the GLM analyst design below. Both analysis and blind screenshot observation now use the same configured Claude Haiku model (`AUDIT_MODEL`, default `claude-haiku-5-5`) and only `ANTHROPIC_API_KEY`. Native Messages API replaces the audit's OpenAI Agents SDK loop. The user will run the live self-test; no new live run is claimed in this update. Python evidence/ticket validation and human approval stay in force.

### Original architecture (superseded by the current user decision above)
- **GLM (the existing `OPENAI_*` config, text-only) is the audit agent.** It reads the text dossiers and writes the analysis.
- **GLM never receives images.** When it needs to know something about a screenshot, it calls one tool:
  `ask_screenshot(screenshot_id, question, options)`. Python sends that **one** screenshot plus the question to **Claude Haiku vision**
  (reuse the existing Anthropic transport and `ANTHROPIC_API_KEY`; model from `AUDIT_VISION_MODEL`, default `claude-haiku-5-5`; PNG as captured, using the existing
  size guard), and returns Claude's structured answer to GLM. (GLM tool calling already worked in Day 1 through the Agents SDK `function_tool`; verify it again.)
  *Why not Clef here:* Clef only answers fixed multiple-choice questions, and the user prefers Claude's more flexible reading for audit questions. Clef stays the
  production route-vision checker; this is a separate, read-only audit helper.
- Claude's answer schema (strict JSON, validated): `choice` (one of the given options), `confidence` (0–1, self-reported), `observation` (≤ 300 chars: what is
  visible that supports the choice). The Claude prompt is **blind to the expected result**: it gets only the question and the options, never the Excel expected text or the test
  verdict (the calibration lesson: a model told the expected answer tends to confirm it).
- Tool rules, **enforced by Python before calling Claude**: the screenshot id must exist in that case's dossier; **3–8 options, one of them `unclear`**; the question
  ≤ 300 chars, neutral wording (the GLM system prompt explains anchoring: list several plausible options, don't ask "is it X? yes/no"). Limits: **≤ 5 questions per case
  and ≤ 25 per suite**; over the limit, the tool returns "limit reached". No retries. Errors return a safe code to GLM (e.g. `VISION_HTTP 429`), and the agent must then
  treat that screenshot as unknown.
- A Claude answer with `confidence` < 0.90 (the existing Claude threshold) or `choice: unclear` is reported to GLM as **"uncertain"**; GLM must not treat it as a fact.
- Each answered question gets an id like `Q-OSM-001-3` and is saved (question, options, choice, confidence, observation, screenshot id, model) in `audit_analysis.json`.
  GLM may cite it as evidence.
- Everything is untrusted data (Excel text, page text, text in screenshots, the model outputs), never instructions; say so in both system prompts.
- Agents SDK: `max_turns` bounded (e.g. 12 per case), tracing disabled. Jenkins: the audit stage needs `OPENAI_*` + `ANTHROPIC_API_KEY` credentials only.

### Input: one "case dossier" per case, **including PASSED cases** (user decision: also look for false passes)
A *false pass* (a test that passed although the expected result isn't really met; some call it a false negative) is checked for **every** case, not only for
FAILED/BLOCKED ones. Built by Python, per case:
- **Test case:** the Excel source (name, preconditions, numbered actions and expected results, post action), `designed_outcome`, the contract essentials.
- **Plan:** the translated steps (actions/checks).
- **Results/logs:** all `audit.csv` rows of that case (with `row_id`s) and short excerpts of `results.json` (reasons, codes, expected/actual, vision probabilities,
  borderline flags). No full traces.
- **Screenshot catalogue:** an id + a one-line description (step, when taken) for **each step screenshot and the vision map crop**, e.g.
  `S-OSM-003-3: after step 3 "Select 'Tracestrack Topo'"`. The images stay with Python and are reached only through `ask_screenshot`.
- One agent run per case (small, isolated failures), then the overall summary.
- For PASSED cases the agent's job is to compare the **expected text in Excel** with the evidence and the screenshots, and to say whether the pass is convincing
  (e.g. OSM-003: ask which layer is selected in the step-3 screenshot; OSM-001: the borderline vision pass).

### Output schema (strict JSON, Pydantic), per finding
`finding_id`, `case_id`, `step` (or null), `title` (≤ 120),
`likely_cause` ∈ {`software_bug`, `test_case_problem`, `test_tool_problem`, `environment_problem`, `possible_false_pass`, `needs_human_review`, `confirmed_pass`},
`confidence` ∈ {low, medium, high},
`explanation` (≤ 800: why it thinks so, referring to the test case text, the results and what the screenshot shows),
`alternative_causes` (list of {`cause` (same enum), `why`} with at most 3 entries),
`screenshot_observations` (≤ 400, or empty if no images),
`suggested_next_step` (≤ 300, e.g. "check whether < 3 h is realistic for Hamburg → Munich; if not, fix the expected result in Excel"),
`evidence_rows` (`row_id`s), `evidence_screenshots` (screenshot ids), `evidence_questions` (screenshot question ids), `recommend_ticket` (bool), `ticket_type` ∈ {`bug`, `test_case_fix`, null}, `severity` ∈ {low, medium, high}.
Plus a top-level `summary` (≤ 800) addressed to the user: the overall picture and the top suggestions.

### Python validation (guard rails; test them well)
- Every cited `row_id` and screenshot id exists and belongs to the finding's case.
- Every cited question id exists, belongs to the case, and was really answered by Claude (not invented by GLM).
- **Every case is covered by at least one finding:** PASSED cases → `confirmed_pass` or `possible_false_pass` (or `needs_human_review`); FAILED/BLOCKED cases → covered as before.
- `possible_false_pass` must cite at least one row or screenshot answer that contradicts the expected result; it **never recommends a ticket automatically**. It's shown
  prominently ("⚠ possible false pass, please check") in `audit_analysis.md` and on the approval page, so the human can decide.
- **Every FAILED or BLOCKED case is covered** by at least one finding.
- `recommend_ticket` with `ticket_type: bug` requires `likely_cause: software_bug` **and** at least one cited row with status **FAILED**. The model may still *say*
  "possibly a software bug" for a BLOCKED case (in `explanation`/`alternative_causes`), but it can't recommend a bug ticket without a FAILED check.
- `ticket_type: test_case_fix` requires `likely_cause: test_case_problem`. No tickets for `test_tool_problem`, `environment_problem` or `needs_human_review`.
- Rows whose only reason codes are `TRANSLATION_REJECTED`, `NAVIGATION`, `FORM_NOT_READY`, `SUBMIT_NO_EFFECT`, `HEAL_FAILED`, `VISION_*` can't be the only evidence for `software_bug`.
- On any violation: drop the finding and record why. For each uncovered FAILED/BLOCKED case add a deterministic fallback finding (`needs_human_review`,
  no ticket). If the model call fails: a fallback analysis with `agent_unavailable: true`. The build never fails because of the audit agent.

### `audit_analysis.md` (for the human, also shown in the Jenkins approval step and linked from the Test Report)
Per finding: case and step, **likely cause + confidence**, explanation, alternative causes, what the screenshot shows, suggested next step, ticket recommendation, evidence
(row ids, screenshot ids), and the designed outcome. Then the dropped findings with reasons, and the model/provider used (text-only or with images).
Clearly labelled: "AI suggestion, verify before acting."

### Tests (fake GLM + fake Claude vision)
Additional: the tool rejects an unknown screenshot id, <3 options, a missing `unclear`, and a call over the limits (without calling Claude); a Claude error reaches GLM as a safe code; the Claude request contains only the question, options and one image (no expected text, no verdict); a low-confidence answer is marked uncertain;
an invented question id → dropped; a PASSED case gets a verdict; `possible_false_pass` without contradicting evidence → dropped; GLM never receives image bytes
(assert the GLM payloads contain no base64 image data).
Existing:
A valid analysis with screenshots; an invented row/screenshot id → dropped; a bug ticket on BLOCKED-only evidence → dropped (while a "possibly software bug" explanation
is kept); a missing coverage → fallback; a ticket for an environment problem → rejected; a text-only model → no images sent and noted; malformed JSON / a timeout → fallback;
the dossier contains the Excel text, the rows and ≤ 4 screenshots, and never credentials or full traces.

### Live (once, after offline tests pass)
Run `audit-agent` on an existing suite with the real GLM + Claude and paste `audit_analysis.md` plus the list of screenshot questions asked (question, options, choice, confidence, observation). Expected kind of answer for OSM-002 (not enforced): step 5 likely a
**test_case_problem** (Hamburg → Munich can't be under 3 h by car) with alternatives; step 4 vision BLOCKED → test tool / needs review.

## Part 2: approval in Jenkins (diagram step 9)
- New stage **"Review tickets"** after Test suite, run only when the analysis has ≥ 1 finding with `recommend_ticket: true` (`when { expression { … } }`).
- **Run the `input` step without holding an executor or container.** Switch to top-level `agent none`, give the work stages the Docker agent, and
  `stash`/`unstash` the `reports/` folder between stages. Explain why in the guide (an input waiting for a human shouldn't block an agent).
- The input shows each proposed ticket (finding id, case, **likely cause + confidence**, ticket type, title, suggested next step, evidence rows, designed outcome; full text in `audit_analysis.md`) and lets the user **select which to create**
  (e.g. one boolean parameter per finding, default **false**). Add `timeout(time: 30, unit: 'MINUTES')` around it. On timeout or abort, **create nothing**,
  and the build result stays as it was (don't turn UNSTABLE into FAILURE because nobody clicked).
- Record who approved and which findings in `jira_decision.json` (archived).

## Part 3: Jira creation (diagram step 10)
`python -m test_agent jira create <reports-folder> --approved F1,F3 [--dry-run]`
- Jira Cloud REST API v3, with Basic auth (email + token) from `JIRA_EMAIL` / `JIRA_API_TOKEN`, plus `JIRA_SITE` and `JIRA_PROJECT=WBSFP`.
  Check the current official Atlassian docs before coding (they changed the search endpoint recently) and cite the URLs in the handoff.
- **First discover the issue types** for WBSFP through the create-metadata endpoint. `ticket_type: bug` → `Bug` if present, otherwise `Task`; `ticket_type: test_case_fix` → `Task`. Record which one was used.
- Include the agent's likely cause, confidence, explanation, alternative causes and suggested next step in the description, under a heading "AI analysis (suggestion, verify)".
- **No duplicates:** each finding gets a stable fingerprint label (e.g. `wbs-OSM-002-step5-duration`). Search for open issues in WBSFP with that label;
  if one exists, add a **comment** with the new build link instead of creating a new issue.
- Issue content (Python-built; the model's title/rationale are included as plain text, truncated):
  summary `[WBS] <case_id> <title>`; description (Atlassian Document Format): case and step, the source action and expected text from Excel, the actual result,
  reason, category, evidence row ids, designed outcome, the Jenkins build URL and the **Test Report** URL; labels `wbs-test-agent`, the fingerprint and the case id.
  **Attach** the relevant step screenshot(s) from `evidence.zip` (the attachment endpoint needs the `X-Atlassian-Token: no-check` header).
- `--dry-run` writes the exact payloads to `jira_payloads.json` and sends nothing. That's the default for local use unless `--send` is given (choose one
  safe default and document it).
- Results: `jira_results.json` (created/commented keys + URLs), archived. The Jenkinsfile sets `currentBuild.description` to the ticket links.
- Errors: safe codes (`JIRA_HTTP` with status only, `JIRA_AUTH`, `JIRA_CONFIG`, `JIRA_TIMEOUT`), with no response bodies or tokens in logs. A Jira failure marks the
  build UNSTABLE with a clear message, but archived reports stay available.
- Jenkins credential: **Username with password** `wbs-jira` (username = the Atlassian email, password = the API token). The guide shows where to create the
  token and how to add it, and says that the token has the same rights as the user account.
- Tests (fake HTTP transport): issue-type discovery (Bug present / absent), create payload (ADF valid, labels, links), attachment request + header,
  duplicate → comment instead of create, `--dry-run` sends nothing, 401 → `JIRA_AUTH`, 5xx → `JIRA_HTTP` without a body in logs.

## Acceptance
- [ ] Part 0: the Post Actions stage green on the next build (UNSTABLE now shown on Test suite).
- [x] Offline tests green (full output pasted).
- [ ] Local: `audit-agent` on an existing suite with the real configured audit model **once** (paste `audit_analysis.md`), then `jira create --dry-run` (paste one payload, without secrets).
- [ ] After review + push (by the user): one Jenkins build where the user sees the approval step, approves **one** ticket, and the ticket appears in WBSFP
      with a screenshot attached and a link back to the build; a second build adds a **comment** to that ticket instead of a duplicate.
- [x] Guide updated: the Jira token, the credential, the approval step, reading `audit_analysis.md`, and finding the ticket.

---

## Handoff (Codex)

### Goal
Implement Parts 0–3: move JUnit stage colouring, case-isolated GLM analysis with guarded Claude screenshot questions, executor-free Jenkins approval, and approved-only Jira Cloud creation/comments/attachments. Update the Chinese learning guide. No commits or pushes; no real Jira issue, comment, attachment or token changes.

### What changed
- `Jenkinsfile`: top-level agent none; Docker work stages grouped under Run tests and audit. JUnit moved into Test suite post/always (prior JUnit review NIT 1 addressed inline). Reports are stashed and published before the approval pause, then republished globally with the final decision/results. Review tickets runs only with validated candidates, defaults booleans to false, captures submitter, catches input timeout/Abort without worsening the test result, and allocates no executor/container. Jira uses a new Docker stage/unstash and credentials only after selection. Credential/API/send failures mark Jira UNSTABLE; archive/HTML remain available. Audit credentials/configuration failures also produce model-free fallbacks rather than failing the build.
- `schemas/audit_analysis.py`: strict Pydantic finding/alternative/case-analysis/screenshot-answer schemas and bounded text/enums.
- `audit_agent.py`: whitelisted per-case dossiers from saved Excel source, plan, audit.csv rows, safe result excerpts and a screenshot catalogue; one bounded text-only GLM run per case through the existing Agents SDK. Exactly one function tool, tracing disabled, max_turns=12, API retries disabled, 300-second per-case total ceiling. Writes audit_analysis.json/.md and audit_review.json. Invalid findings are dropped individually; every uncovered case, including PASSED, gets a deterministic needs_human_review/no-ticket fallback. Diagnostics now save safe exception class and phase, not provider messages.
- `audit_vision.py`: neutral question/option/ownership guards; at most five attempts per case and 25 per suite, before contacting Claude. One original PNG under 4 MiB, existing native oversized-image error guard, no expected text/verdict/filename. Structured choice/confidence/observation is schema-checked. Confidence below .90 or unclear is uncertain. Saves actual Q-* records and model name. Conservative Python contradiction checks cover layer selection, route endpoint labels/aliases and obvious broken/absent line; fuzzy interpretations remain human review.
- `audit_validation.py`: validates case/step/row/screenshot/answered-question ownership, evidence coverage, uncertainty, false-pass contradictions and ticket categories. No automatic ticket for possible_false_pass. A software_bug requires a substantive FAILED check; infrastructure-only rows do not qualify. test_case_fix requires test_case_problem. Confirming a PASSED case with screenshots requires a certain cited screenshot answer.
- `jira.py`: default offline dry-run, explicit --send + approved finding IDs for sending, hash-bound Jenkins decision check, safe Basic auth transport with redirects disabled, paginated create-metadata issue type discovery, current POST search/jql endpoint, stable case/step/source expectation/category fingerprint labels, create or comment, plain-text ADF analysis and build/report links, bounded ZIP screenshot uploads with X-Atlassian-Token: no-check. Saves exact prepared request bodies, selected type and results; safe JIRA_* codes/status only. Preserves created keys if an attachment later fails; no automatic retries.
- `cli.py`: audit-agent, its CI-only --unavailable fallback mode, and jira create --approved ... [--dry-run|--send]. The fallback mode makes no model requests. Local --approved plus --send is the explicit manual authorization; Jenkins passes the separately recorded input decision.
- `artifacts.py`, `reporting.py`: package/archive the analysis/review/decision/payload/results files; clear stale optional files when packaging a different suite; link the Markdown analysis from Test Report and prominently show possible false-pass warnings. Existing five base artifacts remain.
- `.env.example`, `README.md`, `docs/ci/jenkins-guide.md`: blank credential placeholders only; explain GLM/Claude separation, uncertainty and fallbacks, Jira token/wbs-jira, approval/executor behavior, metadata/deduplication/attachments, safe errors and default dry-run. No new dependencies/plugins needed.
- `tests/test_audit_agent.py`, `tests/test_jira.py`: 12 new offline tests (fake GLM/Claude/HTTP) for dossiers/all-case coverage, tool rejection/limits/blind transport, uncertainty/contradictions, invented/foreign evidence, valid siblings and fallback paths, native SDK tool wrapper, no-model CLI mode, XML/HTML packaging links, issue type fallback, ADF/labels/links, attachments, deduplication, dry-run, changed approval hash and safe 401/503 errors.

### How to verify
```sh
uv run python -m unittest discover -s tests -v
# Existing evidence; this invokes the configured external models (already run once below).
uv run python -m test_agent audit-agent artifacts/suite-20261016T085446352441Z
uv run python -m test_agent package artifacts/suite-20261016T085446352441Z --output-dir reports
# No recommendations in that real run, so do not invent approved IDs:
uv run python -m test_agent jira create reports --approved '' --dry-run
```
Do not repeat the live audit without the user's go-ahead: the brief authorized one live run and no retries. The example command is recorded for reproducibility, not an instruction to run it during offline review.

### Verification results
- Final local full suite: 156 tests, 70.562s, OK; Linux Playwright/Jenkins image: 156 tests, 72.017s, OK. No skips. Linux repo mounted read-only with .env masked by /dev/null and no model/Jira credentials.
- Complete Jenkinsfile validated successfully by Declarative Pipeline's /pipeline-model-converter/validate on a disposable local controller using the built project image. Validator required explicit node('') in global post; fixed before final validation.
- Disposable approval fixtures: zero busy executors during input; both timeout and explicit Abort were caught, no ticket branch executed, and an existing UNSTABLE result was preserved. The fixture harness initially used a lowercase input ID; Jenkins normalizes it to Fixture-input. Confirmed the real Abort handler/URL afterward. This did not modify the user's Jenkins controller/jobs. Temporary controller removed.
- Native Agents SDK function_tool wrapper is invoked in an offline test. The single live run also invoked it successfully twice for Claude screenshot questions (records below), proving real GLM tool calling against the configured endpoint.
- The first automatic approval review rejected the live audit as an external-data transfer. Before retrying, verified only public OSM demonstration cases/screenshots were involved, no configured credential values/full traces/inline image bytes were in the dossiers, and inspected the three final public-map screenshots. The second review accepted the explicit Part 1 Live authorization and these checks. Exactly one live suite audit ran; no bypass or repeated live analysis.
- Live outcome is a limitation, not a success claim: agent_unavailable=true, all three cases fell back to needs_human_review, no tickets recommended. Two real Claude layer questions answered at confidence .95; no usable final per-case GLM analysis survived. Original generic error records do not establish whether the cause was transport, SDK turns, or output format. Safe phase/exception-class diagnostics were added afterward for future runs; the live call was not repeated.
- Actual saved analysis packaged into reports/; real Jira dry-run with no approved IDs produced jira_payloads.json = [] and jira_results.json = {dry_run:true, issues:[], errors:[]}. No Jira requests were made.
- To give the reviewer a concrete nonempty payload without fabricating a real recommendation, generated a clearly synthetic fake-model/fake-evidence dry-run under artifacts/audit-jira-offline-preview/reports/. One complete payload is pasted below. It is CASE-2 fixture data, not a ticket proposal for the real OSM suite.
- git diff --check: clean. Existing user-authored post-hoc JUnit review retained; only the requested NIT response added there.

### Official sources checked
- Current Jira OpenAPI: https://dac-static.atlassian.com/cloud/jira/platform/swagger-v3.v3.json — confirmed GET /rest/api/3/issue/createmeta/{projectIdOrKey}/issuetypes, PageOfCreateMetaIssueTypes fields issueTypes/startAt/maxResults/total, and enhanced /search/jql. The large Issues HTML page exceeded the browser fetch limit; verified the official OpenAPI schema directly instead.
- Issue types/create: https://developer.atlassian.com/cloud/jira/platform/rest/v3/api-group-issues/
- Enhanced search: https://developer.atlassian.com/cloud/jira/platform/rest/v3/api-group-issue-search/
- Attachments: https://developer.atlassian.com/cloud/jira/platform/rest/v3/api-group-issue-attachments/
- ADF: https://developer.atlassian.com/cloud/jira/platform/apis/document/structure/
- Basic auth: https://developer.atlassian.com/cloud/jira/platform/basic-auth-for-rest-apis/
- Jenkins agent none/input: https://www.jenkins.io/doc/book/pipeline/syntax/ and https://www.jenkins.io/doc/pipeline/steps/pipeline-input-step/
- OpenAI Docs skill used for SDK tool-boundary guidance; official page fetched: https://developers.openai.com/cookbook/examples/agents_sdk/migrate-from-claude-agent-sdk/readme#final-validation-checklist . No OpenAI-hosted model substituted for GLM.

### Known limitations / open questions
- **Live analyst integration remains unconfirmed:** the single real run produced fallbacks instead of a usable diagnosis. Do not portray this as a successful OSM-002 test-case-problem finding. Review the implementation and authorize a separately instrumented run if further live diagnosis is desired. The fallback behavior is tested and honest, and it will skip ticket approval safely.
- Actual production-job Test suite/Post Actions colours, a human approving one selected ticket, real WBSFP permissions/issue types/creation/attachment, and a later build commenting instead of duplicating remain after review + explicit commit/push + user Jenkins run. No real Jira credential was read or used during the dry-run; no issue/comment/attachment sent.
- Dry-run is completely offline, so its issue type is a provisional Task name; a real send discovers metadata and may select Bug. The actual selected type is recorded. No silent live metadata request during --dry-run.
- Catalogue intentionally includes every step screenshot and map crop (OSM-001/002: 6 each; OSM-003: 3), following the updated input requirement. This supersedes the older test bullet mentioning <=4 screenshots. Only one image is sent per tool request; question and attachment limits are separate (5 per case, 25 per suite; at most 4 related attachments per finding).
- Python validates evidence identity and specific comparable contradictions, not the truth of every free-text hypothesis. Neutral wording is enforced conservatively (question starts Which/What/Where/How/Describe; anchoring/verdict terms rejected), but linguistic neutrality and model confidence are not proofs. Humans review all ticket suggestions.
- Jira enhanced search has indexing latency; timeouts may occur after a server write. No concurrent builds or automatic retries; inspect saved key/labels before another send. No cross-build Jira ledger is added.
- Audit analysis uses existing saved sources/PNG evidence; production verdicts/thresholds and historical results are unchanged. Optional report files are more than the earlier five base downloads by design.

### Actual live audit_analysis.md (single authorized run)
```markdown
# AI suggestion, verify before acting

The analyst was unavailable. Review the saved evidence; no tickets were recommended.

## F-OSM-001-review · OSM-001 · step case
Human review needed

Likely cause: needs_human_review · confidence: low
No validated model finding covers this case; review the saved evidence.

Alternatives: none
Screenshot observation: Not observed / text only
Suggested next step: Read the source case and saved evidence before deciding what to change.
Ticket: False · None
Designed outcome: PASSED
Evidence rows: R0001
Screenshots:
Answered questions:

## F-OSM-002-review · OSM-002 · step case
Human review needed

Likely cause: needs_human_review · confidence: low
No validated model finding covers this case; review the saved evidence.

Alternatives: none
Screenshot observation: Not observed / text only
Suggested next step: Read the source case and saved evidence before deciding what to change.
Ticket: False · None
Designed outcome: FAILED
Evidence rows: R0017
Screenshots:
Answered questions:

## F-OSM-003-review · OSM-003 · step case
Human review needed

Likely cause: needs_human_review · confidence: low
No validated model finding covers this case; review the saved evidence.

Alternatives: none
Screenshot observation: Not observed / text only
Suggested next step: Read the source case and saved evidence before deciding what to change.
Ticket: False · None
Designed outcome: PASSED
Evidence rows: R0033
Screenshots:
Answered questions:

## Dropped findings
unavailable: AUDIT\_UNAVAILABLE
unavailable: AUDIT\_UNAVAILABLE
unavailable: AUDIT\_UNAVAILABLE

## Screenshot questions
\{"question\_id": "Q-OSM-003-1", "case\_id": "OSM-003", "screenshot\_id": "S-OSM-003-2", "question": "Which layer option appears highlighted or selected in the map layers panel shown on screen?", "options": \["Standard", "Tracestrack Topo", "CyclOSM", "Humanitarian", "Multiple layers look selected", "unclear"\], "answered": true, "model": "claude-haiku-5-5", "status": "certain", "choice": "Standard", "confidence": 0.95, "observation": "The Map Layers panel shows the 'Standard' entry with a blue outline/border and a map-thumbnail background, while the other layer entries (CyclOSM, Cycle Map, Transport Map, Tracestrack Topo, etc.) have plain grey backgrounds and no highlight.", "contradicts\_expected": false\}
\{"question\_id": "Q-OSM-003-2", "case\_id": "OSM-003", "screenshot\_id": "S-OSM-003-3", "question": "Which layer option appears highlighted or selected in the panel after the selection step?", "options": \["Standard", "Tracestrack Topo", "Cycle Map", "Transport Map", "unclear"\], "answered": true, "model": "claude-haiku-5-5", "status": "certain", "choice": "Tracestrack Topo", "confidence": 0.95, "observation": "In the Map Layers panel, the 'Tracestrack Topo' entry has a blue highlighted border around its thumbnail, indicating it is the selected layer. The map shows a topographic-style Germany view consistent with that choice.", "contradicts\_expected": false\}

Text model: glm-4.7 (GLM; text only). Vision: claude-haiku-5-5; with images.
Agent unavailable: True

```

### Actual screenshot questions (single authorized run)
```json
[
  {
    "question_id": "Q-OSM-003-1",
    "case_id": "OSM-003",
    "screenshot_id": "S-OSM-003-2",
    "question": "Which layer option appears highlighted or selected in the map layers panel shown on screen?",
    "options": [
      "Standard",
      "Tracestrack Topo",
      "CyclOSM",
      "Humanitarian",
      "Multiple layers look selected",
      "unclear"
    ],
    "answered": true,
    "model": "claude-haiku-5-5",
    "status": "certain",
    "choice": "Standard",
    "confidence": 0.95,
    "observation": "The Map Layers panel shows the 'Standard' entry with a blue outline/border and a map-thumbnail background, while the other layer entries (CyclOSM, Cycle Map, Transport Map, Tracestrack Topo, etc.) have plain grey backgrounds and no highlight.",
    "contradicts_expected": false
  },
  {
    "question_id": "Q-OSM-003-2",
    "case_id": "OSM-003",
    "screenshot_id": "S-OSM-003-3",
    "question": "Which layer option appears highlighted or selected in the panel after the selection step?",
    "options": [
      "Standard",
      "Tracestrack Topo",
      "Cycle Map",
      "Transport Map",
      "unclear"
    ],
    "answered": true,
    "model": "claude-haiku-5-5",
    "status": "certain",
    "choice": "Tracestrack Topo",
    "confidence": 0.95,
    "observation": "In the Map Layers panel, the 'Tracestrack Topo' entry has a blue highlighted border around its thumbnail, indicating it is the selected layer. The map shows a topographic-style Germany view consistent with that choice.",
    "contradicts_expected": false
  }
]
```

### Actual Jira dry-run (no approved recommendations)
```json
{
  "dry_run": true,
  "issues": [],
  "errors": []
}
```

### Synthetic offline Jira payload example — not a real recommendation
```json
{
  "finding_id": "F-CASE-2-1",
  "issue_type": "Task",
  "type_resolution": "offline Task fallback; rediscover on send",
  "create_payload": {
    "fields": {
      "project": {
        "key": "WBSFP"
      },
      "issuetype": {
        "name": "Task"
      },
      "summary": "[WBS] CASE-2 Check the expectation",
      "description": {
        "type": "doc",
        "version": 1,
        "content": [
          {
            "type": "paragraph",
            "content": [
              {
                "type": "text",
                "text": "Case: CASE-2 · Step: 1"
              }
            ]
          },
          {
            "type": "paragraph",
            "content": [
              {
                "type": "text",
                "text": "Source action: 1. Select Topo"
              }
            ]
          },
          {
            "type": "paragraph",
            "content": [
              {
                "type": "text",
                "text": "Expected (Excel): 1. Topo is selected"
              }
            ]
          },
          {
            "type": "paragraph",
            "content": [
              {
                "type": "text",
                "text": "Actual / reason: R0007: FAILED; 7:36 = 456 min ✗; ; 456 >= 180"
              }
            ]
          },
          {
            "type": "paragraph",
            "content": [
              {
                "type": "text",
                "text": "Category: test_case_problem"
              }
            ]
          },
          {
            "type": "paragraph",
            "content": [
              {
                "type": "text",
                "text": "Evidence rows: R0007"
              }
            ]
          },
          {
            "type": "paragraph",
            "content": [
              {
                "type": "text",
                "text": "Designed outcome: FAILED"
              }
            ]
          },
          {
            "type": "paragraph",
            "content": [
              {
                "type": "text",
                "text": "Jenkins build: not available"
              }
            ]
          },
          {
            "type": "paragraph",
            "content": [
              {
                "type": "text",
                "text": "Test Report: not available"
              }
            ]
          },
          {
            "type": "heading",
            "attrs": {
              "level": 2
            },
            "content": [
              {
                "type": "text",
                "text": "AI analysis (suggestion, verify)"
              }
            ]
          },
          {
            "type": "paragraph",
            "content": [
              {
                "type": "text",
                "text": "Likely cause: test_case_problem · confidence: medium"
              }
            ]
          },
          {
            "type": "paragraph",
            "content": [
              {
                "type": "text",
                "text": "Compare the expected Topo selection with the observed evidence."
              }
            ]
          },
          {
            "type": "paragraph",
            "content": [
              {
                "type": "text",
                "text": "Alternative causes: environment_problem: The page may not have settled."
              }
            ]
          },
          {
            "type": "paragraph",
            "content": [
              {
                "type": "text",
                "text": "Screenshot observation: Visible selected radio."
              }
            ]
          },
          {
            "type": "paragraph",
            "content": [
              {
                "type": "text",
                "text": "Suggested next step: Review the source expectation."
              }
            ]
          }
        ]
      },
      "labels": [
        "wbs-test-agent",
        "wbs-case-2-step1-28de4453c186",
        "CASE-2"
      ]
    }
  },
  "search_payload": {
    "jql": "project = \"WBSFP\" AND labels = \"wbs-case-2-step1-28de4453c186\" AND statusCategory != Done ORDER BY created ASC",
    "fields": [
      "summary"
    ],
    "maxResults": 1
  },
  "attachments": [
    "run/CASE-2/screenshot.png"
  ]
}
```

### Test output — local
```text
test_all_row_types_statuses_vision_healing_paths_and_formula_safety (test_audit.AuditTests.test_all_row_types_statuses_vision_healing_paths_and_formula_safety) ... ok
test_csv_prefix_and_truncation_and_invalid_cli (test_audit.AuditTests.test_csv_prefix_and_truncation_and_invalid_cli) ... ok
test_html_locator_wording_keeps_raw_csv (test_audit.AuditTests.test_html_locator_wording_keeps_raw_csv) ... ok
test_missing_results_still_exports_case_and_rejects_outside_evidence (test_audit.AuditTests.test_missing_results_still_exports_case_and_rejects_outside_evidence) ... ok
test_repeat_indexes_and_row_ids_are_stable (test_audit.AuditTests.test_repeat_indexes_and_row_ids_are_stable) ... ok
test_claude_request_blind_one_png_and_native_size_guard (test_audit_agent.AuditAgentTests.test_claude_request_blind_one_png_and_native_size_guard) ... ok
test_dossiers_valid_analysis_all_cases_and_packaged_link (test_audit_agent.AuditAgentTests.test_dossiers_valid_analysis_all_cases_and_packaged_link) ... ok
test_dropped_model_finding_preserves_valid_sibling_and_false_pass_warning (test_audit_agent.AuditAgentTests.test_dropped_model_finding_preserves_valid_sibling_and_false_pass_warning) ... ok
test_evidence_rejections_and_human_fallbacks (test_audit_agent.AuditAgentTests.test_evidence_rejections_and_human_fallbacks) ... ok
test_false_pass_requires_certain_comparable_contradiction_no_ticket (test_audit_agent.AuditAgentTests.test_false_pass_requires_certain_comparable_contradiction_no_ticket) ... ok
test_real_sdk_tool_wrapper_text_payload_and_bounded_runner (test_audit_agent.AuditAgentTests.test_real_sdk_tool_wrapper_text_payload_and_bounded_runner) ... ok
test_tool_rejections_limits_errors_and_uncertainty (test_audit_agent.AuditAgentTests.test_tool_rejections_limits_errors_and_uncertainty) ... ok
test_ci_unavailable_mode_never_calls_models_and_still_writes_review (test_audit_agent.AuditCliTests.test_ci_unavailable_mode_never_calls_models_and_still_writes_review) ... ok
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
test_repeat_never_translates_and_writes_html_json (test_day6.Day6Tests.test_repeat_never_translates_and_writes_html_json) ... Executing <Task finished name='Task-407' coro=<Day6Tests.test_repeat_never_translates_and_writes_html_json() done, defined at /Users/xuenilaw/Documents/myProject/WBS/tests/test_day6.py:255> result=None created at /opt/homebrew/Cellar/python@3.14/3.14.8/Frameworks/Python.framework/Versions/3.14/lib/python3.14/asyncio/runners.py:110> took 0.213 seconds
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
test_bug_metadata_present_or_absent_and_attachment_header (test_jira.JiraTests.test_bug_metadata_present_or_absent_and_attachment_header) ... ok
test_dry_run_sends_nothing_and_writes_plain_adf_payload (test_jira.JiraTests.test_dry_run_sends_nothing_and_writes_plain_adf_payload) ... ok
test_duplicate_uses_new_search_and_comment_no_create (test_jira.JiraTests.test_duplicate_uses_new_search_and_comment_no_create) ... ok
test_unapproved_unknown_changed_analysis_and_safe_http_failures (test_jira.JiraTests.test_unapproved_unknown_changed_analysis_and_safe_http_failures) ... ok
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
Ran 156 tests in 70.562s

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
test_claude_request_blind_one_png_and_native_size_guard (test_audit_agent.AuditAgentTests.test_claude_request_blind_one_png_and_native_size_guard) ... ok
test_dossiers_valid_analysis_all_cases_and_packaged_link (test_audit_agent.AuditAgentTests.test_dossiers_valid_analysis_all_cases_and_packaged_link) ... ok
test_dropped_model_finding_preserves_valid_sibling_and_false_pass_warning (test_audit_agent.AuditAgentTests.test_dropped_model_finding_preserves_valid_sibling_and_false_pass_warning) ... ok
test_evidence_rejections_and_human_fallbacks (test_audit_agent.AuditAgentTests.test_evidence_rejections_and_human_fallbacks) ... ok
test_false_pass_requires_certain_comparable_contradiction_no_ticket (test_audit_agent.AuditAgentTests.test_false_pass_requires_certain_comparable_contradiction_no_ticket) ... ok
test_real_sdk_tool_wrapper_text_payload_and_bounded_runner (test_audit_agent.AuditAgentTests.test_real_sdk_tool_wrapper_text_payload_and_bounded_runner) ... ok
test_tool_rejections_limits_errors_and_uncertainty (test_audit_agent.AuditAgentTests.test_tool_rejections_limits_errors_and_uncertainty) ... ok
test_ci_unavailable_mode_never_calls_models_and_still_writes_review (test_audit_agent.AuditCliTests.test_ci_unavailable_mode_never_calls_models_and_still_writes_review) ... ok
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
test_rejected_points_never_click (test_day5.FaultBrowserTests.test_rejected_points_never_click) ... Executing <Task pending name='Task-281' coro=<FaultBrowserTests.test_rejected_points_never_click() running at /work/tests/test_day5.py:199> wait_for=<Future pending cb=[Task.task_wakeup()] created at /usr/lib/python3.12/asyncio/base_events.py:449> cb=[_run_until_complete_cb() at /usr/lib/python3.12/asyncio/base_events.py:182, <1 more>, ProtocolCallback.__init__.<locals>.cb() at /tmp/wbs-audit-venv/lib/python3.12/site-packages/playwright/_impl/_connection.py:264] created at /usr/lib/python3.12/asyncio/runners.py:100> took 0.118 seconds
ok
test_successful_human_action_never_uses_vision_and_missing_check_never_falls_back (test_day5.FaultBrowserTests.test_successful_human_action_never_uses_vision_and_missing_check_never_falls_back) ... ok
test_check_only_or_undeclared_target_rejected (test_day5.FaultInputTests.test_check_only_or_undeclared_target_rejected) ... ok
test_claude_coordinate_request_has_resize_guard_and_no_expected_values (test_day5.FaultInputTests.test_claude_coordinate_request_has_resize_guard_and_no_expected_values) ... ok
test_interception_exact_hosts_methods_and_tile_subdomains (test_day5.FaultInputTests.test_interception_exact_hosts_methods_and_tile_subdomains) ... ok
test_nonclick_actions_never_invoke_vision_fallback (test_day5.FaultInputTests.test_nonclick_actions_never_invoke_vision_fallback) ... ok
test_screenshot_failure_has_capture_code_and_safe_error_class (test_day5.FaultInputTests.test_screenshot_failure_has_capture_code_and_safe_error_class) ... ok
test_suite_preflights_faults_and_only_injects_matching_cases (test_day5.FaultInputTests.test_suite_preflights_faults_and_only_injects_matching_cases) ... Executing <Task finished name='Task-360' coro=<FaultInputTests.test_suite_preflights_faults_and_only_injects_matching_cases() done, defined at /work/tests/test_day5.py:74> result=None created at /usr/lib/python3.12/asyncio/runners.py:100> took 0.142 seconds
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
test_repeat_never_translates_and_writes_html_json (test_day6.Day6Tests.test_repeat_never_translates_and_writes_html_json) ... Executing <Task finished name='Task-407' coro=<Day6Tests.test_repeat_never_translates_and_writes_html_json() done, defined at /work/tests/test_day6.py:255> result=None created at /usr/lib/python3.12/asyncio/runners.py:100> took 0.455 seconds
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
test_bug_metadata_present_or_absent_and_attachment_header (test_jira.JiraTests.test_bug_metadata_present_or_absent_and_attachment_header) ... Executing <Task finished name='Task-718' coro=<JiraTests.test_bug_metadata_present_or_absent_and_attachment_header() done, defined at /work/tests/test_jira.py:73> result=None created at /usr/lib/python3.12/asyncio/runners.py:100> took 0.120 seconds
ok
test_dry_run_sends_nothing_and_writes_plain_adf_payload (test_jira.JiraTests.test_dry_run_sends_nothing_and_writes_plain_adf_payload) ... ok
test_duplicate_uses_new_search_and_comment_no_create (test_jira.JiraTests.test_duplicate_uses_new_search_and_comment_no_create) ... ok
test_unapproved_unknown_changed_analysis_and_safe_http_failures (test_jira.JiraTests.test_unapproved_unknown_changed_analysis_and_safe_http_failures) ... ok
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
Ran 156 tests in 72.017s

OK

```

## Review (Claude, 2026-10-16)
Verdict: **code APPROVED** (well guarded and honestly reported), **feature not yet accepted**: the one live run produced no analysis.
Verified: 156 tests OK locally. Read `audit_agent.py` / `audit_vision.py`: GLM never gets images; tool rejections are returned to GLM as codes (not raised), so a rejected
question can't abort the run; Claude gets only the question, options and one PNG; validation drops invented evidence; and the fallback never fails the build.
Read the saved live `audit_analysis.json`: all 3 cases `AUDIT_UNAVAILABLE` in phase `model_call` (not a timeout, not invalid JSON), recorded **before** the
`error_class` diagnostics existed. OSM-003 made 2 correct Claude questions (Standard 0.95, then Tracestrack Topo 0.95) before failing, so tool calling works, and the
failure happens inside the GLM run (candidates: `MaxTurnsExceeded`, an SDK `ModelBehaviorError` on a malformed tool call, or a GLM API status error). Unknown until rerun.

1. **MUST: make the analyst work live.** The user runs one local diagnostic audit (command below); Codex reads the new `phase` + `error_class` in
   `audit_analysis.json → dropped_findings`, fixes the cause (e.g. a turn budget, tolerant parsing of a fenced JSON final answer like the Translator, or a GLM
   parameter it rejects), adds a regression test, and shows **one** live `audit_analysis.md` with real findings for all 3 cases. Don't loosen any validation rule to
   get there. If GLM can't produce the schema reliably, report that and propose options (e.g. a smaller output schema) for the user to decide.
   > Codex: The user replaced the GLM analyst with Claude Haiku only. Implemented the native Anthropic tool loop, kept validation intact, and added fake HTTP end-to-end/regression coverage. The user-requested live self-test commands are in guide section 15; real Haiku findings for all three cases remain the acceptance checkpoint. This does not mark the live MUST resolved or claim live success.
2. **NIT:** the `audit_analysis.md` "Ticket: False · None" line reads like Python; use "Ticket: not recommended" / "Ticket: recommended (Bug)", as in the earlier readability round.
   > Codex: Fixed in audit_agent.py: Ticket: not recommended / Ticket: recommended (Bug or Test case fix).

Order: 1 → reviewer re-review → the user commits and pushes → Jenkins acceptance (Post Actions green, approval, one ticket, a second build comments).


## Follow-up handoff (Codex, 2026-10-16): Claude Haiku only

### Goal
Apply the user's decision to replace the GLM/Claude audit split with Claude Haiku only, and provide a self-test the user can run locally. Keep Python evidence/ticket guards, isolated blind image observations, and human approval. No commit, push, Jira writes or new live model calls.

### What changed
- `audit_agent.py`: removed OpenAI Agents SDK/GLM usage from audit. Native Anthropic Messages tool loop uses the same configured provider/model for analysis and screenshot observations. Retained the bounded 12 analyst turns, existing screenshot budgets, no automatic retries and per-case timeout. Added `submit_analysis` for structured final drafts, with existing free JSON text also accepted; all evidence/schema validation still runs afterward. Invalid/unknown tool calls return safe errors without invoking screenshot reading. Repeated call IDs, incomplete replies and turn exhaustion become safe fallback diagnostics. Reporting now says Claude Haiku and uses readable Ticket: not recommended / recommended (...) wording.
- `verification/vision_providers.py`: extracted shared `ClaudeVision.request_message` from the existing native Anthropic transport. Vision's single-text/end-turn behavior, PNG guard, timeout, safe errors and metadata remain checked by the existing tests. Audit alone can handle native tool_use/tool_result exchanges.
- `audit_vision.py`: retained blind observations and guards; removed obsolete GLM wording.
- `Jenkinsfile`: audit credential scope contains only wbs-anthropic-api-key. AUDIT_MODEL=claude-haiku-5-5 controls both analyst and image reader; translator/healing credentials in Test suite remain unchanged.
- `.env.example`: AUDIT_MODEL replaces AUDIT_VISION_MODEL in the example. The old variable remains a compatibility alias in code, with the new one taking precedence. No changes to the user's real .env.
- `cli.py`: help now identifies Claude audit; prints provider/model, finding/dropped counts, and explicitly warns when agent_unavailable makes the output a fallback.
- `tests/test_audit_agent.py`: replaced the obsolete GLM SDK test with end-to-end fake native HTTP for all three cases (two analysis turns plus one image call per case). Added native tool argument/unknown tool/truncation/turn-limit coverage, no-Claude-key/no-GLM-fallback checks and model-setting migration assertions. Existing evidence, false-pass, blind image, no-model fallback and Jira tests remain intact.
- `README.md`, `docs/ci/jenkins-guide.md` section 15: exact local offline/live commands, key/model configuration, actual output files, validation checkpoints and safe errors to report. Clarifies one Claude model in isolated analyst/observer contexts; audit no longer requires OPENAI_*.
- This review file: current user decision marked above the superseded original design; replies under the live MUST and readability NIT. The live MUST is explicitly not claimed resolved until the user's live check produces usable findings.

### How the user can test
1. Ensure local `.env` has ANTHROPIC_API_KEY (never paste it into chat). Optional AUDIT_MODEL defaults to claude-haiku-5-5.
2. Offline, no HTTP:
```sh
cd /Users/xuenilaw/Documents/myProject/WBS
uv run python -m unittest discover -s tests -p 'test_audit_agent.py' -v
```
3. One real audit of saved public OSM evidence, without rerunning browser/translation or sending Jira:
```sh
AUDIT_MODEL=claude-haiku-5-5 uv run python -m test_agent audit-agent artifacts/suite-20261016T085446352441Z
open artifacts/suite-20261016T085446352441Z/audit_analysis.md
```
This updates the suite's analysis files. The user can instead supply another complete suite folder. It sends text evidence and requested PNGs to api.anthropic.com. No GLM calls and no Jira writes.
4. Inspect audit_analysis.json: provider=anthropic, model is the chosen Haiku, agent_unavailable=false, all cases have grounded findings. A needs_human_review diagnosis can be valid, but three deterministic Human review needed / No validated model finding fallbacks do not satisfy acceptance. Report dropped_findings phase/error_class/provider_code/http_status and analysis content, not credentials. A complete inspection command is in guide section 15.

### Verification
- Focused audit/Jira/vision run: 28 tests, 6.034s, OK (fake transports only).
- Full macOS: 158 tests in 71.697s, OK, no skips.
- Full Jenkins Linux agent image: 158 tests in 75.395s, OK, no skips. Read-only repository; .env masked by /dev/null; no model/Jira credentials supplied.
- git diff --check: clean.
- Native tool protocol checked against the official Anthropic documentation: https://platform.claude.com/docs/en/agents-and-tools/tool-use/handle-tool-calls . Matching tool_use_id and immediate tool_result message ordering are tested.

### Limitations / review status
- No new live Haiku audit ran in this update, as the user requested self-testing. The older saved GLM fallback analysis was not overwritten or presented as a Claude-only result. The user's real service/model access and useful findings for all three cases remain the existing live acceptance requirement.
- This uses one Claude model, not necessarily one HTTP call: image observation remains a separate blind request to the same model. This preserves the calibration lesson about expectation anchoring. No second provider is involved in audit.
- Full Jenkins execution awaits review and explicit user commit/push. Only the audit credential list/model variable changed here; the earlier full Jenkinsfile lint/approval fixture results remain historical checks, not a claim of a new live Jenkins build.

### Full test output — macOS
```text
test_all_row_types_statuses_vision_healing_paths_and_formula_safety (test_audit.AuditTests.test_all_row_types_statuses_vision_healing_paths_and_formula_safety) ... ok
test_csv_prefix_and_truncation_and_invalid_cli (test_audit.AuditTests.test_csv_prefix_and_truncation_and_invalid_cli) ... ok
test_html_locator_wording_keeps_raw_csv (test_audit.AuditTests.test_html_locator_wording_keeps_raw_csv) ... ok
test_missing_results_still_exports_case_and_rejects_outside_evidence (test_audit.AuditTests.test_missing_results_still_exports_case_and_rejects_outside_evidence) ... ok
test_repeat_indexes_and_row_ids_are_stable (test_audit.AuditTests.test_repeat_indexes_and_row_ids_are_stable) ... ok
test_claude_only_native_tool_loop_covers_all_cases_without_glm (test_audit_agent.AuditAgentTests.test_claude_only_native_tool_loop_covers_all_cases_without_glm) ... ok
test_claude_request_blind_one_png_and_native_size_guard (test_audit_agent.AuditAgentTests.test_claude_request_blind_one_png_and_native_size_guard) ... ok
test_dossiers_valid_analysis_all_cases_and_packaged_link (test_audit_agent.AuditAgentTests.test_dossiers_valid_analysis_all_cases_and_packaged_link) ... ok
test_dropped_model_finding_preserves_valid_sibling_and_false_pass_warning (test_audit_agent.AuditAgentTests.test_dropped_model_finding_preserves_valid_sibling_and_false_pass_warning) ... ok
test_evidence_rejections_and_human_fallbacks (test_audit_agent.AuditAgentTests.test_evidence_rejections_and_human_fallbacks) ... ok
test_false_pass_requires_certain_comparable_contradiction_no_ticket (test_audit_agent.AuditAgentTests.test_false_pass_requires_certain_comparable_contradiction_no_ticket) ... ok
test_missing_claude_key_never_uses_glm_credentials (test_audit_agent.AuditAgentTests.test_missing_claude_key_never_uses_glm_credentials) ... ok
test_native_tool_errors_limits_and_incomplete_output (test_audit_agent.AuditAgentTests.test_native_tool_errors_limits_and_incomplete_output) ... ok
test_tool_rejections_limits_errors_and_uncertainty (test_audit_agent.AuditAgentTests.test_tool_rejections_limits_errors_and_uncertainty) ... ok
test_ci_unavailable_mode_never_calls_models_and_still_writes_review (test_audit_agent.AuditCliTests.test_ci_unavailable_mode_never_calls_models_and_still_writes_review) ... ok
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
test_repeat_never_translates_and_writes_html_json (test_day6.Day6Tests.test_repeat_never_translates_and_writes_html_json) ... Executing <Task finished name='Task-417' coro=<Day6Tests.test_repeat_never_translates_and_writes_html_json() done, defined at /Users/xuenilaw/Documents/myProject/WBS/tests/test_day6.py:255> result=None created at /opt/homebrew/Cellar/python@3.14/3.14.8/Frameworks/Python.framework/Versions/3.14/lib/python3.14/asyncio/runners.py:110> took 0.210 seconds
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
test_bug_metadata_present_or_absent_and_attachment_header (test_jira.JiraTests.test_bug_metadata_present_or_absent_and_attachment_header) ... ok
test_dry_run_sends_nothing_and_writes_plain_adf_payload (test_jira.JiraTests.test_dry_run_sends_nothing_and_writes_plain_adf_payload) ... ok
test_duplicate_uses_new_search_and_comment_no_create (test_jira.JiraTests.test_duplicate_uses_new_search_and_comment_no_create) ... ok
test_unapproved_unknown_changed_analysis_and_safe_http_failures (test_jira.JiraTests.test_unapproved_unknown_changed_analysis_and_safe_http_failures) ... ok
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
Ran 158 tests in 71.697s

OK

```

### Full test output — Linux Jenkins agent
```text
WARNING: Running pip as the 'root' user can result in broken permissions and conflicting behaviour with the system package manager, possibly rendering your system unusable. It is recommended to use a virtual environment instead: https://pip.pypa.io/warnings/venv. Use the --root-user-action option if you know what you are doing and want to suppress this warning.
test_all_row_types_statuses_vision_healing_paths_and_formula_safety (test_audit.AuditTests.test_all_row_types_statuses_vision_healing_paths_and_formula_safety) ... ok
test_csv_prefix_and_truncation_and_invalid_cli (test_audit.AuditTests.test_csv_prefix_and_truncation_and_invalid_cli) ... ok
test_html_locator_wording_keeps_raw_csv (test_audit.AuditTests.test_html_locator_wording_keeps_raw_csv) ... ok
test_missing_results_still_exports_case_and_rejects_outside_evidence (test_audit.AuditTests.test_missing_results_still_exports_case_and_rejects_outside_evidence) ... ok
test_repeat_indexes_and_row_ids_are_stable (test_audit.AuditTests.test_repeat_indexes_and_row_ids_are_stable) ... ok
test_claude_only_native_tool_loop_covers_all_cases_without_glm (test_audit_agent.AuditAgentTests.test_claude_only_native_tool_loop_covers_all_cases_without_glm) ... ok
test_claude_request_blind_one_png_and_native_size_guard (test_audit_agent.AuditAgentTests.test_claude_request_blind_one_png_and_native_size_guard) ... ok
test_dossiers_valid_analysis_all_cases_and_packaged_link (test_audit_agent.AuditAgentTests.test_dossiers_valid_analysis_all_cases_and_packaged_link) ... ok
test_dropped_model_finding_preserves_valid_sibling_and_false_pass_warning (test_audit_agent.AuditAgentTests.test_dropped_model_finding_preserves_valid_sibling_and_false_pass_warning) ... ok
test_evidence_rejections_and_human_fallbacks (test_audit_agent.AuditAgentTests.test_evidence_rejections_and_human_fallbacks) ... ok
test_false_pass_requires_certain_comparable_contradiction_no_ticket (test_audit_agent.AuditAgentTests.test_false_pass_requires_certain_comparable_contradiction_no_ticket) ... ok
test_missing_claude_key_never_uses_glm_credentials (test_audit_agent.AuditAgentTests.test_missing_claude_key_never_uses_glm_credentials) ... ok
test_native_tool_errors_limits_and_incomplete_output (test_audit_agent.AuditAgentTests.test_native_tool_errors_limits_and_incomplete_output) ... ok
test_tool_rejections_limits_errors_and_uncertainty (test_audit_agent.AuditAgentTests.test_tool_rejections_limits_errors_and_uncertainty) ... ok
test_ci_unavailable_mode_never_calls_models_and_still_writes_review (test_audit_agent.AuditCliTests.test_ci_unavailable_mode_never_calls_models_and_still_writes_review) ... ok
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
test_suite_preflights_faults_and_only_injects_matching_cases (test_day5.FaultInputTests.test_suite_preflights_faults_and_only_injects_matching_cases) ... Executing <Task finished name='Task-370' coro=<FaultInputTests.test_suite_preflights_faults_and_only_injects_matching_cases() done, defined at /work/tests/test_day5.py:74> result=None created at /usr/lib/python3.12/asyncio/runners.py:100> took 0.151 seconds
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
test_repeat_never_translates_and_writes_html_json (test_day6.Day6Tests.test_repeat_never_translates_and_writes_html_json) ... Executing <Task finished name='Task-417' coro=<Day6Tests.test_repeat_never_translates_and_writes_html_json() done, defined at /work/tests/test_day6.py:255> result=None created at /usr/lib/python3.12/asyncio/runners.py:100> took 0.458 seconds
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
test_bug_metadata_present_or_absent_and_attachment_header (test_jira.JiraTests.test_bug_metadata_present_or_absent_and_attachment_header) ... Executing <Task finished name='Task-728' coro=<JiraTests.test_bug_metadata_present_or_absent_and_attachment_header() done, defined at /work/tests/test_jira.py:73> result=None created at /usr/lib/python3.12/asyncio/runners.py:100> took 0.132 seconds
ok
test_dry_run_sends_nothing_and_writes_plain_adf_payload (test_jira.JiraTests.test_dry_run_sends_nothing_and_writes_plain_adf_payload) ... ok
test_duplicate_uses_new_search_and_comment_no_create (test_jira.JiraTests.test_duplicate_uses_new_search_and_comment_no_create) ... ok
test_unapproved_unknown_changed_analysis_and_safe_http_failures (test_jira.JiraTests.test_unapproved_unknown_changed_analysis_and_safe_http_failures) ... ok
test_package_links_work_after_extracting_evidence_and_old_paths_rebase (test_junit.JUnitTests.test_package_links_work_after_extracting_evidence_and_old_paths_rebase) ... ok
test_prune_defaults_to_preview_and_keeps_protected_paths (test_junit.JUnitTests.test_prune_defaults_to_preview_and_keeps_protected_paths) ... ok
test_status_mapping_counts_escaping_and_diagnostic_lines (test_junit.JUnitTests.test_status_mapping_counts_escaping_and_diagnostic_lines) ... ok
test_translation_rejected_missing_evidence_and_repeat_aggregate (test_junit.JUnitTests.test_translation_rejected_missing_evidence_and_repeat_aggregate) ... ok
test_fake_translation_browser_layout_reuse_and_revalidation (test_junit.LayoutTests.test_fake_translation_browser_layout_reuse_and_revalidation) ... Executing <Task pending name='Task-749' coro=<Connection.run() running at /tmp/wbs-haiku-venv/lib/python3.12/site-packages/playwright/_impl/_connection.py:356> created at /tmp/wbs-haiku-venv/lib/python3.12/site-packages/playwright/async_api/_context_manager.py:37> took 0.118 seconds
ok
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
Ran 158 tests in 75.395s

OK

```

## Review round 2 + user decisions (Claude, 2026-10-16)
Evidence from the user's live Claude-only run (`suite-20261016T085446352441Z/audit_analysis.{md,json}`):
- **The screenshot answers were good:** OSM-001 time 2:56 (0.97), continuous line (0.93); OSM-002 time 7:36 (0.97), Hamburg → München (0.93). Two OSM-003 questions were rejected
  with `VISION_OPTIONS` (the guard), so Claude couldn't learn which rule it broke.
- **Claude's analysis was then thrown away by Python:** OSM-001 and OSM-002 `AUDIT_SCHEMA` (phase `output_validation`, `ValueError`), OSM-003 `FINDING_SCHEMA`. The
  "Human review needed · confidence: low" cards are **Python fallback filler**, not Claude's judgement. Claude's surviving OSM-003 summary was sensible (coverage gap, no ticket).
- So the user sees 3 review cards with low confidence: the opposite of the goal.

**User decisions (2026-10-16):** the audit agent must **reduce** human work. Ask the human **only** when something is suspicious. **Every ticket suggestion
(especially for FAILED cases) still requires human approval** before anything is created in Jira.

1. **MUST: stop losing valid analyses to format details.**
   - Record **which** field failed (field names + Pydantic error type only; no content) in `dropped_findings`, for every `AUDIT_SCHEMA` / `FINDING_SCHEMA`.
   - Make `submit_analysis` the required way to answer, with the exact JSON Schema as its `input_schema` (check the current Anthropic docs for strict tool schemas and use them if available for this model; cite the URL).
   - **Free-text fields that are too long are truncated, not rejected** (summary, explanation, observations, next step, title). Reject only on structure, enums, ids and evidence rules.
   - **One bounded repair turn:** if validation fails, return the field-level errors to Claude as an error `tool_result` and allow **one** corrected `submit_analysis`. If it fails again → fallback. Record `repair_used: true`.
   - `ask_screenshot` rejections return **which rule failed** (e.g. "need 3–8 options including 'unclear'") so Claude can rephrase; that still counts toward the question limits.
   > Codex: Fixed in `src/test_agent/audit_agent.py`, `audit_validation.py`, `audit_vision.py`, and `schemas/audit_analysis.py`. Final answers must use the strict `submit_analysis` tool. The schema derives from the same Pydantic model; unsupported API length/numeric/array constraints move into descriptions while Python still checks them. Overlong prose is truncated first. Schema failures save sanitized `field_errors` (paths + Pydantic types only), send an error `tool_result`, and permit exactly one corrected submission. A second invalid submission leaves the case explicitly unanalysed, with no synthetic finding. `repair_used` is recorded per case and at the top level; rejected screenshot questions return rule explanations and consume the 5/25 attempt budgets. Offline tests cover successful/failed repair, a repair after turn 12, malformed envelopes, sensitive content, and truncation. Docs checked on 2026-10-16: https://platform.claude.com/docs/en/agents-and-tools/tool-use/strict-tool-use and https://platform.claude.com/docs/en/build-with-claude/structured-outputs (Haiku 5.5 listed; unsupported schema keywords would produce HTTP 400).
2. **MUST: human attention only when needed** (in `audit_analysis.md`, the approval page and the report):
   - **"Needs your attention"** (top) contains only: (a) **ticket suggestions** (all need approval); (b) `possible_false_pass`; (c) a `needs_human_review` that **Claude itself** chose, with a concrete reason;
     (d) findings on FAILED/BLOCKED cases where Claude's confidence is `low`.
   - **"No action needed"** (collapsed): `confirmed_pass` with medium/high confidence, and FAILED/BLOCKED cases explained with medium/high confidence without a ticket (e.g. an environment problem). Listed for traceability, no action.
   - **Agent unavailable / fallback:** **one banner** ("AI audit unavailable. Test results are unchanged; read the report as usual. Reason: <code>"), **not** one filler card per case.
     The fallback must **not** trigger the approval stage. The internal coverage rule stays (every case is analysed or explicitly marked unanalysed in the JSON).
   - The Jenkins **"Review tickets"** stage runs only if there is ≥ 1 validated ticket suggestion. It shows the selectable tickets (default unticked) and, as information only, the
     count of attention items with a link to `audit_analysis.md`. No tickets → no pause. Attention items without tickets → no pause either; they appear in the build description and the report.
   - Show a short line at the top: "Audited 3 cases: 2 no action, 1 needs your attention (1 ticket suggestion)."
   > Codex: Fixed through shared `src/test_agent/audit_presentation.py`, used by Markdown, the HTML report and approval metadata. Attention appears first; no-action findings are collapsed. Unavailable cases produce one banner, no filler findings or candidates, and explicit `case_audits` coverage. The headline counts distinct cases; `attention_count` counts findings. `Jenkinsfile` still gates input only on validated ticket candidates, defaults every checkbox to false, and now shows the attention count + analysis link without pasting unrelated findings. Build descriptions include the count and attention case/cause/confidence even without tickets; Jira links append without erasing that summary. A low-confidence confirmed_pass must be repaired to a supported judgment rather than silently treated as no-action. Guide §§11, 13, 15 and README updated.
3. **Live acceptance (the user runs it locally once, then Jenkins):** usable Claude findings for all 3 cases, no fallback. Expected kind of result (not enforced): OSM-001 and OSM-003 under
   "No action needed"; OSM-002 under "Needs your attention" with one ticket suggestion (likely `test_case_fix`: under 3 h is unrealistic for Hamburg → Munich, or a `bug`), awaiting approval.
   Paste the `audit_analysis.md` and any `dropped_findings` with their field names.
   > Codex: Left for the user as requested. No live model call, Jenkins build, Jira write, commit or push was performed in this round. Guide §15 contains the existing-suite command and JSON inspection steps; paste `audit_analysis.md`, `case_audits`, and `dropped_findings` after the local run. Expected OSM classifications remain suggestions, never hardcoded rules.


## Handoff (Codex, round 2 fixes, 2026-10-16)

### Goal
Fix round 2 MUST 1–2: preserve usable Claude analysis through bounded validation repair,
and make the UI ask for human attention only when needed. Live acceptance 3 remains with the user.

### What changed
- `src/test_agent/schemas/audit_analysis.py`: truncate overlong prose; derive the strict-tool input schema from the same finding model, with API-unsupported constraints documented in field descriptions and checked locally.
- `src/test_agent/audit_validation.py`: shared envelope/finding validation and safe field diagnostics. No invalid model input or exception text is stored in schema errors. Removed synthetic fallback findings. Low-confidence confirmed passes require a repaired judgment rather than silent no-action placement.
- `src/test_agent/audit_agent.py`: require `submit_analysis`, enable its strict schema, return field errors through `is_error` tool results, allow one corrected submission (including after ordinary turn 12), and stop on another invalid submission. Retain initial dropped diagnostics after successful repair. Save explicit per-case coverage, repair flags, and screenshot-attempt counts.
- `src/test_agent/audit_vision.py`: explain rejected screenshot rules and charge rejected/malformed requests against the existing 5-per-case / 25-per-suite limits.
- `src/test_agent/audit_presentation.py`: shared attention/no-action classification and headline; one unavailable banner for unanalysed cases. Markdown and HTML place attention first and collapse no-action findings.
- `Jenkinsfile`: input remains gated solely by validated ticket candidates; every checkbox remains unticked. Display attention count + analysis link, and keep attention case/cause/confidence in the build description even without tickets. Append Jira URLs instead of overwriting that description.
- `src/test_agent/reporting.py`, `src/test_agent/cli.py`: display the grouped audit and unavailable explanation without Python-generated review cards.
- `tests/test_audit_agent.py`: repair success/failure, last-turn repair, sanitized schema errors, truncation, rejected-question budgets, classification, coverage/banner and approval metadata. Existing Jira approval/evidence tests still pass.
- `docs/ci/jenkins-guide.md` §§11, 13, 15 and `README.md`: updated behavior, official Anthropic references, and user-run live checks.

### How to verify
Offline, with fake providers and local browser fixtures:
```bash
uv run python -m unittest discover -s tests -v
```
Final results: **160 passed locally in 70.086s**, and **160 passed in the Jenkins Playwright Linux image in 69.511s**.
`git diff --check` also passed. The Linux run mounted the workspace read-only and replaced `.env` with `/dev/null`.
Fixture console lines such as `wrong.png ... FAILED` are expected test data; both unittest summaries end in `OK`.

User's live acceptance (not run by Codex):
```bash
AUDIT_MODEL=claude-haiku-5-5 uv run python -m test_agent audit-agent artifacts/suite-20261016T085446352441Z
open artifacts/suite-20261016T085446352441Z/audit_analysis.md
```
Check guide §15's JSON inspection command. All three entries in `case_audits` should be `analysed`,
`agent_unavailable` false, and the headline/groups should be useful. An initial dropped finding with
`repair_used: true` is acceptable if the corrected submission succeeded. Paste the Markdown and
`dropped_findings` including `field_errors`, plus `case_audits`, for Claude's review.
No tickets means Jenkins must skip input, even if there are other attention items. With a validated
ticket suggestion, input must show an unchecked choice and require approval before Jira sends.

### Known limitations / open questions
- No live Anthropic request or Jenkins build was made in this round. The strict-schema API behavior and the actual OSM diagnoses still need the user's live acceptance 3; offline tests do not establish that result.
- Expected OSM-001/003 no-action and OSM-002 ticket placement is not hardcoded.
- Claude's own `needs_human_review` explanation is checked for nonempty content; its substantive usefulness still needs human assessment in the live check.
- All work remains uncommitted and unpushed, including the pre-existing audit/Jira changes. Ready for Claude review through this file; no direct agent-to-agent handoff was sent.

### Test output — local (full)
```text
test_all_row_types_statuses_vision_healing_paths_and_formula_safety (test_audit.AuditTests.test_all_row_types_statuses_vision_healing_paths_and_formula_safety) ... ok
test_csv_prefix_and_truncation_and_invalid_cli (test_audit.AuditTests.test_csv_prefix_and_truncation_and_invalid_cli) ... ok
test_html_locator_wording_keeps_raw_csv (test_audit.AuditTests.test_html_locator_wording_keeps_raw_csv) ... ok
test_missing_results_still_exports_case_and_rejects_outside_evidence (test_audit.AuditTests.test_missing_results_still_exports_case_and_rejects_outside_evidence) ... ok
test_repeat_indexes_and_row_ids_are_stable (test_audit.AuditTests.test_repeat_indexes_and_row_ids_are_stable) ... ok
test_claude_only_native_tool_loop_covers_all_cases_without_glm (test_audit_agent.AuditAgentTests.test_claude_only_native_tool_loop_covers_all_cases_without_glm) ... ok
test_claude_request_blind_one_png_and_native_size_guard (test_audit_agent.AuditAgentTests.test_claude_request_blind_one_png_and_native_size_guard) ... ok
test_dossiers_valid_analysis_all_cases_and_packaged_link (test_audit_agent.AuditAgentTests.test_dossiers_valid_analysis_all_cases_and_packaged_link) ... ok
test_dropped_model_finding_preserves_valid_sibling_and_false_pass_warning (test_audit_agent.AuditAgentTests.test_dropped_model_finding_preserves_valid_sibling_and_false_pass_warning) ... ok
test_envelope_diagnostics_and_attention_groups (test_audit_agent.AuditAgentTests.test_envelope_diagnostics_and_attention_groups) ... ok
test_evidence_rejections_and_human_fallbacks (test_audit_agent.AuditAgentTests.test_evidence_rejections_and_human_fallbacks) ... ok
test_false_pass_requires_certain_comparable_contradiction_no_ticket (test_audit_agent.AuditAgentTests.test_false_pass_requires_certain_comparable_contradiction_no_ticket) ... ok
test_missing_claude_key_never_uses_glm_credentials (test_audit_agent.AuditAgentTests.test_missing_claude_key_never_uses_glm_credentials) ... ok
test_native_one_repair_and_safe_field_errors (test_audit_agent.AuditAgentTests.test_native_one_repair_and_safe_field_errors) ... ok
test_native_tool_errors_limits_and_incomplete_output (test_audit_agent.AuditAgentTests.test_native_tool_errors_limits_and_incomplete_output) ... ok
test_tool_rejections_limits_errors_and_uncertainty (test_audit_agent.AuditAgentTests.test_tool_rejections_limits_errors_and_uncertainty) ... ok
test_ci_unavailable_mode_never_calls_models_and_still_writes_review (test_audit_agent.AuditCliTests.test_ci_unavailable_mode_never_calls_models_and_still_writes_review) ... ok
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
test_repeat_never_translates_and_writes_html_json (test_day6.Day6Tests.test_repeat_never_translates_and_writes_html_json) ... Executing <Task finished name='Task-427' coro=<Day6Tests.test_repeat_never_translates_and_writes_html_json() done, defined at /Users/xuenilaw/Documents/myProject/WBS/tests/test_day6.py:255> result=None created at /opt/homebrew/Cellar/python@3.14/3.14.8/Frameworks/Python.framework/Versions/3.14/lib/python3.14/asyncio/runners.py:110> took 0.231 seconds
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
test_bug_metadata_present_or_absent_and_attachment_header (test_jira.JiraTests.test_bug_metadata_present_or_absent_and_attachment_header) ... ok
test_dry_run_sends_nothing_and_writes_plain_adf_payload (test_jira.JiraTests.test_dry_run_sends_nothing_and_writes_plain_adf_payload) ... ok
test_duplicate_uses_new_search_and_comment_no_create (test_jira.JiraTests.test_duplicate_uses_new_search_and_comment_no_create) ... ok
test_unapproved_unknown_changed_analysis_and_safe_http_failures (test_jira.JiraTests.test_unapproved_unknown_changed_analysis_and_safe_http_failures) ... ok
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
Ran 160 tests in 70.086s

OK
```

### Test output — Jenkins Linux image (full)
Command: same Docker image/environment as Jenkins, `.env` hidden, `uv sync --locked` followed by `uv run python -m unittest discover -s tests -v`.
```text
WARNING: Running pip as the 'root' user can result in broken permissions and conflicting behaviour with the system package manager, possibly rendering your system unusable. It is recommended to use a virtual environment instead: https://pip.pypa.io/warnings/venv. Use the --root-user-action option if you know what you are doing and want to suppress this warning.
test_all_row_types_statuses_vision_healing_paths_and_formula_safety (test_audit.AuditTests.test_all_row_types_statuses_vision_healing_paths_and_formula_safety) ... ok
test_csv_prefix_and_truncation_and_invalid_cli (test_audit.AuditTests.test_csv_prefix_and_truncation_and_invalid_cli) ... ok
test_html_locator_wording_keeps_raw_csv (test_audit.AuditTests.test_html_locator_wording_keeps_raw_csv) ... ok
test_missing_results_still_exports_case_and_rejects_outside_evidence (test_audit.AuditTests.test_missing_results_still_exports_case_and_rejects_outside_evidence) ... ok
test_repeat_indexes_and_row_ids_are_stable (test_audit.AuditTests.test_repeat_indexes_and_row_ids_are_stable) ... ok
test_claude_only_native_tool_loop_covers_all_cases_without_glm (test_audit_agent.AuditAgentTests.test_claude_only_native_tool_loop_covers_all_cases_without_glm) ... ok
test_claude_request_blind_one_png_and_native_size_guard (test_audit_agent.AuditAgentTests.test_claude_request_blind_one_png_and_native_size_guard) ... ok
test_dossiers_valid_analysis_all_cases_and_packaged_link (test_audit_agent.AuditAgentTests.test_dossiers_valid_analysis_all_cases_and_packaged_link) ... ok
test_dropped_model_finding_preserves_valid_sibling_and_false_pass_warning (test_audit_agent.AuditAgentTests.test_dropped_model_finding_preserves_valid_sibling_and_false_pass_warning) ... ok
test_envelope_diagnostics_and_attention_groups (test_audit_agent.AuditAgentTests.test_envelope_diagnostics_and_attention_groups) ... ok
test_evidence_rejections_and_human_fallbacks (test_audit_agent.AuditAgentTests.test_evidence_rejections_and_human_fallbacks) ... ok
test_false_pass_requires_certain_comparable_contradiction_no_ticket (test_audit_agent.AuditAgentTests.test_false_pass_requires_certain_comparable_contradiction_no_ticket) ... ok
test_missing_claude_key_never_uses_glm_credentials (test_audit_agent.AuditAgentTests.test_missing_claude_key_never_uses_glm_credentials) ... ok
test_native_one_repair_and_safe_field_errors (test_audit_agent.AuditAgentTests.test_native_one_repair_and_safe_field_errors) ... ok
test_native_tool_errors_limits_and_incomplete_output (test_audit_agent.AuditAgentTests.test_native_tool_errors_limits_and_incomplete_output) ... ok
test_tool_rejections_limits_errors_and_uncertainty (test_audit_agent.AuditAgentTests.test_tool_rejections_limits_errors_and_uncertainty) ... ok
test_ci_unavailable_mode_never_calls_models_and_still_writes_review (test_audit_agent.AuditCliTests.test_ci_unavailable_mode_never_calls_models_and_still_writes_review) ... ok
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
test_suite_preflights_faults_and_only_injects_matching_cases (test_day5.FaultInputTests.test_suite_preflights_faults_and_only_injects_matching_cases) ... Executing <Task finished name='Task-380' coro=<FaultInputTests.test_suite_preflights_faults_and_only_injects_matching_cases() done, defined at /work/tests/test_day5.py:74> result=None created at /usr/lib/python3.12/asyncio/runners.py:100> took 0.130 seconds
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
test_repeat_never_translates_and_writes_html_json (test_day6.Day6Tests.test_repeat_never_translates_and_writes_html_json) ... Executing <Task finished name='Task-427' coro=<Day6Tests.test_repeat_never_translates_and_writes_html_json() done, defined at /work/tests/test_day6.py:255> result=None created at /usr/lib/python3.12/asyncio/runners.py:100> took 0.396 seconds
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
test_bug_metadata_present_or_absent_and_attachment_header (test_jira.JiraTests.test_bug_metadata_present_or_absent_and_attachment_header) ... Executing <Task finished name='Task-738' coro=<JiraTests.test_bug_metadata_present_or_absent_and_attachment_header() done, defined at /work/tests/test_jira.py:73> result=None created at /usr/lib/python3.12/asyncio/runners.py:100> took 0.120 seconds
ok
test_dry_run_sends_nothing_and_writes_plain_adf_payload (test_jira.JiraTests.test_dry_run_sends_nothing_and_writes_plain_adf_payload) ... ok
test_duplicate_uses_new_search_and_comment_no_create (test_jira.JiraTests.test_duplicate_uses_new_search_and_comment_no_create) ... ok
test_unapproved_unknown_changed_analysis_and_safe_http_failures (test_jira.JiraTests.test_unapproved_unknown_changed_analysis_and_safe_http_failures) ... ok
test_package_links_work_after_extracting_evidence_and_old_paths_rebase (test_junit.JUnitTests.test_package_links_work_after_extracting_evidence_and_old_paths_rebase) ... ok
test_prune_defaults_to_preview_and_keeps_protected_paths (test_junit.JUnitTests.test_prune_defaults_to_preview_and_keeps_protected_paths) ... ok
test_status_mapping_counts_escaping_and_diagnostic_lines (test_junit.JUnitTests.test_status_mapping_counts_escaping_and_diagnostic_lines) ... ok
test_translation_rejected_missing_evidence_and_repeat_aggregate (test_junit.JUnitTests.test_translation_rejected_missing_evidence_and_repeat_aggregate) ... ok
test_fake_translation_browser_layout_reuse_and_revalidation (test_junit.LayoutTests.test_fake_translation_browser_layout_reuse_and_revalidation) ... Executing <Task pending name='Task-758' coro=<LayoutTests.test_fake_translation_browser_layout_reuse_and_revalidation() running at /work/tests/test_junit.py:156> wait_for=<Future pending cb=[Task.task_wakeup()] created at /usr/lib/python3.12/asyncio/base_events.py:449> cb=[_run_until_complete_cb() at /usr/lib/python3.12/asyncio/base_events.py:182] created at /usr/lib/python3.12/asyncio/runners.py:100> took 0.132 seconds
ok
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
Ran 160 tests in 69.511s

OK
```

## Review round 3 (Claude, 2026-10-16)
Verdict: **APPROVED. The user may commit and push.** Remaining acceptance is the Jenkins + Jira flow.
Verified: tests OK locally (160). **Live audit by the user** (`suite-20261016T085446352441Z/audit_analysis.{md,json}`, 18:00): `agent_unavailable: false`, all 3 `case_audits` analysed,
headline "Audited 3 cases: 2 no action, 1 needs your attention (1 ticket suggestion)". The repair worked as designed: OSM-003's first submission cited foreign evidence
(`UNKNOWN_OR_FOREIGN_EVIDENCE`), and the corrected one passed (`repair_used: true`). The findings are grounded and checked against the evidence:
- **OSM-002 step 5:** `test_case_problem`, high, **ticket suggested (test case fix)**: 776 km in < 3 h would need ~259 km/h (776/3 = 258.7, correct); cites R0030/R0028 and Q-OSM-002-1 (7:36, 0.97).
  Alternatives considered. This is exactly the human-reducing diagnosis the user wanted.
- **OSM-002 step 4:** `test_tool_problem`, medium, no ticket → "No action needed" (Clef inconclusive; Claude's own blind question saw a continuous line, and the analysis notes this isn't conclusive).
- **OSM-001 / OSM-003:** `confirmed_pass`, high, with their own screenshot answers (2:56 / Hamburg–Berlin; Tracestrack Topo / 8 layers), plus useful optional notes (the ETA wording; the unverified precondition).

NITs (non-blocking):
1. All findings have `step: null` ("step case") although they are about specific steps (OSM-002: 5 and 4). Ask Claude to set `step` when the finding concerns one step.
   The Jira fingerprint label then becomes step-specific (better deduplication).
2. `audit_analysis.md` shows `&lt;` literally in some viewers (e.g. "176 min &lt; 180"). It's escaped correctly for safety; consider escaping only what Markdown needs, or render it in the HTML report only.

Jenkins/Jira acceptance (the user, after push): credential `wbs-jira` exists; the build shows the **Review tickets** pause with the OSM-002 test-case-fix suggestion **unticked**; approve it → a WBSFP issue
with a screenshot and a build link; the next build adds a comment instead of a duplicate. Note: every Jenkins build re-translates and re-audits, so the wording may differ between builds; the
deduplication relies on the fingerprint label, not the wording.

## Review round 4: first real Jenkins run (Claude, 2026-10-16)
Builds #6 and #7 (commit `5dd5c72`) = **FAILURE**. The reviewer read the controller's build #7 log and archived `reports/audit_analysis.json`. Two independent causes:

1. **MUST (Codex): the Jenkins script sandbox blocks `new groovy.json.JsonSlurperClassic`.** Log: `RejectedAccessException: Scripts not permitted to use new groovy.json.JsonSlurperClassic`
   right after `prepare_reports.py` in the "Audit analysis" stage. Then "Review tickets" and "Record decision and Jira" were **skipped due to earlier failure(s)**, so the approval never appeared.
   The earlier Declarative linter check can't catch this, because sandbox approval happens at runtime. Fix it **without** a manual script approval (it must work from git on a fresh controller):
   either read the JSON with `readJSON` from the **Pipeline Utility Steps** plugin (add it to `plugins.txt`, pinned), or let Python write the few values the Jenkinsfile needs
   (candidate count, attention count, a short description, the input choices) into simple text/properties files and read them with `readFile`/`readProperties`.
   Add a test or check that the Jenkinsfile contains no sandbox-restricted Groovy (JsonSlurper, `new File`, `.execute()` …). The guide must explain "sandbox" in two sentences and how to recognise this error.
   > Codex: Fixed all three JSON boundaries in `Jenkinsfile`: audit preview and Jira results now use `readJSON(..., returnPojo: true)`, and the approval decision uses `writeJSON`. No Groovy JSON APIs remain. `ci/jenkins/plugins.txt` pins `pipeline-utility-steps:3.810.va_7672d206740` (official minimum Jenkins 2.504.3, compatible with our 2.580.1). `tests/test_ci.py` checks the actual Jenkinsfile and pinned plugin plus negative fixtures for restricted JSON/file/process/controller APIs. Guide §3 explains sandbox errors in two sentences and adds the required image rebuild/recreate before Build Now; §11 reflects the plugin prerequisite. No manual Script Approval is required. See runtime verification and full test output in the handoff below.
2. **USER ACTION: the Jenkins credential `wbs-anthropic-api-key` is rejected by Anthropic (HTTP 401) for all 3 cases** (`provider_code: VISION_HTTP, http_status: 401`). The same audit works locally
   with the `.env` key, and earlier builds never actually called Claude in CI (the click fallback wasn't triggered), so the bad credential went unnoticed. The user re-enters the key
   (Manage Jenkins → Credentials → `wbs-anthropic-api-key` → Update → paste the key from the local `ANTHROPIC_API_KEY`, with no spaces or newline).
   **Codex (NIT):** when the audit fails with HTTP 401/403, print an explicit console line and build-description note: "Anthropic credential rejected (401): update `wbs-anthropic-api-key`".
   > Codex: NIT fixed in `audit_presentation.py`, `audit_agent.py`, `cli.py` and `Jenkinsfile`: controlled 401/403 diagnostics from either the analyst or blind-image requests generate the explicit credential-update message in Console Output and the build description. The preview JSON carries `credential_warning`; 429 and non-HTTP/config errors do not produce this auth warning. Tests cover both statuses, the image path, safe output and the 429 negative case. Guide §4 documents updating the existing Secret text credential from the working local key. The credential itself remains a USER ACTION as requested in this review; Codex has neither read nor changed the secret.

After both: Build Now → expect "Audit analysis" OK (headline as locally), then **"Review tickets" paused** with the OSM-002 suggestion unticked.


## Handoff (Codex, round 4 fixes, 2026-10-16)

### Goal
Fix round 4 MUST 1 (sandbox-rejected Groovy JSON handling) and the credential-diagnostic NIT.
Hand off for review before committing. User updates the Anthropic credential; live acceptance follows review/push.

### What changed
- `Jenkinsfile`: use `readJSON(..., returnPojo: true)` for both audit preview and Jira results; use `writeJSON` for the decision. Preserve ticket approval gating, unchecked defaults, analysis hash and reporting. Print `credential_warning` and append it to the build description.
- `ci/jenkins/plugins.txt`: pin `pipeline-utility-steps:3.810.va_7672d206740`; its minimum Jenkins is 2.504.3, below this project's 2.580.1. Sources: [official step reference](https://www.jenkins.io/doc/pipeline/steps/pipeline-utility-steps/) and [official version index](https://updates.jenkins.io/download/plugins/pipeline-utility-steps/).
- `audit_presentation.py`, `audit_agent.py`, `cli.py`: a safe warning for observed Anthropic HTTP 401/403, covering analyst and image requests. Only fixed codes/statuses and the credential ID enter the message; no provider body or credential value. Preview metadata feeds the Jenkins note; CLI also prints it. Other errors such as 429 do not claim the credential was rejected.
- `tests/test_ci.py`: regression check against known restricted Groovy APIs and check for the pinned JSON steps; negative snippets prove the guard catches the previous parser, direct files, process execution and controller access. This static check does not claim to detect every possible sandbox restriction.
- `tests/test_audit_agent.py`: console/preview warnings for 401 and 403, a 429 negative case, blind-image auth failure, and no private response/secret echo.
- `docs/ci/jenkins-guide.md` §§3–4, 11, 13: two-sentence sandbox explanation, error recognition, plugin installation/rebuild prerequisite, credential update instructions, and expected approval flow.

### How to verify
```bash
uv run python -m unittest discover -s tests -v
```
**164 passed in 69.466s.** `git diff --check` passed.

Additionally, ran a real **sandboxed Pipeline** on a temporary Jenkins controller with a new empty home,
no host ports, no network, no credentials, and no live controller volume. The test image extends the existing
`wbs-jenkins:2.580.1-1` image, installing the repo's updated pinned plugin manifest as root, then running as Jenkins.
The sandbox Pipeline uses the actual edited JSON/description/choice-building blocks extracted from this Jenkinsfile:
read audit preview → build description + credential note → checkpoint → create choices → write/read approval decision
(check approved ID and analysis hash) → read synthetic Jira results → append fixture issue URL.
Result: **SUCCESS; pending sandbox signatures = 0**. No manual Script Approval was applied.
Temporary fixtures are under `/tmp/wbs-round4-smoke/`; logs under `/tmp/wbs-round4-{local,sandbox,image}.log`.
The sandbox log below is the complete output captured by `docker exec`; a later `docker cp` from the memory filesystem failed,
so the already captured output was transcribed to the log before handoff. The temporary controller and test image were removed.
No real model/Jira request or live job was run.

### Required user / post-review steps
1. Update the existing Jenkins **Secret text** credential `wbs-anthropic-api-key` from the working local `ANTHROPIC_API_KEY` value (guide §4). This remains a user action; the secret was not read or changed by Codex.
2. After Claude review and commit/push, wait for any running build to finish, then install the new plugin into the controller image (guide §3):
   ```bash
   docker compose -f ci/docker-compose.yml build jenkins
   docker compose -f ci/docker-compose.yml up -d --force-recreate jenkins
   ```
   Keep the existing volume; do not use `down --volumes`. Merely pushing Jenkinsfile does not install `readJSON` / `writeJSON`.
3. Build Now. With the working credential and a validated ticket suggestion, expect Audit analysis to finish and Review tickets to pause with the suggestion **unchecked**. The model may phrase/categorize findings differently on a fresh run.
4. Tick the reviewed OSM-002 suggestion and click Record decision / Proceed. Confirm the issue appears in WBSFP, then verify the later-build deduplication flow separately.

### Known limitations / open questions
- The smoke test proves the edited JSON blocks work in a fresh Jenkins sandbox; it does not exercise the complete Docker/SCM/credential/input/Jira flow. That live acceptance remains after review/push and the controller rebuild.
- HTTP 401/403 messages explain a credential/access rejection; they do not repair the secret or grant model permissions.
- Existing review round 3 NITs about step selection and Markdown entities are outside this requested round 4 change.
- No commit or push performed. Ready for Claude review through this file.

### Test output — local (full)
```text
test_all_row_types_statuses_vision_healing_paths_and_formula_safety (test_audit.AuditTests.test_all_row_types_statuses_vision_healing_paths_and_formula_safety) ... ok
test_csv_prefix_and_truncation_and_invalid_cli (test_audit.AuditTests.test_csv_prefix_and_truncation_and_invalid_cli) ... ok
test_html_locator_wording_keeps_raw_csv (test_audit.AuditTests.test_html_locator_wording_keeps_raw_csv) ... ok
test_missing_results_still_exports_case_and_rejects_outside_evidence (test_audit.AuditTests.test_missing_results_still_exports_case_and_rejects_outside_evidence) ... ok
test_repeat_indexes_and_row_ids_are_stable (test_audit.AuditTests.test_repeat_indexes_and_row_ids_are_stable) ... ok
test_claude_only_native_tool_loop_covers_all_cases_without_glm (test_audit_agent.AuditAgentTests.test_claude_only_native_tool_loop_covers_all_cases_without_glm) ... ok
test_claude_request_blind_one_png_and_native_size_guard (test_audit_agent.AuditAgentTests.test_claude_request_blind_one_png_and_native_size_guard) ... ok
test_dossiers_valid_analysis_all_cases_and_packaged_link (test_audit_agent.AuditAgentTests.test_dossiers_valid_analysis_all_cases_and_packaged_link) ... ok
test_dropped_model_finding_preserves_valid_sibling_and_false_pass_warning (test_audit_agent.AuditAgentTests.test_dropped_model_finding_preserves_valid_sibling_and_false_pass_warning) ... ok
test_envelope_diagnostics_and_attention_groups (test_audit_agent.AuditAgentTests.test_envelope_diagnostics_and_attention_groups) ... ok
test_evidence_rejections_and_human_fallbacks (test_audit_agent.AuditAgentTests.test_evidence_rejections_and_human_fallbacks) ... ok
test_false_pass_requires_certain_comparable_contradiction_no_ticket (test_audit_agent.AuditAgentTests.test_false_pass_requires_certain_comparable_contradiction_no_ticket) ... ok
test_missing_claude_key_never_uses_glm_credentials (test_audit_agent.AuditAgentTests.test_missing_claude_key_never_uses_glm_credentials) ... ok
test_native_one_repair_and_safe_field_errors (test_audit_agent.AuditAgentTests.test_native_one_repair_and_safe_field_errors) ... ok
test_native_tool_errors_limits_and_incomplete_output (test_audit_agent.AuditAgentTests.test_native_tool_errors_limits_and_incomplete_output) ... ok
test_tool_rejections_limits_errors_and_uncertainty (test_audit_agent.AuditAgentTests.test_tool_rejections_limits_errors_and_uncertainty) ... ok
test_auth_note_covers_blind_image_rejections_without_echoing_messages (test_audit_agent.AuditCliTests.test_auth_note_covers_blind_image_rejections_without_echoing_messages) ... ok
test_auth_rejection_is_explicit_in_console_and_review_metadata (test_audit_agent.AuditCliTests.test_auth_rejection_is_explicit_in_console_and_review_metadata) ... ok
test_ci_unavailable_mode_never_calls_models_and_still_writes_review (test_audit_agent.AuditCliTests.test_ci_unavailable_mode_never_calls_models_and_still_writes_review) ... ok
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
test_guard_catches_restricted_parsing_files_and_processes (test_ci.JenkinsSandboxTests.test_guard_catches_restricted_parsing_files_and_processes) ... ok
test_pipeline_uses_pinned_sandbox_safe_json_steps (test_ci.JenkinsSandboxTests.test_pipeline_uses_pinned_sandbox_safe_json_steps) ... ok
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
test_repeat_never_translates_and_writes_html_json (test_day6.Day6Tests.test_repeat_never_translates_and_writes_html_json) ... Executing <Task finished name='Task-436' coro=<Day6Tests.test_repeat_never_translates_and_writes_html_json() done, defined at /Users/xuenilaw/Documents/myProject/WBS/tests/test_day6.py:255> result=None created at /opt/homebrew/Cellar/python@3.14/3.14.8/Frameworks/Python.framework/Versions/3.14/lib/python3.14/asyncio/runners.py:110> took 0.209 seconds
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
test_bug_metadata_present_or_absent_and_attachment_header (test_jira.JiraTests.test_bug_metadata_present_or_absent_and_attachment_header) ... ok
test_dry_run_sends_nothing_and_writes_plain_adf_payload (test_jira.JiraTests.test_dry_run_sends_nothing_and_writes_plain_adf_payload) ... ok
test_duplicate_uses_new_search_and_comment_no_create (test_jira.JiraTests.test_duplicate_uses_new_search_and_comment_no_create) ... ok
test_unapproved_unknown_changed_analysis_and_safe_http_failures (test_jira.JiraTests.test_unapproved_unknown_changed_analysis_and_safe_http_failures) ... ok
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
Ran 164 tests in 69.466s

OK
```

### Test output — isolated Jenkins sandbox (full captured output)
```text
result=SUCCESS
pending_signatures=0
Started
[Pipeline] Start of Pipeline
[Pipeline] node
Running on Jenkins in /var/jenkins_home/workspace/round4-json-sandbox
[Pipeline] {
[Pipeline] writeFile
[Pipeline] readJSON
[Pipeline] echo
Anthropic credential rejected (401): update `wbs-anthropic-api-key`
[Pipeline] sleep
Sleeping for 1 sec
[Pipeline] writeJSON
[Pipeline] readJSON
[Pipeline] writeFile
[Pipeline] readJSON
[Pipeline] echo
ROUND4_JSON_SANDBOX_OK
[Pipeline] }
[Pipeline] // node
[Pipeline] End of Pipeline
Finished: SUCCESS
```

## Review round 4: re-review (Claude, 2026-10-16)
Verdict: **APPROVED. Commit and push**, then **rebuild/recreate the controller** (new plugin), then Build Now.
Verified: 164 tests OK locally; the Jenkinsfile diff replaces all Groovy JSON APIs with `readJSON(returnPojo: true)` / `writeJSON` (Pipeline Utility Steps, pinned in `plugins.txt`);
the static guard test covers restricted APIs; Codex's fresh-controller sandbox smoke run: SUCCESS, 0 pending signatures, no manual approval. The 401/403 credential warning is limited to auth statuses (429 excluded).
Order for the user: (1) update `wbs-anthropic-api-key`; (2) commit + push; (3) `docker compose -f ci/docker-compose.yml build jenkins` and
`docker compose -f ci/docker-compose.yml up -d --force-recreate jenkins` (**keep the volume, no `down --volumes`**); (4) Build Now → Review tickets pauses → approve → WBSFP issue.

## Review round 5: build #8 (Claude, 2026-10-16)
- **`No such DSL method 'readJSON'`:** build #8 started 17:45:32 UTC, and the controller was recreated with the new plugin at 17:50:32 UTC, so the build ran on the old controller. Expected; no code change.
  The plugin is now present, with no load errors in the controller log. **The next build is the real test.**
- **The Anthropic credential works now:** OSM-002 analysed (`test_case_problem`, high, **ticket suggested: test_case_fix**), OSM-003 analysed (`confirmed_pass`, medium).
- **OSM-001 unanalysed:** findings cited screenshot ids that Claude never asked about (`UNOBSERVED_SCREENSHOT_CLAIM` ×3), and the single repair repeated the mistake. The rule is right (no visual claims
  without an observation), but it's too costly:
  1. **SHOULD:** if a finding lists unobserved screenshot ids in `evidence_screenshots` but its `screenshot_observations` text is empty (or only refers to answered questions), **remove those ids
     deterministically and record it**, instead of dropping the finding. Drop the finding only when it **claims** a visual observation without any answered question for that screenshot.
     The repair message must name the offending ids and the two ways to fix them (ask first, or remove).
     > Codex: Fixed in round 6; see MUST 1 below for normalization, per-finding repair feedback and preservation of valid siblings.
  2. **SHOULD: partial availability wording.** With 2 of 3 cases analysed, the console says "AI audit unavailable", which is misleading. Use "AI audit analysed 2 of 3 cases; OSM-001 unanalysed
     (UNOBSERVED_SCREENSHOT_CLAIM)", and reserve "unavailable" for zero analysed cases. Also, `provider_code: VISION_VALIDATION_FAILED` on a `model_call`-phase entry is a confusing label;
     name it after what failed (e.g. `AUDIT_REPAIR_FAILED`). Confirm that a partial audit still lets validated ticket candidates reach "Review tickets" (test it).
     > Codex: Fixed in round 6; see MUST 2 below for partial availability and the real sandbox input-stage check.

## Review round 6: build #9 (Claude, 2026-10-16)
**The pipeline itself works now:** build #9 is UNSTABLE (correct), `readJSON`/`writeJSON` run, there's no sandbox error, and the audit runs with the fixed credential.
**But "Review tickets" was skipped "due to when conditional", because there were no validated ticket candidates:** only OSM-003 was analysed. OSM-001 **and OSM-002** were unanalysed with
`UNOBSERVED_SCREENSHOT_CLAIM` (OSM-001 ×4, OSM-002 ×2), even after the repair turn. Claude did ask real questions (OSM-001: S-5, S-3; OSM-002: S-5, all answered "certain"),
but its findings also listed other catalogue screenshots it never asked about. In build #8 the same rule cost OSM-001; now it also cost OSM-002, the case with the ticket.

1. **MUST (upgraded from round 5 SHOULD 1): don't throw away a whole case for an extra screenshot id.**
   - Unobserved ids in `evidence_screenshots`, **without** a visual claim about them → **remove them deterministically**, keep the finding, and record `stripped_screenshot_ids`.
   - A real visual claim (in `screenshot_observations` or `explanation`, mentioning an unobserved screenshot id) → drop **that finding** only, as now.
   - The repair message names the exact offending ids per finding and both fixes ("ask_screenshot first, or remove the id").
   - The system prompt states the rule up front: "List in evidence_screenshots only the screenshots you asked about."
   - Tests: a finding with 2 observed + 1 unobserved id and no claim → kept, 1 id stripped; a finding that claims what an unobserved screenshot shows → dropped; the repair message contains the ids.
   > Codex: Fixed in `audit_validation.py`, `audit_agent.py` and `audit_vision.py`. Owned screenshot IDs with no answered question cited by that finding are stripped only when there is no explicit unsupported claim; `normalizations` records `case_id`, `finding_id` and `stripped_screenshot_ids`. The guard still rejects invented/foreign IDs, unanswered questions, visual text without observations, and explicit mentions of unobserved catalogue IDs in explanation or screenshot_observations (whole-ID matching). The tool error names the offending IDs per finding and both fixes. The prompt states the rule up front; repair may ask a screenshot question within the existing attempt/turn/time budgets, then submit one corrected draft. Valid findings from either submission survive even when another finding's repair fails. Tests cover 2 observed + 1 stripped, unsupported claims in both fields, foreign IDs, per-finding feedback, ask-before-correction, and a retained ticket despite an invalid sibling.
2. **MUST (from round 5 SHOULD 2):** the partial-availability wording, and a test that a partial audit with a validated ticket candidate still reaches "Review tickets". The description of build #9 ("Audited 1 cases … AI audit
   unavailable") shows why this matters.
   > Codex: Fixed shared Markdown/HTML/preview wording and CLI: partial coverage names analysed/total counts and the unanalysed case/reason; unavailable is reserved for zero analysed cases. `availability` explicitly records complete/partial/unavailable; `agent_unavailable` is true only for zero. A failed corrected submission is an `AUDIT_REPAIR_FAILED` output_validation diagnostic, with no VISION_VALIDATION_FAILED provider label. A fixture with 2 of 3 cases analysed retains its validated ticket. In an isolated real Jenkins sandbox, its actual Review tickets stage reached input and paused; no availability flag blocks its candidate gate. See handoff for logs.
3. **NIT:** "Record decision and Jira" still starts a container and writes a decision when "Review tickets" was skipped. Skip it with the same `when` condition (nothing to record), or record a one-line
   "no ticket candidates" decision without a Docker agent.
   > Codex: Fixed in `Jenkinsfile`: Record decision and Jira uses the same candidate condition as Review tickets, with `beforeAgent true`. The static regression verifies that ordering; an isolated Declarative run with no candidates skipped both stages successfully, with no node or shell allocation. The guide now states that no empty decision file/container is created for that path. Declines/timeouts when candidates exist still get their decision recorded.
4. **Robustness note (no action):** each build re-runs the audit, so results vary from build to build (build #8: OSM-002 analysed with a ticket; build #9: unanalysed). After fix 1 this should be stable enough for
   the demo; if it isn't, report it rather than loosening the evidence rules.


## Handoff (Codex, round 6 fixes, 2026-10-16)

### Goal
Fix round 6 MUST 1–2 and NIT 3 (including their round 5 SHOULD predecessors): retain useful audit findings,
report partial coverage accurately, and avoid a Jira container when there are no ticket candidates.

### What changed
- `src/test_agent/audit_validation.py`: determine screenshot support from this case's answered questions cited by each finding. Remove owned but unobserved screenshot references only when they do not carry an unsupported claim; log each accepted normalization as `{case_id, finding_id, stripped_screenshot_ids}` under `analysis.normalizations`. Unknown/foreign IDs are still rejected. Explicit unobserved catalogue IDs in explanation/observations, and observations without answered questions, still reject that finding. Repair diagnostics include the exact offending screenshot IDs.
- `src/test_agent/audit_agent.py`, `audit_vision.py`: tell the analyst the rule up front; send per-finding screenshot IDs and both fixes in error tool results. Permit screenshot questions during repair within existing 5/25 attempt limits, 13 analyst turns, and timeout; still allow only one corrected submission. Retain validated findings across submissions and recover them if a sibling's correction or later model call fails. Save failed corrections as `AUDIT_REPAIR_FAILED` in output_validation, without a misleading vision-provider code.
- `src/test_agent/audit_presentation.py`, `cli.py`: partial coverage names the count and each missing case/reason in the console, preview/build description, Markdown and HTML. Only zero analysed cases are unavailable. JSON now includes `availability` (complete/partial/unavailable); `agent_unavailable` is true only for zero analysed cases. Fixed singular headline wording (1 case).
- `Jenkinsfile`: gate Record decision and Jira on the same validated-candidate condition as Review tickets, with `beforeAgent true`; no candidate means no Jira container or empty decision file. Existing decline/timeout decisions still record when candidates exist. Partial availability does not block approval of valid candidates.
- `tests/test_audit_agent.py`, `tests/test_ci.py`: two observed + one extra screenshot normalization; claims in either field and foreign-ID rejection; exact repair IDs; asking before correcting; valid ticket retained after a sibling's second invalid submission; partial console/Markdown/HTML/preview; candidate gate and before-agent ordering. Existing Jira guards/dry-run tests remain green.
- `docs/ci/jenkins-guide.md` §§11, 13, 15 and `README.md`: normalization records, repair bounds, partial coverage semantics and the no-candidate skip path.

### How to verify
```bash
uv run python -m unittest discover -s tests -v
```
**169 tests passed in 68.691s.** Full output below; `git diff --check` passed.

Also verified the actual Declarative stage snippets on an isolated Jenkins sandbox using the existing controller image
and a new temporary home, without network, ports, real credentials, a Docker socket or the live Jenkins volume:
- A real `audit_review.json` preview produced by the fake-provider partial-audit test (2 of 3 cases, one validated ticket) was used as fixture metadata. The actual Review tickets stage reached `input` and paused. The synthetic run was then stopped; no Jira stage was included in that partial fixture.
- With candidates empty, both actual Review tickets and Record decision and Jira snippets ran as a separate Declarative fixture: SUCCESS, both skipped due to their condition, no node/shell/agent allocation.
- No pending script signatures. The temporary controller was removed after saving/verifying the log.

Fixture preparation and init scripts remain in `/tmp/wbs-round6-smoke/`; captured logs are `/tmp/wbs-round6-local.log` and `/tmp/wbs-round6-gating.log`.
This runtime check verifies the input/skip boundary, not a real issue submission.

### Known limitations / open questions
- No live model re-audit, production Jenkins build, Jira issue/comment, commit or push was performed in this round. After review/push, rerun the normal build and inspect normalized/dropped findings plus the approval pause.
- Unsupported-claim detection is deliberately conservative for explicit catalogue-ID references in explanation or screenshot_observations; whole-ID matching prevents an ID from matching a longer map/step ID. The model must still ground prose in cited observations; Python does not perform general language understanding of arbitrary visual prose.
- An answered screenshot must also have its Q-ID cited by that finding to count as support. Merely being present in the catalogue or observed elsewhere in the case is insufficient.
- A repair can ask first only within the remaining existing turn/question/time budget. It does not gain unlimited retries or a second corrected submission.
- Results may still vary across live model calls. Report any remaining instability rather than relaxing evidence or ticket rules.
- Ready for Claude review; all changes remain uncommitted and unpushed.

### Test output — unit suite (full)
```text
test_all_row_types_statuses_vision_healing_paths_and_formula_safety (test_audit.AuditTests.test_all_row_types_statuses_vision_healing_paths_and_formula_safety) ... ok
test_csv_prefix_and_truncation_and_invalid_cli (test_audit.AuditTests.test_csv_prefix_and_truncation_and_invalid_cli) ... ok
test_html_locator_wording_keeps_raw_csv (test_audit.AuditTests.test_html_locator_wording_keeps_raw_csv) ... ok
test_missing_results_still_exports_case_and_rejects_outside_evidence (test_audit.AuditTests.test_missing_results_still_exports_case_and_rejects_outside_evidence) ... ok
test_repeat_indexes_and_row_ids_are_stable (test_audit.AuditTests.test_repeat_indexes_and_row_ids_are_stable) ... ok
test_claude_only_native_tool_loop_covers_all_cases_without_glm (test_audit_agent.AuditAgentTests.test_claude_only_native_tool_loop_covers_all_cases_without_glm) ... ok
test_claude_request_blind_one_png_and_native_size_guard (test_audit_agent.AuditAgentTests.test_claude_request_blind_one_png_and_native_size_guard) ... ok
test_dossiers_valid_analysis_all_cases_and_packaged_link (test_audit_agent.AuditAgentTests.test_dossiers_valid_analysis_all_cases_and_packaged_link) ... ok
test_dropped_model_finding_preserves_valid_sibling_and_false_pass_warning (test_audit_agent.AuditAgentTests.test_dropped_model_finding_preserves_valid_sibling_and_false_pass_warning) ... ok
test_envelope_diagnostics_and_attention_groups (test_audit_agent.AuditAgentTests.test_envelope_diagnostics_and_attention_groups) ... ok
test_evidence_rejections_and_human_fallbacks (test_audit_agent.AuditAgentTests.test_evidence_rejections_and_human_fallbacks) ... ok
test_false_pass_requires_certain_comparable_contradiction_no_ticket (test_audit_agent.AuditAgentTests.test_false_pass_requires_certain_comparable_contradiction_no_ticket) ... ok
test_missing_claude_key_never_uses_glm_credentials (test_audit_agent.AuditAgentTests.test_missing_claude_key_never_uses_glm_credentials) ... ok
test_native_one_repair_and_safe_field_errors (test_audit_agent.AuditAgentTests.test_native_one_repair_and_safe_field_errors) ... ok
test_native_partial_audit_retains_ticket_after_failed_sibling_repair (test_audit_agent.AuditAgentTests.test_native_partial_audit_retains_ticket_after_failed_sibling_repair) ... ok
test_native_tool_errors_limits_and_incomplete_output (test_audit_agent.AuditAgentTests.test_native_tool_errors_limits_and_incomplete_output) ... ok
test_repair_can_ask_about_a_missing_screenshot_before_resubmitting (test_audit_agent.AuditAgentTests.test_repair_can_ask_about_a_missing_screenshot_before_resubmitting) ... ok
test_tool_rejections_limits_errors_and_uncertainty (test_audit_agent.AuditAgentTests.test_tool_rejections_limits_errors_and_uncertainty) ... ok
test_unused_screenshot_ids_strip_without_weakening_claim_guards (test_audit_agent.AuditAgentTests.test_unused_screenshot_ids_strip_without_weakening_claim_guards) ... ok
test_auth_note_covers_blind_image_rejections_without_echoing_messages (test_audit_agent.AuditCliTests.test_auth_note_covers_blind_image_rejections_without_echoing_messages) ... ok
test_auth_rejection_is_explicit_in_console_and_review_metadata (test_audit_agent.AuditCliTests.test_auth_rejection_is_explicit_in_console_and_review_metadata) ... ok
test_ci_unavailable_mode_never_calls_models_and_still_writes_review (test_audit_agent.AuditCliTests.test_ci_unavailable_mode_never_calls_models_and_still_writes_review) ... ok
test_partial_cli_reports_coverage_and_keeps_a_ticket_candidate (test_audit_agent.AuditCliTests.test_partial_cli_reports_coverage_and_keeps_a_ticket_candidate) ... ok
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
test_guard_catches_restricted_parsing_files_and_processes (test_ci.JenkinsSandboxTests.test_guard_catches_restricted_parsing_files_and_processes) ... ok
test_no_candidates_skip_jira_before_allocating_its_docker_agent (test_ci.JenkinsSandboxTests.test_no_candidates_skip_jira_before_allocating_its_docker_agent) ... ok
test_pipeline_uses_pinned_sandbox_safe_json_steps (test_ci.JenkinsSandboxTests.test_pipeline_uses_pinned_sandbox_safe_json_steps) ... ok
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
test_repeat_never_translates_and_writes_html_json (test_day6.Day6Tests.test_repeat_never_translates_and_writes_html_json) ... Executing <Task finished name='Task-457' coro=<Day6Tests.test_repeat_never_translates_and_writes_html_json() done, defined at /Users/xuenilaw/Documents/myProject/WBS/tests/test_day6.py:255> result=None created at /opt/homebrew/Cellar/python@3.14/3.14.8/Frameworks/Python.framework/Versions/3.14/lib/python3.14/asyncio/runners.py:110> took 0.203 seconds
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
test_bug_metadata_present_or_absent_and_attachment_header (test_jira.JiraTests.test_bug_metadata_present_or_absent_and_attachment_header) ... ok
test_dry_run_sends_nothing_and_writes_plain_adf_payload (test_jira.JiraTests.test_dry_run_sends_nothing_and_writes_plain_adf_payload) ... ok
test_duplicate_uses_new_search_and_comment_no_create (test_jira.JiraTests.test_duplicate_uses_new_search_and_comment_no_create) ... ok
test_unapproved_unknown_changed_analysis_and_safe_http_failures (test_jira.JiraTests.test_unapproved_unknown_changed_analysis_and_safe_http_failures) ... ok
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
Ran 169 tests in 68.691s

OK
```

### Test output — isolated Jenkins gating check (full captured output)
```text
partial_audit_paused_for_ticket_approval=true
Started
[Pipeline] Start of Pipeline
[Pipeline] stage
[Pipeline] { (Review tickets)
[Pipeline] script
[Pipeline] {
[Pipeline] timeout
Timeout set to expire in 30 min
[Pipeline] {
[Pipeline] input
Input requested
no_candidates_result=SUCCESS
no_candidates_allocated_no_agent=true
Started
[Pipeline] Start of Pipeline
[Pipeline] stage
[Pipeline] { (Review tickets)
Stage "Review tickets" skipped due to when conditional
[Pipeline] getContext
[Pipeline] }
[Pipeline] // stage
[Pipeline] stage
[Pipeline] { (Record decision and Jira)
[Pipeline] timeout
Timeout set to expire in 10 min
[Pipeline] {
[Pipeline] }
[Pipeline] // timeout
Stage "Record decision and Jira" skipped due to when conditional
[Pipeline] getContext
[Pipeline] }
[Pipeline] // stage
[Pipeline] End of Pipeline
Finished: SUCCESS
pending_signatures=0
ROUND6_GATING_OK
```

## Review round 6: re-review (Claude, 2026-10-16)
Verdict: **APPROVED. Commit, push, Build Now** (no controller rebuild needed; no plugin change).
Verified: 169 tests OK; read the normalization in `audit_validation.py`: owned, unobserved ids are stripped only without a claim, and foreign ids and explicit claims are still rejected; `normalizations` is recorded;
the Jenkinsfile gates "Record decision and Jira" on the same candidate condition (`beforeAgent true`); and Codex's sandbox runs show a partial audit pausing at input, with no candidates skipping both stages.
**Watch item (fix only if the next build shows it):** a finding whose `screenshot_observations` text is non-empty but doesn't cite the matching Q-id in `evidence_questions` still counts as an
unsupported claim. If build #10 drops findings with `UNOBSERVED_SCREENSHOT_CLAIM` while the case has answered questions for those screenshots, the next fix is to **auto-link** the case's answered
Q-ids for the screenshots the finding names (deterministic: the answers exist), instead of dropping the finding.

## Review round 7: build #11, first real human-in-the-loop (Claude, 2026-10-16)
**Human-in-the-loop works:** "Review tickets" paused, the user ticked `F-OSM-002-1`, and `jira_decision.json` = approved by the user, with the analysis hash.
**But no ticket was created:** `jira_results.json` = `{"errors":[{"code":"JIRA_HTTP","status":404}]}`. It isn't recorded **which** Jira request returned 404. (Jira Cloud also answers 404 when the
authenticated account can't see the project, so the credential/account is the first suspect, as well as the URL.)

### 1. MUST: make the Jira failure diagnosable, plus a safe connection check
- Record the **phase** of every Jira error (`issue_types` / `search` / `create` / `comment` / `attach`) and the **path template** (e.g. `issue/createmeta/{project}/issuetypes`), never the
  query values, the email or response bodies. Print it in the console: "Jira 404 during issue_types (project WBSFP not found or not visible to the credential's account)".
- New command **`python -m test_agent jira check`** (local and as an optional Jenkins step): `GET myself` (auth OK? prints only the account's display name, not the email), `GET project/{key}`
  (visible?), and the issue types found. Print statuses only. Document it in the guide as the first troubleshooting step: "the email in `wbs-jira` must be the Atlassian account that can see WBSFP; the
  token must belong to that same account".
- Check the paths against the official v3 docs once more, and add a unit test per phase with a fake 404.
  > Codex: Fixed in `jira.py`, `cli.py`, `Jenkinsfile` and tests. Errors now carry a controlled phase and constant path_template (no concrete query values/email/body); console output names 404 during issue_types and the project's possible absence/visibility problem. Added GET-only `jira check`: auth/display name, project visibility, create metadata types, stop/nonzero on first failure, no report/decision write. Added opt-in CHECK_JIRA_CONNECTION (default false) in Jenkins using wbs-jira. Fake 404 tests cover issue_types/search/create/comment/attach separately plus all read-check phases and privacy/GET-only/CLI failure behavior. Verified all seven methods/paths against Atlassian's official OpenAPI (https://dac-static.atlassian.com/cloud/jira/platform/swagger-v3.v3.json). Guide §12 now starts troubleshooting with the same-account email/token and the read-only check. No live Jira request was made; the account/site/permission cause of build #11's 404 is not claimed resolved without that check.

### 2. MUST: a clear approval dialog (user's wording, 2026-10-16)
The user found the input dialog unclear. Change it in the `Jenkinsfile` (input step) and the preview builder:
- **Button:** `ok: 'Create Jira ticket'` (instead of "Record decision").
- **Message (top):** "AI audit requires human approval. Tick the test case(s) you want to report, then click 'Create Jira ticket'. Unticked items are not created."
- **Summary line:** `Total TC: 3; Passed: 2; Failed: 1; Blocked: 0` (from `summary.json`), instead of "2 attention items … 1 needs your attention".
- **Analysis link:** a clickable link to `audit_analysis.md` / the Test Report that opens in a new tab. Check what Jenkins allows: the input message/parameter descriptions are plain text unless the
  global **Markup Formatter** is "Safe HTML", which may strip `target="_blank"`. Implement the best option that works on this controller, and document it (e.g. the link in the build description
  or the sidebar "Test Report" if the dialog can't render links). Don't relax security beyond the Safe HTML formatter.
- **One line per ticket checkbox**, in exactly this format:
  `F-OSM-002-1 | OSM-002 | Cause: Test case problem | Confidence: high | Reason: <one sentence>`
  (human-readable cause names; "Confidence" is the AI's low/medium/high, not a probability.)
  Add a required `short_reason` field to the finding schema (one sentence, ≤ 160 chars; Python truncates and strips newlines), e.g. "The 776 km route takes 7:36, so the 180-minute limit is unrealistic."
  The long explanation stays in `audit_analysis.md` and the Jira description.
- Tests: the dialog text/labels are built from a fixture; the label format; a long `short_reason` truncated to one line; untrusted text escaped.
  > Codex: Fixed the preview builder, required Finding.short_reason, prompt and actual input step. Button and top message match the requested wording; suite totals come from summary.json case verdicts, and each escaped checkbox label is one line with human-readable Cause, AI Confidence and ≤160-character normalized short_reason. Full explanation and Jira description remain intact; all choices remain false by default. Read-only inspection found no configured markupFormatter in the current controller config (default Plain text; Safe HTML plugin present). Therefore the implemented link option is the existing clickable Test Report sidebar: Cmd/Ctrl-click or Open Link in New Tab, with an artifact URL in input text for copying. No formatter/CSP change or raw HTML was introduced; a missing BUILD_URL falls back to the sidebar instruction. Guide §13 explains the limitation and the Safe HTML filtering caveat. Fixture tests cover text, totals, exact labels, required/truncated/newline-free reasons and escaping; a real isolated sandbox input-step check verifies the new button/message/label/default and URL fallback. See handoff below.

Then the user commits, pushes, runs Build Now, approves, and should see a WBSFP issue (or a clear phase-level Jira error).


## Handoff (Codex, round 7 fixes, 2026-10-16)

### Goal
Implement round 7 MUST 1–2: diagnose Jira failures safely and make the human approval dialog clear.
The real account/project/permission cause of build #11's 404 remains for the read-only connection check.

### What changed
- `src/test_agent/jira.py`: record every error's phase and constant path_template; transport phases are issue_types/search/create/comment/attach, with auth/project for connection checks. Local approval/prepare/configuration errors have no HTTP path. No actual query values, emails, tokens or response bodies enter errors. Preserve a created issue key if attachments fail. Added GET-only check_connection and safe console messages, including the requested issue_types/404 project-visibility hint.
- `src/test_agent/cli.py`: new `jira check`, with status/display-name/type-name output only, stopping on the first failed stage and returning nonzero; no issue/comment/attachment/decision writes. Jira create failures now print the phase-level message before their safe result JSON.
- `Jenkinsfile`: optional CHECK_JIRA_CONNECTION parameter (false by default), binding wbs-jira for an explicitly selected read-only stage. Input uses **Create Jira ticket**, the exact requested top instruction, suite case-verdict totals and one-line candidate labels. All choices remain unchecked and hash/ID approval guards remain intact. Analysis instructions use the existing Test Report sidebar and a copyable artifact URL; an unset BUILD_URL falls back to the sidebar text.
- `src/test_agent/schemas/audit_analysis.py`: required short_reason, minimum 1 / maximum 160 characters; collapse whitespace/newlines before truncation. Schema description and analyst prompt ask for one plain sentence.
- `src/test_agent/audit_presentation.py`, `audit_agent.py`: generate the dialog message, counts from summary.json case entries, human-readable causes and HTML-escaped single-line labels. Keep the existing attention summary for reports/build description; use suite totals specifically in the dialog. Long explanation remains in Markdown and the Jira ADF description.
- `tests/test_jira.py`: separate fake 404 tests for all five send-flow phases, check failures for auth/project/issue_types, GET-only/no-write behavior, CLI status/nonzero-exit behavior, email/account-ID/body/token exclusion, and display-name email redaction.
- `tests/test_audit_agent.py`, `tests/test_ci.py`: fixture totals and exact label/message, required/truncated/newline-free short_reason, escaping, optional stage wiring, button and URL fallback. Existing audit, approval, deduplication and attachment tests pass.
- `docs/ci/jenkins-guide.md` §§12–13, 15 and README: first troubleshooting step, same-account email/token requirement, connection-check usage, endpoint table, new dialog wording, current formatter fallback, and old-analysis schema migration.

### How to verify
```bash
uv run python -m unittest discover -s tests -v
```
**180 tests passed in 68.433s.** `git diff --check` passed. Full output below.

**API verification:** downloaded [Atlassian's public OpenAPI](https://dac-static.atlassian.com/cloud/jira/platform/swagger-v3.v3.json) and asserted the documented method for each of:
GET myself; GET project/{projectIdOrKey}; GET issue/createmeta/{projectIdOrKey}/issuetypes;
POST search/jql; POST issue; POST issue/{issueIdOrKey}/comment; POST issue/{issueIdOrKey}/attachments.
All seven matched. This was public documentation access, not a request to the user's Jira account.

**Real sandbox input-step check:** used a fresh isolated Jenkins home, fake-provider preview and the actual edited Review tickets stage.
Verified input.ok, exact top instruction, suite counts, one-line human-readable label, default false,
and the missing-public-URL fallback; pending script signatures = 0. No network/ports/credentials/live volume/Docker socket.
The synthetic fixture has one PASSED, one FAILED and one BLOCKED case, so its displayed counts intentionally differ from the OSM example.
The unit fixture separately verifies Total TC: 3; Passed: 2; Failed: 1; Blocked: 0.
The temporary controller was stopped/removed after capturing the result; no real ticket approval or Jira request was performed.
Fixture scripts remain under `/tmp/wbs-round7-ui/`; logs are `/tmp/wbs-round7-local.log` and `/tmp/wbs-round7-dialog.log`.

**Current controller link behavior:** a read-only configuration check found no markupFormatter element and the installed Safe HTML plugin;
Jenkins therefore uses its default Plain text formatter, also confirmed as EscapedMarkupFormatter in the isolated run.
The dialog cannot promise an inline clickable HTML link or preserved target=_blank. The supported fallback is the existing clickable
**Test Report** sidebar link, opened with Cmd/Ctrl-click or the browser's Open Link in New Tab command; the dialog explains this.
No global formatter/CSP change, plugin change, raw HTML or controller rebuild is required.

### User checks after review/push
1. In `.env`, set the Jira email/token for the same Atlassian account that can view WBSFP, then run:
   ```bash
   uv run python -m test_agent jira check
   ```
   Or select CHECK_JIRA_CONNECTION in Build with Parameters to check the actual wbs-jira credential. A success only proves the GET checks; write permissions still matter.
2. Re-run the audit/build so new findings contain required short_reason. Old analysis lacking it must be re-audited/packaged and approved under its new hash; existing approvals are not silently migrated.
3. Check the new dialog, open Test Report in another tab, select only intended candidates and click Create Jira ticket.
4. Expect a WBSFP issue/comment or a clear phase/status/path-template error. For 404 in project/issue_types, check the site/key and that account's visibility before changing API routes.

### Known limitations / open questions
- No live Jira authentication/project visibility/create/comment/attachment or live Anthropic call was made in this round. Build #11's underlying 404 cause is still unconfirmed.
- short_reason's one-sentence wording is requested through the prompt/schema description; deterministic Python rules enforce nonempty, one line and ≤160 characters rather than language-specific sentence parsing.
- Escaped malicious model text may display HTML entities under Plain text; it remains safe if Safe HTML is enabled later. The dialog's analysis URL is plain text on the current controller; sidebar/browser navigation is the documented link fallback.
- CHECK_JIRA_CONNECTION changes no Jira data. A failed optional check marks its stage/build UNSTABLE and leaves the existing test flow running.
- No commit or push performed. Ready for Claude review through this file.

### Test output — unit suite (full)
```text
test_all_row_types_statuses_vision_healing_paths_and_formula_safety (test_audit.AuditTests.test_all_row_types_statuses_vision_healing_paths_and_formula_safety) ... ok
test_csv_prefix_and_truncation_and_invalid_cli (test_audit.AuditTests.test_csv_prefix_and_truncation_and_invalid_cli) ... ok
test_html_locator_wording_keeps_raw_csv (test_audit.AuditTests.test_html_locator_wording_keeps_raw_csv) ... ok
test_missing_results_still_exports_case_and_rejects_outside_evidence (test_audit.AuditTests.test_missing_results_still_exports_case_and_rejects_outside_evidence) ... ok
test_repeat_indexes_and_row_ids_are_stable (test_audit.AuditTests.test_repeat_indexes_and_row_ids_are_stable) ... ok
test_approval_dialog_uses_suite_totals_short_reason_and_escaped_one_line_labels (test_audit_agent.AuditAgentTests.test_approval_dialog_uses_suite_totals_short_reason_and_escaped_one_line_labels) ... ok
test_claude_only_native_tool_loop_covers_all_cases_without_glm (test_audit_agent.AuditAgentTests.test_claude_only_native_tool_loop_covers_all_cases_without_glm) ... ok
test_claude_request_blind_one_png_and_native_size_guard (test_audit_agent.AuditAgentTests.test_claude_request_blind_one_png_and_native_size_guard) ... ok
test_dossiers_valid_analysis_all_cases_and_packaged_link (test_audit_agent.AuditAgentTests.test_dossiers_valid_analysis_all_cases_and_packaged_link) ... ok
test_dropped_model_finding_preserves_valid_sibling_and_false_pass_warning (test_audit_agent.AuditAgentTests.test_dropped_model_finding_preserves_valid_sibling_and_false_pass_warning) ... ok
test_envelope_diagnostics_and_attention_groups (test_audit_agent.AuditAgentTests.test_envelope_diagnostics_and_attention_groups) ... ok
test_evidence_rejections_and_human_fallbacks (test_audit_agent.AuditAgentTests.test_evidence_rejections_and_human_fallbacks) ... ok
test_false_pass_requires_certain_comparable_contradiction_no_ticket (test_audit_agent.AuditAgentTests.test_false_pass_requires_certain_comparable_contradiction_no_ticket) ... ok
test_missing_claude_key_never_uses_glm_credentials (test_audit_agent.AuditAgentTests.test_missing_claude_key_never_uses_glm_credentials) ... ok
test_native_one_repair_and_safe_field_errors (test_audit_agent.AuditAgentTests.test_native_one_repair_and_safe_field_errors) ... ok
test_native_partial_audit_retains_ticket_after_failed_sibling_repair (test_audit_agent.AuditAgentTests.test_native_partial_audit_retains_ticket_after_failed_sibling_repair) ... ok
test_native_tool_errors_limits_and_incomplete_output (test_audit_agent.AuditAgentTests.test_native_tool_errors_limits_and_incomplete_output) ... ok
test_repair_can_ask_about_a_missing_screenshot_before_resubmitting (test_audit_agent.AuditAgentTests.test_repair_can_ask_about_a_missing_screenshot_before_resubmitting) ... ok
test_tool_rejections_limits_errors_and_uncertainty (test_audit_agent.AuditAgentTests.test_tool_rejections_limits_errors_and_uncertainty) ... ok
test_unused_screenshot_ids_strip_without_weakening_claim_guards (test_audit_agent.AuditAgentTests.test_unused_screenshot_ids_strip_without_weakening_claim_guards) ... ok
test_auth_note_covers_blind_image_rejections_without_echoing_messages (test_audit_agent.AuditCliTests.test_auth_note_covers_blind_image_rejections_without_echoing_messages) ... ok
test_auth_rejection_is_explicit_in_console_and_review_metadata (test_audit_agent.AuditCliTests.test_auth_rejection_is_explicit_in_console_and_review_metadata) ... ok
test_ci_unavailable_mode_never_calls_models_and_still_writes_review (test_audit_agent.AuditCliTests.test_ci_unavailable_mode_never_calls_models_and_still_writes_review) ... ok
test_partial_cli_reports_coverage_and_keeps_a_ticket_candidate (test_audit_agent.AuditCliTests.test_partial_cli_reports_coverage_and_keeps_a_ticket_candidate) ... ok
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
test_approval_wording_and_optional_read_only_jira_check (test_ci.JenkinsSandboxTests.test_approval_wording_and_optional_read_only_jira_check) ... ok
test_guard_catches_restricted_parsing_files_and_processes (test_ci.JenkinsSandboxTests.test_guard_catches_restricted_parsing_files_and_processes) ... ok
test_no_candidates_skip_jira_before_allocating_its_docker_agent (test_ci.JenkinsSandboxTests.test_no_candidates_skip_jira_before_allocating_its_docker_agent) ... ok
test_pipeline_uses_pinned_sandbox_safe_json_steps (test_ci.JenkinsSandboxTests.test_pipeline_uses_pinned_sandbox_safe_json_steps) ... ok
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
test_repeat_never_translates_and_writes_html_json (test_day6.Day6Tests.test_repeat_never_translates_and_writes_html_json) ... Executing <Task finished name='Task-462' coro=<Day6Tests.test_repeat_never_translates_and_writes_html_json() done, defined at /Users/xuenilaw/Documents/myProject/WBS/tests/test_day6.py:255> result=None created at /opt/homebrew/Cellar/python@3.14/3.14.8/Frameworks/Python.framework/Versions/3.14/lib/python3.14/asyncio/runners.py:110> took 0.204 seconds
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
test_check_404_reports_each_read_phase_and_stops (test_jira.JiraCheckTests.test_check_404_reports_each_read_phase_and_stops) ... ok
test_check_cli_prints_safe_statuses_and_failure_has_nonzero_exit (test_jira.JiraCheckTests.test_check_cli_prints_safe_statuses_and_failure_has_nonzero_exit) ... ok
test_check_uses_only_get_and_returns_no_email_or_account_id (test_jira.JiraCheckTests.test_check_uses_only_get_and_returns_no_email_or_account_id) ... ok
test_email_shaped_display_name_is_redacted (test_jira.JiraCheckTests.test_email_shaped_display_name_is_redacted) ... ok
test_404_during_attach_is_diagnosable (test_jira.JiraTests.test_404_during_attach_is_diagnosable) ... ok
test_404_during_comment_is_diagnosable (test_jira.JiraTests.test_404_during_comment_is_diagnosable) ... ok
test_404_during_create_is_diagnosable (test_jira.JiraTests.test_404_during_create_is_diagnosable) ... ok
test_404_during_issue_types_is_diagnosable (test_jira.JiraTests.test_404_during_issue_types_is_diagnosable) ... ok
test_404_during_search_is_diagnosable (test_jira.JiraTests.test_404_during_search_is_diagnosable) ... ok
test_bug_metadata_present_or_absent_and_attachment_header (test_jira.JiraTests.test_bug_metadata_present_or_absent_and_attachment_header) ... ok
test_dry_run_sends_nothing_and_writes_plain_adf_payload (test_jira.JiraTests.test_dry_run_sends_nothing_and_writes_plain_adf_payload) ... ok
test_duplicate_uses_new_search_and_comment_no_create (test_jira.JiraTests.test_duplicate_uses_new_search_and_comment_no_create) ... ok
test_unapproved_unknown_changed_analysis_and_safe_http_failures (test_jira.JiraTests.test_unapproved_unknown_changed_analysis_and_safe_http_failures) ... ok
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
Ran 180 tests in 68.433s

OK
```

### Test output — isolated Jenkins dialog (full captured output)
```text
button=Create Jira ticket
message=AI audit requires human approval. Tick the test case(s) you want to report, then click 'Create Jira ticket'. Unticked items are not created.
Total TC: 3; Passed: 1; Failed: 1; Blocked: 1
Analysis: Cmd/Ctrl-click 'Test Report' in this build's sidebar to open it in a new tab.
Full analysis: open Test Report from the build page.
checkbox=F-CASE-2-1 | CASE-2 | Cause: Test case problem | Confidence: medium | Reason: The observed duration needs comparison with the source expectation.
default_checked=false
formatter=hudson.markup.EscapedMarkupFormatter
pending_signatures=0
ROUND7_DIALOG_OK
```

## Review round 7: re-review (Claude, 2026-10-16)
Verdict: **APPROVED. Commit and push.** Verified: 180 tests OK; Jenkinsfile has `ok: 'Create Jira ticket'`, the requested top message, suite totals, one-line labels with `short_reason`, all unticked;
optional read-only `CHECK_JIRA_CONNECTION`; Jira errors carry phase + path template only; the seven v3 paths were checked against the official OpenAPI. Clickable links: the controller uses the default
Plain text formatter, so the dialog points to the clickable **Test Report** sidebar (Cmd/Ctrl-click for a new tab). That's acceptable without relaxing security.
The user corrected the `wbs-jira` email (2026-10-16). Recommended order: push → "Build with Parameters" with **CHECK_JIRA_CONNECTION ✓** (proves auth + WBSFP visibility) → approve → issue.
