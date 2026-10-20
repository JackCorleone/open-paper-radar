"""解析器与核心逻辑的单元测试。

运行：cd paper-radar && PYTHONPATH=src python3 -m unittest discover -s tests -v
"""

from __future__ import annotations

import json
import os
import sys
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from paper_radar.models import Paper, normalize_arxiv_id, normalize_title  # noqa: E402
from paper_radar.rank import (  # noqa: E402
    ai_hot,
    final_rank,
    merge_papers,
    prefilter,
    relevance_score,
    tag_directions,
)
from paper_radar.render import (  # noqa: E402
    latex_to_plain,
    render_markdown,
    render_wechat,
    render_wechat_html,
)
from paper_radar.sources.arxiv import _parse_atom, _parse_list_html  # noqa: E402
from paper_radar.sources.scirate import parse_scirate_html, parse_scirate_markdown  # noqa: E402

FIXTURES = ROOT / "tests" / "fixtures"


def read_fixture(name: str) -> str:
    return (FIXTURES / name).read_text(encoding="utf-8")


class TestModels(unittest.TestCase):
    def test_normalize_arxiv_id(self):
        self.assertEqual(normalize_arxiv_id("http://arxiv.org/abs/2610.22476v1"), "2610.22476")
        self.assertEqual(normalize_arxiv_id("https://scirate.com/arxiv/2610.22476"), "2610.22476")
        self.assertEqual(normalize_arxiv_id("quant-ph/0501001v2"), "quant-ph/0501001")
        self.assertIsNone(normalize_arxiv_id("https://example.com/blog"))

    def test_normalize_title(self):
        self.assertEqual(normalize_title("A: B-C!"), normalize_title("a b c"))

    def test_dedup_key_prefers_arxiv_id(self):
        a = Paper(title="X", arxiv_id="2610.22476", source="arxiv")
        b = Paper(title="Totally Different", url="https://arxiv.org/abs/2610.22476v3", source="scirate")
        self.assertEqual(a.dedup_key, b.dedup_key)


class TestScirateParser(unittest.TestCase):
    def test_parse_html(self):
        rows = parse_scirate_html(read_fixture("scirate_sample.html"))
        self.assertEqual(len(rows), 3)
        first = rows[0]
        self.assertEqual(first["title"], "Typical Superpositions are Magical")
        self.assertIn("/arxiv/2610.22476", first["url"])
        self.assertEqual(first["scites"], 12)
        self.assertIn("2610.22476", first["uid_text"])
        self.assertIn("Joshuah T. Heath", first["owners"])

    def test_parse_html_order(self):
        rows = parse_scirate_html(read_fixture("scirate_sample.html"))
        self.assertEqual([r["scites"] for r in rows], [12, 7, 3])

    def test_parse_markdown(self):
        rows = parse_scirate_markdown(read_fixture("scirate_sample.md"))
        self.assertEqual(len(rows), 3)
        self.assertEqual(rows[0]["title"], "Typical Superpositions are Magical")
        self.assertIn("2610.22476", rows[0]["url"])
        self.assertEqual(
            [r["url"] for r in rows],
            [
                "https://scirate.com/arxiv/2610.22476",
                "https://scirate.com/arxiv/2610.22111",
                "https://scirate.com/arxiv/2610.19987",
            ],
        )


class TestArxivParser(unittest.TestCase):
    def test_parse_atom_filters_old(self):
        papers = _parse_atom(read_fixture("arxiv_atom_sample.xml"), lookback_hours=72)
        ids = [p.arxiv_id for p in papers]
        self.assertIn("2610.22476", ids)
        self.assertNotIn("2401.00001", ids)  # 太旧的被过滤
        first = next(p for p in papers if p.arxiv_id == "2610.22476")
        self.assertEqual(first.title, "Typical Superpositions are Magical")
        self.assertEqual(len(first.authors), 4)
        self.assertIn("stabilizer", first.abstract)

    def test_parse_list_html(self):
        papers = _parse_list_html(read_fixture("arxiv_list_sample.html"), lookback_hours=72)
        self.assertEqual(len(papers), 3)
        self.assertEqual(papers[0].title, "Typical Superpositions are Magical")
        self.assertEqual(papers[0].arxiv_id, "2610.22476")
        self.assertTrue(papers[0].authors)
        self.assertTrue(papers[0].abstract)


class TestRank(unittest.TestCase):
    def _papers(self):
        now = datetime.now(timezone.utc)
        return [
            Paper(title="QRC paper A", arxiv_id="2610.00001", source="scirate",
                  scirate_rank=1, scites=20, abstract="quantum reservoir computing",
                  published=now - timedelta(hours=5)),
            Paper(title="QRC paper B", arxiv_id="2610.00002", source="arxiv",
                  abstract="reservoir computing with spins", published=now - timedelta(hours=6)),
            Paper(title="Unrelated paper", arxiv_id="2610.00003", source="arxiv",
                  abstract="cosmology of the early universe", published=now - timedelta(hours=6)),
            Paper(title="Search hit", url="https://example.com/blog", source="search",
                  search_score=2.5, published=now - timedelta(hours=3)),
        ]

    def test_merge_dedup(self):
        a = Paper(title="Same", arxiv_id="2610.00009", source="arxiv")
        b = Paper(title="Same", url="https://arxiv.org/abs/2610.00009v2", source="scirate", scites=5)
        merged = merge_papers([[a], [b]])
        self.assertEqual(len(merged), 1)
        self.assertEqual(merged[0].scites, 5)
        self.assertEqual(merged[0].sources, {"arxiv", "scirate"})

    def test_prefilter_keeps_scirate(self):
        papers = self._papers() + [Paper(title=f"filler {i}", arxiv_id=f"2610.1{i:04d}", source="arxiv")
                                   for i in range(50)]
        picked = prefilter(papers, {"core_any": ["reservoir computing"]}, max_candidates=5, scirate_top_n=10)
        self.assertTrue(any(p.scirate_rank == 1 for p in picked))
        self.assertEqual(len(picked), 5)

    def test_ai_hot_sorts_by_llm_score(self):
        papers = [
            Paper(title=f"P{i}", arxiv_id=f"2610.1000{i}", llm_score=float(i)) for i in range(1, 6)
        ]
        hot = ai_hot(papers, top_n=3)
        self.assertEqual([p.title for p in hot], ["P5", "P4", "P3"])
        self.assertEqual([p.scirate_rank for p in hot], [1, 2, 3])
        self.assertTrue(all(p.scites == 0 for p in hot))

    def test_ai_hot_ignores_unscored(self):
        papers = [Paper(title="No score", arxiv_id="2610.20001"),
                  Paper(title="Scored", arxiv_id="2610.20002", llm_score=6.0)]
        hot = ai_hot(papers, top_n=5)
        self.assertEqual([p.title for p in hot], ["Scored"])

    def test_final_rank_groups(self):
        papers = self._papers()
        for p in papers:
            p.llm_score = 8.0 if "QRC" in p.title else 3.0
            p.llm_reason = "理由"
        groups = final_rank(papers, papers, {"core_any": ["reservoir computing"]},
                            max_items=10, scirate_top_n=10)
        self.assertEqual(len(groups["scirate_hot"]), 1)
        self.assertTrue(any(p.title == "QRC paper B" for p in groups["highlights"]))
        self.assertTrue(all(p.llm_score >= 6.5 for p in groups["highlights"]))


class TestDirectionsAndPriority(unittest.TestCase):
    KEYWORDS = {
        "priority_any": ["quantum query complexity", "near-optimal quantum"],
        "core_any": ["quantum algorithm", "quantum simulation"],
        "adjacent_any": ["quantum advantage", "entanglement"],
    }
    DIRECTIONS = [
        {"name": "QRC", "any": ["quantum reservoir", "reservoir computing"]},
        {"name": "量子算法", "any": ["quantum algorithm", "quantum query complexity"]},
    ]

    def test_priority_beats_adjacent(self):
        # 命中 priority 的近最优量子算法论文
        priority_paper = Paper(
            title="Near-optimal quantum algorithms for Hamiltonian simulation",
            abstract="We achieve the optimal query complexity for simulating sparse Hamiltonians.",
        )
        # 只命中宣传性热词 adjacent 的论文
        noise_paper = Paper(
            title="Quantum advantage in a photonic platform",
            abstract="We claim a quantum advantage using entanglement.",
        )
        self.assertGreater(
            relevance_score(priority_paper, self.KEYWORDS),
            relevance_score(noise_paper, self.KEYWORDS),
        )
        self.assertGreaterEqual(relevance_score(priority_paper, self.KEYWORDS), 3.0)

    def test_priority_capped_at_five(self):
        paper = Paper(
            title="Near-optimal quantum algorithm with quantum query complexity lower bound",
            abstract="quantum algorithm quantum simulation",
        )
        self.assertLessEqual(relevance_score(paper, self.KEYWORDS), 5.0)

    def test_tag_directions(self):
        qrc = Paper(title="Quantum reservoir computing with spins", abstract="reservoir computing")
        algo = Paper(title="Optimal quantum algorithms for linear systems", abstract="query complexity")
        other = Paper(title="Cosmological constant", abstract="cosmology")
        papers = [qrc, algo, other]
        tag_directions(papers, self.DIRECTIONS)
        self.assertEqual(qrc.direction, "QRC")
        self.assertEqual(algo.direction, "量子算法")
        self.assertEqual(other.direction, "")

    def test_llm_prompt_contains_both_directions(self):
        from paper_radar.llm import build_user_prompt
        from datetime import date

        prompt = build_user_prompt([Paper(title="X", abstract="Y")], "QRC 与量子算法（近最优优先）", date(2026, 10, 20))
        self.assertIn("量子算法", prompt)
        self.assertIn("QRC", prompt)


class TestRender(unittest.TestCase):
    def _ctx(self):
        now = datetime.now(timezone.utc)
        hot = [Paper(title="Hot paper", arxiv_id="2610.00001", source="scirate",
                     scirate_rank=1, scites=12, llm_score=9.0, llm_reason="值得读",
                     tags=["QRC"], published=now, authors=["A", "B"], direction="量子算法")]
        hl = [Paper(title="Highlight paper", arxiv_id="2610.00002", source="arxiv",
                    llm_score=8.0, llm_reason="有启发", published=now, authors=["C"])]
        return {
            "date": now.date(),
            "title": "量子论文雷达",
            "subtitle": "测试",
            "scan": [{"name": "arXiv quant-ph", "ok": True, "status": "", "count": "134 篇"}],
            "new_count": 2,
            "candidate_count": 2,
            "llm_calls": 1,
            "warnings": [],
            "scirate_hot": hot,
            "highlights": hl,
            "worth_scanning": [],
            "generated_at": "2026-10-20 08:30",
            "stats_line": "扫描 2 篇",
        }

    def test_markdown(self):
        md = render_markdown(self._ctx())
        self.assertIn("量子论文雷达", md)
        self.assertIn("Scirate 今日热榜", md)
        self.assertIn("[Hot paper](https://arxiv.org/abs/2610.00001)", md)
        self.assertIn("值得读", md)
        self.assertIn("`量子算法`", md)

    def test_wechat_contains_links(self):
        text = render_wechat(self._ctx())
        self.assertIn("Scirate 热榜", text)
        self.assertIn("https://arxiv.org/abs/2610.00001", text)
        self.assertLess(len(text), 4000)

    def test_wechat_html_has_breaks_and_links(self):
        ctx = self._ctx()
        ctx["hot_source"] = "ai"
        out = render_wechat_html(ctx)
        self.assertIn("<br>", out)
        self.assertIn('<a href="https://arxiv.org/abs/2610.00001">', out)
        self.assertIn("今日热榜（AI 排序）", out)
        # 标题里的尖括号要转义
        self.assertNotIn("<script>", out)

    def test_wechat_html_escapes_and_converts_latex(self):
        ctx = self._ctx()
        ctx["highlights"][0].llm_reason = "复杂度为 $O(\\sqrt{N})$，用 $\\mathcal{D}_q^{\\otimes n}$ 噪声"
        out = render_wechat_html(ctx)
        self.assertIn("√N", out)
        self.assertIn("⊗", out)
        self.assertNotIn("$", out)

    def test_latex_to_plain(self):
        self.assertEqual(latex_to_plain("$O(\\sqrt{N})$"), "O(√N)")
        self.assertIn("≤", latex_to_plain("$L \\leq K$"))
        self.assertIn("⊗", latex_to_plain("$D^{\\otimes n}$"))
        self.assertEqual(latex_to_plain("no math"), "no math")

    def test_latex_mathcal_and_ket(self):
        # 之前显示成 mathcalN_q 的写法
        out = latex_to_plain("$\\Phi_u = \\mathcal{N}_q \\circ \\mathcal{E}_u$")
        self.assertNotIn("mathcal", out)
        self.assertIn("∘", out)
        self.assertIn("N_q", out)
        self.assertIn("⟩", latex_to_plain("$|0\\rangle$"))

    def test_md_inline_to_html(self):
        from paper_radar.render import _md_inline_to_html

        out = _md_inline_to_html("① **核心上界证明**：利用 $\\mathcal{N}_q$\n② 第二步")
        self.assertIn("<b>核心上界证明</b>", out)
        self.assertIn("<br>②", out)
        self.assertNotIn("mathcal", out)

    def test_wechat_empty(self):
        ctx = self._ctx()
        ctx.update({"scirate_hot": [], "highlights": [], "worth_scanning": []})
        text = render_wechat(ctx)
        self.assertIn("没有新的相关论文", text)


if __name__ == "__main__":
    unittest.main(verbosity=2)
