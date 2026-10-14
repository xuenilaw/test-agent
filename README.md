# Test Agent：Playwright、GLM 与自然语言测试用例

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

guardrail 是验证与阻断的机制，不一定是 agent。本阶段是确定性的 Python 验证门：
动作白名单、参数类型、来源覆盖、明确的用例约束。暂未使用 SDK guardrail decorator。
以后可增加语义审查 agent，检测自然语言中漏掉的含义；它补充规则，不替代规则。

阅读顺序：`readers/excel.py` → `schemas/plan.py` → `translation/validator.py` →
`translation/translator.py` → `cli.py`，这些文件都在 `src/test_agent/` 内。

## 项目结构

```text
src/test_agent/
  __main__.py, cli.py        # python -m test_agent 的入口
  readers/excel.py           # workflow 1：读取用例
  schemas/plan.py            # 纯 Pydantic 数据模型
  translation/translator.py  # workflow 1b：自然语言翻译
  translation/validator.py   # 通用验证和路线约束验证，分开维护
cases/osm/                  # 样例 Excel、contracts.json、vocabulary.json、locators.json
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

`run` 不调用 LLM。Plan Loader 要求 VALIDATED、合法的 plan.json 和新格式 source.json，
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

限制：只执行一条用例，没有 Planner、自愈或 Vision。route_connects 只检查路线面板可见、
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
