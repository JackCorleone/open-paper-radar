"""端到端集成测试：mock 掉外部网络，验证 run() 全流程。

覆盖：Scirate 直连解析 → arXiv 合并 → DeepSeek Chat 打分 → 渲染 → 落盘。
不覆盖真实 API（那需要真实 Key），但能保证编排逻辑与数据流正确。
"""

from __future__ import annotations

import argparse
import json
import sys
import tempfile
import threading
import unittest
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from paper_radar.__main__ import run  # noqa: E402
from paper_radar.config import Config  # noqa: E402
from paper_radar.models import Paper  # noqa: E402

FIXTURES = ROOT / "tests" / "fixtures"


class _Handler(BaseHTTPRequestHandler):
    def log_message(self, *args) -> None:  # noqa: D102
        pass

    def do_POST(self) -> None:  # noqa: N802
        length = int(self.headers.get("Content-Length") or 0)
        body = json.loads(self.rfile.read(length) or b"{}")
        if self.path == "/v1/tools/search":
            payload = {
                "results": [
                    {
                        "title": "A Web Signal about Quantum Reservoir Computing",
                        "url": "https://example.com/qrc-blog",
                        "summary": "A blog post discussing quantum reservoir computing experiments.",
                        "rerank_score": 2.6,
                        "authority": 2,
                        "date": "2026-10-19T00:00:00+00:00",
                        "site_name": "Example Blog",
                    }
                ]
            }
        elif self.path == "/v1/chat/completions":
            last = ""
            try:
                last = body["messages"][-1]["content"]
            except (KeyError, IndexError, TypeError):
                pass
            if "深度解读" in last or "核心方法或创新" in last:
                deep = {
                    "title_zh": "测试论文的中文标题",
                    "abstract_zh": "这是摘要的中文翻译。",
                    "problem": "主要解决的问题。",
                    "method": "① **方法一**：细节展开。\n② **方法二**：细节展开。",
                    "results": "① 关键结果 $O(\\sqrt{N})$。",
                }
                payload = {"choices": [{"message": {"content": json.dumps(deep, ensure_ascii=False)}}]}
            else:
                items = [
                {"id": 1, "score": 9.2, "reason": "直接研究量子储备池的记忆容量上界", "tags": ["QRC", "noise"]},
                {"id": 2, "score": 7.8, "reason": "量子核方法的表达力分析，对 QRC 特征映射有参考价值", "tags": ["kernel"]},
                {"id": 3, "score": 3.0, "reason": "纯宇宙学，与关注方向无关", "tags": ["cosmology"]},
                {"id": 4, "score": 8.6, "reason": "噪声下量子储备池记忆容量的理论上界，与主线高度相关", "tags": ["QRC"]},
                {"id": 5, "score": 7.2, "reason": "量子核表达力分析，对特征映射设计有启发", "tags": ["kernel"]},
                {"id": 6, "score": 2.5, "reason": "与关注方向无关", "tags": ["cosmology"]},
                {"id": 7, "score": 6.8, "reason": "量子机器学习的实验进展，可作参考", "tags": ["QML"]},
                ]
                payload = {"choices": [{"message": {"content": json.dumps({"papers": items}, ensure_ascii=False)}}]}
        else:
            payload = {"error": {"message": "not found"}}
        data = json.dumps(payload).encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)


class PipelineTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.server = HTTPServer(("127.0.0.1", 0), _Handler)
        cls.port = cls.server.server_address[1]
        threading.Thread(target=cls.server.serve_forever, daemon=True).start()

    @classmethod
    def tearDownClass(cls) -> None:
        cls.server.shutdown()
        cls.server.server_close()

    def test_full_run_generates_report(self):
        scirate_html = (FIXTURES / "scirate_sample.html").read_text(encoding="utf-8")
        arxiv_papers = [
            Paper(title="The Fundamental Memory Ceiling of Noisy Quantum Reservoirs",
                  arxiv_id="2610.26228", source="arxiv",
                  abstract="We study quantum reservoir computing and derive a memory ceiling under noise.",
                  authors=["Alice", "Bob"]),
            Paper(title="Quantum Kernel Expressivity via Reproducing Kernel Hilbert Spaces",
                  arxiv_id="2610.23692", source="arxiv",
                  abstract="Expressivity of IQP feature-map quantum kernels.",
                  authors=["Carol"]),
            Paper(title="Cosmological Constraints from the Early Universe",
                  arxiv_id="2610.11111", source="arxiv",
                  abstract="We constrain cosmological parameters.",
                  authors=["Dave"]),
        ]
        topics = json.loads((ROOT / "config" / "topics.json").read_text(encoding="utf-8"))
        # 缩短检索词，减少网络请求
        topics["search"]["queries"] = [{"name": "QRC", "query": "quantum reservoir computing", "count": 5}]

        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            cfg = Config(
                root=tmp_path,
                topics=topics,
                config_path=ROOT / "config" / "topics.json",
                api_key="sk-test",
                base_url=f"http://127.0.0.1:{self.port}",
                state_file=tmp_path / "seen.json",
                reports_dir=tmp_path / "reports",
            )
            args = argparse.Namespace(
                command="run", config=None, date="2026-10-20", dry_run=True,
                no_llm=False, no_notify=True, no_state=True, no_deep_dive=True, verbose=False,
            )
            with mock.patch(
                "paper_radar.sources.scirate.fetch_direct", return_value=scirate_html
            ), mock.patch(
                "paper_radar.sources.arxiv.get_arxiv_papers", return_value=arxiv_papers
            ):
                code = run(cfg, args)

            self.assertEqual(code, 0)
            report = tmp_path / "reports" / "2026-10-20.md"
            self.assertTrue(report.exists(), "日报未生成")
            content = report.read_text(encoding="utf-8")
            # Scirate 热榜按票数排序
            self.assertIn("Scirate 今日热榜", content)
            self.assertIn("Typical Superpositions are Magical", content)
            self.assertIn("Quantum Reservoir Computing with Dissipative Spin Networks", content)
            # LLM 理由写进了日报
            self.assertIn("记忆容量上界", content)
            # 高分新论文进入精选，无关论文不出现
            self.assertIn("## 🎯 今日精选", content)
            highlight_section = content.split("## 🎯 今日精选")[1].split("##")[0]
            self.assertNotIn("Cosmological Constraints", highlight_section)
            # arXiv 论文被合并
            self.assertIn("The Fundamental Memory Ceiling", content)


    def test_deep_dive_appears_in_report(self):
        """深度解读链路：全文解析 + LLM 三段式 + 报告模板。"""
        from paper_radar.sources.fulltext import parse_arxiv_html

        scirate_html = (FIXTURES / "scirate_sample.html").read_text(encoding="utf-8")
        fulltext_html = (FIXTURES / "arxiv_fulltext_sample.html").read_text(encoding="utf-8")
        fulltext_obj = parse_arxiv_html(fulltext_html)
        fulltext_obj.arxiv_id = "2610.22476"
        fulltext_obj.source = "arxiv_html"

        arxiv_papers = [
            Paper(title="Quantum Reservoir Computing with Dissipative Spin Networks",
                  arxiv_id="2610.22111", source="arxiv",
                  abstract="reservoir computing with spins", authors=["Wei Chen"]),
        ]
        topics = json.loads((ROOT / "config" / "topics.json").read_text(encoding="utf-8"))
        topics["search"]["queries"] = [{"name": "QRC", "query": "quantum reservoir computing", "count": 5}]
        topics["deep_dive"]["per_direction"] = {"QRC": {"top_n": 1, "min_llm_score": 0}}

        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            cfg = Config(
                root=tmp_path,
                topics=topics,
                config_path=ROOT / "config" / "topics.json",
                api_key="sk-test",
                base_url=f"http://127.0.0.1:{self.port}",
                state_file=tmp_path / "seen.json",
                reports_dir=tmp_path / "reports",
            )
            args = argparse.Namespace(
                command="run", config=None, date="2026-10-20", dry_run=True,
                no_llm=False, no_notify=True, no_state=True, no_deep_dive=False, verbose=False,
            )
            with mock.patch(
                "paper_radar.sources.scirate.fetch_direct", return_value=scirate_html
            ), mock.patch(
                "paper_radar.sources.arxiv.get_arxiv_papers", return_value=arxiv_papers
            ), mock.patch(
                "paper_radar.sources.fulltext.fetch_fulltext", return_value=fulltext_obj
            ):
                code = run(cfg, args)

            self.assertEqual(code, 0)
            content = (tmp_path / "reports" / "2026-10-20.md").read_text(encoding="utf-8")
            self.assertIn("## 📖 重点论文深度解读", content)
            self.assertIn("**中文标题**：测试论文的中文标题", content)
            self.assertIn("| 作者 | 论文署名机构 |", content)
            self.assertIn("| Songyao Xue | School of Software；Luoyang Normal University", content)
            self.assertIn("**1. 主要解决的问题**", content)
            self.assertIn("**2. 核心方法或创新**", content)
            self.assertIn("**3. 值得关注的结果或意义**", content)
            self.assertIn("[arXiv DOI](https://doi.org/10.48550/arXiv.", content)


if __name__ == "__main__":
    unittest.main(verbosity=2)
