"""合并去重、规则预筛、综合排序。

排序公式（0~1）：
    combined = 0.55 * LLM分 + 0.25 * Scirate热度 + 0.12 * 搜索信号 + 0.08 * 时效
没有 LLM 分时（未配置 key 或调用失败）退化为规则分。
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Iterable, Optional

from .models import Paper, normalize_title
from .util import get_logger

log = get_logger(__name__)


# 被认为是「论文页面」的域名（用于过滤搜索结果里的博客、聚合页、学位论文库等）
PAPER_HOSTS = (
    "arxiv.org", "openreview.net", "doi.org", "nature.com", "science.org",
    "aps.org", "link.aps.org", "ieeexplore.ieee.org", "springer.com",
    "sciencedirect.com", "iop.org", "pnas.org", "cell.com", "oup.com",
    "tandfonline.com", "wiley.com", "iopscience.iop.org", "academic.oup.com",
    "quantum-journal.org", "prx.aps.org", "scipost.org",
)


def is_paper_like(paper: Paper) -> bool:
    """判断一条结果是否像「论文」而不是博客/聚合页/学位论文库。"""
    if paper.arxiv_id:
        return True
    url = (paper.url or "").lower()
    return any(host in url for host in PAPER_HOSTS)


def _same_paper_title(a: str, b: str) -> bool:
    """标题层面的模糊去重：同一篇论文在不同站点上标题常被截断或加站点后缀。"""
    from difflib import SequenceMatcher

    na, nb = normalize_title(a), normalize_title(b)
    if not na or not nb:
        return False
    if na == nb:
        return True
    short, long_ = (na, nb) if len(na) <= len(nb) else (nb, na)
    if len(short) >= 25 and long_.startswith(short[: min(len(short), 80)]):
        return True
    if max(len(na), len(nb)) > 0 and abs(len(na) - len(nb)) <= 0.25 * max(len(na), len(nb)):
        return SequenceMatcher(None, na, nb).ratio() >= 0.92
    return False


def merge_papers(groups: Iterable[Iterable[Paper]]) -> list[Paper]:
    """把多个数据源的结果合并成一份去重列表（arXiv ID 精确匹配 + 标题模糊匹配）。"""
    merged: list[Paper] = []
    index: dict[str, Paper] = {}
    for group in groups:
        for paper in group:
            key = paper.dedup_key
            if key in index:
                index[key].merge(paper)
                continue
            # 没有 arXiv ID 的条目，按标题模糊匹配已有条目
            if not paper.arxiv_id:
                matched = next(
                    (existing for existing in merged
                     if _same_paper_title(existing.title, paper.title)),
                    None,
                )
                if matched is not None:
                    matched.merge(paper)
                    index[key] = matched
                    continue
            merged.append(paper)
            index[key] = paper
    return merged


def _haystack(paper: Paper) -> str:
    return f"{paper.title} {paper.abstract}".lower()


def relevance_score(paper: Paper, keywords: dict) -> float:
    """关键词相关性分（0~5）。

    分三层：priority（用户明确盯的方向，如近最优量子算法）> core（强相关）> adjacent（邻近）。
    """
    text = _haystack(paper)
    priority = [k.lower() for k in keywords.get("priority_any", [])]
    core = [k.lower() for k in keywords.get("core_any", [])]
    adjacent = [k.lower() for k in keywords.get("adjacent_any", [])]
    exclude = [k.lower() for k in keywords.get("exclude_any", [])]

    if any(k in text for k in exclude):
        return 0.0

    score = 0.0
    priority_hits = sum(1 for k in priority if k in text)
    if priority_hits:
        score += 3.0 + 0.5 * (priority_hits - 1)
    core_hits = sum(1 for k in core if k in text)
    if core_hits:
        score += min(2.5, 2.0 + 0.4 * (core_hits - 1))
    adj_hits = sum(1 for k in adjacent if k in text)
    if adj_hits:
        score += min(1.2, 0.35 * adj_hits)
    return min(5.0, score)


def scirate_signal(paper: Paper) -> float:
    if paper.scirate_rank is None:
        return 0.0
    return max(0.0, 1.0 - (paper.scirate_rank - 1) / 10.0)


def search_signal(paper: Paper) -> float:
    if paper.search_score is None:
        return 0.0
    return max(0.0, min(1.0, paper.search_score / 3.0))


def recency_signal(paper: Paper, now: Optional[datetime] = None) -> float:
    if not paper.published:
        return 0.4
    now = now or datetime.now(timezone.utc)
    published = paper.published
    if published.tzinfo is None:
        published = published.replace(tzinfo=timezone.utc)
    age_hours = max(0.0, (now - published).total_seconds() / 3600)
    if age_hours <= 24:
        return 1.0
    if age_hours <= 72:
        return 0.7
    if age_hours <= 168:
        return 0.4
    return 0.2


def prefilter(
    papers: list[Paper],
    keywords: dict,
    max_candidates: int,
    scirate_top_n: int = 10,
) -> list[Paper]:
    """规则预筛出送 LLM 精读的候选。

    保证：Scirate 榜单论文全部入选；其余按规则分从高到低补满。
    """
    if len(papers) <= max_candidates:
        return list(papers)

    scored: list[tuple[float, Paper]] = []
    guaranteed: list[Paper] = []
    for paper in papers:
        if paper.scirate_rank is not None and paper.scirate_rank <= scirate_top_n:
            guaranteed.append(paper)
            continue
        rule = (
            relevance_score(paper, keywords)
            * 1.0
            + scirate_signal(paper) * 2.0
            + search_signal(paper) * 2.0
            + recency_signal(paper) * 1.5
        )
        scored.append((rule, paper))

    selected: list[Paper] = list(guaranteed)
    selected_keys = {p.dedup_key for p in selected}
    scored.sort(key=lambda item: item[0], reverse=True)
    for _, paper in scored:
        if len(selected) >= max_candidates:
            break
        if paper.dedup_key in selected_keys:
            continue
        selected.append(paper)
        selected_keys.add(paper.dedup_key)
    return selected


def final_rank(
    all_papers: list[Paper],
    new_papers: list[Paper],
    keywords: dict,
    max_items: int,
    scirate_top_n: int,
    min_llm_score: float = 5.0,
) -> dict[str, list[Paper]]:
    """产出日报需要的分组。

    - scirate_hot: 当日 Scirate 榜单（可能包含昨天已推送的论文，保证榜单完整）
    - highlights:   从「未推送过的新论文」中选出的 LLM 高分工作
    - worth_scanning: 其余新论文里可扫读的
    """
    # 给没有 LLM 分的论文补规则综合分
    for paper in all_papers:
        if paper.llm_score is None:
            # 没有 LLM 分时，关键词相关性是唯一可靠信号，权重给足
            paper.combined_score = (
                0.50 * (relevance_score(paper, keywords) / 5.0)
                + 0.25 * scirate_signal(paper)
                + 0.15 * recency_signal(paper)
                + 0.10 * search_signal(paper)
            )

    scirate_hot = sorted(
        [p for p in all_papers if p.scirate_rank is not None and p.scirate_rank <= scirate_top_n],
        key=lambda p: (p.scirate_rank or 999),
    )
    hot_keys = {p.dedup_key for p in scirate_hot}

    rest = [p for p in new_papers if p.dedup_key not in hot_keys]
    rest.sort(key=lambda p: p.combined_score, reverse=True)

    budget = max(0, max_items - len(scirate_hot))
    highlights = [p for p in rest if (p.llm_score or 0) >= 6.5][:budget]
    hl_keys = {p.dedup_key for p in highlights}

    remaining = max(0, budget - len(highlights))
    worth: list[Paper] = []
    for paper in rest:
        if paper.dedup_key in hl_keys:
            continue
        if not is_paper_like(paper):
            continue
        if paper.llm_score is not None:
            take = paper.llm_score >= min_llm_score
        else:
            # 没有 LLM 分时，只要有任何相关性信号就按综合分取前 N 篇
            take = (
                relevance_score(paper, keywords) > 0
                or (paper.search_score is not None and paper.search_score >= 1.5)
                or paper.scirate_rank is not None
            )
        if take:
            worth.append(paper)
        if len(worth) >= remaining:
            break
    return {"scirate_hot": scirate_hot, "highlights": highlights, "worth_scanning": worth}


def tag_directions(papers: list[Paper], directions: list[dict]) -> None:
    """按关键词把论文标注到某个关注方向（取第一个命中的方向）。"""
    if not directions:
        return
    for paper in papers:
        text = _haystack(paper)
        for direction in directions:
            words = [str(k).lower() for k in direction.get("any", [])]
            if any(w and w in text for w in words):
                paper.direction = str(direction.get("name") or "")
                break


def ai_hot(papers: list[Paper], top_n: int = 10) -> list[Paper]:
    """Scirate 不可达时的替代热榜：按模型评分对论文排序取前 N。

    只考虑有 LLM 分数、且看起来是论文的条目（排除博客、聚合页、学位论文库）。
    """
    scored = [p for p in papers if p.llm_score is not None and is_paper_like(p)]
    scored.sort(key=lambda p: ((p.llm_score or 0.0), p.combined_score), reverse=True)
    picked = scored[:top_n]
    for rank, paper in enumerate(picked, start=1):
        paper.scirate_rank = rank  # 复用排名字段，渲染时按热榜展示
        paper.scites = 0
    return picked
