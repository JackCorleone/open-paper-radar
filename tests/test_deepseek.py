"""用本地 mock HTTP 服务验证 DeepSeek 客户端的请求格式与响应解析。

这样即使没有真实 API Key，也能保证：
- Search 请求体是 {"query","count","need_content"}
- Fetch 请求体是 {"url"}
- Chat 请求体带 model / messages / response_format
- 401 / 402 错误会被转换成可读的 DeepSeekError
- Scirate 的 DeepSeek Fetch 兜底路径可用
"""

from __future__ import annotations

import json
import sys
import threading
import unittest
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from paper_radar.deepseek import DeepSeekClient, DeepSeekError, extract_json  # noqa: E402
from paper_radar.llm import score_papers  # noqa: E402
from paper_radar.models import Paper  # noqa: E402
from paper_radar.sources.scirate import get_scirate_papers  # noqa: E402

FIXTURES = ROOT / "tests" / "fixtures"


class _MockState:
    def __init__(self) -> None:
        self.requests: list[tuple[str, dict, dict]] = []
        self.responses: dict[str, tuple[int, dict]] = {}
        self.fail_scirate = False


class _Handler(BaseHTTPRequestHandler):
    state: _MockState

    def log_message(self, *args) -> None:  # noqa: D102 - 静音
        pass

    def do_POST(self) -> None:  # noqa: N802 - BaseHTTPRequestHandler 约定
        length = int(self.headers.get("Content-Length") or 0)
        raw = self.rfile.read(length)
        try:
            body = json.loads(raw or b"{}")
        except json.JSONDecodeError:
            body = {"_raw": raw.decode("utf-8", "replace")}
        headers = {k: v for k, v in self.headers.items()}
        self.state.requests.append((self.path, body, headers))
        status, payload = self.state.responses.get(self.path, (200, {}))
        data = json.dumps(payload).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)


class DeepSeekClientTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.state = _MockState()
        handler = type("Handler", (_Handler,), {"state": cls.state})
        cls.server = HTTPServer(("127.0.0.1", 0), handler)
        cls.port = cls.server.server_address[1]
        cls.thread = threading.Thread(target=cls.server.serve_forever, daemon=True)
        cls.thread.start()

    @classmethod
    def tearDownClass(cls) -> None:
        cls.server.shutdown()
        cls.server.server_close()

    def setUp(self) -> None:
        self.state.requests.clear()
        self.state.responses.clear()
        self.base = f"http://127.0.0.1:{self.port}"
        self.client = DeepSeekClient("sk-test-key", base_url=self.base, timeout=10)

    # --- Search ---
    def test_search_request_and_parse(self):
        self.state.responses["/v1/tools/search"] = (
            200,
            {
                "results": [
                    {
                        "title": "Quantum reservoir computing on a spin chain",
                        "url": "https://arxiv.org/abs/2610.12345",
                        "summary": "We show a quantum reservoir computer.",
                        "snippet": "short",
                        "rerank_score": 2.4,
                        "authority": 3,
                        "date": "2026-10-18T00:00:00+00:00",
                    }
                ]
            },
        )
        results = self.client.search("quantum reservoir computing", count=5, need_content=False)
        self.assertEqual(len(results), 1)
        path, body, headers = self.state.requests[0]
        self.assertEqual(path, "/v1/tools/search")
        self.assertEqual(body["query"], "quantum reservoir computing")
        self.assertEqual(body["count"], 5)
        self.assertIs(body["need_content"], False)
        self.assertEqual(headers.get("Authorization"), "Bearer sk-test-key")

    def test_search_count_is_clamped(self):
        self.state.responses["/v1/tools/search"] = (200, {"results": []})
        self.client.search("x", count=999)
        _, body, _ = self.state.requests[0]
        self.assertEqual(body["count"], 50)

    # --- Fetch ---
    def test_fetch_scirate_markdown(self):
        markdown = (FIXTURES / "scirate_sample.md").read_text(encoding="utf-8")
        self.state.responses["/v1/tools/fetch"] = (200, {"title": "Top arXiv papers", "content": markdown})
        data = self.client.fetch("https://scirate.com/quant-ph")
        self.assertIn("Typical Superpositions", data["content"])
        path, body, _ = self.state.requests[0]
        self.assertEqual(path, "/v1/tools/fetch")
        self.assertEqual(body["url"], "https://scirate.com/quant-ph")

    # --- Chat ---
    def test_chat_request_format(self):
        self.state.responses["/v1/chat/completions"] = (
            200,
            {"choices": [{"message": {"content": '{"papers": []}'}}]},
        )
        text = self.client.chat([{"role": "user", "content": "hi"}])
        self.assertEqual(text, '{"papers": []}')
        path, body, _ = self.state.requests[0]
        self.assertEqual(path, "/v1/chat/completions")
        self.assertEqual(body["model"], "deepseek-chat")
        self.assertEqual(body["response_format"], {"type": "json_object"})
        self.assertIs(body["stream"], False)

    # --- 错误 ---
    def test_invalid_key_raises_readable_error(self):
        self.state.responses["/v1/tools/search"] = (
            401,
            {"error": {"message": "invalid api key", "type": "invalid_request_error"}},
        )
        with self.assertRaises(DeepSeekError) as ctx:
            self.client.search("x")
        self.assertIn("Key 无效", str(ctx.exception))

    def test_no_balance_raises_readable_error(self):
        self.state.responses["/v1/tools/search"] = (402, {"error": {"message": "no balance"}})
        with self.assertRaises(DeepSeekError) as ctx:
            self.client.search("x")
        self.assertIn("余额不足", str(ctx.exception))

    def test_no_api_key(self):
        client = DeepSeekClient("", base_url=self.base)
        self.assertFalse(client.available)
        with self.assertRaises(DeepSeekError):
            client.search("x")


class ScirateFetchFallbackTest(unittest.TestCase):
    def test_uses_deepseek_fetch_when_direct_blocked(self):
        markdown = (FIXTURES / "scirate_sample.md").read_text(encoding="utf-8")

        def fake_fetch(url: str) -> dict:
            self.assertIn("scirate.com/quant-ph", url)
            return {"title": "Top arXiv papers", "content": markdown}

        papers, channel = get_scirate_papers(
            feed="quant-ph", top_n=3, timeout=5, fetch_fn=fake_fetch
        )
        self.assertEqual(channel, "deepseek_fetch")
        self.assertEqual(len(papers), 3)
        self.assertEqual(papers[0].scirate_rank, 1)
        self.assertEqual(papers[0].arxiv_id, "2610.22476")
        self.assertEqual(papers[0].title, "Typical Superpositions are Magical")
        self.assertEqual(papers[0].url, "https://arxiv.org/abs/2610.22476")


class LLMScoreTest(unittest.TestCase):
    def test_score_papers_applies_scores(self):
        client = DeepSeekClient("sk-test", base_url="http://127.0.0.1:9", timeout=5)

        captured = {}

        def fake_chat(messages, temperature=0.2, max_tokens=3000, json_mode=True):
            captured["messages"] = messages
            return json.dumps(
                {
                    "papers": [
                        {"id": 1, "score": 9.0, "reason": "直接相关 QRC，方法清晰", "tags": ["QRC"]},
                        {"id": 2, "score": 4.0, "reason": "弱相关", "tags": ["其他"]},
                    ]
                },
                ensure_ascii=False,
            )

        client.chat = fake_chat  # type: ignore[method-assign]
        papers = [
            Paper(title="QRC paper", arxiv_id="2610.00001", abstract="quantum reservoir computing"),
            Paper(title="Other paper", arxiv_id="2610.00002", abstract="cosmology"),
        ]
        ok = score_papers(client, papers, "量子储备池计算", __import__("datetime").date(2026, 10, 20))
        self.assertTrue(ok)
        self.assertEqual(papers[0].llm_score, 9.0)
        self.assertEqual(papers[0].llm_reason, "直接相关 QRC，方法清晰")
        self.assertEqual(papers[0].tags, ["QRC"])
        self.assertEqual(papers[1].llm_score, 4.0)
        # prompt 里应包含关注方向与候选标题
        prompt = captured["messages"][-1]["content"]
        self.assertIn("量子储备池计算", prompt)
        self.assertIn("QRC paper", prompt)

    def test_extract_json_variants(self):
        self.assertEqual(extract_json('{"a": 1}'), {"a": 1})
        self.assertEqual(extract_json('```json\n{"a": 1}\n```'), {"a": 1})
        self.assertEqual(extract_json('前面废话 {"a": 1} 后面废话'), {"a": 1})
        with self.assertRaises(ValueError):
            extract_json("完全不是 JSON")


if __name__ == "__main__":
    unittest.main(verbosity=2)
