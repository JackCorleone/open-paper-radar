"""日报渲染：完整 Markdown 版 + 微信推送精简版。"""

from __future__ import annotations

import html as html_lib
import re
from datetime import date
from typing import Optional

from .models import Paper
from .util import truncate

WEEKDAYS = ["周一", "周二", "周三", "周四", "周五", "周六", "周日"]


def _authors(paper: Paper, limit: int = 3) -> str:
    names = [a for a in paper.authors if a]
    if not names:
        return ""
    if len(names) <= limit:
        return "、".join(names)
    return "、".join(names[:limit]) + " 等"


def _source_label(paper: Paper) -> str:
    labels = []
    if "scirate" in paper.sources:
        labels.append("Scirate")
    if "arxiv" in paper.sources:
        labels.append("arXiv")
    if "search" in paper.sources:
        labels.append("网页搜索")
    return " · ".join(labels) or "未知来源"


def _paper_block_md(index: int, paper: Paper, show_rank: bool = False) -> str:
    lines: list[str] = []
    title = paper.title.strip()
    url = paper.url
    meta_bits: list[str] = []
    if paper.direction:
        meta_bits.append(f"`{paper.direction}`")
    if show_rank:
        meta_bits.append(f"#{index}")
    if paper.scites:
        meta_bits.append(f"⬆ {paper.scites} scites")
    if paper.llm_score is not None:
        meta_bits.append(f"AI {paper.llm_score:.1f}/10")
    if paper.published:
        meta_bits.append(paper.published.astimezone().strftime("%m-%d"))
    meta = " · ".join(meta_bits)

    lines.append(f"{index}. **[{title}]({url})**")
    if meta:
        lines.append(f"   {meta}")
    authors = _authors(paper)
    if authors:
        lines.append(f"   作者：{authors}")
    if paper.deep_dive:
        lines.append("   📖 见下方「重点论文深度解读」")
    if paper.llm_reason:
        lines.append(f"   > 💡 {paper.llm_reason}")
    elif paper.abstract:
        lines.append(f"   > {truncate(paper.abstract, 160)}")
    if paper.tags:
        tags = " ".join(f"`{t}`" for t in paper.tags[:4])
        lines.append(f"   {tags}")
    if not paper.arxiv_id and paper.venue:
        lines.append(f"   来源：{paper.venue}")
    return "\n".join(lines)


def _arxiv_links(arxiv_id: str) -> str:
    return " · ".join(
        [
            f"[SciRate](https://scirate.com/arxiv/{arxiv_id})",
            f"[arXiv](https://arxiv.org/abs/{arxiv_id})",
            f"[全文](https://arxiv.org/pdf/{arxiv_id})",
            f"[arXiv DOI](https://doi.org/10.48550/arXiv.{arxiv_id})",
        ]
    )


def _render_deep_dive_md(index: int, paper: Paper, level: int = 4) -> str:
    """按简报模板渲染一篇深度解读。"""
    dd = paper.deep_dive or {}
    lines: list[str] = [f"{'#' * level} {index}. {paper.title}", ""]

    if dd.get("title_zh"):
        lines.append(f"**中文标题**：{dd['title_zh']}")
        lines.append("")

    authors = dd.get("authors") or []
    if authors:
        lines.append("**作者与机构**")
        lines.append("")
        lines.append("| 作者 | 论文署名机构 |")
        lines.append("| --- | --- |")
        for author in authors:
            name = str(author.get("name") or "").replace("|", "/")
            affs = author.get("affiliations") or []
            aff = (
                "；".join(re.sub(r"\s+", " ", str(a)).strip() for a in affs).replace("|", "/")
                if affs else "—"
            )
            lines.append(f"| {name} | {aff} |")
        lines.append("")

    if paper.arxiv_id:
        lines.append("**链接**：" + _arxiv_links(paper.arxiv_id))
        lines.append("")

    if dd.get("abstract_zh"):
        lines.append("**摘要中文翻译**")
        lines.append("")
        lines.append(str(dd["abstract_zh"]))
        lines.append("")

    for label, key in (
        ("1. 主要解决的问题", "problem"),
        ("2. 核心方法或创新", "method"),
        ("3. 值得关注的结果或意义", "results"),
    ):
        value = dd.get(key)
        if value:
            lines.append(f"**{label}**")
            lines.append("")
            lines.append(str(value))
            lines.append("")

    if dd.get("based_on") != "fulltext":
        lines.append("> ⚠️ 本文未抓到全文，以上解读基于摘要，细节可能有偏差。")
        lines.append("")
    return "\n".join(lines).rstrip()


def _render_deep_dive_wechat(index: int, paper: Paper) -> str:
    """微信版深度解读：保留问题/方法/结果三段，按长度截断。"""
    dd = paper.deep_dive or {}
    title_zh = dd.get("title_zh") or paper.title
    parts = [f"{index}. {title_zh}"]
    if dd.get("title_zh"):
        parts.append(f"   原文：{truncate(paper.title, 80)}")
    meta = []
    if paper.direction:
        meta.append(f"[{paper.direction}]")
    if paper.llm_score is not None:
        meta.append(f"AI {paper.llm_score:.1f}/10")
    if meta:
        parts.append("   " + " · ".join(meta))
    if dd.get("problem"):
        parts.append(f"   ▸ 解决：{truncate(str(dd['problem']), 90)}")
    if dd.get("method"):
        parts.append(f"   ▸ 方法：{truncate(str(dd['method']), 230)}")
    if dd.get("results"):
        parts.append(f"   ▸ 结果：{truncate(str(dd['results']), 170)}")
    if paper.arxiv_id:
        parts.append(f"   🔗 https://arxiv.org/abs/{paper.arxiv_id}")
    return "\n".join(parts)


def render_markdown(ctx: dict) -> str:
    """生成完整日报 Markdown。"""
    run_date: date = ctx["date"]
    parts: list[str] = []
    parts.append(f"# {ctx.get('title', '量子论文雷达')} · {run_date.year}年{run_date.month}月{run_date.day}日")
    parts.append("")
    if ctx.get("pdf_url"):
        parts.append(f"📄 [下载 PDF 版]({ctx['pdf_url']})")
        parts.append("")
    if ctx.get("subtitle"):
        parts.append(f"> {ctx['subtitle']}")
        parts.append("")

    scan = ctx.get("scan") or {}
    new_count = ctx.get("new_count", 0)
    lines = []
    if scan:
        lines.append("## 今日概览")
        lines.append("")
        lines.append("| 数据源 | 状态 | 数量 |")
        lines.append("| --- | --- | --- |")
        for item in scan:
            status = "✅" if item["ok"] else "⚠️"
            lines.append(f"| {item['name']} | {status} {item.get('status', '')} | {item.get('count', '-')} |")
        lines.append("")
    stats = []
    stats.append(f"新增（未推送过）**{new_count}** 篇")
    if ctx.get("candidate_count"):
        stats.append(f"候选精读 **{ctx['candidate_count']}** 篇")
    if ctx.get("llm_calls"):
        stats.append(f"LLM 调用 **{ctx['llm_calls']}** 次")
    if lines:
        parts.extend(lines)
    if stats:
        parts.append("；".join(stats) + "。")
        parts.append("")

    if ctx.get("warnings"):
        parts.append("> ⚠️ " + "；".join(ctx["warnings"]))
        parts.append("")

    hot = ctx.get("scirate_hot") or []
    if hot:
        if ctx.get("hot_source") == "ai":
            parts.append("## 🔥 今日量子热榜（AI 排序）")
            parts.append("")
            parts.append("> Scirate 社区票数当前不可达，改为按模型对论文的重要性评分排序，仍取前 10 篇。")
        else:
            parts.append("## 🔥 Scirate 今日热榜")
            parts.append("")
            parts.append("> 按社区 scites 票数排序，代表当天量子领域最受关注的预印本。")
        parts.append("")
        for i, paper in enumerate(hot, start=1):
            parts.append(_paper_block_md(i, paper, show_rank=True))
            parts.append("")

    deep_dives = ctx.get("deep_dives") or []
    if deep_dives:
        parts.append("## 📖 重点论文深度解读")
        parts.append("")
        parts.append("> 由 DeepSeek 阅读全文后生成的简报：问题、方法、结果三段式，便于判断是否精读。")
        parts.append("")
        grouped: dict[str, list] = {}
        for paper in deep_dives:
            grouped.setdefault(paper.direction or "其他", []).append(paper)
        for direction, group in grouped.items():
            parts.append(f"### {direction}（{len(group)} 篇）")
            parts.append("")
            for i, paper in enumerate(group, start=1):
                parts.append(_render_deep_dive_md(i, paper, level=4))
                parts.append("")

    highlights = ctx.get("highlights") or []
    if highlights:
        parts.append("## 🎯 今日精选")
        parts.append("")
        parts.append("> LLM 从新论文中挑出的值得优先阅读的工作。")
        parts.append("")
        for i, paper in enumerate(highlights, start=1):
            parts.append(_paper_block_md(i, paper))
            parts.append("")

    worth = ctx.get("worth_scanning") or []
    if worth:
        if ctx.get("llm_calls"):
            parts.append("## 👀 可以扫一眼")
        else:
            parts.append("## 👀 关键词匹配（未启用 AI 精读）")
            parts.append("")
            parts.append("> 配置 `DEEPSEEK_API_KEY` 后会按研究相关性精读打分、生成阅读理由。")
        parts.append("")
        for paper in worth:
            tag = f"`{paper.direction}` " if paper.direction else ""
            reason = f" — {paper.llm_reason}" if paper.llm_reason else ""
            parts.append(f"- {tag}[{paper.title}]({paper.url}){reason}")
        parts.append("")

    if not hot and not highlights and not worth:
        parts.append("## 今日无新增")
        parts.append("")
        parts.append("所有抓取到的论文都已在之前推送过。")

    parts.append("---")
    parts.append("")
    footer = f"*由 paper-radar 自动生成 · 生成时间 {ctx.get('generated_at', '')}*"
    parts.append(footer)
    parts.append("")
    return "\n".join(parts)


def render_wechat(ctx: dict, max_chars: int = 9000) -> str:
    """生成适合微信推送的精简版（纯文本 + 链接）。"""
    run_date: date = ctx["date"]
    weekday = WEEKDAYS[run_date.weekday()]
    head = f"【{ctx.get('title', '量子论文雷达')}】{run_date.month:02d}-{run_date.day:02d} {weekday}"
    parts: list[str] = [head, ""]

    hot = ctx.get("scirate_hot") or []
    if hot:
        parts.append("🔥 今日热榜（AI 排序）" if ctx.get("hot_source") == "ai" else "🔥 Scirate 热榜")
        for i, paper in enumerate(hot, start=1):
            meta = f"（⬆{paper.scites}）" if paper.scites else ""
            mark = " 📖" if paper.deep_dive else ""
            parts.append(f"{i}. {paper.title}{meta}{mark}")
            if paper.llm_reason:
                parts.append(f"   💡 {truncate(paper.llm_reason, 90)}")
            parts.append(f"   {paper.url}")
        parts.append("")

    deep_dives = ctx.get("deep_dives") or []
    if deep_dives:
        parts.append(f"📖 重点论文深度解读 {len(deep_dives)} 篇")
        grouped: dict[str, list] = {}
        for paper in deep_dives:
            grouped.setdefault(paper.direction or "其他", []).append(paper)
        for direction, group in grouped.items():
            parts.append(f"【{direction}】")
            for i, paper in enumerate(group, start=1):
                parts.append(_render_deep_dive_wechat(i, paper))
        parts.append("")

    highlights = ctx.get("highlights") or []
    if highlights:
        parts.append(f"🎯 今日精选 {len(highlights)} 篇")
        for i, paper in enumerate(highlights, start=1):
            tag = f"[{paper.direction}] " if paper.direction else ""
            parts.append(f"{i}. {tag}{paper.title}")
            if paper.llm_reason:
                parts.append(f"   💡 {truncate(paper.llm_reason, 90)}")
            parts.append(f"   {paper.url}")
        parts.append("")

    worth = ctx.get("worth_scanning") or []
    if worth:
        parts.append("👀 可以扫一眼")
        for paper in worth:
            tag = f"[{paper.direction}] " if paper.direction else ""
            reason = f"：{truncate(paper.llm_reason, 50)}" if paper.llm_reason else ""
            parts.append(f"· {tag}{paper.title}{reason}")
            parts.append(f"  {paper.url}")
        parts.append("")

    if not hot and not highlights and not worth:
        parts.append("今日没有新的相关论文。")

    stats = ctx.get("stats_line")
    if stats:
        parts.append(stats)
    if ctx.get("warnings"):
        parts.append("⚠️ " + "；".join(ctx["warnings"]))
    parts.append("")
    parts.append("—— paper-radar 自动生成")

    text = "\n".join(parts)
    if len(text) > max_chars:
        text = text[:max_chars].rstrip() + "\n…（完整版见仓库 reports/）"
    return text


# ---------------- 微信推送用的纯文本 / HTML 渲染 ----------------

_LATEX_SYMBOLS = {
    r"\otimes": "⊗", r"\leq": "≤", r"\le": "≤", r"\geq": "≥", r"\ge": "≥",
    r"\sqrt": "√", r"\approx": "≈", r"\neq": "≠", r"\pm": "±", r"\times": "×",
    r"\cdot": "·", r"\infty": "∞", r"\in": "∈", r"\subset": "⊂", r"\cup": "∪",
    r"\cap": "∩", r"\sum": "Σ", r"\prod": "Π", r"\int": "∫", r"\partial": "∂",
    r"\to": "→", r"\rightarrow": "→", r"\leftarrow": "←", r"\Rightarrow": "⇒",
    r"\alpha": "α", r"\beta": "β", r"\gamma": "γ", r"\delta": "δ",
    r"\epsilon": "ε", r"\varepsilon": "ε", r"\zeta": "ζ", r"\eta": "η",
    r"\theta": "θ", r"\kappa": "κ", r"\lambda": "λ", r"\mu": "μ",
    r"\nu": "ν", r"\xi": "ξ", r"\pi": "π", r"\rho": "ρ", r"\sigma": "σ",
    r"\tau": "τ", r"\phi": "φ", r"\varphi": "φ", r"\chi": "χ", r"\psi": "ψ",
    r"\omega": "ω", r"\Gamma": "Γ", r"\Delta": "Δ", r"\Theta": "Θ",
    r"\Lambda": "Λ", r"\Xi": "Ξ", r"\Pi": "Π", r"\Sigma": "Σ", r"\Phi": "Φ",
    r"\Psi": "Ψ", r"\Omega": "Ω", r"\ell": "ℓ", r"\hbar": "ℏ",
    r"\mathcal{D}": "D", r"\mathcal{O}": "O", r"\mathcal{L}": "L",
    r"\mathcal{H}": "H", r"\mathbb{R}": "R", r"\mathbb{C}": "C",
    r"\log": "log", r"\exp": "exp", r"\ln": "ln", r"\max": "max",
    r"\min": "min", r"\lim": "lim", r"\Tr": "Tr", r"\mathrm": "",
    r"\text": "", r"\left": "", r"\right": "", r"\quad": " ", r"\,": " ", r"\|": "‖", r"\{": "{", r"\}": "}", r"\%": "%",
    r"\circ": "∘", r"\rangle": "⟩", r"\langle": "⟨", r"\dagger": "†",
    r"\sim": "∼", r"\propto": "∝", r"\equiv": "≡", r"\ldots": "…",
    r"\cdots": "⋯", r"\nabla": "∇", r"\prime": "′", r"\ast": "*",
    r"\star": "⋆", r"\uparrow": "↑", r"\downarrow": "↓", r"\oplus": "⊕",
    r"\otimes": "⊗", r"\wedge": "∧", r"\vee": "∨", r"\neg": "¬",
    r"\mathcal{N}": "N", r"\mathcal{E}": "E", r"\mathcal{U}": "U",
    r"\mathcal{S}": "S", r"\mathcal{T}": "T", r"\mathcal{F}": "F",
    r"\mathbb{E}": "E", r"\mathbb{P}": "P", r"\cdot": "·",
}


def latex_to_plain(text: str) -> str:
    """把常见 LaTeX 公式转成微信可读的 Unicode 文本。

    处理不了复杂结构时会退化为去掉反斜杠和花括号，仍然比原样显示好读。
    """
    if not text:
        return ""
    out = str(text)
    # 先把 $...$ 和 $$...$$ 的标记去掉，保留内容
    out = re.sub(r"\$\$(.+?)\$\$", r"\1", out, flags=re.S)
    out = re.sub(r"\$(.+?)\$", r"\1", out, flags=re.S)
    for latex, plain in _LATEX_SYMBOLS.items():
        out = out.replace(latex, plain)
    # 通用数学字体命令：\mathcal{N} / \mathbf{x} / \mathbb{R} / \text{...}
    out = re.sub(r"\\math(?:rm|cal|bf|bb|it|sf|tt)\{([^{}]*)\}", r"\1", out)
    out = re.sub(r"\\text(?:bf|it|rm)?\{([^{}]*)\}", r"\1", out)
    out = re.sub(r"\\operatorname\{([^{}]*)\}", r"\1", out)
    # 上下标：^{...} -> ^(...)，_{...} -> _(...)
    out = re.sub(r"\^\{([^{}]*)\}", r"^(\1)", out)
    out = re.sub(r"_\{([^{}]*)\}", r"_(\1)", out)
    # 剩余的花括号和反斜杠
    out = out.replace("{", "").replace("}", "")
    out = re.sub(r"\\([A-Za-z]+)", r"\1", out)
    out = re.sub(r"[ \t]+", " ", out)
    return out.strip()


def _esc(text: str) -> str:
    return html_lib.escape(str(text or ""), quote=False)


def _md_inline_to_html(text) -> str:
    """模型输出的简单 markdown → HTML 片段：公式转 Unicode、转义、加粗、换行。"""
    plain = latex_to_plain(str(text or ""))
    escaped = html_lib.escape(plain, quote=False)
    escaped = re.sub(r"\*\*(.+?)\*\*", r"<b>\1</b>", escaped)
    return escaped.replace("\n", "<br>")


def render_wechat_html(ctx: dict, max_chars: int = 12000) -> str:
    """生成 HTML 版微信消息：用 <br> 控制换行，链接可点击，公式转 Unicode。"""
    run_date: date = ctx["date"]
    weekday = WEEKDAYS[run_date.weekday()]
    lines: list[str] = []

    lines.append(f"<b>【{_esc(ctx.get('title', '量子论文雷达'))}】{run_date.month:02d}-{run_date.day:02d} {weekday}</b>")
    if ctx.get("pdf_url"):
        lines.append(f'📄 <a href="{_esc(ctx["pdf_url"])}">下载完整版 PDF 日报</a>')
    lines.append("")

    hot = ctx.get("scirate_hot") or []
    if hot:
        label = "🔥 今日热榜（AI 排序）" if ctx.get("hot_source") == "ai" else "🔥 Scirate 热榜"
        lines.append(f"<b>{label}</b>")
        for i, paper in enumerate(hot, start=1):
            title = _md_inline_to_html(paper.title)
            mark = " 📖" if paper.deep_dive else ""
            scites = f"（⬆{paper.scites}）" if paper.scites else ""
            lines.append(f"{i}. {title}{scites}{mark}")
            if paper.llm_reason:
                lines.append(f"💡 {_md_inline_to_html(paper.llm_reason)}")
            lines.append(f'<a href="{_esc(paper.url)}">{_esc(paper.url)}</a>')
        lines.append("")

    deep_dives = ctx.get("deep_dives") or []
    if deep_dives:
        lines.append(f"<b>📖 重点论文深度解读 {len(deep_dives)} 篇</b>")
        grouped: dict[str, list] = {}
        for paper in deep_dives:
            grouped.setdefault(paper.direction or "其他", []).append(paper)
        for direction, group in grouped.items():
            lines.append(f"<b>【{_esc(direction)}】</b>")
            for i, paper in enumerate(group, start=1):
                dd = paper.deep_dive or {}
                title_zh = dd.get("title_zh") or paper.title
                lines.append(f"{i}. <b>{_md_inline_to_html(title_zh)}</b>")
                if dd.get("title_zh"):
                    lines.append(f"原文：{_md_inline_to_html(paper.title)}")
                meta = []
                if paper.llm_score is not None:
                    meta.append(f"AI {paper.llm_score:.1f}/10")
                if meta:
                    lines.append(" · ".join(meta))
                if dd.get("problem"):
                    lines.append(f"▸ 解决：{_md_inline_to_html(truncate(str(dd['problem']), 150))}")
                if dd.get("method"):
                    lines.append(f"▸ 方法：{_md_inline_to_html(truncate(str(dd['method']), 420))}")
                if dd.get("results"):
                    lines.append(f"▸ 结果：{_md_inline_to_html(truncate(str(dd['results']), 280))}")
                if paper.arxiv_id:
                    url = f"https://arxiv.org/abs/{paper.arxiv_id}"
                    lines.append(f'🔗 <a href="{_esc(url)}">{_esc(url)}</a>')
                lines.append("")

    highlights = ctx.get("highlights") or []
    if highlights:
        lines.append(f"<b>🎯 今日精选 {len(highlights)} 篇</b>")
        for i, paper in enumerate(highlights, start=1):
            tag = f"[{_esc(paper.direction)}] " if paper.direction else ""
            lines.append(f"{i}. {tag}{_md_inline_to_html(paper.title)}")
            if paper.llm_reason:
                lines.append(f"💡 {_md_inline_to_html(paper.llm_reason)}")
            lines.append(f'<a href="{_esc(paper.url)}">{_esc(paper.url)}</a>')
        lines.append("")

    worth = ctx.get("worth_scanning") or []
    if worth:
        lines.append("<b>👀 可以扫一眼</b>")
        for paper in worth:
            tag = f"[{_esc(paper.direction)}] " if paper.direction else ""
            reason = f"：{_md_inline_to_html(truncate(paper.llm_reason, 70))}" if paper.llm_reason else ""
            lines.append(f"· {tag}{_md_inline_to_html(paper.title)}{reason}")
            lines.append(f'<a href="{_esc(paper.url)}">{_esc(paper.url)}</a>')
        lines.append("")

    if not hot and not deep_dives and not highlights and not worth:
        lines.append("今日没有新的相关论文。")
        lines.append("")

    if ctx.get("stats_line"):
        lines.append(_esc(ctx["stats_line"]))
    lines.append("")
    lines.append("—— paper-radar 自动生成")

    text = "<br>".join(lines)
    if len(text) > max_chars:
        text = text[:max_chars] + "<br>…（完整版见仓库 reports/）"
    return text
