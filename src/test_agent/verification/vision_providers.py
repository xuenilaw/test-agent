"""Vision transports and credential-safe diagnostic errors; no browser tools."""

import asyncio
import base64
import json
import os
import time
from typing import Protocol
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from openai import AsyncOpenAI, APIStatusError, APITimeoutError, APIConnectionError


class VisionError(ValueError):
    def __init__(self, code: str, **safe_details):
        super().__init__("VISION_" + code)
        self.code, self.details = code, safe_details


class VisionProvider(Protocol):
    async def observe(self, image: bytes) -> dict: ...


class UnavailableVision:
    def __init__(self, error: VisionError):
        self.error = error

    async def observe(self, image):
        raise self.error


def elapsed(start):
    return round((time.perf_counter() - start) * 1000)


def transport_error(exc, start) -> VisionError:
    details = {"latency_ms": elapsed(start)}
    if isinstance(exc, (HTTPError, APIStatusError)):
        status = exc.code if isinstance(exc, HTTPError) else exc.status_code
        if isinstance(exc, HTTPError):
            exc.close()
        return VisionError("HTTP", http_status=status, **details)
    if isinstance(exc, (TimeoutError, APITimeoutError)) or (
            isinstance(exc, URLError) and isinstance(exc.reason, TimeoutError)):
        return VisionError("TIMEOUT", **details)
    if isinstance(exc, json.JSONDecodeError):
        return VisionError("INVALID_JSON", **details)
    return VisionError("NETWORK", **details)


def usage_metadata(usage):
    # Keep token counts only, never arbitrary provider strings/errors.
    return {k: v for k, v in (usage if isinstance(usage, dict) else {}).items()
            if k.endswith("tokens") and isinstance(v, int) and not isinstance(v, bool) and v >= 0}


def reason_token(value):
    return value if isinstance(value, str) and value in {"end_turn", "max_tokens", "refusal", "tool_use", "stop_sequence",
                             "pause_turn", "stop", "length", "content_filter"} else "unknown"


class GLMVision:
    def __init__(self, *, api_key: str, model: str, base_url: str):
        self.api_key, self.model, self.base_url = api_key, model, base_url

    @classmethod
    def from_env(cls):
        key = os.getenv("VISION_API_KEY") or os.getenv("OPENAI_API_KEY")
        url = os.getenv("VISION_BASE_URL") or os.getenv("OPENAI_BASE_URL")
        model = os.getenv("VISION_MODEL")
        if not key or not url or not model:
            raise VisionError("CONFIG", fields=["VISION_MODEL", "VISION_API_KEY/OPENAI_API_KEY", "VISION_BASE_URL/OPENAI_BASE_URL"])
        return cls(api_key=key, model=model, base_url=url)

    async def observe(self, image: bytes) -> dict:
        from test_agent.verification.vision import INSTRUCTIONS, VisualObservation
        start = time.perf_counter()
        try:
            async with AsyncOpenAI(api_key=self.api_key, base_url=self.base_url, timeout=60.0, max_retries=0) as client:
                response = await client.chat.completions.create(model=self.model, messages=[
                    {"role": "system", "content": INSTRUCTIONS},
                    {"role": "user", "content": [
                        {"type": "text", "text": json.dumps({"output_schema": VisualObservation.model_json_schema()})},
                        {"type": "image_url", "image_url": {
                            "url": "data:image/png;base64," + base64.b64encode(image).decode()}}]}])
        except Exception as exc:
            raise transport_error(exc, start) from None
        meta = {"provider": "glm", "model": response.model, "requested_model": self.model,
                "latency_ms": elapsed(start), "usage": usage_metadata(response.usage.model_dump() if response.usage else {})}
        finish = reason_token(response.choices[0].finish_reason) if response.choices else "unknown"
        meta["finish_reason"] = finish
        if finish != "stop":
            raise VisionError("INCOMPLETE", **meta)
        return {**meta, "content": response.choices[0].message.content}


class ClaudeVision:
    def __init__(self, *, api_key: str, model: str):
        self.api_key, self.model = api_key, model

    async def observe(self, image: bytes) -> dict:
        from test_agent.verification.vision import INSTRUCTIONS, VisualObservation
        body = {"model": self.model, "max_tokens": 2048, "system": INSTRUCTIONS,
                "messages": [{"role": "user", "content": [
                    {"type": "image", "source": {"type": "base64", "media_type": "image/png",
                                                  "data": base64.b64encode(image).decode()}},
                    {"type": "text", "text": json.dumps({"output_schema": VisualObservation.model_json_schema()})}]}]}
        request = Request("https://api.anthropic.com/v1/messages", data=json.dumps(body).encode(),
                          headers={"x-api-key": self.api_key, "anthropic-version": "2023-06-01",
                                   "Content-Type": "application/json"}, method="POST")
        def send():
            with urlopen(request, timeout=60) as response:
                return response.read(), response.status
        start = time.perf_counter()
        try:
            raw, status = await asyncio.to_thread(send)
        except Exception as exc:
            raise transport_error(exc, start) from None
        meta = {"provider": "anthropic", "model": self.model, "requested_model": self.model,
                "latency_ms": elapsed(start), "http_status": status}
        try:
            response = json.loads(raw)
        except (json.JSONDecodeError, UnicodeError):
            raise VisionError("INVALID_JSON", **meta) from None
        if not isinstance(response, dict):
            raise VisionError("SCHEMA", fields=["response"], **meta)
        if not isinstance(response.get("model"), str):
            raise VisionError("SCHEMA", fields=["model"], **meta)
        meta["model"] = response["model"]
        meta.update(usage=usage_metadata(response.get("usage")),
                    stop_reason=reason_token(response.get("stop_reason")))
        blocks = response.get("content")
        meta["block_types"] = [b.get("type") if isinstance(b, dict) and b.get("type") in
            {"text", "thinking", "redacted_thinking", "tool_use", "server_tool_use"} else "unknown"
            for b in blocks] if isinstance(blocks, list) else []
        if meta["stop_reason"] != "end_turn":
            raise VisionError("INCOMPLETE", **meta)
        types = meta["block_types"]
        meta["thinking_present"] = any(t in {"thinking", "redacted_thinking"} for t in types)
        if (not types or types[-1] != "text" or types.count("text") != 1
                or any(t not in {"thinking", "redacted_thinking"} for t in types[:-1])
                or not isinstance(blocks[-1].get("text"), str)):
            raise VisionError("NOT_SINGLE_TEXT", **meta)
        return {**meta, "content": blocks[-1]["text"]}


def provider_from_env() -> VisionProvider:
    provider = os.getenv("VISION_PROVIDER", "anthropic")
    if provider == "glm":
        return GLMVision.from_env()
    if provider != "anthropic":
        raise VisionError("CONFIG", fields=["VISION_PROVIDER"])
    key = os.getenv("VISION_API_KEY") or os.getenv("ANTHROPIC_API_KEY")
    model = os.getenv("VISION_MODEL")
    if not key or not model:
        raise VisionError("CONFIG", fields=["ANTHROPIC_API_KEY/VISION_API_KEY", "VISION_MODEL"])
    return ClaudeVision(api_key=key, model=model)
