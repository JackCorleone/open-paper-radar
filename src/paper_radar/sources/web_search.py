"""DeepSeek Search API 数据源：发现 arXiv 之外的论文与周边信号。"""

from __future__ import annotations

from datetime import date
from typing import Optional

from ..deepseek import DeepSeekClient, DeepSeekError
from ..models import Paper, normalize_arxiv_id
from ..util import get_logger, parse_date_loose, replace_date_placeholders, truncate

log = get_logger(__name__)


def search_papers(
    client: Optional[DeepSeekClient],
    queries: list[dict],
    base_date: Optional[date] = None,
) -> list[Paper]:
    """按配置里的查询逐条调用 Search API，合并结果。"""
    if not client or not client.available:
        log.info("未配置 DeepSeek API Key，跳过 Search API 发现")
        return []

    papers: list[Paper] = []
    for item in queries:
        raw_query = item.get("query") or ""
        name = item.get("name") or raw_query[:30]
        query = replace_date_placeholders(raw_query, base_date)
        try:
            results = client.search(query, count=int(item.get("count", 10)))
        except DeepSeekError as exc:
            log.warning("搜索「%s」失败：%s", name, exc)
            continue
        log.info("搜索「%s」：%d 条结果", name, len(results))
        for result in results:
            url = (result.get("url") or "").strip()
            title = (result.get("title") or "").strip()
            if not url or not title:
                continue
            summary = result.get("summary") or result.get("content") or result.get("snippet") or ""
            published = parse_date_loose(result.get("date"))
            paper = Paper(
                title=title,
                url=url,
                arxiv_id=normalize_arxiv_id(url) or normalize_arxiv_id(title),
                source="search",
                abstract=truncate(summary, 1200),
                published=published,
                search_score=_as_float(result.get("rerank_score")),
                authority=int(result.get("authority") or -1),
                venue=(result.get("site_name") or "").strip(),
            )
            papers.append(paper)
    return papers


def _as_float(value) -> Optional[float]:
    try:
        return float(value)
    except (TypeError, ValueError):
        return None
