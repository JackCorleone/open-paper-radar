"""arXiv 数据源。

优先用官方 API（结构稳定、字段全），被限流时自动降级到列表页 HTML。
两者都只读取 quant-ph 之类的分类，不做全站抓取。
"""

from __future__ import annotations

import re
import xml.etree.ElementTree as ET
from datetime import datetime, timedelta, timezone
from typing import Optional

from ..http import HttpError, request
from ..models import Paper, normalize_arxiv_id
from ..util import get_logger, parse_date_loose, squash_ws, strip_html, truncate

log = get_logger(__name__)

ATOM_NS = {"atom": "http://www.w3.org/2005/Atom", "arxiv": "http://arxiv.org/schemas/atom"}
API_URL = "https://export.arxiv.org/api/query"
LIST_URL = "https://arxiv.org/list/{category}/new"


def _parse_atom(xml_text: str, lookback_hours: int) -> list[Paper]:
    root = ET.fromstring(xml_text)
    cutoff = datetime.now(timezone.utc) - timedelta(hours=lookback_hours)
    papers: list[Paper] = []
    for entry in root.findall("atom:entry", ATOM_NS):
        raw_id = (entry.findtext("atom:id", default="", namespaces=ATOM_NS) or "").strip()
        arxiv_id = normalize_arxiv_id(raw_id)
        title = squash_ws(entry.findtext("atom:title", default="", namespaces=ATOM_NS) or "")
        if not title or not arxiv_id:
            continue
        published = parse_date_loose(entry.findtext("atom:published", default="", namespaces=ATOM_NS))
        if published and published < cutoff:
            continue
        abstract = squash_ws(entry.findtext("atom:summary", default="", namespaces=ATOM_NS) or "")
        authors = [
            squash_ws(name.text or "")
            for name in entry.findall("atom:author/atom:name", ATOM_NS)
            if name.text
        ]
        primary = entry.find("arxiv:primary_category", ATOM_NS)
        category = primary.get("term") if primary is not None else ""
        papers.append(
            Paper(
                title=title,
                url=f"https://arxiv.org/abs/{arxiv_id}",
                arxiv_id=arxiv_id,
                source="arxiv",
                abstract=truncate(abstract, 1600),
                authors=authors,
                published=published,
                venue=f"arXiv {category}".strip() or "arXiv",
            )
        )
    return papers


_DT_SPLIT = re.compile(r"<dt>", re.I)
_TAG = re.compile(r"<[^>]+>")


def _clean(fragment: str) -> str:
    fragment = re.sub(r"(?is)<(script|style).*?</\1>", " ", fragment)
    return squash_ws(strip_html(fragment))


def _parse_list_html(html: str, lookback_hours: int) -> list[Paper]:
    """解析 arxiv.org/list/<cat>/new 页面。"""
    cutoff = datetime.now(timezone.utc) - timedelta(hours=lookback_hours)
    # 页面上的公告日期，形如 "Showing new listings for Monday, 19 October 2026"
    page_date: Optional[datetime] = None
    m = re.search(r"Showing new listings for\s+\w+,\s+(\d{1,2}\s+\w+\s+\d{4})", html)
    if m:
        page_date = parse_date_loose(m.group(1))
        if page_date:
            page_date = page_date.replace(hour=0, minute=0, tzinfo=timezone.utc)

    # 只处理 New submissions 与 Cross submissions，跳过 Replacement submissions
    body = html
    rep = re.search(r"<h3[^>]*>\s*Replace(?:ment)?", body, re.I)
    if rep:
        body = body[: rep.start()]

    papers: list[Paper] = []
    for chunk in _DT_SPLIT.split(body)[1:]:
        chunk = chunk.split("</dd>")[0]
        id_match = re.search(r'href\s*=\s*["\']/abs/([^"\']+)["\']', chunk)
        if not id_match:
            continue
        arxiv_id = normalize_arxiv_id(id_match.group(1))
        if not arxiv_id:
            continue
        title_match = re.search(r"list-title[^>]*>(.*?)</div>", chunk, re.S | re.I)
        title = _clean(title_match.group(1)) if title_match else ""
        title = re.sub(r"^Title:\s*", "", title, flags=re.I)
        if not title:
            continue
        if page_date and page_date < cutoff - timedelta(days=1):
            # 页面公告日期明显过旧（例如手动补跑），跳过整页
            continue
        authors_match = re.search(r"list-authors[^>]*>(.*?)</div>", chunk, re.S | re.I)
        authors: list[str] = []
        if authors_match:
            authors = [
                _clean(a) for a in re.findall(r">([^<>]{2,120})<", authors_match.group(1)) if _clean(a)
            ]
        subjects_match = re.search(r"list-subjects[^>]*>(.*?)</div>", chunk, re.S | re.I)
        subjects = _clean(subjects_match.group(1)) if subjects_match else ""
        if subjects.lower().startswith("subjects:"):
            subjects = subjects[len("subjects:"):].strip()
        abstract_match = re.search(r"<p[^>]*class=['\"]mathjax['\"][^>]*>(.*?)</p>", chunk, re.S | re.I)
        abstract = _clean(abstract_match.group(1)) if abstract_match else ""
        papers.append(
            Paper(
                title=title,
                url=f"https://arxiv.org/abs/{arxiv_id}",
                arxiv_id=arxiv_id,
                source="arxiv",
                abstract=truncate(abstract, 1600),
                authors=authors,
                published=page_date,
                venue=truncate(subjects, 80) if subjects else "arXiv",
            )
        )
    return papers


def get_arxiv_papers(
    categories: list[str],
    max_results: int = 200,
    lookback_hours: int = 72,
) -> list[Paper]:
    """按分类拉取最新论文，API 失败时降级到列表页。"""
    collected: dict[str, Paper] = {}
    for category in categories:
        papers = _fetch_category(category, max_results, lookback_hours)
        for paper in papers:
            key = paper.dedup_key
            if key in collected:
                continue
            collected[key] = paper
    return list(collected.values())


def _fetch_category(category: str, max_results: int, lookback_hours: int) -> list[Paper]:
    query = f"cat:{category}"
    url = (
        f"{API_URL}?search_query={query}&start=0&max_results={max_results}"
        "&sortBy=submittedDate&sortOrder=descending"
    )
    try:
        xml_text = request(
            url,
            headers={"Accept": "application/atom+xml"},
            timeout=45,
            retries=2,
            backoff=4.0,
        )
        papers = _parse_atom(xml_text, lookback_hours)
        log.info("arXiv API %s：%d 篇", category, len(papers))
        return papers
    except (HttpError, ET.ParseError) as exc:
        log.warning("arXiv API 失败（%s），降级到列表页：%s", type(exc).__name__, exc)

    list_url = LIST_URL.format(category=category)
    try:
        html = request(
            list_url,
            headers={"Accept": "text/html"},
            timeout=45,
            retries=2,
            backoff=4.0,
        )
        papers = _parse_list_html(html, lookback_hours)
        log.info("arXiv 列表页 %s：%d 篇", category, len(papers))
        return papers
    except HttpError as exc:
        log.error("arXiv 列表页也失败（HTTP %s）：%s", exc.status, list_url)
        return []
