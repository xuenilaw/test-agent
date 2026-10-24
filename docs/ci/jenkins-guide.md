# Connecting Excel to CI with Jenkins: a step-by-step guide

English | [中文](jenkins-guide.zh-CN.md)

This guide covers the `Jenkinsfile` and the `ci/` folder. Review and commit/push your changes first, and only then create the SCM job. Jenkins reads committed files from GitHub. It cannot see uncommitted changes on your Mac.
Each step ends with a checkpoint. Never share passwords or API keys.

## 1. The basic concepts in five minutes

**What to do:** Learn the flow: push → check for a new commit → install the environment → unit tests → translate and validate Excel → Playwright / Clef → download the evidence.

| Term | Meaning in this project | Testing analogy |
| --- | --- | --- |
| image / container | Environment template / a running instance started from it | Environment configuration / a test machine |
| controller | Jenkins in Docker; stores jobs, credentials and history | Scheduler |
| agent | Playwright Linux container that runs the commands | Machine that executes the tests |
| pipeline / stage / step | Jenkinsfile / a phase such as Setup / one command | Process / phase / action |
| workspace | Checkout under `/var/jenkins_home/workspace/...` | Working directory for this run |
| artifact | Archived HTML, CSV, screenshots, JSON, traces | Test evidence |
| credential | Secret injected into a specific stage | Test account configuration |
| trigger | Poll SCM checks Git for changes about every five minutes | Automatic trigger |

**Why:** A case status is not the same as the build result.

| Command result | Build result | Meaning |
| --- | --- | --- |
| suite exit 0, no JUnit failure/error | SUCCESS | All cases and Cleanup passed |
| suite exit 0, JUnit Cleanup has failure/error | UNSTABLE | Case checks passed but cleanup failed; investigate |
| suite exit 1 | UNSTABLE (usually yellow) | The run finished but has FAILED/BLOCKED cases; investigate |
| suite exit 2, any other non-zero exit, or a crash | FAILURE (usually red) | A command or the execution flow broke |
| Unit tests fail | FAILURE | The tool's own regression tests failed; the live suite does not run |

**What you should see:** OSM-002 is designed to FAIL, so a normal demo may be UNSTABLE. Do not change expectations or thresholds to get a green build. BLOCKED is not a confirmed product defect either.
A Python crash can also return 1, so `ci/suite_result.py` also checks the run's complete summary, HTML, CSV and JUnit. Missing or inconsistent files, suite input errors, or a suite with no cases are FAILURE, so infrastructure problems are never reported as test findings.

**If something goes wrong:** First decide whether you are looking at a step, case or build status, then look for the matching evidence.

## 2. Start Jenkins

**What to do:** Open Docker Desktop, wait until the Engine is running, then:

```bash
# Run from the project root
docker version
lsof -nP -iTCP:8080 -sTCP:LISTEN
docker compose -f ci/docker-compose.yml config
docker compose -f ci/docker-compose.yml up -d --build
docker compose -f ci/docker-compose.yml ps
```

Open [http://127.0.0.1:8080](http://127.0.0.1:8080). The first start can take a few minutes.

**Known state on the development machine (2026-10-16):** A Terminal check found a Homebrew Jenkins already running on port 8080. If `lsof` still shows that Java/Jenkins process, run `brew services list` to confirm the service. Once you decide to use Docker Jenkins instead, run `brew services stop jenkins-lts` yourself to free the port, then run `up`. This does not delete the Homebrew Jenkins data. To restore the old service later, run `compose down` first, then `brew services start jenkins-lts`. Never let both services use port 8080 at once, and do not mistake the old service's page for the new container.

**Why:** Compose manages the controller and the persistent `wbs-ci_jenkins_home` volume. The port is bound to 127.0.0.1:8080 only, so it is not exposed to the local network. Port 50000 is not opened.
This local learning setup runs the controller as root and mounts `/var/run/docker.sock`. **That socket gives Jenkins full control over Docker Desktop's containers, images, volumes and every file Docker can mount on your Mac. Use it only for local learning with a trusted repository, never on a shared or production server.** Do not run untrusted PRs or Jenkinsfiles, and do not touch other n8n containers.

**What you should see:** `ps` shows Up and the page shows Unlock Jenkins.

**If something goes wrong:** Read the logs. Do not delete the volume first:

```bash
docker compose -f ci/docker-compose.yml logs --tail=80 jenkins
```

## 3. Unlock, plugins and admin account

**What to do:** Read the initial admin password locally:

```bash
docker compose -f ci/docker-compose.yml exec jenkins cat /var/jenkins_home/secrets/initialAdminPassword
```

Paste it only into your own Unlock Jenkins page, never into a chat. The Dockerfile pre-installs Pipeline, Git, Docker Pipeline, Credentials Binding, Pipeline Stage View, HTML Publisher (pinned to 429) and Pipeline Utility Steps (pinned to `3.810.va_7672d206740`). JUnit comes in as a dependency.
If a plugin selection page appears, choose **Select plugins to install**. You do not need to reinstall what is already there. Then create your own admin account and save the local Jenkins URL.

**Why:** These plugins provide pipelines, Docker agents and `withCredentials`. The required Docker Pipeline plugin ID is `docker-workflow`. You do not need the Docker cloud plugin.

**What you should see:** The Dashboard. The plugins above are listed under Manage Jenkins → Plugins → Installed plugins.

**If something goes wrong:** Look for a failed dependency in the logs. `plugins.txt` pins the direct plugin versions and the plugin manager resolves transitive dependencies. When upgrading later, review the controller and plugins together. Do not blindly switch to latest.

### Existing controller: apply the new report / JSON plugins and settings

**What to do:** After this change is reviewed, committed and pushed, run this in the Mac repository (wait for running builds to finish first):

```bash
docker compose -f ci/docker-compose.yml build jenkins
docker compose -f ci/docker-compose.yml up -d --force-recreate jenkins
docker compose -f ci/docker-compose.yml ps
```

**Why:** Plugins are baked into the new controller image, and `JAVA_OPTS` takes effect when the controller starts. Pushing only the Jenkinsfile does not replace the controller.
These commands keep the `jenkins_home` volume, accounts, credentials, jobs and history. Do not run `down --volumes`. Plugins missing from an existing volume are copied in from the image's ref directory.

The local Compose file sets the HTML CSP to `sandbox; default-src 'none'; img-src 'self' data:; style-src 'self' 'unsafe-inline';`.
This allows the report's inline CSS and `data:` thumbnails while still blocking scripts. The report itself has no scripts. **This is a controller-wide setting that affects other archived pages. It is only meant for this local learning Jenkins with a trusted repository.**
On shared or production servers, keep the default CSP and open the downloaded HTML locally. Do not add `script-src` or disable the sandbox for the report.

**What you should see:** Manage Jenkins → Plugins → Installed plugins lists HTML Publisher and Pipeline Utility Steps, and new builds show Test Report. If the report has no styling or images, check the JAVA_OPTS the container started with. Changing only the Jenkinsfile is not enough.

### Pipeline Groovy sandbox (the cause of builds #6/#7)

The sandbox restricts which Groovy APIs a Jenkinsfile may call, so scripts cannot directly manipulate controller files or processes.
A log line `RejectedAccessException: Scripts not permitted to use ...` means the sandbox blocked the script at runtime. Passing the Declarative linter does not prove those calls can run.

This project uses Pipeline Utility Steps' `readJSON(..., returnPojo: true)` and `writeJSON` to read and write the approval / Jira JSON. This avoids `JsonSlurperClassic` / `JsonOutput`, so no manual Script Approval is needed.
`returnPojo: true` returns plain Maps/Lists that survive pipeline checkpoints. See the [official step documentation](https://www.jenkins.io/doc/pipeline/steps/pipeline-utility-steps/) and the [pinned version and minimum Jenkins version](https://updates.jenkins.io/download/plugins/pipeline-utility-steps/).
After review and commit/push, first run the controller **build + up --force-recreate** commands above to install the new plugin, then click Build Now. Pulling the Jenkinsfile alone does not install plugins.
If you see `No such DSL method 'readJSON'` / `'writeJSON'`, confirm the plugin is installed and the controller has restarted.

## 4. Credentials: CI does not use .env

**What to do:** Manage Jenkins → Credentials → System → Global credentials (unrestricted) → Add Credentials. Add each item below as **Kind: Secret text**, **Scope: Global**, with your local value as the Secret. The IDs must match exactly:

| ID | Environment variable | Purpose |
| --- | --- | --- |
| `wbs-openai-api-key` | OPENAI_API_KEY | GLM translation / DOM healing |
| `wbs-openai-base-url` | OPENAI_BASE_URL | GLM OpenAI-compatible endpoint |
| `wbs-openai-model` | OPENAI_MODEL | GLM model name; if you use OPENAI_DEFAULT_MODEL locally, use the same value |
| `wbs-openrouter-api-key` | OPENROUTER_API_KEY | Clef route verification |
| `wbs-anthropic-api-key` | ANTHROPIC_API_KEY | Claude screenshot-click fallback |

VISION_PROVIDER=clef and VISION_MODEL=cloudflare/clef are plain settings in the Jenkinsfile. The route threshold comes from the contract: Clef 0.85, Anthropic 0.90. The click fallback stays Claude at 0.90.

For a private repository, also create a **Kind: Username with password** credential: Username = your GitHub username, Password = a GitHub token, ID = `wbs-github-read`. Choose a token that can only read test-agent, for example a fine-grained token with Contents: Read-only. Complete organization authorization if needed. Never put the token in the repository URL.

**Why:** Model credentials are bound only inside the Test suite stage's `withCredentials` block. Unit tests need no API keys. The scripts run `set +x` and never echo keys. Do not debug with `env`/`printenv`. Masking cannot stop a malicious Jenkinsfile from leaking secrets, so only build trusted branches. The GitHub checkout credential and the model keys are separate things.

**What you should see:** Five Secret text items, plus the GitHub credential for a private repository. Only the IDs are shown.

**If something goes wrong:** `Could not find credentials entry`: check the ID and scope. 401/403: check permissions, endpoint and account balance. Do not share full logs that contain keys.

**Anthropic 401/403 (builds #6/#7):** The Console and build description say so explicitly, for example `Anthropic credential rejected (401): update wbs-anthropic-api-key` (the real message wraps the ID in backticks).
Go to Manage Jenkins → Credentials → System → Global credentials → `wbs-anthropic-api-key` → Update. Keep Kind **Secret text** and the same ID, click Change Secret, paste the working `ANTHROPIC_API_KEY` value from your local `.env` without quotes, spaces or line breaks, then Save.
Jenkins holds its own copy, so editing your local `.env` does not update it. Never share the key. A 429 only means rate limiting and is not reported as a rejected credential.

## 5. Create a Pipeline from SCM

**What to do:** New Item → `test-agent` → Pipeline → OK. In the Pipeline section:

1. Definition = Pipeline script from SCM; SCM = Git.
2. Repository URL = `https://github.com/xuenilaw/test-agent.git`.
3. Credentials = `wbs-github-read` (private repository).
4. Branch Specifier = `*/main`; Script Path = `Jenkinsfile`.
5. Save, then click Build Now once by hand to load the Jenkinsfile's trigger.

**Why:** The pipeline is versioned together with the test cases. `pollSCM('H/5 * * * *')` checks for new commits about every five minutes; `H` spreads out the check times. **Any new commit on that branch can trigger a build, not only Excel changes.** No public webhook is needed. Nothing is polled while the Mac or Docker is stopped.

**What you should see:** After the first build, Configure → Build Triggers shows Poll SCM. Without new commits it should not re-run every five minutes. Check the Poll SCM Log.

**If something goes wrong:** If the Jenkinsfile is not found, confirm it was reviewed and pushed. If checkout fails, check the credential and branch. Never put a token in the URL.

## 6. The first build: stages, logs and downloading reports

**What to do:** Click the build number → Console Output / Stage View and follow Setup → Guardrail → Unit tests → Test suite (the optional Jira connection check comes after Guardrail).

**Why:** Setup cleans the workspace, checks out, installs the pinned uv==0.12.17, then runs `uv sync --locked`. The image `mcr.microsoft.com/playwright/python:v1.63.0-noble` must match playwright==1.63.0 in uv.lock: the image provides the Linux browsers and uv installs the Python package. PLAYWRIGHT_BROWSERS_PATH=/ms-playwright points at the Linux browsers. Never mount the Mac's `.browsers`.
Each build starts clean, so there are no earlier artifacts or locator cache. Every run is **Excel → GLM → validation → Playwright → Clef**, without `--reuse`, so it costs API calls.
GLM re-translates each time and results can differ. If you get TRANSLATION_REJECTED, read that case's validation.json. Do not hand-edit plan.json to bypass validation, and do not keep re-running to keep only the passing attempt.

**What you should see:** Unit tests do not call a live LLM. Test suite shows each case translating/running. Even when UNSTABLE, `post always` still publishes JUnit, HTML and the five named artifacts. Read them as described in the next section; you do not need to dig through nested folders for the report.

To open the CSV in Excel use Data → From Text/CSV and import as UTF-8. There is one row per case, action, check and cleanup. The raw `locator_source` values are: human = locator file, cache = cached, healed = GLM self-heal, vision = Claude click. The HTML uses readable names. `row_id` is stable when the same evidence is re-exported; `repeat_index` starts at 1. `reason_code` only stores an existing machine code and is otherwise blank. Summaries are in expected/actual/reason, and the full evidence is at the results_json/screenshot relative paths. A case that never ran still has a case row; no steps are invented. `duration_s` is only filled on case rows, and a blank does not mean zero. healed/borderline are Yes/No. Cells starting with the dangerous formula characters = + - @ are prefixed with a single quote so they are read as text. Do not remove this protection.

After the first CI build that produces evidence (it may be UNSTABLE here), check the start/end/line probabilities for OSM-001 step 4 and record the Linux numbers in the review. Check again after the first real SUCCESS. On the Mac, Berlin scored 0.856–0.870 against a threshold of 0.85. Linux rendering differences may make it BLOCKED. Record that honestly; do not adjust the threshold.

**If something goes wrong:** If Setup or Unit tests fail, there may be no suite artifacts at all. `allowEmptyArchive` does not fake a report or turn an earlier failure into success. Start with the first red stage.

### Reading the results in Jenkins

**What to do:** Open the build number and use these three entry points:

| Entry point | What it is good for | Why |
| --- | --- | --- |
| Test Result | One row per case and per source step, plus Cleanup; failure reasons and, in system-out, expected/actual, locator_source, Clef probabilities, reason code and relative evidence paths | JUnit XML turns test results into data Jenkins understands; trends appear once two or more builds have published results |
| Test Report | One click opens the HTML: case overview, collapsible steps, thumbnails and detailed observations | A complete, human-readable explanation without reading Console Output |
| Build Artifacts → reports/ | Five named downloads, see the table below | Fixed file locations instead of archiving the nested suite tree |

Test Result here shows the **Excel acceptance cases**, not the 136 Python unit tests. The unit tests are still in the Unit tests stage log.
One case contains several steps, so the test count Jenkins shows is "steps + Cleanup", which differs from the number of Excel cases. Repeated runs carry "Run n" in their names.
JUnit now runs in the Test suite stage's `post/always`, so the yellow UNSTABLE appears on Test suite. The global Post Actions only publish files and no longer turn yellow because of JUnit.

| Original step status | JUnit representation | Testing meaning |
| --- | --- | --- |
| PASSED | No failure/error/skipped child element | Requirement verified; borderline still passes and is flagged in system-out |
| FAILED | failure | Requirement not met |
| BLOCKED | error | No test conclusion could be reached; investigate |
| NOT_RUN | skipped | Not executed, for example because an earlier step failed |
| TRANSLATION_REJECTED | error named Translation | Test infrastructure / translation validation problem; must not be classed as a product bug |

OSM-002 is designed to FAIL and still shows red. An expected failure must not be disguised as a pass. The testsuite properties store `designed_outcome` / `outcome_as_designed`; the HTML's Designed / as designed column is easier to read.
JUnit itself marks the build UNSTABLE on failure/error. `ci/suite_result.py` separately checks the exit code and the complete summary, and classifies pipeline crashes or input errors as FAILURE.
The two cover **step display** and **run integrity** respectively; JUnit cannot turn an existing FAILURE back into UNSTABLE. When Setup/Unit tests fail early there may be no XML; `allowEmptyResults: false` reports that honestly instead of inventing an empty passing report.
Cleanup is shown separately. Even if a case's checks passed, a cleanup error/failure makes the build UNSTABLE. The classifier agrees with JUnit and does not rewrite historical case verdicts. Missing, empty or corrupt XML is FAILURE.

| File | Purpose |
| --- | --- |
| report.html | Downloadable on its own, with embedded thumbnails |
| audit.csv | Item-by-item record readable by Excel and later audit agents |
| junit.xml | Case/step XML read by Jenkins |
| summary.json | Case summary and original statuses |
| evidence.zip | All other evidence: screenshots, results, traces, translation and validation records |

**Full evidence links:** Download all five files into one folder, then **extract evidence.zip next to report.html** (extract its folders directly; do not wrap them in an extra evidence/ folder).
For example, the report links to `cases/OSM-001/run/screenshots/step-1.png`, and that path should exist after extraction. The standalone HTML still shows thumbnails; full-size images and trace links from the Jenkins page only work after downloading and extracting.
Absolute paths inside summary/JSON are kept as the original run record. Evidence links in HTML/JUnit use relative paths.

**Offline export on your machine:** No browser and no model calls:

```bash
uv run python -m test_agent junit artifacts/suite-<id>
uv run python -m test_agent package artifacts/suite-<id> --output-dir reports
```

`junit` / `package` also accept repeat folders. `reports/` is a dedicated output folder; do not put other files in it. Extract evidence into a separate download folder.

**Checkpoint:** A new build has Test Result and Test Report, and reports/ contains the five base artifacts. With audit/Jira enabled there are also analysis and decision files. OSM-002 shows its duration failure and the threshold is unchanged.
If an entry point is missing, check that HTML Publisher is installed, the JUnit XML path, and the post stage in Console Output. Old builds do not get the new views retroactively.

### Local evidence folders and retention

The suite folder layout is now:

```text
artifacts/suite-<id>/
  report.html, audit.csv, junit.xml, summary.json
  cases/OSM-001/
    translation/  # source, plan, validation, model-output
    run/          # results, screenshots, trace, vision, etc.
```

A repeat uses `artifacts/repeat-<id>/run-1/`, `run-2/`, each with the same layout inside, plus an aggregate HTML/CSV/JUnit and repeatability.json at the top level.
`--reuse` recognizes both old and new validated plans and copies them into the current suite when reused, so the evidence stays self-contained. `report` / `audit` / `junit` can read the old layout.
Even just adding a Munich/München hint makes an old plan's vocabulary stale. Use `revalidate <translation-folder>` to re-validate offline without re-running the model or changing historical evidence.

**Preview before cleaning up:**

```bash
uv run python -m test_agent prune --keep 10
# Check the listed paths before actually deleting
uv run python -m test_agent prune --keep 10 --yes
```

Keeps the newest **10 (across all four kinds combined)** suite-/repeat-/run-/translation- folders by top-level modification time, and deletes each older folder together with its evidence.
By default it only lists "Would delete". It does not follow symlinks and does not touch cases/, calibration-*, frozen images or the locator cache. Do not use a global Docker prune instead.

<a id="guardrail"></a>
## Guardrail: test input passes rules before any AI call

**Why:** Excel is editable input. The guardrail is pure Python plus one human-owned config file, not an LLM. It checks the whole workbook first, so unrelated or malicious content never reaches the Translator, the browser, audit or Jira.
The new **Guardrail** stage after Setup runs before any credentials are bound. A single violation calls `error(...)`: the stage and build turn red with FAILURE, the build description shows the first violation, and all later stages are skipped.
The default WORKBOOK is `cases/osm/WBS_testcase1_osm.xlsx`, which Poll SCM uses. The three original OSM cases need no Excel changes.

**Where the config lives:** Every workbook needs a `guardrail.json` in the same folder. A missing file, invalid JSON, unknown fields, wrong types or an invalid app URL all fail closed.
The OSM config, for example:

```json
{
  "allowed_apps": {"OSM Website": "https://www.openstreetmap.org/"},
  "allowed_step_verbs": ["open", "go to", "navigate", "click", "select", "enter", "type", "fill", "press", "observe", "check", "verify", "clean up", "set", "close"],
  "blocked_words": ["password", "api key", "apikey", "token", "secret", ".env", "credential", "email it", "send to", "ignore previous instructions", "system prompt"]
}
```

| Check | Rule |
| --- | --- |
| Application | Target Application, trimmed and case-insensitive, must be a key in allowed_apps |
| URL | For every URL / www. address in any cell, the host must exactly equal the host of that case's app URL; subdomains or look-alike suffixes do not match |
| Steps | Every Actions / Post action line, after removing numbering, quotes and leading punctuation, must start with an allowed verb/phrase |
| Blocked words | All text columns are matched against blocked_words as whole words/phrases, case-insensitive; the last word may end in s / es (passwords, API keys, tokens, secrets); phrases split across line breaks are also caught |
| Emails/secrets | Blocks email addresses, sk-/sk-ant-/ghp_/github_pat_/AKIA/xoxb-/xoxp- prefixes, Bearer tokens, private-key PEM and JWT shapes; no entropy guessing |

Extra columns, notes sheets and headers are scanned too. A URL that belongs to no case cannot be proven to belong to an allowed app, so it is blocked. The rules only check configuration and text patterns; they cannot prove that all natural language is safe.
Each violation records the case, column, step (if any), rule, a masked snippet of at most 80 characters, and an English explanation. Secret matches keep only the first 4 characters + …, and emails are masked too. The Console merges violations into one line per case + step, listing every matching rule and blocked word; guardrail.json keeps the full record of each violation.
Word boundaries still apply: tokenizer / tokenization do not count as token. This is a deliberate rule choice; the rules do no general stemming. Never put real credentials into Excel for a demo.

**How to check locally:**

```sh
uv run python -m test_agent guardrail cases/osm/WBS_testcase1_osm.xlsx
uv run python scripts/make_guardrail_demo.py
uv run python -m test_agent guardrail cases/guardrail-demo/guardrail-demo.xlsx
```

`cases/<suite>/guardrail.json` is the input rule set. The guardrail.json of the same name in Artifacts is the check result and must never be used to overwrite the config.
`--output-dir` sets a separate folder for the standalone report; do not point it at the workbook's config folder. A pass returns 0. Any guardrail block (including guardrail config/input errors) returns **3**, distinct from test failure 1 and the config/input error 2 used by other commands.
`translate` and `suite` check all cases automatically first. Any violation means no model or browser calls and no audit/Jira; only guardrail.json and a summary.json with status=`BLOCKED_BY_GUARDRAIL` are written.
After a pass, each case's URL in the suite comes from its allowed_apps value. If `--url` is given, it must equal the case's configured full URL; it cannot be used to bypass the allow-list. The plan validator still forbids navigating to other URLs.

**How to demo in Jenkins:** After review and push, choose **Build with Parameters** → `WORKBOOK=cases/guardrail-demo/guardrail-demo.xlsx`. Expect a red Guardrail stage, all other stages skipped, and guardrail.json in Artifacts.
Switch back to the default WORKBOOK to restore the normal suite. Troubleshooting needs no extra plugin.

**How to add a website:** A human adds `"Example Website": "https://example.test/"` to allowed_apps and uses that name as the Excel Target Application, then runs the standalone check.
If a legitimate step uses a new verb, update allowed_step_verbs after human review. Never widen the rules to let malicious content through. This config controls allowed input and navigation addresses; DOM actions on a new site still need matching locators / vocabulary / contract support. The Jenkins example currently uses the OSM locators.
For a future **login test**, deliberately remove `password` from blocked_words and review the rules. Test credentials must come only from Jenkins Credentials and **must never be written into Excel**.

## 7. Push Excel to trigger a run

**What to do:** Edit and save `cases/osm/WBS_testcase1_osm.xlsx`, then after review:

```bash
git status --short
git diff --stat
git add cases/osm/WBS_testcase1_osm.xlsx
git commit -m "Update OSM test cases"
git push origin main
```

When contract requirements such as cities, thresholds or layers change, review/update contracts.json at the same time. Otherwise the validator will correctly reject the contradicting requirements.

**Why:** Jenkins sees the GitHub version. Saving locally without pushing does not trigger anything. You never upload Excel by hand.

**What you should see:** After the next poll a new build appears, checks out that commit and re-translates the three cases.

**If something goes wrong:** Check the branch and commit in the Poll SCM Log, and make sure the Mac and Docker are awake. xlsx is binary, so a review must compare the Excel source with the translation results.

## 8. Failure drill

**What to do:** Create a `ci-demo` branch and a separate Pipeline from SCM job `test-agent-ci-demo` with branch `*/ci-demo`. Only in the demo branch's Jenkinsfile, add `--fault directions-503` after the suite command. Commit/push after review, then click Build Now.

**Why:** The existing deterministic fault simulates the directions service returning 503 without permanently changing locators or expectations. Unit tests should still pass, affected cases become BLOCKED, suite exit 1 → UNSTABLE, and the other cases keep running.

**What you should see:** The faults, reasons and screenshots in HTML/CSV/summary match the UNSTABLE result. The OSM-003 layer case may not be affected by the directions fault.

**If something goes wrong:** On FAILURE check syntax, commands and credentials. After the drill run `git revert <drill commit>` on the demo branch, push, then disable the demo job. Do not adjust thresholds to get back to green.

## 9. Stop, restart, data and reset

**What to do:** Stop/remove this project's container and network while keeping the volume:

```bash
docker compose -f ci/docker-compose.yml down
docker compose -f ci/docker-compose.yml up -d
docker volume inspect wbs-ci_jenkins_home
```

**Why:** The volume stores users, credentials, jobs and history. Recreating the container does not lose data. The volume also contains sensitive information, so only back it up to trusted places.

**What you should see:** After restarting, your account and job are still there.

**If something goes wrong:** Make sure you always use the project name wbs-ci and the same Compose file. Only when you are sure you want to discard all Jenkins history and credentials and fully reset, run this command that **deletes all Jenkins data**:

```bash
docker compose -f ci/docker-compose.yml down --volumes
```

Do not run a global Docker prune; it affects other projects.

## 10. Troubleshooting

Work through "check → cause → checkpoint":

| Problem | What to do, why, and what you should see |
| --- | --- |
| Port 8080 in use | Find the owner with `lsof -nP -iTCP:8080 -sTCP:LISTEN`; do not kill it blindly. To change the port, keep the 127.0.0.1 binding after review and use the new port in the browser. |
| Docker socket permission | Confirm Desktop is running, the socket is mounted and the local-learning `user: "0:0"` is set; `docker compose -f ci/docker-compose.yml exec jenkins docker version` should show Client and Server. Do not chmod the machine-wide socket. |
| Pull/metadata timeout | First run `docker pull mcr.microsoft.com/playwright/python:v1.63.0-noble` and check Desktop network/VPN/proxy. If there is no Pulling output for a long time, docker-credential-desktop may be hanging; this verification used a temporary anonymous config to pull the public image without changing the user config. Diagnose first; do not wipe the keychain or reset Docker. Rebuild once it recovers, without deleting the volume. |
| Browser executable missing | The Playwright image tag must match the uv.lock version, and the environment variable must point to /ms-playwright; never use the Mac's .browsers. |
| Unit tests pass locally but fail intermittently in CI | Read the last complete traceback and result in Console Output, not just the test name at the top. In build #3 the vision-click test returned VISION_INTERNAL before clicking; the fixture's original 150 ms browser timeout also limited screenshots and was suspected to be too short under Docker load, so it is now 2 seconds. No assertions were relaxed and no retries added; if it fails again, keep the full traceback. The fix must be committed/pushed before Jenkins checks it out. |
| uv sync --locked fails | Check Python/network/lock. Do not run `uv lock` in CI to change dependencies on the fly. Fix it in the development environment, review it, then update the matching image. |
| Missing credential / 401 / 403 | Check ID/scope/key/balance against step 4; do not debug with echo. The Git token and model keys are not interchangeable. |
| OSM 503 / blank / timeout | Look at the fault, step reason/code and screenshots to tell an injected fault from a real external service problem. Keep the evidence, then rebuild by hand; do not hide failures behind automatic retries. |
| Evidence links broken after download | Download the whole suite tree and keep its folders. The original Linux absolute paths are a run record, not Mac paths. |
| No Stage View | Confirm the pipeline-stage-view plugin; meanwhile read each stage in Console Output. |

**Basic checkpoint:** You can explain controller vs. agent, find the build after pushing Excel, read Test Result / Test Report, tell UNSTABLE from FAILURE and find the evidence. Next come review and Jira.

## 11. Audit analysis: let AI explain the evidence

**What to do:** After review and commit/push, the working part of the pipeline is Setup → Guardrail → Unit tests → Test suite → Audit analysis.
Audit analysis binds only `wbs-anthropic-api-key` as `ANTHROPIC_API_KEY`; it no longer binds the GLM / OPENAI_* credentials. JSON reading/writing needs the Pipeline Utility Steps plugin listed in section 3. No Jira-specific plugin is needed.
`AUDIT_MODEL=claude-haiku-5-5` controls both the analyst and the screenshot observer, so there is only one provider/model. The old `AUDIT_VISION_MODEL` remains as a temporary compatibility alias; the new setting takes precedence.
Excel translation and DOM healing still use GLM, and the production route checker is still Clef. Only the audit was replaced.

**The mechanism at a glance:** Completed test → Python gathers evidence → Claude analyses → Python validates and decides candidates → human approves → Python deduplicates and comments on or creates Jira issues.

| Who | Responsible for |
| --- | --- |
| Python | Collecting Excel, results and the screenshot catalog; calling the model; validating evidence IDs and schema; choosing candidates by rule and computing fingerprints; calling Jira after approval |
| Claude Haiku (LLM) | Explaining likely causes of failures, alternative causes and next steps; when it needs to see the screen, asking neutral questions through the isolated screenshot observer |
| Human | Judging whether the analysis is sound and ticking the findings to report; without approval no Jira write request is sent |

For example, the executor has already recorded "actual 456 minutes, required under 180" as FAILED. Claude may infer "the test expectation is unrealistic". Python confirms the finding cites a real FAILED check and, from test_case_problem, generates a test_case_fix candidate, even if Claude's advisory said false.
This does not re-run the test, edit Excel or turn FAILED into PASSED. The cause classification is still the LLM's judgment and may vary between builds. What is now stable is the candidate rule for the same cause + same cited evidence, and a dedup identity that does not depend on the AI's step or wording.

**Why:** `audit.csv` is a record; the audit agent does the reasoning. Python prepares a dossier for every case (including PASSED): the Excel source text, contract, plan, that case's rows, a results summary and the screenshot catalog.
Claude Haiku reads the dossier and reasons about it. When it needs an image it calls `ask_screenshot(id, question, options)`, and Python sends a separate screenshot observation request to the same Haiku model.
The observation request receives only a neutral question, 3–8 options (one must be unclear), an output schema and one image. It never sees the Excel expected text, the actual test verdict or the image file name.
These are two isolated contexts of the same model, not a GLM → Claude delegation. The isolation is kept so that known expectations cannot steer the visual answer.
Claude **must** call `submit_analysis` to submit a structured draft; plain-text JSON is not accepted instead. The tool uses `strict: true` and a schema generated from the same Pydantic model. This tool does not create tickets.
The [Anthropic strict tools documentation](https://platform.claude.com/docs/en/agents-and-tools/tool-use/strict-tool-use) and the
[compatibility and schema limits](https://platform.claude.com/docs/en/build-with-claude/structured-outputs) (checked 2026-10-16) list Haiku 5.5 as supported.
Length, number and array limits the API does not support are written into the schema descriptions and still validated by Python. Field structure, enums, ID patterns and the ban on extra fields stay consistent.
Over-long summary/title/explanation/observation/next-step text is truncated, so valid analysis is not lost because of text length.
If the structure, enums, IDs or evidence fail validation, Python returns a `tool_result` with `is_error: true` containing only field paths and error types, and allows one corrected `submit_analysis`.
The original failure records are kept in `dropped_findings`; `case_audits` and the top-level `repair_used` record whether a repair was used. If the repair also fails, only the invalid findings are dropped. Findings for the same case that already passed the rules are kept; only a case with no valid findings at all is marked unanalysed.
All Excel content, page text, image content and model output is treated as untrusted data, never as instructions.

At most 5 screenshot question attempts per case and 25 per suite are allowed, **and attempts rejected by the guard also count**. A rejection explains the specific rule, for example that 3–8 options including unclear are required. Each case gets at most 12 native Messages API analyst turns, plus 1 dedicated format/evidence repair turn. There are no automatic network retries. Reviewing one case can take several Haiku requests, all using the same configured model.
PNGs use the existing 4 MiB and oversized-image guard; images are not resampled and runs are not re-cropped. A Claude self-reported confidence below 0.90, or an unclear answer, counts as uncertain and must not be treated as fact.
`evidence_screenshots` may only list images that were asked about, answered, and cited in that finding's `evidence_questions`.
If extra unobserved image IDs from this case are listed but the explanation / screenshot_observations make no claim about what they show, Python removes the extra IDs and records the finding ID and `stripped_screenshot_ids` under `normalizations` in the JSON, without dropping the valid analysis.
If the text explicitly mentions an unobserved image ID, or screenshot observation text is filled in without any observation Q&A, only that finding is dropped. The repair lists the specific IDs and asks Claude to `ask_screenshot` first before citing them, or to remove the IDs and the unsupported visual descriptions.
During the repair Claude may first ask additional screenshot questions and then submit one corrected `submit_analysis`, still within the 5/25 question attempts, 13 analyst turns and the per-case timeout. No second corrected submission is allowed.
IDs that do not exist or belong to another case are still rejected; they are not hidden by "removing extra references".

The screenshot catalog contains every step screenshot and map crop. Images only go into the separate Claude observation request; the analyst receives validated text observations. Each answer has a Q-… number, and Python checks that cited answers really exist and belong to that case.

**What you should see:** Test Report has an **AI audit analysis — suggestion, verify before acting** link, and Build Artifacts also contains:

| File | What to read |
| --- | --- |
| audit_analysis.md | Human summary, likely cause + confidence, explanation, alternative causes, screenshot observations, next steps, suggested tickets, evidence and designed outcome |
| audit_analysis.json | The same analysis, the text dossier, the real screenshot Q&A, dropped findings with reasons, and the model used |
| audit_review.json | Ticket candidates that passed Python validation, attention_count, summary, unavailability banner and analysis SHA-256 |

`software_bug`, `test_case_problem`, `test_tool_problem` and `environment_problem` are the AI's cause hypotheses and never replace the original PASSED/FAILED/BLOCKED.
OSM-002 can stay FAILED while the analysis says "Hamburg → Munich in under 3 hours" is worth checking. Do not automatically edit Excel, relax the threshold, or disguise a designed failure as a pass.
PASSED cases are reviewed too. If a FAILED check or a reliable screenshot answer contradicts the expectation, **⚠ possible false pass, please check** is shown, but no ticket is recommended automatically.
The screenshot contradictions Python can compare directly currently include the selected layer, route start/end names/aliases and obvious line breaks. Vaguer visual interpretations stay as needs_human_review.

**How to read the report:** The top says, for example, `Audited 3 cases: 2 no action, 1 needs your attention (1 ticket suggestion).`
**Needs your attention** shows only: all ticket suggestions, possible_false_pass, needs_human_review that Claude chose deliberately with a specific explanation, and low-confidence findings on FAILED/BLOCKED cases.
**No action needed** is collapsed by default: medium/high-confidence confirmed_pass, and explained medium/high-confidence FAILED/BLOCKED that need no ticket. A failure does not automatically require human intervention, and the original case verdict stays unchanged.
When a case has several findings, the case count at the top counts it once; any attention finding makes it an attention case. attention_count counts findings.
The HTML Test Report uses the same grouping. The full alternative causes, evidence and screenshot Q&A are in the Markdown.

**If something goes wrong:** Invented rows/screenshots/questions, unsafe categories or insufficient evidence go through the repair flow. A case with no valid analysis is explicitly marked `unanalysed` in the JSON's `case_audits`.
When some cases succeed, the Console, build description, Markdown and HTML show for example **AI audit analysed 2 of 3 cases; OSM-001 unanalysed (UNOBSERVED_SCREENSHOT_CLAIM)**.
Only when zero cases succeed is **AI audit unavailable. Test results are unchanged; read the report as usual. Reason: <code>** shown; there are no per-case Python human-review cards.
`availability` is complete / partial / unavailable; `agent_unavailable` is true only when zero cases succeed. `case_audits` still states the coverage of each case.
When some cases fail, valid findings from the other cases can still be used. The `field_errors` of `AUDIT_SCHEMA` / `FINDING_SCHEMA` store only field names and Pydantic error types, never the rejected input.
A text-model, JSON or timeout error in one case does not make other valid cases unavailable. `AUDIT_REPAIR_FAILED` belongs to output_validation and is no longer labelled VISION_VALIDATION_FAILED. Only zero successful cases sets `agent_unavailable: true`; the test report is still kept, and an audit model failure never turns the build into FAILURE.
`VISION_HTTP` + status, VISION_CONFIG and VISION_LIMIT mean the screenshot is unknown, not a product bug. Check key/model permissions, but never print the key or private response bodies.

## 12. Jira Cloud token and Jenkins credential

**What to do:** Create an API token for your own account at [Atlassian API tokens](https://id.atlassian.com/manage-profile/security/api-tokens) with a sensible expiry date.
This project uses the site `https://lawxueni.atlassian.net` and project key `WBSFP`. Direct Basic auth for local learning uses the account email + API token (not the login password).
Choose a token that works with site Basic auth. Scoped tokens may need the Atlassian gateway URL; do not mix authentication methods.

Manage Jenkins → Credentials → System → Global credentials → Add Credentials:

| Field | Value |
| --- | --- |
| Kind | Username with password |
| Username | Atlassian account email (entered only in the credential) |
| Password | API token |
| ID | wbs-jira |
| Description | WBS Jira approval workflow (no token here) |

**Why:** The token carries your account's permissions. The account needs Browse / Create issues / Edit issues / Add comments / Create attachments permissions on WBSFP.
A token never adds permissions the user lacks. The email/token never go into Git, reports or Console Output. The Jira sending stage, and the explicitly enabled read-only connection check, inject `JIRA_EMAIL` / `JIRA_API_TOKEN` via `withCredentials`.
The site URL and project key can be version-controlled. The Audit stage has no Jira credential and no tool that writes to Jira.

**Checkpoint:** Installed credentials show the ID wbs-jira. Never share a screenshot of the token. If no ticket is approved and the read-only connection check is not enabled, the pipeline never reads this credential.

### When Jira fails, run the read-only connection check first (the 404 in build #11)

**First check:** The `wbs-jira` email must be an Atlassian account that can see **WBSFP** on this Jira site, and the API token must belong to that same account. A token created by another Jira account cannot be combined with this email.
First put the same `JIRA_EMAIL` / `JIRA_API_TOKEN` in your local `.env`, confirm `JIRA_SITE=https://lawxueni.atlassian.net` and `JIRA_PROJECT=WBSFP`, then run:

```bash
uv run python -m test_agent jira check
```

It only performs GETs: myself → project/WBSFP → create-metadata issue types, stops at the first error and returns a non-zero exit code.
It prints only the stage status, the account display name (not the email/accountId) and the creatable issue type names. It does not save full responses, create issues/comments/attachments, or write decision files.
Success looks like `Jira auth: OK — <display name>`, `Jira project: OK`, `Jira issue_types: OK — Bug, Task`.
These successful GETs prove authentication, project visibility and metadata access. They do not guarantee write permissions for Create issues / Add comments / Create attachments.

`CHECK_JIRA_CONNECTION` is only for troubleshooting (after changing credentials or when Jira errors appear). You do not need to tick it for every build.

**Check with the same credential in Jenkins:** Once the new Jenkinsfile is loaded, use **Build with Parameters**, tick `CHECK_JIRA_CONNECTION` (default false), and the **Jira connection check** stage runs.
It uses `wbs-jira` after Setup. If the read-only check fails, it marks that stage/build UNSTABLE and continues the normal test flow. No Jira write is performed.
The parameter only appears on the job page after the Jenkinsfile has been loaded once. Left unticked (the default), it adds no Jira requests.

Every error in `jira_results.json` now has a `phase` and `path_template`. The request phases are issue_types / search / create / comment / label / attach; the connection check also has auth / project.
approval / prepare / configuration are local checks before any request, with path_template null. Templates never contain real query values, email or response bodies.
Console example: `Jira 404 during issue_types (project WBSFP not found or not visible to the credential's account)`, followed by the safe path template.
For a 404, first check the site, project key and whether this credential's account can see the project. Do not assume the Jira API path is broken.

On 2026-10-16 each method/path was checked against the [official Atlassian OpenAPI spec](https://dac-static.atlassian.com/cloud/jira/platform/swagger-v3.v3.json) (all under `/rest/api/3/`):

| Phase | Method / path template |
| --- | --- |
| auth | GET myself |
| project | GET project/{project} |
| issue_types | GET issue/createmeta/{project}/issuetypes |
| search | POST search/jql |
| create | POST issue |
| comment | POST issue/{issue}/comment |
| label | PUT issue/{issue} (update.labels.add; only on legacy matches) |
| attach | POST issue/{issue}/attachments |

JIRA_AUTH (401/403): check the account/token, expiry and permissions. JIRA_CONFIG: check configuration, available issue types, approval hash or evidence. JIRA_HTTP + status: check the request for that phase. JIRA_TIMEOUT: check the network.
Errors never include private response bodies and issue creation is never retried automatically. If an attachment fails, the created issue key is kept; check Jira before deciding what to do next.

## 13. Review tickets: a human decides, nothing is selected by default

**What to do:** Python decides candidates from validated evidence. Review tickets only runs when there is at least one candidate:
`software_bug` + at least one cited FAILED check → `bug`; `test_case_problem` + at least one cited FAILED check → `test_case_fix`; anything else produces no candidate.
Claude's `recommend_ticket` / `ticket_type` are advisory only and shown in the analysis. false does not suppress a candidate backed by failure evidence, and true cannot turn BLOCKED / environment problems into candidates.
The top shows: **AI audit requires human approval. Tick the test case(s) you want to report, then click 'Create Jira ticket'. Unticked items are not created.**
The `Total TC: 3; Passed: 2; Failed: 1; Blocked: 0` line below comes from this run's summary.json case verdicts; the numbers vary with the results. It is not the audit attention count.
Tick each finding you want to create (**all false by default**) and click **Create Jira ticket**. Unticked items are not created and do not add comments to existing issues.
Each checkbox description is a single line, for example:
`F-OSM-002-1 | OSM-002 | Cause: Test case problem | Confidence: high | Reason: The 776 km route takes 7:36, so the 180-minute limit is unrealistic.`
Confidence is the AI's self-reported low / medium / high, not a probability. The reason uses the required `short_reason`, which must be one sentence; Python removes line breaks, collapses whitespace and truncates to 160 characters. The full explanation stays in the Markdown and the Jira description.

**How to view the analysis in a new tab:** The current controller uses the default **Plain text** formatter (configuration checked read-only on 2026-10-16; the Safe HTML plugin is installed but not enabled). The input message and checkbox descriptions cannot rely on HTML anchors.
In **this build's** sidebar, Cmd-click (Mac) / Ctrl-click (Windows or Linux) **Test Report**, or right-click → Open Link in New Tab. The report contains the AI audit analysis link, and Build Artifacts also has audit_analysis.md.
The input keeps the full artifact URL for copying; it does not claim a plain-text URL becomes a clickable new-window link. Opening the sidebar link with the browser's new-tab action avoids relying on `target="_blank"` or loosening the report CSP.
[Jenkins Markup Formatter documentation](https://www.jenkins.io/doc/book/security/markup-formatter/): Plain text escapes HTML; Safe HTML also filters disallowed tags/attributes, so `target` is not guaranteed to survive.
This change does not modify the global formatter / CSP or enable raw HTML. All model label text is still HTML-escaped so it displays safely under Plain text or a future Safe HTML (malicious text may show as entity text under Plain text).

The input only lists approvable tickets. Possible false passes and other attention items without tickets appear in the build description / Test Report; **they never pause the build on their own**.

**Why:** The pipeline uses `agent none` at the top level. Setup/tests/audit run inside the working Docker agent, which then runs `stash reports/` and publishes the reports first.
Review tickets has no agent, no executor and no container: however long a human takes, no test machine is occupied. After the input, the Jira stage allocates a new agent, checks out and runs `unstash reports/`.
This copies evidence.zip and other files, which is a simple implementation for local learning; larger evidence sets could move to external artifact storage later.

If nobody responds to the approval within 30 minutes, no ticket is created. Jenkins may show the waiting input as aborted and the actual sending as not run. The pipeline catches the interruption and can still run Record decision and Jira to save timeout_or_abort, and the build keeps its test results. When there are no candidates, both stages show skipped by design.
Approval has a 30-minute timeout. Abort on the input, a timeout, or deselecting everything **sends no Jira requests** and keeps the earlier SUCCESS/UNSTABLE.
`jira_decision.json` records the status, approver, selected finding IDs and the analysis file's SHA-256. The hash and IDs are checked again before sending, to stop the analysis being swapped after approval.
A partial audit still enters Review tickets as long as one ticket candidate passed the rules; availability / agent_unavailable do not decide whether approval happens.
With no candidates, Review tickets and Record decision and Jira are **both skipped**. The latter checks its condition before allocating a Docker agent, so no container is started for an empty decision and no jira_decision.json is written.
With candidates that a human rejects entirely or that time out, the decision is still recorded and no Jira request is sent. An unavailable model never creates tickets out of nothing.

**Checkpoint:** Once the credential is updated and the JSON plugin installed, Audit analysis should finish normally. With a validated ticket suggestion, Review tickets pauses with nothing ticked; a human ticks and clicks Create Jira ticket. While waiting, Test Report and audit_analysis.md are already readable, and no Jenkins executor is held by the input. Jira sending only starts after a finding is approved.
The final Post Actions archive the reports again with the decision/results. While waiting, "no Jira ticket yet" does not mean failure, because sending has not been authorized.

**If something goes wrong:** If there is no input, check the candidates in audit_review.json first. Do not loosen the evidence rules just to make approval appear. TRANSLATION_REJECTED, navigation errors or VISION_* errors alone cannot recommend a bug.
If the whole build fails in a working stage, the approval never runs; fix the earliest red stage first.

## 14. Jira creation, deduplication and attachments

**What to do:** The REST API is only called for approved findings. Python first queries the issue types creatable in WBSFP through create-metadata: bug → Bug (or Task if unavailable); test_case_fix → Task.
The description uses Atlassian Document Format (ADF), with model text treated only as plain text: Excel source action/expected, actual/reason, category, evidence rows, designed outcome, build/Test Report URL, plus **AI analysis (suggestion, verify)**.
Screenshots are read from evidence.zip by their validated relative paths and uploaded with the header `X-Atlassian-Token: no-check`. Full traces are not uploaded.

**Why:** The v2 fingerprint label hashes only the case ID, the step numbers Python extracts from the cited FAILED rows (sorted; BLOCKED rows if there are no FAILED rows), and the original Excel expected text for those steps.
It does not use the AI's step, ticket_type, title, explanation, source action or the build number. When the AI step is null and all cited non-case rows share a single step, Python fills in that step for display.
`POST /rest/api/3/search/jql` is paged to find unresolved WBSFP issues with the same v2 label, plus older `wbs-<case>-step<number/case>-<hash>` issues carrying this case's label.
The legacy-label compatibility may match a different historical problem in the same case, so read existing tickets before approving. With several open matches, the earliest created issue gets the comment and jira_results.json records duplicate_keys and a warning; a new issue is only created when nothing matches. On a legacy-only match, after commenting Python adds this run's v2 label via update.labels.add and records added_v2_label on success; an existing v2 label is not added twice. A second run also needs a fresh approval.
Only when nothing matches is an issue created; each finding gets at most 4 relevant step/map images. Every type choice, created/commented key, URL, attachment count and error is written to jira_results.json.

**Checkpoint:** The build description has the Jira URL. The WBSFP ticket carries the wbs-test-agent, fingerprint and case ID labels, with screenshots and a link back to Jenkins.
After a repeated build approves the same problem, the original ticket gets one more comment. Resolved tickets do not count as open, so a recurring problem can get a new ticket.
Jira search has indexing delay. Do not run builds concurrently and do not blindly retry sending. If attachments fail after the issue was created, results keep the created key; check that ticket before deciding the next step.

**If something goes wrong:** Jira API/credential errors mark that stage and the build UNSTABLE, and the test report and partial results are still archived. A sending failure must never change a test case's status.
A Jira request timeout may happen after the server has already processed it. There is no automatic retry; check the project for the label by hand first to avoid duplicates.

## 15. Testing the Claude-only audit locally (no Jira)

**Preparation:** Put `ANTHROPIC_API_KEY` in your local `.env`, optionally with `AUDIT_MODEL=claude-haiku-5-5`. Do not paste the key into a chat or into your command history.
Running only audit-agent needs no OPENAI_* or OpenRouter keys. You need access to api.anthropic.com and an account with access to that model.

**Step 1, offline verification (zero API calls):**

```bash
# Run from the project root
uv run python -m unittest discover -s tests -p 'test_audit_agent.py' -v
```

**Step 2, a real review of an existing suite:**

```bash
AUDIT_MODEL=claude-haiku-5-5 uv run python -m test_agent audit-agent artifacts/suite-20261016T085446352441Z
open artifacts/suite-20261016T085446352441Z/audit_analysis.md
```

This path is an existing demo suite; you can substitute any other complete `artifacts/suite-...` folder. The command only reads the saved test evidence. It does not re-run the web pages or translation, but it does send the text dossier and the required PNGs to Anthropic, which costs model calls.
It updates this suite's audit_analysis.json/.md and audit_review.json. It never changes results.json, case verdicts or thresholds, and never creates Jira tickets.

**Step 3, confirm it is a real analysis and not a fallback:**

```bash
uv run python - <<'PYTHON'
import json
from pathlib import Path
p = Path('artifacts/suite-20261016T085446352441Z/audit_analysis.json')
a = json.loads(p.read_text())
print('Provider / model:', a['provider'], a['text_model'])
print('Availability:', a['availability'])
print('Agent unavailable:', a['agent_unavailable'])
print('Coverage / repairs:', a['case_audits'])
print('Any repair used:', a['repair_used'])
print('Stripped screenshot references:', a['normalizations'])
for f in a['findings']:
    print(f['case_id'], f['likely_cause'], f['title'])
print('Dropped findings / safe errors:', a['dropped_findings'])
PYTHON
```

**Checkpoint:** The provider is anthropic, and both the analyst and screenshot models are the configured Haiku. `agent_unavailable` is false and all three cases have evidence-backed explanations.
Check whether the Markdown's categories, causes, next steps and Q-* screenshot observations make sense; all three `case_audits` entries should be analysed. Expect OSM-001/003 to need no action and OSM-002 to have one ticket suggestion awaiting approval. This is an acceptance expectation, not a model answer Python enforces. This round's live acceptance requires no unavailability banner.
The Console reports the model and the number of findings. If an unavailability message appears, look at dropped_findings' field_errors/repair_used/phase/error_class/provider_code/http_status. It is normal for the original dropped diagnostics to remain after a successful repair; keep the Markdown and these fields for diagnosis.
These **safe diagnostic fields and the analysis content** can be shared for troubleshooting. Never share the key.

**If something goes wrong:** VISION_CONFIG: check the Anthropic key. VISION_HTTP + 401/403: check permissions; 404: check that AUDIT_MODEL is available; 429: check limits. VISION_TIMEOUT: check the network. VISION_INCOMPLETE: check for truncated output. VISION_TURN_LIMIT means the normal 12-turn limit was hit; the single extra turn is only for a submit_analysis repair that has already been triggered.
Do not automatically re-run repeatedly to pick a good result. Keep the failing output and look at the safe error fields first. Jenkins reads pushed code, so you can test locally before review/commit; Jenkins acceptance still requires review first, then commit/push.

### Offline Jira preview only (nothing is sent by default)

```bash
# Review saved evidence; calls only Claude Haiku, no browser re-run, no GLM
uv run python -m test_agent audit-agent artifacts/suite-<id>
# Copy the analysis into reports/ as well
uv run python -m test_agent package artifacts/suite-<id> --output-dir reports
# IDs must be validated findings that recommend a ticket; the default equals --dry-run and sends no HTTP at all
uv run python -m test_agent jira create reports --approved F-OSM-002-1 --dry-run
```

**What you should see:** jira_payloads.json contains the request bodies without auth information, the JQL and attachment paths. jira_results.json marks dry_run=true with no created/commented issues.
The offline preview cannot query issue types, so it uses the conservative Task name. Real sending discovers the metadata first and records the actual choice (bug may become Bug). Test case fixes always use Task.
This file shows exactly the ADF/labels/links this preview prepared; it does not pretend unqueried metadata is known. With no candidates, passing `--approved ''` only produces an empty preview.

If an old audit_analysis.json has no short_reason, re-run audit-agent and package first, then approve the new analysis hash. An old approval cannot be reused to send.
Sending only happens when `--send` is given explicitly. Locally, typing `--approved` IDs together with `--send` is the human authorization for that operation; Jenkins uses the saved input decision and hash.
The commands above never approve tickets or send real issues/comments on their own. The real approval happens in Jenkins after your changes are committed and pushed.

## Official references

- [Installing Jenkins with Docker and the initial unlock](https://www.jenkins.io/doc/book/installing/docker/)
- [Docker Pipeline and workspace sharing](https://www.jenkins.io/doc/book/pipeline/docker/)
- [Jenkinsfile and credentials](https://www.jenkins.io/doc/book/pipeline/jenkinsfile/)
- [Playwright Python Docker and version matching](https://playwright.dev/python/docs/docker)
- [uv container integration and version pinning](https://docs.astral.sh/uv/guides/integration/docker/)
