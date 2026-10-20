"""数据模型与论文标识归一化。"""

from __future__ import annotations

import re
import unicodedata

from .util import squash_ws
from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional

# 新式 arXiv ID：2610.22476(v2)；旧式：quant-ph/0501001(v1)
_ARXIV_NEW = re.compile(r"(\d{4}\.\d{4,5})(?:v\d+)?")
# 旧式 ID 的归档名是有限集合，不能写成任意 [a-z-]+，否则 "literature/3215984" 会被误判成 arXiv ID
_ARXIV_OLD = re.compile(
    r"((?:quant-ph|hep-th|hep-ph|hep-ex|hep-lat|cond-mat|astro-ph|math-ph|gr-qc|"
    r"nucl-th|nucl-ex|cs|math|physics|q-bio|q-fin|stat|econ|eess|nlin|comp|"
    r"e-print)(?:\.[A-Z]{2})?/\d{7})(?:v\d+)?"
)


def normalize_arxiv_id(value: Optional[str]) -> Optional[str]:
    """把任意包含 arXiv ID 的字符串归一化成不带版本号的 ID。"""
    if not value:
        return None
    m = _ARXIV_NEW.search(value) or _ARXIV_OLD.search(value)
    return m.group(1) if m else None


def normalize_url(url: str) -> str:
    """去掉 URL 锚点和跟踪参数，避免同一页面出现多个 URL。"""
    if not url:
        return ""
    url = str(url).strip().split("#")[0]
    if "?" in url:
        base, _, query = url.partition("?")
        keep = [
            part for part in query.split("&")
            if part and not part.startswith(("utm_", "ref=", "source=", "spm="))
        ]
        url = base + ("?" + "&".join(keep) if keep else "")
    return url


_NEWS_TITLE_NOISE = (
    " - skip to main content", " | skip to main content", "- skip to main content",
    " - loading", " | loading", " - loading...", "skip to main content",
)


def clean_title(title: str) -> str:
    """清理搜索结果标题里的网页导航噪音。"""
    text = str(title or "").strip()
    low = text.lower()
    for noise in _NEWS_TITLE_NOISE:
        idx = low.find(noise)
        if idx != -1:
            text = text[:idx].rstrip(" -|·")
            low = text.lower()
    return squash_ws(text)


def normalize_title(title: str) -> str:
    """标题归一化，用于跨源去重。"""
    text = unicodedata.normalize("NFKC", title or "").lower()
    # 只保留字母、数字和中文，去掉标点与空白，避免「A: B」和「A - B」被当成两篇
    text = re.sub(r"[^0-9a-z\u4e00-\u9fff]+", "", text)
    return text


@dataclass
class Paper:
    """跨数据源统一的论文条目。"""

    title: str
    url: str = ""
    source: str = ""  # arxiv | scirate | search
    abstract: str = ""
    authors: list[str] = field(default_factory=list)
    arxiv_id: Optional[str] = None
    published: Optional[datetime] = None
    scites: int = 0
    scirate_rank: Optional[int] = None  # 1 表示当天票数最高
    search_score: Optional[float] = None  # DeepSeek 搜索 rerank_score，0~3
    authority: int = -1  # DeepSeek 搜索返回的权威性，0~4
    venue: str = ""
    llm_score: Optional[float] = None  # 0~10
    llm_reason: str = ""
    tags: list[str] = field(default_factory=list)
    combined_score: float = 0.0
    direction: str = ""  # 关注方向标签：QRC / 量子算法
    deep_dive: dict = field(default_factory=dict)  # 深度解读内容（标题翻译/方法/结果等）
    sources: set[str] = field(default_factory=set)

    def __post_init__(self) -> None:
        self.title = clean_title(self.title)
        self.url = normalize_url(self.url)
        if not self.arxiv_id:
            self.arxiv_id = normalize_arxiv_id(self.url) or normalize_arxiv_id(self.title)
        if self.source:
            self.sources.add(self.source)
        if not self.url and self.arxiv_id:
            self.url = f"https://arxiv.org/abs/{self.arxiv_id}"
        if self.arxiv_id and "/abs/" not in self.url and "/pdf/" not in self.url:
            self.url = f"https://arxiv.org/abs/{self.arxiv_id}"

    @property
    def dedup_key(self) -> str:
        """跨源去重键：优先 arXiv ID，没有则用归一化标题。"""
        if self.arxiv_id:
            return f"arxiv:{self.arxiv_id}"
        return f"title:{normalize_title(self.title)}"

    def merge(self, other: "Paper") -> None:
        """把同一条论文的另一个来源合并进来，保留信息更全的字段。"""
        self.sources |= other.sources
        # Scirate Markdown 路径可能只有占位标题，合并时用真实标题覆盖
        if (not self.title or self.title.startswith("arXiv:")) and other.title and not other.title.startswith("arXiv:"):
            self.title = other.title
        if not self.abstract and other.abstract:
            self.abstract = other.abstract
        if not self.authors and other.authors:
            self.authors = other.authors
        if self.scirate_rank is None or (
            other.scirate_rank is not None and other.scirate_rank < self.scirate_rank
        ):
            if other.scirate_rank is not None:
                self.scirate_rank = other.scirate_rank
                self.scites = max(self.scites, other.scites)
        if other.scites > self.scites:
            self.scites = other.scites
        if self.search_score is None or (
            other.search_score is not None and other.search_score > self.search_score
        ):
            self.search_score = other.search_score if other.search_score is not None else self.search_score
        if other.authority > self.authority:
            self.authority = other.authority
        if self.published is None and other.published is not None:
            self.published = other.published
        if not self.venue and other.venue:
            self.venue = other.venue
        if not self.url and other.url:
            self.url = other.url
        # 合并来源标记到 tags 便于日报展示
        for src in other.sources:
            if src not in self.tags:
                self.tags.append(src)

    def to_dict(self) -> dict:
        return {
            "title": self.title,
            "url": self.url,
            "arxiv_id": self.arxiv_id,
            "sources": sorted(self.sources),
            "scites": self.scites,
            "scirate_rank": self.scirate_rank,
            "search_score": self.search_score,
            "llm_score": self.llm_score,
            "llm_reason": self.llm_reason,
            "tags": self.tags,
            "combined_score": round(self.combined_score, 3),
            "direction": self.direction,
            "published": self.published.isoformat() if self.published else None,
        }
