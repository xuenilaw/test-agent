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
cases/osm/                  # 样例 Excel、contracts.json
examples/                   # 保留 Day 1 Playwright 和 Agent 教学脚本
tests/fixtures/             # 不需要网络或真实模型的回归测试
docs/reviews/               # Codex handoff 与 Claude review
artifacts/<run_id>/cases/<case_id>/  # 每条用例独立证据
```

从项目根目录运行 `uv sync --locked`，它安装 editable package。
目录名 `test_agent` 用于 Python import，发行包名 `test-agent` 与 GitHub repo 一致。
CLI 默认从当前目录读取 `.env`、`cases/osm/contracts.json` 并写入 `artifacts/`。
从其他目录调用时，可用 `python -m test_agent --project-dir /path/to/test-agent translate ...`；
显式提供的 workbook/contracts 相对路径仍相对于当前工作目录。
`--output-dir` 可覆盖 artifacts 的根目录。执行器、套件 summary 和 HTML 报告后续实现，
当前不创建空的预留代码目录或假的报告文件。
