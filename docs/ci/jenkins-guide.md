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

只粘贴到自己的 Unlock Jenkins 页，不发到聊天。Dockerfile 已预装 Pipeline、Git、Docker Pipeline、Credentials Binding、Pipeline Stage View 和 HTML Publisher（固定 429）；JUnit 由依赖带入。
若出现插件选择页，选 **Select plugins to install**；已安装项不必重复安装。然后创建自己的管理员账号，保存本地 Jenkins URL。

**为什么：** 插件支持 pipeline、Docker agent 和 withCredentials；所需 Docker Pipeline 的 ID 是 `docker-workflow`，不必装 Docker cloud plugin。

**你应该看到：** Dashboard；Manage Jenkins → Plugins → Installed plugins 中能找到上述插件。

**如果不顺利：** 查看日志中的 failed dependency。`plugins.txt` 固定直接插件版本，传递依赖由 plugin manager 解析；未来升级时一并 review controller 和插件，不盲目改为 latest。

### 已有 controller：应用新的报告插件和设置

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

**你应该看到：** Manage Jenkins → Plugins → Installed plugins 有 HTML Publisher；新 build 出现 Test Report。若报告无样式/图片，核对容器启动的 JAVA_OPTS，不能只修改 Jenkinsfile。

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

**Checkpoint：** 新 build 有 Test Result、Test Report，reports/ 下仅五个 artifact；OSM-002 能看到持续时间失败，未改变阈值。
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

**终点 checkpoint：** 你能说明 controller/agent，push Excel 后找到 build，下载 HTML/CSV，区分 UNSTABLE/FAILURE 并找到证据。Audit agent、Jenkins input 审批、Jira 是下一任务，本轮未接入。

## 官方参考

- [Jenkins Docker 安装和初始解锁](https://www.jenkins.io/doc/book/installing/docker/)
- [Docker Pipeline 与 workspace 共享](https://www.jenkins.io/doc/book/pipeline/docker/)
- [Jenkinsfile 和 credentials](https://www.jenkins.io/doc/book/pipeline/jenkinsfile/)
- [Playwright Python Docker 与版本匹配](https://playwright.dev/python/docs/docker)
- [uv 容器集成和版本固定](https://docs.astral.sh/uv/guides/integration/docker/)
