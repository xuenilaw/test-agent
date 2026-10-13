# Day 1：Playwright → Agents SDK

今天只验证：打开页面 → 找到搜索框 → 输入 Hamburg → 断言输入值 → 截图 → 清理。
这还不是路线搜索测试，也没有 AI 自愈或 Vision。

## 安装

```sh
uv sync --locked
PLAYWRIGHT_BROWSERS_PATH="$PWD/.browsers" uv run playwright install chromium
```

## 先运行纯 Playwright

```sh
uv run python browser_tool.py --offline
uv run python browser_tool.py
uv run python browser_tool.py --headed
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
uv run python day1_agent.py --offline
uv run python day1_agent.py
```

Agent 调用需要对应模型提供商的 API 账户和额度；`--offline` 仅指浏览器页面离线，模型仍需联网。
SDK 的模型/工具循环和测试套件的步骤/用例循环是两种不同的 Runner。
程序使用 `AsyncOpenAI(base_url=...)` 指定提供商，并用 `OpenAIChatCompletionsModel`
选择兼容的 Chat Completions 接口。SDK 负责调度工具，实际模型可以是 GLM。
本例关闭 SDK tracing，不需要另一个 OpenAI tracing key。

## 按这个顺序阅读

1. `browser_tool.py`：先读 `check_search_box()`，看建立会话、断言和 `finally`。
2. `day1_agent.py`：看 `@function_tool`，它把普通函数暴露为模型可以调用的工具。
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
