"""Expose the same deterministic Playwright function as an SDK tool."""

import asyncio
import json
import os

from agents import Agent, ModelSettings, OpenAIChatCompletionsModel, RunConfig, Runner, function_tool
from dotenv import load_dotenv
from openai import AsyncOpenAI

from browser_tool import ROOT, arguments, check_search_box


def build_tool(*, offline: bool, headed: bool):
    @function_tool(failure_error_function=None)
    async def locate_search_box() -> str:
        """Open the configured page, locate its search box, fill Hamburg,
        verify the input value, and return JSON with status and evidence.
        This checks an existing locator; it does not discover new locators.
        """
        result = await check_search_box(offline=offline, headed=headed)
        return json.dumps(result, ensure_ascii=False)

    return locate_search_box


async def main() -> int:
    args = arguments()
    load_dotenv(ROOT / ".env")
    api_key = os.getenv("OPENAI_API_KEY", "").strip()
    model_name = (os.getenv("OPENAI_MODEL") or os.getenv("OPENAI_DEFAULT_MODEL") or "").strip()
    base_url = os.getenv("OPENAI_BASE_URL", "").strip() or None
    if not api_key or not model_name:
        missing = []
        if not api_key:
            missing.append("OPENAI_API_KEY")
        if not model_name:
            missing.append("OPENAI_MODEL or OPENAI_DEFAULT_MODEL")
        print("Missing configuration: " + ", ".join(missing) + ". Set these in .env.")
        return 2
    # Agent Runner manages the model/tool interaction. This is distinct from
    # the test-suite Runner that we will build on Day 2.
    try:
        # The SDK orchestrates tools; the client selects the model provider.
        # GLM's compatible endpoint uses Chat Completions, not Responses.
        async with AsyncOpenAI(api_key=api_key, base_url=base_url,
                               timeout=60.0, max_retries=0) as client:
            agent = Agent(
                name="Day 1 browser agent",
                instructions="Call locate_search_box exactly once. The tool performs the check and returns its evidence.",
                model=OpenAIChatCompletionsModel(model=model_name, openai_client=client),
                tools=[build_tool(offline=args.offline, headed=args.headed)],
                model_settings=ModelSettings(tool_choice="required"),
                tool_use_behavior="stop_on_first_tool",
            )
            response = await Runner.run(agent, "Check the search box.", max_turns=2,
                                        run_config=RunConfig(tracing_disabled=True))
        # Only a real tool result is accepted, not a model-written PASS.
        if not any(getattr(item, "type", None) == "tool_call_output_item"
                   for item in response.new_items):
            print("Agent did not execute the browser tool. Check model tool-calling support.")
            return 2
        result = json.loads(response.final_output)
    except Exception as exc:
        status = getattr(exc, "status_code", None)
        suffix = f", HTTP {status}" if status is not None else ""
        print(f"Agent call failed ({type(exc).__name__}{suffix}). Check API credentials, base URL, model access, and tool-calling support.")
        return 2
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if result["status"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
