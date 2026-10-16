# 用 Jenkins 把 Excel 接入 CI：一步一步学习

对应 `Jenkinsfile` 和 `ci/`。先完成 Claude review、经你批准 commit/push，再创建 SCM job：Jenkins 从 GitHub 读取已提交文件，看不到 Mac 上未提交的修改。
每完成一步可以将 checkpoint 告诉 Codex；不要发送密码或 API key。

## 1. 五分钟理解基本概念

**做什么：** 看懂流程：push → 检查新 commit → 安装环境 → 单元测试 → Excel 翻译和验证 → Playwright / Clef → 下载证据。

| 名词 | 本项目中的含义 | 测试工作的类比 |
| --- | --- | --- |
| image / container | 环境模板 / 启动的运行实例 | 环境配置 / 一台测试机 |
| controller | Docker 中的 Jenkins，保存 job、凭据和历史 | 调度台 |
| agent | Playwright Linux 容器，运行命令 | 执行测试的机器 |
| pipeline / stage / step | Jenkinsfile / Setup 等阶段 / 一条命令 | 流程 / 阶段 / 操作 |
| workspace | `/var/jenkins_home/workspace/...` 中的 checkout | 本轮工作目录 |
| artifact | 归档的 HTML、CSV、截图、JSON、trace | 测试证据 |
| credential | 按阶段注入的秘密 | 测试账号配置 |
| trigger | Poll SCM 每约五分钟看 Git 变化 | 自动触发 |

**为什么：** case status 与 build result 不同。

| 命令结果 | Build result | 含义 |
| --- | --- | --- |
| suite exit 0，JUnit 无 failure/error | SUCCESS | 所有 case 和 Cleanup 通过 |
| suite exit 0，JUnit 的 Cleanup 有 failure/error | UNSTABLE | case 检查通过，但清理失败，需要调查 |
| suite exit 1 | UNSTABLE（通常黄色） | 流程完成，但有 FAILED/BLOCKED，需要调查 |
| suite exit 2、其他非零退出或崩溃 | FAILURE（通常红色） | 命令或执行流程出错 |
| 单元测试失败 | FAILURE | 工具自己的回归测试失败，不继续 live suite |

**你应该看到：** OSM-002 原本就设计 FAILED，所以正常演示也可能是 UNSTABLE。不能为了绿色 build 改预期或阈值；BLOCKED 也不是已确认的产品缺陷。
Python 崩溃也可能返回 1，因此 `ci/suite_result.py` 还检查本轮完整 summary、HTML、CSV、JUnit；缺失/不一致、套件输入错误或没有用例均判 FAILURE，不把基础设施问题当成测试发现。

**如果不顺利：** 先判断看到的是 step、case 还是 build 状态，再找相应证据。

## 2. 启动 Jenkins

**做什么：** 打开 Docker Desktop，等 Engine running，然后：

```bash
cd /Users/xuenilaw/Documents/myProject/WBS
docker version
lsof -nP -iTCP:8080 -sTCP:LISTEN
docker compose -f ci/docker-compose.yml config
docker compose -f ci/docker-compose.yml up -d --build
docker compose -f ci/docker-compose.yml ps
```

打开 [http://127.0.0.1:8080](http://127.0.0.1:8080)，首次可能等几分钟。

**本机已知情况（2026-10-16）：** Terminal 检查发现 Homebrew 的 Jenkins 已在 8080 运行，Codex 没有停止它。若 lsof 仍显示该 Java/Jenkins 进程，先执行 `brew services list` 确认服务。你决定本次改用 Docker Jenkins 后，可自己执行 `brew services stop jenkins-lts` 释放端口，再运行 up；这不会删除 Homebrew Jenkins 的数据。将来需要恢复原服务时，先 compose down，再 `brew services start jenkins-lts`。不要同时让两套服务占用 8080，也不要误把旧服务的页面当成新容器。

**为什么：** Compose 管理 controller 和持久化的 `wbs-ci_jenkins_home` volume。端口只绑定 127.0.0.1:8080，不向局域网开放；不开放 50000。
本地学习配置以 root 运行 controller 并挂载 `/var/run/docker.sock`。**这个 socket 让 Jenkins 完全控制 Mac 上 Docker Desktop 的容器、镜像、volume 和 Docker 可访问的挂载文件。仅用于可信仓库的本地学习，不用于共享或 production server。** 不运行不可信的 PR/Jenkinsfile，也不调整其他 n8n 容器。

**你应该看到：** `ps` 显示 Up，页面显示 Unlock Jenkins。

**如果不顺利：** 看日志，不要先删除 volume：

```bash
docker compose -f ci/docker-compose.yml logs --tail=80 jenkins
```

## 3. 解锁、插件和管理员

**做什么：** 在本机查看 initial admin password：

```bash
docker compose -f ci/docker-compose.yml exec jenkins cat /var/jenkins_home/secrets/initialAdminPassword
```

只粘贴到自己的 Unlock Jenkins 页，不发到聊天。Dockerfile 已预装 Pipeline、Git、Docker Pipeline、Credentials Binding、Pipeline Stage View 和 HTML Publisher（固定 429）、Pipeline Utility Steps（固定 `3.810.va_7672d206740`）；JUnit 由依赖带入。
若出现插件选择页，选 **Select plugins to install**；已安装项不必重复安装。然后创建自己的管理员账号，保存本地 Jenkins URL。

**为什么：** 插件支持 pipeline、Docker agent 和 withCredentials；所需 Docker Pipeline 的 ID 是 `docker-workflow`，不必装 Docker cloud plugin。

**你应该看到：** Dashboard；Manage Jenkins → Plugins → Installed plugins 中能找到上述插件。

**如果不顺利：** 查看日志中的 failed dependency。`plugins.txt` 固定直接插件版本，传递依赖由 plugin manager 解析；未来升级时一并 review controller 和插件，不盲目改为 latest。

### 已有 controller：应用新的报告 / JSON 插件和设置

**做什么：** 本轮修改 review、commit/push 后，在 Mac 仓库执行（先等运行中的 build 结束）：

```bash
docker compose -f ci/docker-compose.yml build jenkins
docker compose -f ci/docker-compose.yml up -d --force-recreate jenkins
docker compose -f ci/docker-compose.yml ps
```

**为什么：** 插件进入新 controller image，`JAVA_OPTS` 在 controller 启动时生效。仅 push Jenkinsfile 不会替换 controller。
以上命令保留 `jenkins_home` volume、账号、credentials、job 和历史；不执行 `down --volumes`。已存在 volume 中缺少的插件由镜像 ref 目录补入。

本机 Compose 为 HTML 设置 `sandbox; default-src 'none'; img-src 'self' data:; style-src 'self' 'unsafe-inline';`。
这允许报告内嵌 CSS 和 `data:` 缩略图，仍阻止脚本；报告本身没有脚本。**这是 controller 范围的设置，会影响其他归档页面，只适用于这台可信仓库的本地学习 Jenkins。**
共享或 production server 保持默认 CSP，下载 HTML 在本机打开。不要为了报告增加 `script-src` 或关闭 sandbox。

**你应该看到：** Manage Jenkins → Plugins → Installed plugins 有 HTML Publisher 和 Pipeline Utility Steps；新 build 出现 Test Report。若报告无样式/图片，核对容器启动的 JAVA_OPTS，不能只修改 Jenkinsfile。

### Pipeline Groovy sandbox（build #6/#7 的原因）

Sandbox 会限制 Jenkinsfile 中可调用的 Groovy API，避免脚本直接操作 controller 文件或进程。
日志出现 `RejectedAccessException: Scripts not permitted to use ...` 表示脚本在运行时被 sandbox 拦截，Declarative linter 通过也不能证明这些调用可执行。

本项目使用 Pipeline Utility Steps 的 `readJSON(..., returnPojo: true)` 和 `writeJSON` 读写审批 / Jira JSON，避免 `JsonSlurperClassic` / `JsonOutput`，无需手动 Script Approval。
`returnPojo: true` 返回普通 Map/List，可跨 pipeline checkpoint 使用；[官方步骤说明](https://www.jenkins.io/doc/pipeline/steps/pipeline-utility-steps/) 与 [固定版本及最低 Jenkins 版本](https://updates.jenkins.io/download/plugins/pipeline-utility-steps/) 可供核对。
review、commit/push 后，先执行上面的 controller **build + up --force-recreate** 命令安装新插件，再 Build Now；仅拉取 Jenkinsfile 不会安装插件。
若出现 `No such DSL method 'readJSON'` / `'writeJSON'`，确认插件已安装并已完成重启。

## 4. Credentials：CI 不使用 .env

**做什么：** Manage Jenkins → Credentials → System → Global credentials (unrestricted) → Add Credentials。下列各项用 **Kind: Secret text**、**Scope: Global**，Secret 填本地对应值，ID 必须一致：

| ID | 环境变量 | 用途 |
| --- | --- | --- |
| `wbs-openai-api-key` | OPENAI_API_KEY | GLM 翻译 / DOM healing |
| `wbs-openai-base-url` | OPENAI_BASE_URL | GLM OpenAI-compatible endpoint |
| `wbs-openai-model` | OPENAI_MODEL | GLM 模型名；本地若用 OPENAI_DEFAULT_MODEL，填相同值 |
| `wbs-openrouter-api-key` | OPENROUTER_API_KEY | Clef route verification |
| `wbs-anthropic-api-key` | ANTHROPIC_API_KEY | Claude screenshot-click fallback |

VISION_PROVIDER=clef 和 VISION_MODEL=cloudflare/clef 是 Jenkinsfile 中的普通配置。Route threshold 来自 contract：Clef 0.85，Anthropic 0.90；点击 fallback 仍为 Claude、0.90。

私有仓库另建 **Kind: Username with password**：Username = GitHub 用户名，Password = GitHub token，ID = `wbs-github-read`。选仅能读取 test-agent 的 token，例如 fine-grained token 的 Contents: Read-only；必要时完成组织授权。不要把 token 写进 repo URL。

**为什么：** 模型 credentials 仅在 Test suite 的 withCredentials 范围绑定，Unit tests 不需要 API key。脚本先 set +x，不 echo key；不要用 env/printenv 调试。Masking 不能防止恶意 Jenkinsfile 泄漏，因此只构建可信分支。GitHub checkout credential 和模型 key 是两回事。

**你应该看到：** 五项 Secret text，以及私有仓库的 GitHub credential，只显示 ID。

**如果不顺利：** Could not find credentials entry 查 ID/scope；401/403 查权限、endpoint、余额。不要分享含 key 的完整日志。

**Anthropic 401/403（build #6/#7）：** Console 与 build description 会明确显示，例如 `Anthropic credential rejected (401): update wbs-anthropic-api-key`（实际提示中的 ID 带反引号）。
进入 Manage Jenkins → Credentials → System → Global credentials → `wbs-anthropic-api-key` → Update，保留 Kind **Secret text** 和原 ID，点击 Change Secret 后粘贴本机 `.env` 中可用的 `ANTHROPIC_API_KEY` 的值，去掉引号、空格与换行，再 Save。
这是 Jenkins 中的独立副本，修改本机 `.env` 不会同步过去；不需要把 key 发给 Codex / Claude。429 只表示限流，不会被提示为 credential rejected。

## 5. 创建 Pipeline from SCM

**做什么：** New Item → `test-agent` → Pipeline → OK。Pipeline 区域填写：

1. Definition = Pipeline script from SCM；SCM = Git。
2. Repository URL = `https://github.com/xuenilaw/test-agent.git`。
3. Credentials = `wbs-github-read`（私有仓库）。
4. Branch Specifier = `*/main`；Script Path = `Jenkinsfile`。
5. Save，然后手动 Build Now 一次，加载 Jenkinsfile 的 trigger。

**为什么：** Pipeline 与用例一起版本管理。`pollSCM('H/5 * * * *')` 每约五分钟检查新 commit，H 分散检查时间。**该分支任何新 commit 都可能触发，不仅 Excel**；无需公网 webhook，Mac/Docker 停止时不会 poll。

**你应该看到：** 首次 build 后 Configure → Build Triggers 中有 Poll SCM。无 commit 变化不应每五分钟无条件重跑；可看 Poll SCM Log。

**如果不顺利：** 找不到 Jenkinsfile，确认已通过 review 并 push；checkout 失败查 credential/branch，不要在 URL 放 token。

## 6. 第一次 build：阶段、日志、下载报告

**做什么：** 点击 build 编号 → Console Output / Stage View，依次看 Setup → Unit tests → Test suite。

**为什么：** Setup 清理 workspace、checkout、安装固定 uv==0.12.17，再 uv sync --locked。Image `mcr.microsoft.com/playwright/python:v1.63.0-noble` 必须匹配 uv.lock 的 playwright==1.63.0：image 提供 Linux browsers，uv 安装 Python package。PLAYWRIGHT_BROWSERS_PATH=/ms-playwright 指向 Linux 浏览器，不能挂载 Mac 的 .browsers。
每次都清理，故没有历史 artifacts 或 locator cache。每轮是 **Excel → GLM → 验证 → Playwright → Clef**，不带 --reuse，会产生 API 费用。
GLM 每次重新翻译可能有差异；若出现 TRANSLATION_REJECTED，查看该 case 的 validation.json，不手工改 plan.json 绕过校验，也不反复重跑只保留通过的一次。

**你应该看到：** Unit tests 不调用 live LLM；Test suite 显示各 case translating/running。即使 UNSTABLE，post always 仍发布 JUnit、HTML 和五个命名 artifact。按下一节阅读，不必从深层目录找报告。

CSV 可用 Excel → Data → From Text/CSV，以 UTF-8 导入。每 case、action、check、cleanup 各有一行；raw locator_source：human = locator file，cache = 缓存，healed = GLM 自愈，vision = Claude 点击。HTML 使用易读名称。row_id 在同一证据重新导出时稳定；repeat_index 从 1 开始。reason_code 只保存已有机器码，缺失留空。摘要在 expected/actual/reason，完整证据见 results_json/screenshot 相对路径。没执行的 case 仍有 case 行，不虚构步骤。duration_s 只在 case 行记执行秒数，空值不代表零。healed/borderline 为 Yes/No。危险公式开头 = + - @ 会加单引号作为文本，不能删除这个保护。

首个成功产生证据的 CI build 后（这里可能是 UNSTABLE），核对 OSM-001 step 4 的 start/end/line probabilities，把 Linux 数字记录到 review；首次真正 SUCCESS 后也核对一次。Mac Berlin 曾是 0.856–0.870，阈值 0.85；Linux render 差异可能令它 BLOCKED，如实记录，不调阈值。

**如果不顺利：** Setup/Unit tests 失败可能根本没有 suite artifacts；allowEmptyArchive 不会伪造报告，也不会把前面的失败变成功。先看第一个红色阶段。

### Reading the results in Jenkins（在 Jenkins 阅读结果）

**做什么：** 打开 build 编号，按这三个入口阅读：

| 入口 | 适合看什么 | 为什么 |
| --- | --- | --- |
| Test Result | 每 case、每 source step 一行，另有 Cleanup；失败原因和 system-out 中的 expected/actual、locator_source、Clef 概率、reason code、相对证据路径 | JUnit XML 把测试结果变成 Jenkins 可识别的数据；两个以上发布结果的 build 可观察趋势 |
| Test Report | 一键打开 HTML：case 概览、折叠步骤、缩略图和详细观测 | 提供面向人的完整解释，无须翻 Console Output |
| Build Artifacts → reports/ | 五个命名下载，见下表 | 文件位置固定，不再归档深层 suite 树 |

这里 Test Result 对应 **Excel acceptance cases**，不是 136 个 Python unit tests；unit tests 仍在 Unit tests 阶段日志中。
一个 case 包含多步，因此 Jenkins 显示的测试数量是「步骤 + Cleanup」，与 Excel case 数不同；重复执行的名称带 Run n。
JUnit 现在在 Test suite 的 post/always 执行，UNSTABLE 的黄色显示在 Test suite；全局 Post Actions 只发布文件，不再因 JUnit 而变黄。

| 原始 step 状态 | JUnit 表示 | 测试含义 |
| --- | --- | --- |
| PASSED | 无 failure/error/skipped 子元素 | 要求已验证；borderline 仍通过，在 system-out 标注 |
| FAILED | failure | 要求不满足 |
| BLOCKED | error | 未能建立测试结论，需要调查 |
| NOT_RUN | skipped | 因前置失败等原因未执行 |
| TRANSLATION_REJECTED | 名为 Translation 的 error | 测试基础设施/翻译验证问题，不能归类为产品 bug |

OSM-002 的设计结果是 FAILED，仍会显示红色，不能为了预期失败而伪装为通过。testsuite properties 保存 `designed_outcome` / `outcome_as_designed`；HTML 的 Designed / as designed 列更容易阅读。
JUnit 自己会因 failure/error 将 build 标为 UNSTABLE；`ci/suite_result.py` 另外校验退出码与完整 summary，识别 pipeline 崩溃/输入错误为 FAILURE。
两者分别负责**步骤展示**与**流程完整性**，JUnit 不能把已有 FAILURE 改回 UNSTABLE。Setup/Unit tests 提前失败时可能没有 XML；`allowEmptyResults: false` 如实报告缺失，不捏造空的通过报告。
Cleanup 单独显示；即使 case 的检查通过，cleanup 的 error/failure 也会使 build UNSTABLE，分类器与 JUnit 保持一致，不改写历史 case verdict。缺失、空或损坏的 XML 属于 FAILURE。

| 文件 | 用途 |
| --- | --- |
| report.html | 可独立下载，已嵌入缩略图 |
| audit.csv | Excel / 后续 audit agent 可读的逐项记录 |
| junit.xml | Jenkins 读取的 case/step XML |
| summary.json | case 总结和原始状态 |
| evidence.zip | 其余证据：截图、results、trace、翻译及验证记录 |

**完整证据链接：** 下载五个文件到同一目录，然后**把 evidence.zip 解压到 report.html 旁边**（直接展开内部目录，不额外包一层 evidence/）。
例如报告链接 `cases/OSM-001/run/screenshots/step-1.png`，解压后应存在这个路径。单独 HTML 仍显示缩略图；Jenkins 页面上的完整图片/trace 链接需下载解压后使用。
summary/JSON 内的绝对路径保留为原运行记录；HTML/JUnit 的证据链接使用相对路径。

**本机离线导出：** 不启动浏览器，不调用模型：

```bash
uv run python -m test_agent junit artifacts/suite-<id>
uv run python -m test_agent package artifacts/suite-<id> --output-dir reports
```

`junit` / `package` 也支持 repeat 目录。`reports/` 是专用输出，不放其他文件；解压证据请使用单独的下载目录。

**Checkpoint：** 新 build 有 Test Result、Test Report，reports/ 下有五个基础 artifact；启用 audit/Jira 后另有分析与决策文件。OSM-002 能看到持续时间失败，未改变阈值。
若没有入口，核对 HTML Publisher 安装、JUnit XML 路径和 Console Output 的 post 阶段；旧 build 不会自动补发新的展示。

### 本机证据目录与保留数量

suite 的目录现在为：

```text
artifacts/suite-<id>/
  report.html, audit.csv, junit.xml, summary.json
  cases/OSM-001/
    translation/  # source、plan、validation、model-output
    run/          # results、截图、trace、vision 等
```

repeat 使用 `artifacts/repeat-<id>/run-1/`、`run-2/`，每次内部使用同样布局，外层另有 aggregate HTML/CSV/JUnit 和 repeatability.json。
`--reuse` 识别新旧 validated plan，复用时复制进当前 suite，保证证据自包含；`report` / `audit` / `junit` 可以读取旧结构。
只增加 Munich/München hint 也会令旧 plan 的 vocabulary 过期；使用 `revalidate <translation-folder>` 离线重新验证，不重跑模型、不改历史证据。

**清理前先预览：**

```bash
uv run python -m test_agent prune --keep 10
# 核对列出的路径后，才实际删除
uv run python -m test_agent prune --keep 10 --yes
```

按顶层目录修改时间保留最新 **10 个（四类合计）** suite-/repeat-/run-/translation- 目录，整个旧目录连同证据删除。
默认只列出 Would delete；不会进入 symlink，不清理 cases/、calibration-*、冻结图片或 locator cache。不要使用全局 Docker prune 代替它。

## 7. Push Excel 触发运行

**做什么：** 修改并保存 `cases/osm/WBS_testcase1_osm.xlsx`，经 review 后：

```bash
git status --short
git diff --stat
git add cases/osm/WBS_testcase1_osm.xlsx
git commit -m "Update OSM test cases"
git push origin main
```

城市、阈值、layer 等 contract 要求变更时，同时 review/update contracts.json，否则 validator 会正确拒绝矛盾要求。

**为什么：** Jenkins 看到 GitHub 版本，本机只保存不 push 不触发；无需手动上传 Excel。

**你应该看到：** 下一轮 poll 后出现新 build，checkout 对应 commit，重新翻译三条 case。

**如果不顺利：** 看 Poll SCM Log 中的分支和 commit，确认 Mac/Docker 已唤醒。xlsx 是 binary，review 要对照 Excel 源文和翻译结果。

## 8. 故障练习

**做什么：** 自建 `ci-demo` 分支和独立 Pipeline from SCM job `test-agent-ci-demo`，branch 指向 `*/ci-demo`。只在 demo 分支 Jenkinsfile 的 suite 命令后加 `--fault directions-503`，经 review 提交/push，然后 Build Now。

**为什么：** 现有 deterministic fault 模拟 directions 返回 503，不永久修改 locator 或预期。Unit tests 仍应通过，受影响的 case BLOCKED，suite exit 1 → UNSTABLE，其他 case 继续执行。

**你应该看到：** HTML/CSV/summary 的 faults、reason、截图与 UNSTABLE 对应。OSM-003 layer case 可能不受 directions fault 影响。

**如果不顺利：** FAILURE 查语法/命令/credentials。练习后在 demo 分支执行 `git revert <练习commit>` 并 push，再禁用 demo job。不要调阈值恢复绿色。

## 9. 停止、重启、数据和 reset

**做什么：** 停止/移除本项目 container 和 network，但保留 volume：

```bash
docker compose -f ci/docker-compose.yml down
docker compose -f ci/docker-compose.yml up -d
docker volume inspect wbs-ci_jenkins_home
```

**为什么：** volume 保存用户、credentials、job、历史，container 重建不等于数据丢失。volume 也含敏感信息，只做可信备份。

**你应该看到：** 重启后原账号/job 还在。

**如果不顺利：** 确认始终使用项目名 wbs-ci 和同一 Compose 文件。只有你确定不要 Jenkins 的所有历史和凭据、决定完全重置时，才运行这条**删除全部 Jenkins 数据**的命令：

```bash
docker compose -f ci/docker-compose.yml down --volumes
```

不要执行全局 Docker prune，它会影响其他项目。

## 10. Troubleshooting

按“检查 → 原因 → checkpoint”处理：

| 情况 | 做什么、为什么、应该看到什么 |
| --- | --- |
| 8080 占用 | `lsof -nP -iTCP:8080 -sTCP:LISTEN` 查占用者，不随意 kill；如需改端口，经 review 保持 127.0.0.1 绑定，浏览器用新端口。 |
| Docker socket permission | 确认 Desktop running、socket 挂载和本地学习用 user: "0:0"；`docker compose -f ci/docker-compose.yml exec jenkins docker version` 应有 Client/Server。不 chmod 全机 socket。 |
| Pull/metadata 超时 | 先 `docker pull mcr.microsoft.com/playwright/python:v1.63.0-noble`，查 Desktop 网络/VPN/proxy。若长期没有 Pulling 输出，也可能是 docker-credential-desktop 挂起；本次验证使用临时匿名配置下载公开镜像，未改用户配置。可让 Codex帮助定位，不直接清空 keychain 或重置 Docker。恢复后重新 build，不删除 volume。 |
| Browser executable 不存在 | Playwright tag 必须与 uv.lock 同版本，环境变量指向 /ms-playwright；不可使用 Mac .browsers。 |
| Unit tests 本机通过、CI 偶发失败 | 读 Console Output 最后完整的 traceback 和 result，不能只看顶部测试名。build #3 的 vision-click 测试在点击前返回 VISION_INTERNAL；该 fixture 原来的 150 ms browser timeout 也限制截图，怀疑在 Docker 负载下过短，现改为 2 秒。没有放宽断言或增加重试；若再次失败，保留完整 traceback。修复须 commit/push 后 Jenkins checkout 才能取到。 |
| uv sync --locked 失败 | 查 Python/network/lock；不在 CI 用 uv lock 临时改依赖。开发环境修正并 review，再更新匹配 image。 |
| Credential 缺失/401/403 | 对照第 4 步核对 ID/scope/key/余额；不用 echo 调试。Git token 和模型 key 不能互换。 |
| OSM 503 / blank / timeout | 看 fault、step reason/code、截图，分清注入与真实外部服务问题。保留证据再手动重建，不用自动重试掩盖失败。 |
| 下载后 evidence 链接失效 | 下载整个 suite 树并保留目录；Linux 原始绝对路径是运行记录，不能当 Mac 路径。 |
| 无 Stage View | 确认 pipeline-stage-view 插件，先用 Console Output 阅读各 stage。 |

**基础 checkpoint：** 你能说明 controller/agent，push Excel 后找到 build，阅读 Test Result / Test Report，区分 UNSTABLE/FAILURE 并找到证据。下面接上审阅与 Jira。

## 11. Audit analysis：让 AI 解释证据

**做什么：** review、commit/push 后，Pipeline 的工作部分为 Setup → Unit tests → Test suite → Audit analysis。
Audit analysis 只绑定 `wbs-anthropic-api-key`，使用 `ANTHROPIC_API_KEY`，不再绑定 GLM / OPENAI_* credentials。JSON 读写需要第 3 节列出的 Pipeline Utility Steps；无需 Jira 专用 plugin。
`AUDIT_MODEL=claude-haiku-5-5` 同时控制 analyst 与截图观察，只有一个 provider/model。旧 `AUDIT_VISION_MODEL` 暂作兼容别名，新设置优先。
Excel 翻译与 DOM healing 仍使用原来的 GLM；生产 route checker 仍是 Clef，本次只替换 audit。

**为什么：** `audit.csv` 是记录；audit agent 才负责推理。Python 为每个 case（包括 PASSED）准备 dossier：Excel 原文、contract、plan、该 case 的 rows、结果摘要与截图目录。
Claude Haiku 读取 dossier 并推理；需要图片时，它调用 `ask_screenshot(id, question, options)`，Python 用同一个 Haiku model 发起独立的截图观察请求。
观察请求只收到中性问题、3–8 个选项（必须有 unclear）、输出 schema 和一张图，不收到 Excel 的 expected text、实际 test verdict 或图片文件名。
这是同一模型的两个隔离上下文，不是 GLM → Claude 的模型委派；保留隔离是为避免用已知预期引导视觉答案。
Claude **必须**调用 `submit_analysis` 提交结构化草稿，不能用普通文字 JSON 代替。该 tool 使用 `strict: true` 和由同一 Pydantic 模型生成的 schema；这个 tool 不创建 ticket。
[Anthropic strict tools 文档](https://platform.claude.com/docs/en/agents-and-tools/tool-use/strict-tool-use) 和
[兼容性与 schema 限制](https://platform.claude.com/docs/en/build-with-claude/structured-outputs)（2026-10-16 查阅）列出 Haiku 5.5 支持。
API 不支持的长度、数字与数组上限放入 schema 的 description，仍由 Python 校验；字段结构、枚举、ID pattern、禁止额外字段保持一致。
summary/title/explanation/观察文字/next step 过长时截短，不因文字长度丢掉有效分析。
如果结构、枚举、ID 或证据校验失败，Python 返回 `is_error: true` 的 `tool_result`，仅含字段路径与错误类型，允许一次修正后的 `submit_analysis`。
原始失败记录保留在 `dropped_findings`；`case_audits` 和顶层的 `repair_used` 记录是否用了修正。修正仍失败时只丢弃无效 finding；此前已经通过规则的同 case finding 仍保留，只有没有任何有效 finding 的 case 才标为 unanalysed。
所有 Excel、页面文字、图中内容、模型输出均视为不可信数据，不能当成指令。

每 case 最多 5 次截图问题尝试、每 suite 最多 25 次，**被 guard 拒绝也计数**；拒绝答复会解释具体规则，例如需 3–8 个选项且包含 unclear。每 case 最多 12 个原生 Messages API analyst turns，另允许 1 个专用格式/证据修正 turn；没有网络自动重试。审阅一条 case 可能有多次 Haiku 请求，全部使用同一配置模型。
PNG 使用现有 4 MiB 与 oversized-image guard，不重采图、不裁剪重跑；低于 0.90 的 Claude 自报 confidence 或 unclear 均为 uncertain，不能视为事实。
`evidence_screenshots` 只能列出已经询问、得到答复且在该 finding 的 `evidence_questions` 中引用的图片。
若多列了本 case 的未观察图片 ID，却没有在 explanation / screenshot_observations 中声称它显示了什么，Python 会移除多余 ID，并在 JSON 的 `normalizations` 中记录 finding ID 与 `stripped_screenshot_ids`，不丢掉有效分析。
若文字明确提到未观察图片 ID，或没有任何观察问答却填了截图观察文字，只丢弃该 finding，repair 会列出具体 ID，要求先 `ask_screenshot` 再引用，或移除 ID 及无证据的画面描述。
修正可先补截图问题、再提交一次 corrected `submit_analysis`，仍受 5/25 问题尝试数、13 个 analyst turns 和每 case timeout 约束；不添加第二次 corrected submission。
不存在或其他 case 的 ID 仍会被拒绝，不会通过“移除多余引用”来隐藏。

截图目录包含每个 step screenshot 和 map crop；图片只进入独立的 Claude 观察请求，analyst 收到经过验证的文字观察。每次答复有 Q-… 编号，Python 校验引用是否真实存在且属于该 case。

**你应该看到：** Test Report 有 **AI audit analysis — suggestion, verify before acting** 链接；Build Artifacts 另有：

| 文件 | 读什么 |
| --- | --- |
| audit_analysis.md | 给人的摘要、likely cause + confidence、解释、替代原因、截图观察、下一步、建议 ticket、证据与 designed outcome |
| audit_analysis.json | 同一分析、文字 dossier、真实截图问答、被丢弃的 finding 与原因、所用模型 |
| audit_review.json | 已通过 Python 校验的候选 ticket 列表、attention_count、summary、不可用 banner 与 analysis SHA-256 |

`software_bug`、`test_case_problem`、`test_tool_problem`、`environment_problem` 是 AI 的原因假设，不能替代原始 PASSED/FAILED/BLOCKED。
OSM-002 可以保留 FAILED，同时分析认为「Hamburg → Munich 少于 3 小时」值得检查；不要自动改 Excel、放宽阈值，或因为测试设计为失败就伪装通过。
PASSED case 也会审阅。若有与预期矛盾的 FAILED check 或可靠截图答案，显示 **⚠ possible false pass, please check**，但不会自动推荐 ticket。
Python 能直接比对的截图矛盾目前包括选中 layer、route 起终点名称/别名和明显断线；更模糊的画面解释保留为 needs_human_review。

**报告如何读：** 顶部例如 `Audited 3 cases: 2 no action, 1 needs your attention (1 ticket suggestion).`
**Needs your attention** 只显示：全部 ticket suggestions、possible_false_pass、Claude 主动选择且解释具体原因的 needs_human_review，以及 FAILED/BLOCKED 的低 confidence finding。
**No action needed** 默认折叠：中/高 confidence confirmed_pass，以及已解释且无需 ticket 的中/高 confidence FAILED/BLOCKED。失败不等于必须人工介入；原 case verdict 保持不变。
一个 case 有多条 finding 时，顶部 case 数不重复计数，任一 attention finding 就归为 attention case；attention_count 则计 finding 数。
HTML Test Report 使用相同分类；完整的替代原因、证据与截图问答可在 Markdown 查看。

**如果不顺利：** invented row/screenshot/question、类别不安全或证据不足会进入修正流程；无法得到有效分析的 case 在 JSON 的 `case_audits` 中明确为 `unanalysed`。
有部分 case 成功时，Console、build description、Markdown 与 HTML 显示例如 **AI audit analysed 2 of 3 cases; OSM-001 unanalysed (UNOBSERVED_SCREENSHOT_CLAIM)**。
只有零 case 成功才显示 **AI audit unavailable. Test results are unchanged; read the report as usual. Reason: <code>**；没有逐 case 的 Python 人工 review 卡片。
`availability` 为 complete / partial / unavailable；`agent_unavailable` 只在零 case 成功时为 true。`case_audits` 仍逐 case 明确覆盖状态。
部分 case 失败时，其他 case 的有效 finding 仍可使用。`AUDIT_SCHEMA` / `FINDING_SCHEMA` 的 `field_errors` 仅保存字段名和 Pydantic 错误类型，不保存被拒绝的输入内容。
单个 case 的文字模型、JSON 或 timeout 错误不会让其他有效 case 不可用；`AUDIT_REPAIR_FAILED` 属于 output_validation，不再标成 VISION_VALIDATION_FAILED。零 case 成功才有 `agent_unavailable: true`，仍保留测试报告，不使 build 因 audit 模型失败而变成 FAILURE。
`VISION_HTTP` + status、VISION_CONFIG、VISION_LIMIT 是截图未知，不是产品 bug。确认 key/model 权限，但不要输出 key 或私有响应正文。

## 12. Jira Cloud token 与 Jenkins credential

**做什么：** 使用 [Atlassian API tokens](https://id.atlassian.com/manage-profile/security/api-tokens) 为自己的账号创建一个 API token，设置合理到期日。
本项目使用站点 `https://lawxueni.atlassian.net` 和 project key `WBSFP`。本地学习的直连 Basic auth 使用账号 email + API token（不是登录密码）。
选择适用于站点 Basic auth 的 token；带 scope 的 token可能需要 Atlassian gateway URL，不要把不同认证方式混用。

Manage Jenkins → Credentials → System → Global credentials → Add Credentials：

| 字段 | 值 |
| --- | --- |
| Kind | Username with password |
| Username | Atlassian account email（只在 credential 中填写） |
| Password | API token |
| ID | wbs-jira |
| Description | WBS Jira approval workflow（不填 token） |

**为什么：** token 代表你的账号权限；账号需要 WBSFP 的 Browse/Create issues/Add comments/Create attachments 权限。
用户没有的权限，token 也不会增加。email/token 不进 Git、报告或 Console Output；只在 Jira 发送阶段用 `withCredentials` 注入 `JIRA_EMAIL` / `JIRA_API_TOKEN`。
站点 URL、project key 可以版本管理。Audit stage 没有 Jira credential，也没有写 Jira 的 tool。

**Checkpoint：** Installed credentials 可见 ID wbs-jira；不要把 token 截图发给 reviewer。没有批准 ticket 时，流程根本不会读取这个 credential。

**如果不顺利：** JIRA_AUTH（401/403）查 email/token、到期与权限；JIRA_CONFIG 查站点/project/issue types、approval hash 或 evidence；JIRA_HTTP + status 查 Jira 服务/项目配置；JIRA_TIMEOUT 查网络。
错误只记录安全 code/status，不输出响应正文，不自动重试创建。

## 13. Review tickets：人决定，默认不选

**做什么：** Audit 有至少一个安全的 `recommend_ticket: true` finding，才进入 Review tickets。
在 build 的 input 页面通过链接打开完整分析，再逐项勾选要创建的 finding（**默认全部 false**），点击 **Record decision**。
每项显示 finding ID、case、likely cause + confidence、ticket type、title、next step、evidence rows 和 designed outcome。
input 只列可批准的 ticket，并显示 attention items 数量与分析链接作为参考。possible false pass 和其他无 ticket 的 attention item 出现在 build description / Test Report；**不会单独暂停 build**。

**为什么：** Pipeline 顶层用 `agent none`。Setup/测试/audit 在工作 Docker agent 内执行，结束后 `stash reports/` 并先发布报告。
Review tickets 无 agent、无 executor、无 container：人考虑多久，都不占用测试机。输入完成后，Jira 阶段重新分配 agent、checkout 和 `unstash reports/`。
这会复制 evidence.zip 等文件，是本地学习的简单实现；更大证据集可以将来改为外部 artifact storage。

审批有 30 分钟 timeout；在 input 上 Abort、超时、全部不选，都**不发送任何 Jira 请求**，保留之前的 SUCCESS/UNSTABLE。
`jira_decision.json` 记录 status、批准者、选中的 finding IDs、分析文件 SHA-256。发送前再次检查 hash 和 IDs，防止批准后分析被更换。
partial audit 只要有一个通过规则的 ticket candidate，仍进入 Review tickets；不以 availability / agent_unavailable 决定是否审批。
没有 candidate 时，Review tickets 与 Record decision and Jira **都跳过**；后者在分配 Docker agent 之前检查条件，不再为了空决定启动 container，也不生成 jira_decision.json。
有 candidate 但人工全部拒绝 / 超时时，仍记录决定，不发送 Jira 请求。模型不可用不会凭空创建 ticket。

**Checkpoint：** credential 更新且 JSON 插件安装完成后，Audit analysis 应正常结束；有已验证的 ticket suggestion 时 Review tickets 暂停，默认不勾选，人工勾选后点击 Record decision（部分 UI 显示 Proceed）。等待时 Test Report 和 audit_analysis.md 已可阅读；Jenkins 没有 executor 被 input 占住。批准一个 finding 后才进入 Jira 发送。
最终 Post Actions 再归档带 decision/results 的报告。等待期间不能用“没有 Jira ticket”判断失败，因为还没有授权发送。

**如果不顺利：** 没有 input 先看 audit_review.json 的 candidates；不要为了出现审批而放宽证据规则。TRANSLATION_REJECTED、导航错误或 VISION_* 错误不能单独推荐 bug。
若整条 build 在工作阶段失败，后续审批不会运行；先修最早的红色阶段。

## 14. Jira 创建、去重和附件

**做什么：** 只对批准的 finding 调用 REST API。Python 先通过 create-metadata 查询 WBSFP 可创建的 issue types：bug → Bug（若没有则 Task）；test_case_fix → Task。
描述使用 Atlassian Document Format（ADF），模型文字只作为普通文本：Excel source action/expected、actual/reason、category、证据行、designed outcome、build/Test Report URL，另有 **AI analysis (suggestion, verify)**。
截图从 evidence.zip 中按已验证的相对路径读取，上传 header 为 `X-Atlassian-Token: no-check`，不上传完整 trace。

**为什么：** fingerprint label 来自 case/step、source action/expected、ticket type 的稳定散列，不使用会变化的模型 title 或 build number。
使用新的 `POST /rest/api/3/search/jql` 查 WBSFP 同 label 且未完成的 issue；已有则添加本次 build 的 comment，不再创建新 issue。第二次运行也需要重新批准。
无匹配才 create；同一 finding 最多附 4 张相关 step/map 图。每次类型选择、created/commented key、URL、附件数量和错误均写入 jira_results.json。

**Checkpoint：** Build description 有 Jira URL；WBSFP ticket 带 wbs-test-agent、fingerprint、case ID labels，有截图和回到 Jenkins 的链接。
重复 build 审批同一个问题后，原 ticket 多一条 comment。已完成的 ticket 不算 open，会允许新建一个用于重新发生的问题。
Jira 搜索存在索引延迟；不并发构建、不盲目重试发送。若创建成功后附件失败，results 保留创建的 key；先检查该 ticket，再决定下一步。

**如果不顺利：** Jira API/credential 错误标记该阶段与 build UNSTABLE，仍归档测试报告和部分结果。不能因为发送失败就把测试 case 状态改掉。
Jira 请求超时可能发生在服务器已处理之后；没有自动重试，人工先检查 project 中的 label，避免重复。

## 15. 本机自行测试 Claude-only audit（不会发 Jira）

**准备：** 在本机 `.env` 中填写 `ANTHROPIC_API_KEY`，可选设置 `AUDIT_MODEL=claude-haiku-5-5`；不要把 key 粘贴到聊天或写进命令历史。
只执行 audit-agent 不需要 OPENAI_* 或 OpenRouter key。需要能访问 api.anthropic.com，账号有该模型权限。

**第一步，离线验证（零 API 调用）：**

```bash
cd /Users/xuenilaw/Documents/myProject/WBS
uv run python -m unittest discover -s tests -p 'test_audit_agent.py' -v
```

**第二步，用现有 suite 做一次真实审阅：**

```bash
AUDIT_MODEL=claude-haiku-5-5 uv run python -m test_agent audit-agent artifacts/suite-20261016T085446352441Z
open artifacts/suite-20261016T085446352441Z/audit_analysis.md
```

这条路径是已有演示 suite；也可换为另一个完整的 `artifacts/suite-...` 目录。命令只读取保存的测试证据，不重跑网页或翻译，但会把文字 dossier 和所需 PNG 发给 Anthropic、产生模型调用。
会更新这个 suite 的 audit_analysis.json/.md 与 audit_review.json；不会改 results.json、case verdict 或阈值，不会创建 Jira ticket。
本轮 Codex 不替你运行这个 live call，以便由你验证真实结果。

**第三步，确认是真分析而非 fallback：**

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

**Checkpoint：** provider 为 anthropic，analyst 与 screenshot model 都是配置的 Haiku；`agent_unavailable` 为 false，三条 case 都有证据支持的解释。
看 Markdown 的分类、原因、下一步和 Q-* 截图观察是否合理；`case_audits` 三条都应为 analysed。预期 OSM-001/003 无需行动，OSM-002 有一条待批准的 ticket 建议；这只是验收期望，不是 Python 强制的模型答案。没有不可用 banner 才满足本轮 live acceptance。
Console 会提示模型和 finding 数；出现不可用提示时，查看 dropped_findings 的 field_errors/repair_used/phase/error_class/provider_code/http_status。修正成功后保留最初的 dropped 诊断是正常的；请贴出 Markdown 和这些字段供 review。
你可以把这些**安全诊断字段和分析内容**交给 Codex/Claude，不要提供 key。

**如果不顺利：** VISION_CONFIG 查 Anthropic key；VISION_HTTP + 401/403 查权限，404 查 AUDIT_MODEL 是否可用，429 查限额；VISION_TIMEOUT 查网络；VISION_INCOMPLETE 查输出截断；VISION_TURN_LIMIT 表示触及一般 12-turn 上限；唯一额外 turn 仅用于已经触发的 submit_analysis 修正。
不要自动反复重跑来挑一个好结果。保留失败输出，先看安全错误字段。Jenkins 读取 push 后的代码，本地可在 review/commit 前测试；Jenkins 验收仍需先 review 再 commit/push。

### Jira 仅离线预览（默认不发送）

```bash
# 审阅已保存证据；只调用 Claude Haiku，不重跑浏览器、不调用 GLM
uv run python -m test_agent audit-agent artifacts/suite-<id>
# 把分析一起复制到 reports/
uv run python -m test_agent package artifacts/suite-<id> --output-dir reports
# IDs 必须是已验证、推荐 ticket 的 finding；默认与 --dry-run 相同，完全不发 HTTP
uv run python -m test_agent jira create reports --approved F-OSM-002-1 --dry-run
```

**你应该看到：** jira_payloads.json 中是无认证信息的请求正文、JQL、附件路径；jira_results.json 标记 dry_run=true，没有 created/commented issue。
离线预览不能查询 issue types，因此使用保守的 Task 名称；真正发送先发现元数据并记录实际选择（bug 可能改为 Bug）。测试用例修复始终选 Task。
此文件准确展示本次预览准备的 ADF/labels/链接；没有把“未查询的元数据”伪装成已知。没有 candidate 时传 `--approved ''` 只得到空预览。

只有明确提供 `--send` 才会发送；本机输入 `--approved` IDs 加 `--send` 就是该次操作的人工授权，Jenkins 则使用保存的 input 决策和 hash。
本轮交付只运行一次授权的 live audit 和 Jira dry-run，不替你批准 ticket，不发送真实 issue/comment。review、commit/push 后再由你在 Jenkins 完成一次真实审批验收。

## 官方参考

- [Jenkins Docker 安装和初始解锁](https://www.jenkins.io/doc/book/installing/docker/)
- [Docker Pipeline 与 workspace 共享](https://www.jenkins.io/doc/book/pipeline/docker/)
- [Jenkinsfile 和 credentials](https://www.jenkins.io/doc/book/pipeline/jenkinsfile/)
- [Playwright Python Docker 与版本匹配](https://playwright.dev/python/docs/docker)
- [uv 容器集成和版本固定](https://docs.astral.sh/uv/guides/integration/docker/)
