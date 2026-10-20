"""深度解读链路测试：全文解析、prompt 构建、LLM 输出解析、报告渲染。"""

from __future__ import annotations

import json
import sys
import unittest
from datetime import date, datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from paper_radar.deep_dive import (  # noqa: E402
    build_user_prompt,
    deep_dive,
    select_deep_dive,
)
from paper_radar.deepseek import DeepSeekClient  # noqa: E402
from paper_radar.models import Paper  # noqa: E402
from paper_radar.render import render_markdown, render_wechat  # noqa: E402
from paper_radar.sources.fulltext import parse_arxiv_html  # noqa: E402

FIXTURES = ROOT / "tests" / "fixtures"


class FullTextParseTest(unittest.TestCase):
    def setUp(self):
        html = (FIXTURES / "arxiv_fulltext_sample.html").read_text(encoding="utf-8")
        self.ft = parse_arxiv_html(html)

    def test_title_and_math(self):
        self.assertIn("Exact Quantum Query Complexity", self.ft.title)
        self.assertIn(r"$\Exact^{5}_{3,4}$", self.ft.title)
        self.assertNotIn("Thanks", self.ft.title)  # 脚注被去掉

    def test_authors_and_affiliations(self):
        names = [a["name"] for a in self.ft.authors]
        self.assertEqual(names, ["Guoliang Xu", "Songyao Xue"])
        xue = self.ft.authors[1]
        self.assertEqual(
            xue["affiliations"],
            ["School of Software", "Luoyang Normal University", "Luoyang 471934, China"],
        )

    def test_abstract_clean(self):
        self.assertIn(r"$f=\text{EXACT}^{5}_{3,4}$", self.ft.abstract)
        self.assertFalse(self.ft.abstract.startswith("Abstract"))

    def test_sections_skip_references(self):
        headings = [s["heading"] for s in self.ft.sections]
        self.assertEqual(headings, ["1 Introduction", "2 Main Theorem", "3 Conclusion"])
        self.assertTrue(self.ft.has_body)

    def test_prompt_text_contains_sections(self):
        text = self.ft.to_prompt_text(max_chars=5000)
        self.assertIn("【摘要】", text)
        self.assertIn("【1 Introduction】", text)
        self.assertLessEqual(len(text), 5000)


class DeepDiveLLMTest(unittest.TestCase):
    def _paper(self):
        return Paper(
            title="Exact Quantum Query Complexity of a Symmetric Boolean Function",
            arxiv_id="2610.24518",
            abstract="We prove the exact query complexity is four.",
            authors=["Guoliang Xu", "Songyao Xue"],
            llm_score=8.6,
            source="arxiv",
            direction="量子算法",
        )

    def test_prompt_contains_paper_and_focus(self):
        ft = parse_arxiv_html((FIXTURES / "arxiv_fulltext_sample.html").read_text(encoding="utf-8"))
        prompt = build_user_prompt(self._paper(), ft, "近最优量子算法", 20000)
        self.assertIn("Exact Quantum Query Complexity", prompt)
        self.assertIn("近最优量子算法", prompt)
        self.assertIn("1 Introduction", prompt)
        self.assertIn("论文全文", prompt)

    def test_parse_llm_output(self):
        client = DeepSeekClient("sk-test", base_url="http://127.0.0.1:9", timeout=5)
        payload = {
            "title_zh": "对称布尔函数的精确量子查询复杂度",
            "abstract_zh": "我们证明该函数的精确量子查询复杂度为 4。",
            "problem": "三查询算法是否存在长期未决。",
            "method": "① **Fourier–Gram 层分解**：把每个三查询算法写成低阶 Fourier 系数的 Gram 矩阵。\n② **有理对偶证书**：构造固定有理证书排除三查询。",
            "results": "证明精确量子查询复杂度为 4；\n\n| 查询数 | 是否可行 |\n| --- | --- |\n| 3 | 否 |\n| 4 | 是 |",
        }

        def fake_chat(messages, temperature=0.3, max_tokens=3200, json_mode=True):
            return json.dumps(payload, ensure_ascii=False)

        client.chat = fake_chat  # type: ignore[method-assign]
        ft = parse_arxiv_html((FIXTURES / "arxiv_fulltext_sample.html").read_text(encoding="utf-8"))
        result = deep_dive(client, self._paper(), ft, focus="近最优量子算法")
        self.assertIsNotNone(result)
        assert result is not None
        self.assertEqual(result["title_zh"], "对称布尔函数的精确量子查询复杂度")
        self.assertIn("Fourier", result["method"])
        self.assertEqual(result["based_on"], "fulltext")
        # 作者机构来自全文解析而非模型生成
        self.assertEqual(result["authors"][1]["name"], "Songyao Xue")
        self.assertIn("Luoyang Normal University", result["authors"][1]["affiliations"])

    def test_llm_garbage_returns_none(self):
        client = DeepSeekClient("sk-test", base_url="http://127.0.0.1:9", timeout=5)
        client.chat = lambda *a, **k: "抱歉，我无法完成"  # type: ignore[method-assign]
        result = deep_dive(client, self._paper(), None, focus="x")
        self.assertIsNone(result)

    def _papers(self):
        return [
            Paper(title="QRC-1", arxiv_id="2610.00001", llm_score=8.0, direction="QRC"),
            Paper(title="QRC-2", arxiv_id="2610.00002", llm_score=7.0, direction="QRC"),
            Paper(title="QRC-3", arxiv_id="2610.00003", llm_score=6.8, direction="QRC"),
            Paper(title="QRC-low", arxiv_id="2610.00004", llm_score=6.0, direction="QRC"),
            Paper(title="ALGO-1", arxiv_id="2610.00011", llm_score=9.0, direction="量子算法"),
            Paper(title="ALGO-2", arxiv_id="2610.00012", llm_score=8.5, direction="量子算法"),
            Paper(title="ALGO-3", arxiv_id="2610.00013", llm_score=8.0, direction="量子算法"),
            Paper(title="ALGO-4", arxiv_id="2610.00014", llm_score=7.5, direction="量子算法"),
            Paper(title="ALGO-5", arxiv_id="2610.00015", llm_score=7.2, direction="量子算法"),
            Paper(title="ALGO-6", arxiv_id="2610.00016", llm_score=6.0, direction="量子算法"),
            Paper(title="UNTAGGED", arxiv_id="2610.00021", llm_score=7.5, direction=""),
            Paper(title="NO-ID", arxiv_id=None, llm_score=9.9, direction="QRC"),
        ]

    def test_select_deep_dive_by_direction(self):
        picked = select_deep_dive(
            self._papers(),
            per_direction={
                "QRC": {"top_n": 2, "min_llm_score": 6.5},
                "量子算法": {"top_n": 3, "min_llm_score": 7.0},
            },
        )
        titles = [p.title for p in picked]
        self.assertEqual(titles, ["QRC-1", "QRC-2", "ALGO-1", "ALGO-2", "ALGO-3"])
        self.assertEqual(sum(1 for p in picked if p.direction == "QRC"), 2)
        self.assertEqual(sum(1 for p in picked if p.direction == "量子算法"), 3)
        self.assertNotIn("NO-ID", titles)  # 没有 arXiv ID 的不能深度解读

    def test_select_deep_dive_fills_with_untagged(self):
        # 去掉所有 QRC 方向论文，只剩量子算法方向 + 一个未标方向的
        papers = [p for p in self._papers() if p.direction != "QRC"]
        picked = select_deep_dive(
            papers,
            per_direction={"QRC": {"top_n": 2, "min_llm_score": 6.5}},
        )
        self.assertEqual([p.title for p in picked], ["UNTAGGED"])


class DeepDiveRenderTest(unittest.TestCase):
    def _paper(self):
        now = datetime.now(timezone.utc)
        paper = Paper(
            title="Exact Quantum Query Complexity of a Symmetric Boolean Function",
            arxiv_id="2610.24518",
            source="arxiv",
            authors=["Guoliang Xu", "Songyao Xue"],
            llm_score=8.6,
            llm_reason="紧确界结果",
            direction="量子算法",
            published=now,
        )
        paper.deep_dive = {
            "title_zh": "对称布尔函数的精确量子查询复杂度",
            "abstract_zh": "我们证明该函数的精确量子查询复杂度为 4。",
            "problem": "三查询算法是否存在长期未决。",
            "method": "① **Fourier–Gram 层分解**：把每个三查询算法写成低阶 Fourier 系数的 Gram 矩阵。",
            "results": "证明精确量子查询复杂度为 4。",
            "based_on": "fulltext",
            "authors": [
                {"name": "Guoliang Xu", "affiliations": []},
                {"name": "Songyao Xue", "affiliations": ["Luoyang Normal University"]},
            ],
        }
        return paper

    def _ctx(self, paper):
        return {
            "date": date(2026, 10, 20),
            "title": "量子论文雷达",
            "subtitle": "QRC · 量子算法",
            "scan": [],
            "new_count": 1,
            "candidate_count": 1,
            "llm_calls": 2,
            "warnings": [],
            "scirate_hot": [],
            "deep_dives": [paper],
            "highlights": [],
            "worth_scanning": [],
            "generated_at": "2026-10-20 09:30",
            "stats_line": "扫描 1 篇",
        }

    def test_markdown_template(self):
        md = render_markdown(self._ctx(self._paper()))
        for expected in (
            "## 📖 重点论文深度解读",
            "### 1. Exact Quantum Query Complexity",
            "**中文标题**：对称布尔函数的精确量子查询复杂度",
            "| 作者 | 论文署名机构 |",
            "| Songyao Xue | Luoyang Normal University |",
            "[SciRate](https://scirate.com/arxiv/2610.24518)",
            "[全文](https://arxiv.org/pdf/2610.24518)",
            "[arXiv DOI](https://doi.org/10.48550/arXiv.2610.24518)",
            "**摘要中文翻译**",
            "**1. 主要解决的问题**",
            "**2. 核心方法或创新**",
            "**3. 值得关注的结果或意义**",
        ):
            self.assertIn(expected, md, f"缺少：{expected}")

    def test_wechat_contains_three_parts(self):
        text = render_wechat(self._ctx(self._paper()))
        self.assertIn("📖 重点论文深度解读", text)
        self.assertIn("▸ 解决：", text)
        self.assertIn("▸ 方法：", text)
        self.assertIn("▸ 结果：", text)
        self.assertIn("https://arxiv.org/abs/2610.24518", text)


if __name__ == "__main__":
    unittest.main(verbosity=2)
