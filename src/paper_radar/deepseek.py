"""DeepSeek API 客户端：Search / Fetch / Chat 三个接口。

官方文档：https://api-docs.deepseek.com/zh-cn/guides/search/
- Search: POST /v1/tools/search，按 query 返回结构化网页结果
- Fetch:  POST /v1/tools/fetch，抓取单页并返回 Markdown
- Chat:   POST /v1/chat/completions，OpenAI 兼容

计费：Search/Fetch 每 1000 次成功请求 5 元；只有返回 200 且结果非空才计费。
"""

from __future__ import annotations

import json
import re
from typing import Any, Optional

from .http import HttpError, request_json
from .util import get_logger

log = get_logger(__name__)

DEFAULT_BASE = "https://api.deepseek.com"


class DeepSeekError(RuntimeError):
    """DeepSeek 接口调用失败。"""


class NoApiKey(DeepSeekError):
    """没有配置 DEEPSEEK_API_KEY。"""


def extract_json(text: str) -> Any:
    """从模型输出里抠出 JSON（兼容 ```json 代码块和前后废话）。"""
    if not text:
        raise ValueError("空文本")
    stripped = text.strip()
    try:
        return json.loads(stripped)
    except json.JSONDecodeError:
        pass
    fenced = re.search(r"```(?:json)?\s*(.*?)```", stripped, re.S)
    if fenced:
        candidate = fenced.group(1).strip()
        try:
            return json.loads(candidate)
        except json.JSONDecodeError:
            stripped = candidate
    # 退而求其次：找第一个 { 或 [ 到最后一个 } 或 ]
    for opener, closer in (("{", "}"), ("[", "]")):
        start = stripped.find(opener)
        end = stripped.rfind(closer)
        if start != -1 and end > start:
            try:
                return json.loads(stripped[start : end + 1])
            except json.JSONDecodeError:
                continue
    raise ValueError(f"无法从输出中解析 JSON：{text[:200]}")


class DeepSeekClient:
    """最少依赖的 DeepSeek API 封装。"""

    def __init__(
        self,
        api_key: Optional[str],
        base_url: str = DEFAULT_BASE,
        timeout: float = 90.0,
        model: str = "deepseek-chat",
    ) -> None:
        self.api_key = (api_key or "").strip()
        self.base_url = (base_url or DEFAULT_BASE).rstrip("/")
        self.timeout = timeout
        self.model = model
        self._search_calls = 0
        self._fetch_calls = 0
        self._chat_calls = 0

    # --- 基础 ---
    @property
    def available(self) -> bool:
        return bool(self.api_key)

    def _headers(self) -> dict[str, str]:
        if not self.api_key:
            raise NoApiKey("未配置 DEEPSEEK_API_KEY")
        return {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }

    def _post(self, path: str, payload: dict, timeout: Optional[float] = None) -> dict:
        url = f"{self.base_url}{path}"
        try:
            data = request_json(
                url,
                method="POST",
                payload=payload,
                headers=self._headers(),
                timeout=timeout or self.timeout,
                retries=2,
            )
        except HttpError as exc:
            if exc.status == 401:
                raise DeepSeekError("DeepSeek API Key 无效（401）") from None
            if exc.status == 402:
                raise DeepSeekError("DeepSeek 账户余额不足（402）") from None
            raise DeepSeekError(f"{path} 调用失败：{exc}") from None
        if not isinstance(data, dict):
            raise DeepSeekError(f"{path} 返回格式异常：{type(data)}")
        return data

    # --- Search ---
    def search(self, query: str, count: int = 10, need_content: bool = False) -> list[dict]:
        """调用 /v1/tools/search，返回 results 数组。"""
        if len(query) > 128:
            query = query[:128]
            log.warning("搜索词超过 128 字符，已截断：%s", query)
        data = self._post(
            "/v1/tools/search",
            {"query": query, "count": max(1, min(50, count)), "need_content": need_content},
        )
        self._search_calls += 1
        results = data.get("results") or []
        return [r for r in results if isinstance(r, dict) and r.get("url")]

    # --- Fetch ---
    def fetch(self, url: str) -> dict:
        """调用 /v1/tools/fetch，返回 {title, content(Markdown)}。"""
        data = self._post("/v1/tools/fetch", {"url": url}, timeout=max(self.timeout, 120))
        self._fetch_calls += 1
        return {"title": data.get("title") or "", "content": data.get("content") or ""}

    # --- Chat ---
    def chat(
        self,
        messages: list[dict],
        temperature: float = 0.2,
        max_tokens: int = 3000,
        json_mode: bool = True,
    ) -> str:
        payload: dict[str, Any] = {
            "model": self.model,
            "messages": messages,
            "temperature": temperature,
            "max_tokens": max_tokens,
            "stream": False,
        }
        if json_mode:
            payload["response_format"] = {"type": "json_object"}
        data = self._post("/v1/chat/completions", payload, timeout=max(self.timeout, 180))
        self._chat_calls += 1
        try:
            return data["choices"][0]["message"]["content"]
        except (KeyError, IndexError, TypeError):
            raise DeepSeekError(f"Chat 返回格式异常：{str(data)[:300]}") from None

    # --- 统计 ---
    def stats(self) -> dict:
        return {
            "search_calls": self._search_calls,
            "fetch_calls": self._fetch_calls,
            "chat_calls": self._chat_calls,
        }
