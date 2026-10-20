"""重点论文深度解读：用 LLM 把全文压缩成结构化中文简报。

输出与日报模板一一对应：
- title_zh        中文标题
- abstract_zh     摘要中文翻译
- problem         「1. 主要解决的问题」
- method          「2. 核心方法或创新」（①②③ 分点，详细且易读）
- results         「3. 值得关注的结果或意义」（关键数字、对比、边界条件）
"""

from __future__ import annotations

import json
from datetime import date
from typing import Optional

from .deepseek import DeepSeekClient, DeepSeekError, extract_json
from .models import Paper
from .sources.fulltext import FullText
from .util import get_logger, truncate

log = get_logger(__name__)

SYSTEM_PROMPT = """你是一位量子信息方向的研究员，负责为每日论文简报撰写深度解读。
读者是同一方向的研究者，他希望通过简报快速判断：这篇论文值不值得精读、核心方法是什么、结果有多硬。

写作要求：
1. 全中文，术语保留英文原词；专业但不堆砌，读完就能抓住要害。
2. 公式保留 LaTeX（$...$），不要展开推导，只保留理解方法所必需的部分。
3. 方法部分必须具体：关键设置、参数取值、对照设计、用了什么手段，分点写清楚；不要写「作者提出了一个方法」这种空话。
4. 结果部分给关键数字、对比基线、适用边界和局限；有表格数据就提炼出来。
5. 严格基于论文内容，不要编造；论文没写的不要补。
6. 只输出一个 JSON 对象，不要 markdown 代码块，不要任何解释文字。

JSON 结构（严格按此输出）：
{
  "title_zh": "标题的中文翻译",
  "abstract_zh": "摘要的中文翻译，150-250 字，保留关键术语的英文",
  "problem": "主要解决的问题：2-4 句话，说明问题是什么、之前的难点或未解之处在哪里",
  "method": "核心方法与创新：用 ①②③ 分点，每点以一句加粗小标题开头再展开 2-4 句。要具体到设置、参数、对照、公式。总长 300-650 字",
  "results": "值得关注的结果或意义：用 ①②③ 分点或 markdown 表格给出关键数字、上下界、对比；最后一句说明局限或下一步。总长 250-500 字"
}"""


def build_user_prompt(paper: Paper, fulltext: Optional[FullText], focus: str, max_fulltext_chars: int) -> str:
    meta = [f"英文标题：{paper.title}"]
    if paper.authors:
        meta.append("作者：" + "、".join(paper.authors[:12]))
    if paper.arxiv_id:
        meta.append(f"arXiv ID：{paper.arxiv_id}")
    if paper.direction:
        meta.append(f"关注方向标签：{paper.direction}")

    if fulltext and fulltext.has_body:
        body = fulltext.to_prompt_text(max_chars=max_fulltext_chars)
        note = "下面是论文全文（已按章节裁剪）："
    else:
        body = paper.abstract or ""
        note = "注意：全文抓取失败，下面只有摘要，请基于摘要做尽量可靠的解读，并在结果部分避免过度推断。"

    return (
        f"今天是 {date.today().isoformat()}。研究员的关注方向：{focus}。\n\n"
        + "\n".join(meta)
        + f"\n\n{note}\n{body}\n\n"
        "请按系统提示的 JSON 结构输出这篇论文的深度解读。"
    )


def _clean_text(value) -> str:
    if value is None:
        return ""
    return str(value).strip()


def deep_dive(
    client: Optional[DeepSeekClient],
    paper: Paper,
    fulltext: Optional[FullText] = None,
    focus: str = "",
    max_fulltext_chars: int = 50000,
    max_tokens: int = 3200,
    temperature: float = 0.3,
) -> Optional[dict]:
    """生成单篇论文的深度解读；失败返回 None。"""
    if not client or not client.available:
        return None

    messages = [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user", "content": build_user_prompt(paper, fulltext, focus, max_fulltext_chars)},
    ]
    data = None
    for attempt in (1, 2):
        try:
            raw = client.chat(messages, temperature=temperature, max_tokens=max_tokens)
            data = extract_json(raw)
            break
        except (DeepSeekError, ValueError) as exc:
            log.warning("深度解读第 %d 次失败（%s）：%s", attempt, paper.arxiv_id, exc)
            if attempt == 1:
                messages.append(
                    {
                        "role": "user",
                        "content": "上次输出无法解析为 JSON。请重新输出，只输出一个合法 JSON 对象，不要代码块。",
                    }
                )
    if not isinstance(data, dict):
        log.warning("深度解读失败，跳过：%s", paper.title[:60])
        return None

    result = {
        "title_zh": _clean_text(data.get("title_zh")),
        "abstract_zh": _clean_text(data.get("abstract_zh")),
        "problem": _clean_text(data.get("problem")),
        "method": _clean_text(data.get("method")),
        "results": _clean_text(data.get("results")),
        "based_on": "fulltext" if (fulltext and fulltext.has_body) else "abstract",
        "authors": [],
    }
    # 作者与机构来自全文解析（不是 LLM 生成，避免编造机构）
    if fulltext and fulltext.authors:
        result["authors"] = [
            {"name": a.get("name", ""), "affiliations": a.get("affiliations") or []}
            for a in fulltext.authors
        ]
    elif paper.authors:
        result["authors"] = [{"name": name, "affiliations": []} for name in paper.authors]

    if not result["problem"] and not result["method"]:
        log.warning("深度解读内容为空，跳过：%s", paper.title[:60])
        return None
    log.info("深度解读完成：%s（基于%s）", paper.title[:60], "全文" if result["based_on"] == "fulltext" else "摘要")
    return result


def select_deep_dive(
    papers: list[Paper],
    per_direction: dict,
    fallback_min_score: float = 7.0,
) -> list[Paper]:
    """按方向分配深度解读名额。

    per_direction 形如 {"QRC": {"top_n": 3, "min_llm_score": 6.5}, "量子算法": {...}}。
    某方向候选不足时，用「没有方向标签但 LLM 分达标」的论文补位；仍不足就少解读几篇。
    """
    selected: list[Paper] = []
    used: set[str] = set()

    def _rank(pool: list[Paper]) -> list[Paper]:
        return sorted(pool, key=lambda p: p.llm_score or 0.0, reverse=True)

    base = [
        p
        for p in papers
        if p.arxiv_id and p.llm_score is not None and p.dedup_key not in used
    ]

    for direction, conf in (per_direction or {}).items():
        conf = conf or {}
        top_n = int(conf.get("top_n", 0) or 0)
        if top_n <= 0:
            continue
        min_score = float(conf.get("min_llm_score", fallback_min_score))

        primary = _rank(
            [
                p
                for p in base
                if p.direction == direction and (p.llm_score or 0) >= min_score
            ]
        )[:top_n]
        picked = list(primary)

        if len(picked) < top_n:
            picked_keys = {p.dedup_key for p in picked}
            # 补位 1：同方向但分数略低于门槛的论文（不低于 5.0），尽量填满配额
            low_bar = max(5.0, min_score - 2.0)
            same_dir = _rank(
                [
                    p
                    for p in base
                    if p.direction == direction
                    and p.dedup_key not in picked_keys
                    and (p.llm_score or 0) >= low_bar
                ]
            )[: top_n - len(picked)]
            picked.extend(same_dir)
            picked_keys |= {p.dedup_key for p in same_dir}
        if len(picked) < top_n:
            # 补位 2：没有方向标签但分数达标的论文
            need = top_n - len(picked)
            picked_keys = {p.dedup_key for p in picked}
            filler = _rank(
                [
                    p
                    for p in base
                    if not p.direction
                    and p.dedup_key not in picked_keys
                    and (p.llm_score or 0) >= min_score
                ]
            )[:need]
            picked.extend(filler)

        if len(picked) < top_n:
            log.info("方向「%s」深度解读候选不足：%d/%d 篇", direction, len(picked), top_n)
        selected.extend(picked)
        used |= {p.dedup_key for p in picked}
        base = [p for p in base if p.dedup_key not in used]

    return selected
