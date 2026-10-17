# Test Agent：Playwright、GLM 与自然语言测试用例

Docker/Jenkins CI：从 [中文学习指南](docs/ci/jenkins-guide.md) 开始，包含 credentials、Pipeline from SCM、Poll SCM 和报告下载。
`suite` / `repeat` 自动写入 `audit.csv`；已有结果可用 `uv run python -m test_agent audit artifacts/suite-<id>`（或 repeat 目录）离线导出。
同时生成逐 case/step 的 `junit.xml`。Jenkins 的 **Test Result** 展示步骤，**Test Report** 打开 HTML，`reports/` 归档五个命名文件。
离线生成：`uv run python -m test_agent junit artifacts/suite-<id>`；打包：`uv run python -m test_agent package artifacts/suite-<id> --output-dir reports`。
完整截图链接需将 `evidence.zip` 解压到下载的 `report.html` 旁边。Controller 插件/CSP 更新步骤及状态映射见 [Jenkins guide](docs/ci/jenkins-guide.md)。
suite 使用 `suite-<id>/cases/<case_id>/{translation,run}/`；repeat 使用 `repeat-<id>/run-<n>/cases/…`。旧结构仍可离线读取。
`uv run python -m test_agent prune --keep 10` 默认仅预览，核对后加 `--yes` 删除最旧的顶层运行目录，保留最新十个（四类合计）；冻结 calibration 与 cases 不受影响。
HTML 的 locator source 显示 locator file / cache / healed (GLM) / vision (Claude)；CSV 保留 human / cache / healed / vision 原始值。

今天只验证：打开页面 → 找到搜索框 → 输入 Hamburg → 断言输入值 → 截图 → 清理。
这还不是路线搜索测试，也没有 AI 自愈或 Vision。

## 安装

```sh
uv sync --locked
PLAYWRIGHT_BROWSERS_PATH="$PWD/.browsers" uv run playwright install chromium
```

## 先运行纯 Playwright

```sh
uv run python examples/browser_tool.py --offline
uv run python examples/browser_tool.py
uv run python examples/browser_tool.py --headed
```

`--offline` 用内存中的本地 HTML，验证浏览器、定位、输入、断言和清理。
不加该参数才访问 OpenStreetMap。固定英文 locale，让 Search placeholder 更可预测。
每次执行在 `artifacts/<run_id>/` 保存 `result.json` 和截图。
退出码：0 = PASS，1 = 浏览器检查 FAIL/BLOCKED；Agent 入口的 2 表示配置或模型调用错误。
Day 1 的状态分类只是入门版，Day 2 再按步骤语义细化。

## 再运行 Agent

在 `.env` 填写提供商的 API key、模型名和兼容接口地址。GLM 配置使用：

```dotenv
OPENAI_API_KEY=你的GLM密钥
OPENAI_DEFAULT_MODEL=你的GLM模型名
OPENAI_BASE_URL=你的GLM兼容接口地址
```

`OPENAI_MODEL` 也受支持，优先于 `OPENAI_DEFAULT_MODEL`；只配置一个模型变量即可。
使用你订阅对应的接口地址，不需要更换现有 `.env`。
不要把 key 发到聊天中；`.env` 已加入 `.gitignore`。

```sh
uv run python examples/day1_agent.py --offline
uv run python examples/day1_agent.py
```

Agent 调用需要对应模型提供商的 API 账户和额度；`--offline` 仅指浏览器页面离线，模型仍需联网。
SDK 的模型/工具循环和测试套件的步骤/用例循环是两种不同的 Runner。
程序使用 `AsyncOpenAI(base_url=...)` 指定提供商，并用 `OpenAIChatCompletionsModel`
选择兼容的 Chat Completions 接口。SDK 负责调度工具，实际模型可以是 GLM。
本例关闭 SDK tracing，不需要另一个 OpenAI tracing key。

## 按这个顺序阅读

1. `examples/browser_tool.py`：先读 `check_search_box()`，看建立会话、断言和 `finally`。
2. `examples/day1_agent.py`：看 `@function_tool`，它把普通函数暴露为模型可以调用的工具。
3. 看 `Agent(tools=...)` 与 `Runner.run(...)` 如何连接模型和工具。

| 对象 | 作用 |
| --- | --- |
| browser | Chromium 浏览器进程 |
| context | 独立会话；用例间隔离 cookies、localStorage 等 |
| page | context 内的标签页 |
| locator | 找元素的规则，例如 `get_by_placeholder("Search", exact=True)` |
| expect | 验证条件，等待条件满足或在超时后失败 |
| await | 等待浏览器或网络操作完成，再继续下一行 |
| finally | 正常或异常路径都执行，用于截图与资源清理 |

Day 1 的工具使用预先定义的 locator，Agent 只负责调用工具。
后续才让 Locator Agent 根据真实页面信息推荐 locator；不能把本例称为 AI 自动发现。

实际 OSM 首次检查发现 `Search` 匹配两个元素。因此定位增加 `.filter(visible=True)`，
仍然断言匹配数量为 1；不使用 `.first()` 隐藏歧义。

官方资料：[Playwright Python](https://playwright.dev/python/docs/library)、
[OpenAI Agents SDK 工具示例](https://developers.openai.com/cookbook/examples/partners/aws/chatgpt_agents_sdk_aws_agentcore_cookbook/notebooks/chatgpt_agents_sdk_aws_agentcore_cookbook)。

## Day 2：只翻译，不执行

```sh
uv sync --locked
uv run python -m test_agent translate cases/osm/WBS_testcase1_osm.xlsx
uv run python -m unittest discover -s tests -v
```

Excel 每条用例一行，Actions 和 Expected 的单元格内使用从 1 开始的连续编号。
表头：TestCase_ID、Target Application、TestCase_Name、Pre-condition、Actions、Expected、Post action。
读取时去掉表头和单元格首尾空白，不改变原 Excel。
当前入口读取指定的一条用例，外层套件循环后续再实现。

流程：Excel Reader → Translator Agent（GLM）→ Pydantic schema → Python 验证规则 → JSON。
此入口没有浏览器工具，不导入 Playwright，也不调用执行器。
GLM 返回普通 JSON，再在本地验证；不假设第三方支持 OpenAI 严格结构化输出接口。

项目内的样例 Excel 已包含请求路线、输入框可见性和严格小于 180 分钟的要求。
直接以 Excel 为输入，不再使用 amendments 文件或 `--amendments` 参数。
Downloads 中的旧副本尚未更新，请使用 `cases/osm/` 内的文件。
修改关键要求或步骤编号时，也要同步调整约束文件，并重新翻译计划。

`cases/osm/contracts.json` 是 OSM-001 的明确验收约束，用于检查城市、提交顺序、
输入框可见性和严格时间阈值。它不是从模型输出生成的，避免模型自证正确。
新用例的约束需要单独定义；没有约束的用例只有 schema 和来源覆盖检查。
默认在所选 workbook 的同一目录查找 `contracts.json`，也可以用 `--contracts` 指定。
没有默认文件或没有该 Case ID 时，仍可翻译，但输出会明确显示 `contract_applied: false`。
`contract_applied: true` 表示候选计划已执行该用例的 contract 检查，不等于检查通过或测试 PASS。
选中的 contract 会先经过 `schemas/contracts.py` 的 `RouteContract` 校验；字段缺失或类型错误
会在调用模型前 REJECTED，错误会指出 contract 字段。显式指定不存在的文件也会拒绝。

每次输出在 `artifacts/translation-<run_id>/cases/<case_id>/`（旧运行记录保留在原位置）：

- `source.json`：直接读取的 `case`、来源位置、验收约束和应用 URL。
- `model-output.txt`：原始模型响应。
- `candidate-plan.json`：通过 schema 的候选计划，即使后续规则拒绝也保留。
- `validation.json`：VALIDATED 或 REJECTED、错误、非阻断 notes。
- `plan.json`：只有全部已实现规则通过才保存。

VALIDATED 不是测试 PASS，也不是完整语义正确的证明；尚未检查网页 locator 或路线。
前置条件只保留文本，还没有执行检查。cleanup 已翻译但不执行，关闭 context 属于后续 Runner。
任何缺步骤、源文字被改写、非法动作或未解决的 issues 都会拒绝计划。
未来可增加用例审查 agent，在翻译/执行前发现歧义；当前没有实现该功能。

### Validator 与 guardrail agent

guardrail 是验证与阻断的机制，不一定是 agent。现在 `translate` / `suite` 首先读取 Excel 旁的 `guardrail.json`，用纯 Python 检查整本 workbook；任一违规或配置缺失即退出 3，不调用模型或浏览器。计划生成后还有确定性的 Python 验证门：
动作白名单、参数类型、来源覆盖、明确的用例约束。暂未使用 SDK guardrail decorator。
以后可增加语义审查 agent，检测自然语言中漏掉的含义；它补充规则，不替代规则。

阅读顺序：`readers/excel.py` → `schemas/plan.py` → `translation/validator.py` →
`translation/translator.py` → `cli.py`，这些文件都在 `src/test_agent/` 内。

## 项目结构

```text
src/test_agent/
  __main__.py, cli.py        # python -m test_agent 的入口
  guardrail.py               # workflow 0：纯 Python 全 workbook 输入阻断
  readers/excel.py           # workflow 1：读取用例
  schemas/plan.py            # 纯 Pydantic 数据模型
  translation/translator.py  # workflow 1b：自然语言翻译
  translation/validator.py   # 通用验证和路线约束验证，分开维护
cases/osm/                  # 样例 Excel、guardrail.json、contracts.json、vocabulary.json、locators.json
cases/guardrail-demo/       # 故意被阻断的 demo；scripts/make_guardrail_demo.py 可重新生成
examples/                   # 保留 Day 1 Playwright 和 Agent 教学脚本
tests/fixtures/             # 不需要网络或真实模型的回归测试
docs/reviews/               # Codex handoff 与 Claude review
artifacts/<run_id>/cases/<case_id>/  # 每条用例独立证据
```

从项目根目录运行 `uv sync --locked`，它安装 editable package。
目录名 `test_agent` 用于 Python import，发行包名 `test-agent` 与 GitHub repo 一致。
CLI 默认从当前目录读取 `.env` 并写入 `artifacts/`，从 workbook 所在目录读取 `contracts.json`。
从其他目录调用时，可用 `python -m test_agent --project-dir /path/to/test-agent translate ...`；
显式提供的 workbook/contracts 相对路径仍相对于当前工作目录。
`--output-dir` 可覆盖 artifacts 的根目录。执行器、套件 summary 和 HTML 报告后续实现，
当前不创建空的预留代码目录或假的报告文件。

Translator 的套件词汇/hints 现在位于 `cases/osm/vocabulary.json`，通用 prompt 不再硬编码 OSM 控件名。

## Part B：执行一条已验证的计划

```sh
uv run python -m test_agent translate cases/osm/WBS_testcase1_osm.xlsx
# 把下面路径换成上一条命令输出的 output_directory
uv run python -m test_agent run artifacts/<translation-run>/cases/OSM-001 --locators cases/osm/locators.json --headed
```

`run` 默认执行 contract 中声明的视觉检查；没有声明时只使用 DOM。Plan Loader 要求 VALIDATED、合法的 plan.json 和新格式 source.json，
并再次检查当前 Excel、contract 与保存的来源是否一致，再跑原有验证规则。
输入错误退出码为 2，且不启动浏览器。旧 amendments 格式或 Excel/contract 已改动时请重新翻译。
自定义 `--contracts` 路径会保存到 source.json。旧 artifact 没有此字段时按 workbook 旁的路径查找。

手写 locator 将语义名称映射到真实网页元素。例如：
```json
{"starting-point field": {"strategy":"placeholder","value":"From"}}
```
支持 `role`（role + name）、`label`、`placeholder`、`text`、`test_id`、`css`。
`aliases` 列出明确的同义 target；不会模糊匹配。重复 alias 或非法策略是输入错误。
未知 target 是 BLOCKED，reason 为 `no locator for target '<name>'`，code 为 NO_LOCATOR。
元素只保留可见匹配，并要求数量正好为 1；不会使用 `.first()` 隐藏歧义。

实测 OSM 使用可见 Car label 配合隐藏 radio；执行 select 时点击 label，检查 radio 的真实 checked/value。
OSM 没有 Go 按钮：`request-directions button` 映射到 To 输入框，并使用 `submit_key: "Enter"`。
这项实现细节也记录在 results.json 的 action 中。使用英文 locale，固定 desktop viewport。
点击路线规划后，先等待 `ready_selector` 指定的侧栏模板挂载，再填字段。
按 Enter 后，等待 `submit_effect_target` 对应的路线结果可见；没有效果时 BLOCKED，
code 为 SUBMIT_NO_EFFECT。只提交一次，记录 attempts=1，不自动重试动作或断言。
radio/label 的选择会先比对真实 control value 和明确的 selection_aliases；不匹配时
BLOCKED（SELECTION_MISMATCH），避免把执行器的选择错误误报为网页 FAILED。
路线结果读取 `#directions_route`，行程时间读取 `#directions_route_time`，格式如 `2:56`。

状态：PASSED 为执行及检查成功；FAILED 为已获得实际值但不符合预期；BLOCKED 为无法定位、
执行、解析或加载；停止后的步骤为 NOT_RUN。退出码 0 = PASSED，1 = FAILED/BLOCKED，2 = 输入错误。
后续未执行的动作和断言也保留为 NOT_RUN。清理始终尝试执行，清理错误单独记录，不改变用例状态。

结果保存在 `artifacts/run-<run_id>/cases/<case_id>/`：results.json、执行时的 plan/source/locators
快照、screenshots/step-<n>.png、screenshots/final.png 和 trace.zip。final 截图在清理前拍摄。
可用 `uv run playwright show-trace <trace.zip路径>` 回看浏览器动作。

本地测试使用 `tests/fixtures/fake_osm.html` 拦截 OSM URL，其他请求全部中止；没有真实模型调用。
测试需要项目 `.browsers/` 内的 Chromium，缺少时浏览器测试明确 skip。

限制：只执行一条用例，没有 Planner 或自愈。DOM route_connects 只检查路线面板可见、
起点和终点字段包含 contract 城市，不证明地图上的路线几何正确；results.json 明确记录
`route_geometry_verified: false`。其他通用前置条件尚未解释执行，网络前置条件由实际导航结果判断。
显示时间等于或超过 3 小时应 FAILED；不可解析的时间应 BLOCKED，不能改阈值来让它通过。

## Translator 的标准 target 名称

翻译时默认读取 workbook 旁边的 `vocabulary.json`，也可以用 `--vocabulary` 指定。
文件的 `targets` 声明标准名称和含义，`hints` 保存套件说明；不包含 CSS selector。
Translator 收到整个列表，必须把自然语言同义词翻译为标准名称。例如 route time/ETA
在行程时间语境中统一为 `estimated journey duration`。

Python 验证每个 action、check 和 cleanup 的 target。即使名称属于运行时 alias，
新计划也必须使用 vocabulary 中的标准名称，否则 REJECTED，错误为 UNKNOWN_TARGET；
保留 candidate-plan.json 供排错，但不生成可执行的 plan.json。不会自动修正错误名称。
validation.json 的 `vocabulary_applied` 明确说明是否执行了这项检查。默认文件不存在时
允许旧的通用翻译流程，并记录 false；显式指定不存在或格式错误的文件在调用模型前拒绝。

来源快照保留 vocabulary 内容和路径。执行前再次检查 vocabulary 是否变化，并验证 target。
已有不带 vocabulary 快照的历史计划仍兼容原有检查，运行时 aliases 也保留。
重新翻译可以启用新验证。声明 target 不要求 locator 已存在，后续 Planner 可以为已声明
但尚未定位的目标找 DOM locator；UNKNOWN_TARGET 和运行时 NO_LOCATOR 是不同问题。

## D1：按用例声明的截图验证（Claude 优先，实验阶段）

视觉检查由人决定，写在 workbook 旁的 `contracts.json` 中；Translator 不选择使用视觉的步骤，
`plan.json` 只保留原有动作与 DOM 检查。OSM-001 的声明：

```json
"vision_checks": [
  {"step": 4, "kind": "route_geometry",
   "requirement": "The map shows one continuous route line from Hamburg to Berlin.",
   "min_confidence": 0.90}
]
```

起终点来自 contract 的 origin/destination。每项必须显式给出 min_confidence，要求 0.5 < 值 ≤ 1；
没有代码默认值。目前只支持 route_geometry，step 必须存在，不允许重复 step/kind。
Contract 改动后原翻译 artifact 会被判过期，需要重新翻译或重新验证生成新的 artifact，不能改旧运行结果。
Excel 暂不改动；以后可考虑增加 Verify by 列。

本地 `.env` 设置 `VISION_PROVIDER=anthropic`、`VISION_MODEL=<Claude API model ID>`
和 `ANTHROPIC_API_KEY`。Claude 使用原生 Messages API；翻译仍使用 GLM。不要提交 `.env`。
可选 `VISION_PROVIDER=glm` 使用 OpenAI compatible 接口；VISION_API_KEY、VISION_BASE_URL
省略时沿用 OPENAI_API_KEY、OPENAI_BASE_URL，视觉模型必须显式配置。

```bash
uv run python -m test_agent run artifacts/<新的有效翻译>/cases/OSM-001 --locators cases/osm/locators.json --headed
# 离线开发：跳过视觉检查，但仍记 BLOCKED，用例不能 PASSED
uv run python -m test_agent run artifacts/<新的有效翻译>/cases/OSM-001 --locators cases/osm/locators.json --skip-vision
```

原来的 --vision 已移除。默认运行所有声明的检查；--skip-vision 不调用模型，逐项记录 VISION_SKIPPED。
顺序：执行步骤动作 → 该步所有 DOM 检查通过 → 全页截图留证 → vision map locator 对应区域截图 →
模型判断地图 → Python 校验 JSON 和结构化证据 → 后续步骤。DOM 失败时该步视觉检查保留 NOT_RUN。
Selector 在 locators.json（vision map → #map），不写死在 Python 中；模型只收到地图，不收到侧栏。

状态规则：视觉 FAILED（高置信 mismatch）立即停止；视觉 BLOCKED（不确定、规则拒绝、API 错误、
跳过）继续后续步骤，用例最终仍 BLOCKED。若后续 DOM FAILED，则最终 FAILED，并保留两个原因。
最终优先级为 FAILED > BLOCKED > PASSED。动作和 DOM 的 FAIL/BLOCKED 仍停止用例；清理照常执行。

每个视觉 reason 都由 Python 写前半句，再附模型 summary（模型解释，不是事实证明），例如：
- Vision FAILED: mismatch (0.94; min_confidence=0.85). Route ends at Munich.
- Vision inconclusive (0.62 < 0.85): Map tiles still loading.
- Vision match rejected by rule (min_confidence=0.85): endpoints_identifiable=false. ...
- VISION_INCOMPLETE (min_confidence=0.85): stop_reason=max_tokens. No model explanation available.

这些原因进入 StepResult、CaseResult 及 console 输出。summary 最多 200 字符，evidence 保存时截断到
2000 字符，放在 actual.model_summary/model_evidence；都是不可信模型文本，后续 HTML Reporter 必须转义。
0.90 是用户选择的未校准实验值，不代表 90% 实际正确率；match/mismatch 都使用它。
即使 confidence 达标，也要求端点可识别、路线连续且城市匹配。Hamburg 可匹配 Hamburg, Germany，
只比较逗号前完整城市名；不做模糊或子串匹配。要求自带国家/地区时保留完整限定词比较。
视觉通过才设置 route_geometry_verified=true；行程时间仍可 FAILED。跳过或不确定时保持 false。

证据保存在每次 run 的 vision/step-4-0/{request,response,verdict}.json，以及
screenshots/route-4-0.png（地图）和 screenshots/step-4.png（全页）。记录两个路径、地图 SHA256、
实际 min_confidence、provider/model、usage 和 latency_ms。response.json 在失败时也生成。
错误码：VISION_INCOMPLETE、VISION_NOT_SINGLE_TEXT、VISION_HTTP、VISION_TIMEOUT、VISION_NETWORK、
VISION_INVALID_JSON、VISION_SCHEMA、VISION_CONFIG。只记录安全的状态码、停止原因、block 类型或字段名；
不记录 HTTP 异常原文、key 或认证 header。模型/动作/断言不自动重试。

vision_providers.py 负责 API 和错误分类，vision.py 负责结构化判断，Runner 负责步骤和清理。
以后接 Clef 时新增 provider adapter，复用运行规则。记录 tokens 和 latency 供比较，实际费用另按价格计算。
校准集（正确、错误、交换方向、空地图、加载中）仍待建立；离线 fake 只证明运行逻辑。
视觉 PASS 是模型判断，不是坐标或拓扑证明。

官方参考：[Claude Vision](https://platform.claude.com/docs/en/build-with-claude/vision)、
[GLM-4.6V](https://docs.z.ai/guides/vlm/glm-4.6v)。

## 不调用 LLM 的重新验证

只改 contract/vocabulary（例如视觉阈值 0.85 → 0.90）时，使用：

```bash
uv run python -m test_agent revalidate artifacts/translation-20261014T131235938292Z/cases/OSM-001
```

重新读取当前 Excel、contract、vocabulary，执行全部原有计划验证，并写新的 translation-... 文件夹。
source.revalidated_from 记录来源，原 artifact 不变。只有 VALIDATED 才保存 plan.json。
Excel 文字变化时 REJECTED/退出码 1，需要重新 translate；不能用 revalidate 绕过翻译。
重新验证不调用模型或浏览器。运行时 load_plan 仍检查来源是否过期。

代码内部错误标记 VISION_INTERNAL + error_class，传输错误才使用 NETWORK；不输出异常原文。
Claude 同时保存 requested_model（请求名称）与 model（API 实际返回名称）。

## 固定截图的视觉校准

数据集：cases/osm/vision_calibration/images/*.png 和 labels.json。标签由人定义：
PASS 表示应通过；NOT_PASS 表示不能通过；ideal 是最理想的 PASSED/FAILED/BLOCKED。
当前 8 张：Hamburg→Berlin、不同 viewport 的正确路线、Munich、Potsdam、反向路线、Bremen 起点、
没有路线、空白瓦片/加载中。主 viewport 为 1280×800；鲁棒性样本为 1024×768。
通过 tools/dom.py 的 capture_map 读取 vision map 和 vision sidebar 定位条目，排除左侧侧栏覆盖。
生产 Runner 和 capture 共用该方法；不修改 PNG 像素。加载中样本通过拦截瓦片请求制造不可读画面。

仅在建立新数据集时捕获（会访问 OSM）；已冻结的图片不会覆盖：

```bash
uv run python -m test_agent calibrate capture cases/osm/vision_calibration
```

--only <预设文件名> 可补充一个不存在的图片，仍禁止覆盖；用于修正捕获设置时，必须在模型测量之前
固定数据集并记录原因。不要为提高模型成绩而改图片或标签。

测量只读本地固定图片，调用模型，不再访问 OSM：

```bash
uv run python -m test_agent calibrate run cases/osm/vision_calibration --runs 5
```

每图×5次顺序调用，无自动重试。使用生产同一 prompt/schema/provider 和 contract 阈值 0.90。
artifacts/calibration-.../ 保存 labels/contract 快照、responses/（每次 request/response/verdict）、
results.json 和 report.md。传输错误算 BLOCKED，不删除失败样本。
报告包含逐图三种状态次数、置信度统计、模型 summary、false PASS（错误图通过）、missed PASS
（正确图没有通过）、明确错误图的 FAILED 比例、BLOCKED 比例、错误码、延迟 p50/p95 和 tokens。
未报告 usage 的调用按零计入每次尝试平均值，这是下界，不是精确账单；另列 usage 覆盖数。
served model 来自 API 回应。

decide(observation, requirement, min_confidence) 是纯函数。生产和校准共用判断；threshold 表把
同一批 observation 在 0.80/0.85/0.90/0.95 重评分，不额外调用模型。API/解析等错误保持 BLOCKED。
acceptance 看四项：false PASS=0、正确图通过率≥90%、明确错误图 FAILED≥80%、无 INTERNAL 错误。
不达标时先看具体图片和 model_summary，报告事实，不能自动调整 prompt/标签/阈值。

小样本不能代表生产准确率；confidence 是模型自报；OSM 瓦片外观会变化，因此此数据集刻意冻结。
Claude/Clef 比较以后使用相同图片和标签。HTML 报告和 D2 locator fallback 不属于此功能。

## Blind observation 与 hold-out（2026-10-15）

视觉模型现在只接收地图和 observation schema，不接收预期城市、requirement 文本或图片文件名。
它报告 green start / red end 的 city、position（on_label / near_other_city / unclear）、
route_line（continuous / broken / none / unclear）、confidence、summary、evidence。
Python 再与本地 contract 比较：城市和方向准确、两个端点都 on_label、路线连续且 confidence 达标才 PASS；
明确的其他城市或断线为 FAILED；低 confidence、没有路线、不清楚或只能说在其他城市附近时 BLOCKED。
模型仍可能看错，不能把 schema 当作识别正确性的证明。

Claude adapter 接受 thinking/redacted_thinking 前缀 + 唯一 text 结果；只保存 thinking_present 和 block_types，
不保存私有推理内容。零个或多个 text 仍 BLOCKED/NOT_SINGLE_TEXT。原来的 verdict schema 属于历史阶段；
旧报告原样保留，其 threshold 表是当时判断规则的结果。新的 decide/replay 使用 blind-map-v2 schema。

先捕获/检查/冻结新的 hold-out，再改 prompt，避免只对原有图片优化。当前 hold-out 包含 Leipzig、Rostock、
新 viewport 的反向和正确路线、Bernau near-miss，图片和标签的 hash 在 capture.json。

```bash
# 仅用于新的空目录：访问 OSM 一次捕获 hold-out
uv run python -m test_agent calibrate capture cases/osm/vision_calibration_holdout --profile holdout
# 两组分别测量，使用相同 0.90 阈值；不再访问 OSM
uv run python -m test_agent calibrate run cases/osm/vision_calibration --runs 5
uv run python -m test_agent calibrate run cases/osm/vision_calibration_holdout --runs 5
```

不要覆盖已冻结的图片、改标签来提高成绩或自动采用别的阈值。比较需要同时看原集与 hold-out 的四条门槛，
保持 0.90，等用户决定后再考虑阈值或 Clef。

若 OSM 的 lazy directions 请求出错，FORM_NOT_READY 会附上已观察到的 GET 路径和 HTTP 状态
（如 GET /directions → 503）；不额外请求，不重试。不知道状态时不会猜测。

## Step 0：输入 Guardrail（无 AI）

```sh
uv run python -m test_agent guardrail cases/osm/WBS_testcase1_osm.xlsx
uv run python scripts/make_guardrail_demo.py
uv run python -m test_agent guardrail cases/guardrail-demo/guardrail-demo.xlsx
```

正常 workbook 退出 0；demo 退出 3，并保存 masked guardrail.json 和 status=BLOCKED_BY_GUARDRAIL 的 summary.json。
`translate` / `suite` 也会先检查所有 case（包括没选中的 case）；guardrail.json 缺失/无效也 fail closed。
应用 URL 来自配置的 allowed_apps；`--url` 仅可重复该 case 的配置 URL，不能绕过 allow-list。
Jenkins 的 WORKBOOK 参数选择 workbook，Setup 后立即运行 Guardrail，阻断时显示红色 FAILURE，之后的测试、AI、审批与 Jira 阶段跳过。
配置与新网站操作见 [Jenkins guide：Guardrail](docs/ci/jenkins-guide.md#guardrail)。

## 多用例 suite（Part A）

```bash
uv run python -m test_agent suite cases/osm/WBS_testcase1_osm.xlsx --locators cases/osm/locators.json --headed
# 未改变的计划复用；过期时重新翻译
uv run python -m test_agent suite cases/osm/WBS_testcase1_osm.xlsx --locators cases/osm/locators.json --reuse --headed
```

按 Excel 中的顺序读取全部 Case ID，逐个 translate → validate → run。翻译 REJECTED 的 case 为
BLOCKED/TRANSLATION_REJECTED，继续下一条；执行 FAILED/BLOCKED 也继续下一条。每条用例都新建
browser/context，执行各自 cleanup 并关闭，状态不污染后续用例。
--reuse 查找最新且通过现有 loader 校验的 VALIDATED 计划，同时要求 workbook/sidecar 来源一致；
文字、contract、vocabulary 改变都会使旧计划过期。旧的无 vocabulary 快照计划不复用已有新词表。
--skip-vision 仍记录视觉 BLOCKED，不能把缺少验证当通过。

结果在 artifacts/suite-.../summary.json，包含每条 case 的状态/原因、翻译和执行时间、计划/运行路径、
designed_outcome 与 outcome_as_designed，以及 suite totals。计划和 run 各自保留原来的目录格式。
只有全部实际 PASSED 才退出 0，否则退出 1。OSM-002 设计为 FAILED，因此正常演示 suite 也会退出 1。

contract 支持 type=route（旧数据默认）和 type=layer，由 discriminated union 严格验证。
route 的 origin_aliases/destination_aliases 只做精确城市名称匹配（含原有大小写/空白规范化）；
Munich 的 München alias 同时用于 DOM 和 Python 的 blind vision 比较，不发送给视觉模型。
layer 声明 expected_options、selected_layer、default_layer 和步骤；options_present 记录所有缺少和
额外选项，只要全部预期选项存在即可通过。selected 检查 checked radio；URL 的 layers 参数仅作额外证据。
cleanup 重选 Standard 再关 drawer。没有为 layers 新增视觉检查：图块外观未经过视觉验证。
前置条件仍保留为原文；打开 panel 后会记录当时选中的 layer，但不构造通用前置条件检查器。

designed_outcome 是可选的演示预期 PASSED/FAILED，不参与应用断言、不改变真实状态。
OSM-001 设计 PASSED，OSM-002 设计在 step 5 因 duration≥180 FAILED，OSM-003 设计 PASSED。
例如 OSM-002 实际 FAILED 会显示 outcome_as_designed=true；若提前 BLOCKED 则 false。

## Locator cache 与有限自愈（Part B）

执行 click/fill/select/press 动作时先尝试人工 `locators.json`，再尝试同目录的 `locators.cache.json`，最后才调用 GLM Planner。
cache 每次都必须重新匹配到**一个可见元素**，才可以使用。cache 自动生成并被 Git 忽略；删除后可重新学习。
人工文件永远不会被自愈改写。正常运行命令与上面的 `suite` / `run` 相同。

只有 vocabulary 中声明的 target，出现 NO_LOCATOR 或零匹配时才可自愈。人工 locator 匹配到多个
元素时直接 BLOCKED，不让模型猜。Planner 没有工具，只收到 target、description 与最多 16000 字符的
body ARIA snapshot；不会收到 HTML、cookies 或测试预期值。页面文字被当作数据处理。
它只能建议 role+name / label / placeholder / text / test_id，不能生成 CSS，也不能改动作、输入或断言。
Python 严格检查 JSON 和唯一可见匹配；每个 target 每条 case 最多一次模型调用，失败为 HEAL_FAILED。
唯一匹配仍不等于语义一定正确，因此保留后续断言以及人工 review。

成功的 cache entry 保存 locator、rationale、case、run id、model、timestamp 与 snapshot hash。
运行目录的 `locator-input-<hash>.json` 保存截断输入；`locator-heals.json` 保存提议、匹配数和处理结果。
`resolved-locators.json` 保存本次真正使用的定位规则，包括 cache 命中，便于事后复查。
动作包含 healed、locator_source（human/cache/healed）；summary 的 heals 统计成功修复数。
DOM 断言、提交后的结果检测、cleanup 验证读取与 map 截图只使用人工 locators，不使用 cache，也不会调用 Planner。
即使同一个 target 刚被动作修复，之后的检查仍必须有可用的人工定位规则；缺失证据保持 BLOCKED，防止自愈隐藏应用问题。
成功解析的 DOM 检查记录 healed=false、locator_source=human。
复用 cache 不计作一次新修复。导航本身不需要 locator，因此没有 locator_source。

本次 live 故障注入使用 `artifacts/selfheal-demo-20261015/locators.json`（仅移除 layers control）。
重跑该 demo 会先尝试使用其旁边的 cache；若要重新演示 Planner，先删除该临时目录内的 cache。
不需要删除或编辑人工 `cases/osm/locators.json`。

## Day 5：故障注入与一次 vision click

`run` 与 `suite` 都支持重复的 `--fault` 参数；不知道的名称、未声明或仅用于断言的 target 返回 exit 2。
正常不用 `--fault` 时维持原流程。suite 的故障模式先翻译/验证所有计划，确认 target 属于至少一条用例的动作，
再启动浏览器；target 故障只施加到使用该 target 的用例。用例内的断言继续只用人工 locator。

| 参数 | 注入方式 | 演示预期 |
|---|---|---|
| `--fault 'broken-locator:layers control'` | 只在内存移除 locator；本 run 的私有空 cache | OSM-003 自愈并 PASSED |
| `--fault blank-tiles` | 拦截并 abort OSM tile hosts 的请求 | OSM-001 vision BLOCKED，step 5 仍执行 |
| `--fault directions-503` | GET /directions 返回 503 | OSM-001 step 2 BLOCKED，后续 NOT_RUN |
| `--fault 'vision-click:layers control'` | 内存禁用此 action 的 locator/cache/healing | OSM-003 通过截图点击并 PASSED |

```bash
uv run python -m test_agent run <VALIDATED_CASE_FOLDER> --locators cases/osm/locators.json --fault 'vision-click:layers control' --headed
uv run python -m test_agent suite cases/osm/WBS_testcase1_osm.xlsx --locators cases/osm/locators.json --reuse --fault directions-503 --headed
```

不会编辑 cases 下的输入文件。结果/summary 记录 faults_injected 与 outcome_as_designed；后者还检查故障的
关键行为（如真的 healed/vision、503 或 step 5 仍运行），不更改实际 PASSED/FAILED/BLOCKED。
多个故障都满足才算 as designed；矛盾的组合可能为 false，这是诊断数据。

Vision click 只支持 click：人工 locator → cache → heal 都不能定位时才考虑，fill/select/press 与任何检查都不走它。
只有人工 locator 配置同时声明 `vision_click_effect` 和 `vision_click: {"min_confidence": 0.90}` 的 target 可用；
effect 自己也必须有人工 locator。模型只收到完整 1280×800 PNG、target 的 vocabulary description 和输出 schema，
不接收用例的 expected/value。Python 严格验证 found、confidence≥0.90 和图内坐标，一条用例每个 target 最多一次。
点击使用独立 Claude provider；即使 route provider 选 Clef，点击也走 Claude 的凭证/模型，详见 Day 6 配置。

点击前 effect 必须不可见，点击后必须通过人工 locator 变为唯一可见；没有效果则 VISION_CLICK_NO_EFFECT，不重试。
因此错误点击不能单凭模型自信得到 PASS：Python 的 effect 检查和后续断言决定结果；这里不新增视觉真假判定的校准集。
attempts/successes 仅为本次观察数量，不能当模型准确率。route vision 仍使用冻结图像校准；当前阈值为 Clef 0.85 / Claude 0.90（见 Day 6 的事后选阈值说明）。
依据 [Claude 坐标文档](https://platform.claude.com/docs/en/build-with-claude/vision-coordinates)，1280×800 在标准上限内；
请求还设置 oversized_image=error，禁止服务端悄悄缩放。图像 origin 在左上角，CSS 像素与截图坐标一致。
`vision-click/click-N/` 保存原截图、标点副本、request/response/decision JSON；动作记录 locator_source=vision、
坐标/confidence/summary，Case 与 suite totals 记录实际鼠标点击次数和成功次数。

## Clef：先做 text-only smoke test（Part 2.1）

在本地 `.env` 添加 `OPENROUTER_API_KEY`，不要粘贴到聊天或提交到 Git。然后运行：

```bash
uv run python -m test_agent clef-smoke
```

该命令只发一条 traffic-light 文本请求到 OpenRouter `/api/alpha/decisions`，model 为 `cloudflare/clef`，
不使用 Chat Completions、不发送图片、不重试。成功输出 choice、probabilities、provider 和 usage；
请求/安全结果保存在 artifacts/clef-smoke-...。缺 key 为 VISION_CONFIG（没有 HTTP 请求）；HTTP 错误只记录状态码。
接口依据 [OpenRouter Decisions 文档](https://openrouter.ai/docs/guides/community/multimodal-decisions)。
2026-10-15 的 text-only smoke 已成功（用户运行，HTTP 200）；后续实现了下面的 blind Clef provider。

## Clef 图像验证与固定 JPEG 对照

可在 `.env` 选择 `VISION_PROVIDER=clef`、`VISION_MODEL=cloudflare/clef`，凭证独立使用 `OPENROUTER_API_KEY`。
切回 Claude 使用 `VISION_PROVIDER=anthropic`、原有 Claude `VISION_MODEL` 和 `ANTHROPIC_API_KEY`。
不会替你改 `.env` 或选定生产 provider。GLM 的 Translator/Planner 仍使用 OPENAI_* 设置。
Clef 不返回坐标；Day 6 将 vision click 明确配置为独立的 Claude provider，阈值仍为 0.90。

Clef 每张图固定问三个 choice：绿色起点城市、红色终点城市、路线 continuous/broken/none/unclear。
`cases/osm/vision_cities.json` 是全套用例共用的城市候选，不根据当前预期城市裁剪；预期与断言不发送给模型。
Python 使用**所选选项的 probability**（不是另一个 confidence 指标）与 contract 中当前 provider 的阈值比较（Clef 0.85，Claude 0.90）：
全部清晰匹配 → SUCCESS/PASSED；任一高概率错误城市（含 other）或断线 → FAILURE/FAILED；其余 → UNCLEAR/BLOCKED。
actual 和 response.json 保存 choice、全部 probabilities、confidence；reason 列出所选概率。
直接把需求问成 SUCCESS/FAILURE/UNCLEAR 会引入 anchoring，因此生产只实现 blind A；可选 direct B 没有运行。

PNG 原件与 labels 不动。固定压缩规则：JPEG quality 90→85→80→75→70，保留彩色细节（subsampling=0），
只有仍 ≥300000 bytes 才按固定上限缩小。JPEG、原 PNG hash、quality、大小和尺寸存于 compressed/manifest.json。
重复 compress 不覆盖不同内容；校准前检查每张 JPEG 和原 PNG 的 hash。Clef 与 Claude JPEG 对照使用同一份字节。
每个 run 的 vision evidence 还保存 sent-image.jpg 和处理参数，可用来人工检查小字是否仍可判断。

```bash
# 一次冻结（已有文件一致则保留；不覆写变化）
uv run python -m test_agent calibrate compress cases/osm/vision_calibration
uv run python -m test_agent calibrate compress cases/osm/vision_calibration_holdout

# 两套都各运行 5 次；这些命令会调用 API 并产生费用
VISION_PROVIDER=clef VISION_MODEL=cloudflare/clef uv run python -m test_agent calibrate run cases/osm/vision_calibration --image-variant jpeg --runs 5
VISION_PROVIDER=clef VISION_MODEL=cloudflare/clef uv run python -m test_agent calibrate run cases/osm/vision_calibration_holdout --image-variant jpeg --runs 5
VISION_PROVIDER=anthropic VISION_MODEL=claude-haiku-5-5 uv run python -m test_agent calibrate run cases/osm/vision_calibration --image-variant jpeg --runs 5
VISION_PROVIDER=anthropic VISION_MODEL=claude-haiku-5-5 uv run python -m test_agent calibrate run cases/osm/vision_calibration_holdout --image-variant jpeg --runs 5
```

默认 `--image-variant png` 保留原流程。freeze 后更改任何原件都需要显式建立新数据集，不可偷偷替换。
比较沿用 zero false PASS、正确图 PASS≥90%、明显错误 FAILED≥80%、无 INTERNAL error 的同一标准。
选择 provider 前看 review 中 Claude PNG / Claude JPEG / Clef A 的表；速度、费用与错误率须一起评估。
Claude 费用按官方短输入标准价格估算（非账单），Clef 使用 API 返回 cost；未知费用不当成零。

本次 65+65 次 JPEG 对照（2026-10-15，另复用 65 次 Claude PNG 历史结果）已写入 review：
Clef median 791 ms，Claude JPEG 1730 ms；但在 0.90 下，Clef 正确图 PASS=0%，Claude JPEG=100%。
两者 false PASS 都为 0，明显错误 FAILED 分别只有 50.0% / 43.3%，因此两者都未达到全部验收标准。
Clef 每张图 5 次返回的概率向量完全一致。未调低阈值、未改 prompt/label，未自动切换生产 provider。
完整对照表见 `artifacts/clef-comparison-20261015/report.md`，可复查 `summary.json` 中所有原始报告路径。
JPEG 没有降低 Claude 的正确图通过率，所以此数据不支持把 Clef 的较低表现归因于压缩；这是小样本结论。


## Day 6：provider 阈值、离线 HTML 报告和重复运行

用户已选择 Clef 作为 route-vision provider。**程序没有修改你的 `.env`**；请自行把这两行改为：

```dotenv
VISION_PROVIDER=clef
VISION_MODEL=cloudflare/clef
```

保留 OPENROUTER_API_KEY、ANTHROPIC_API_KEY。VISION_CLICK_MODEL 可单独指定 Claude 点击模型，默认
claude-haiku-5-5；vision click 始终由 Claude 执行，阈值 0.90。若缺 Anthropic key，会 BLOCKED，不会把 OpenRouter/GLM key 当 Claude key。
切回 route 的 Claude provider 时，设置 VISION_PROVIDER=anthropic 及对应 Claude VISION_MODEL；route 阈值使用 0.90。

contract 的 vision_checks[].min_confidence 现在支持 `{"clef":0.85,"anthropic":0.90}`，旧的单一数字仍有效。
当前 provider 必须有条目，缺少时是 contract error，不启动浏览器，不猜默认阈值。
这次三条计划已通过 revalidate 生成新 VALIDATED 目录，不重新调用 Translator。以后只改 contract 时也可用 revalidate；
如果 Excel 原文变了，仍需重新翻译。

**校准限制（报告中也自动显示）：**
Clef threshold 0.85 was chosen after seeing Clef's calibration results (post-hoc), justified by Clef's calibrated probabilities
being on a different scale than Claude's self-reported confidence; replay showed 0 false PASS and 0 missed PASS on both frozen sets.
Not confirmed on a new set.
0.85 是看过数据后选的，不可作为独立新数据验证；前面的 0.90 对照结果保留为历史测量，不改写。

```bash
# suite 结束后自动生成 report.html；也可只从现有 JSON 重新生成，不调用 API
uv run python -m test_agent report artifacts/suite-<id>
uv run python -m test_agent report artifacts/repeat-<id>

# 测量执行重复性：所有 case 必须已有当前有效计划，绝不在中途调用 GLM
uv run python -m test_agent repeat cases/osm/WBS_testcase1_osm.xlsx --locators cases/osm/locators.json --times 3 --reuse
```

repeat 总是复用计划（--reuse 可显式写出）；缺计划或计划过期时要求先 translate/revalidate。
输出 artifacts/repeat-.../repeatability.json、report.html、audit.csv、junit.xml，每次 run-<n>/ 也有自己的报告。
N 次都执行真实浏览器/API，会产生费用；本次已做一次 times=3（9 个 case），无需为检查 HTML 再访问 OSM。
有任何真实 case FAILED/BLOCKED，退出码为 1；OSM-002 设计 FAILED，所以状态符合设计也会退出 1。

报告可直接在浏览器离线打开，无 JavaScript、外部 CSS、字体或网络图片。缩略图内嵌 JPEG，完整截图、results.json、trace.zip
使用相对路径链接；单独分享 HTML 仍能看缩略图，完整链接需要保留相关 artifact 目录结构。
所有 workbook/page/model 文字都转义为文本，不作为 HTML 执行。
头部显示 UTC 时间（带时区）、workbook、工具版本/Git hash 和 dirty 状态，及实际 provider/model/threshold。
api_host 是请求的服务域名；upstream_provider 是响应报告的上游名称，upstream_host 未报告时不猜测域名。

Case totals 是**用例最终状态**；另列 Route vision checks，避免 FAIL 用例里的 BLOCKED vision 被隐藏。
顶部的 What happened 用简单文字解释每条 case；repeat 页面说明运行次数，并链接到每次 suite 报告。
步骤表直接显示预期和实际结果，原始 JSON 收在默认折叠的 Technical details 里。
布尔值显示 Yes/No，执行时间保留一位小数；没有 heal 或 vision click 时显示 —。
若通过的 vision check 有任一所选概率在阈值至阈值 + 0.03（含边界）之间，显示 PASSED (borderline) 和概率。
这只是显示提醒，不改变 results.json 的状态或阈值。`report` 命令只重建 HTML，不执行测试或调用模型。
展开每条 case 可看源步骤/预期、动作/断言、定位来源、实际值/概率、截图、cleanup 和 trace。
每个步骤和 Cleanup 默认折叠；点击步骤行才展开表格和截图。步骤行显示简短动作、状态，未通过时附简短原因；完整文字保留在展开内容中。
Known limitations 自动列出地图模型判断、layer tile 未视觉验证、前置条件只保留原文，以及上面的校准限制。

Repeatability 表的 consistent 只表示各次**case status 相同**，不表示所有证据完全一致。
probability spread 列出每个问题/每个选项的 min/max、所选概率 min/max、choices，以及上游 provider/host；
单独列出 step/status/reason 的变化。duration mean/min/max 使用 case execution_seconds，不包含翻译。
同样截图上的 Clef 概率可重复，但真实页面每次的瓦片加载/画面不同，概率仍可能不同；报告保留变化，不重试求通过。

## Audit agent → Jenkins approval → Jira

`uv run python -m test_agent audit-agent artifacts/suite-<id>` 从现有 Excel/plan/results/audit rows 建立每 case dossier（包括 PASSED），Claude Haiku 负责全部 audit 推理；需要画面时，通过受限 tool 用同一 Haiku 模型在隔离上下文中读取单张 PNG。Audit 不调用 GLM。
配置只需要 `ANTHROPIC_API_KEY` 和可选 `AUDIT_MODEL=claude-haiku-5-5`（同一模型用于分析和截图观察）。
结果为 `audit_analysis.json` / `.md`；不重跑测试，不自动改变 verdict 或阈值。AI 推理只是建议；Python 校验引用、截图问答与 ticket 规则，校验失败允许一次有字段诊断的修正；多余但未声称画面内容的 screenshot ID 会移除并记录 stripped_screenshot_ids；部分成功时显示逐 case 覆盖和原因，零 case 成功才显示 unavailable banner，并在 JSON 标记 unanalysed，不使 build 因模型失败而中断。
报告顶部只列需要行动的 finding；无须行动的分析默认折叠。只有有效 ticket 候选才触发 Jenkins 审批，所有 ticket 仍需人工批准。

Jenkins 在无 executor/container 的 Review tickets input 中让人选择 finding（默认不选）；点击 Create Jira ticket 批准后才发送；可选的 CHECK_JIRA_CONNECTION 参数会提前用 wbs-jira 做只读检查。未批准、Abort、超时均不创建或评论。
`jira_decision.json` 记录批准者/IDs/分析 hash，`jira_results.json` 记录 created/commented 链接与安全的 phase/path-template 错误。审批页面显示本次 suite 的 Passed/Failed/Blocked 总数和每项一行的 short_reason。

```bash
uv run python -m test_agent package artifacts/suite-<id> --output-dir reports
uv run python -m test_agent jira create reports --approved F-OSM-002-1 --dry-run
```

Jira 默认离线 dry-run，写 `jira_payloads.json`，不进行 HTTP；实际发送必须显式 `--send` 与人工批准的 finding IDs。
Python 按 cause + 引用的 FAILED check 决定候选，AI recommend_ticket 仅供参考。发送前发现 issue types，用 case ID + 引用失败 steps + Excel expected 的 v2 fingerprint 搜索未完成 ticket（`/search/jql`），兼容旧 case label；多个匹配评论最早的 issue 并记录 duplicates；旧 label 匹配成功后添加 v2 label 并记录 added_v2_label；附相关截图。
Jira 404/认证问题先运行只读检查（本机 .env 需填与 Jenkins 相同账号的 email/token）：

```bash
uv run python -m test_agent jira check
```

只 GET 账号 display name、项目可见性与 issue types，不创建 ticket 或打印 email；Jenkins 也可勾选 CHECK_JIRA_CONNECTION 运行同样检查。
旧分析缺少必填 short_reason 时，应重新审阅并批准新的分析 hash。
Credential/token、审批页面、错误码和学习步骤见 [Jenkins guide](docs/ci/jenkins-guide.md)。

自行测试 audit（本机现有演示 suite，不发送 Jira）：

```bash
uv run python -m unittest discover -s tests -p 'test_audit_agent.py' -v
AUDIT_MODEL=claude-haiku-5-5 uv run python -m test_agent audit-agent artifacts/suite-20261016T085446352441Z
open artifacts/suite-20261016T085446352441Z/audit_analysis.md
```

第二条命令会调用 Anthropic；在本机 `.env` 配好 key。核对 JSON 的 provider=anthropic、agent_unavailable=false，并确认 case_audits 三条都为 analysed；dropped_findings 会列字段错误和 repair_used。详细排查见 guide 第 15 节。
