"""Scirate 数据源。

Scirate 的默认列表页就是「当日论文按 scites 票数降序」，因此页面顺序即排名。
它的站点被 Cloudflare 的 managed challenge 保护，普通 HTTP 客户端会拿到 403。
抓取策略按顺序降级：

1. 直连 scirate.com（本机/某些出口 IP 可能直接可用）
2. 通过 DeepSeek Fetch API 由服务端抓取（很多情况下能绕过本机出口限制）
3. 都失败则由上层用 arXiv + LLM 排序兜底

页面结构来自 Scirate 开源仓库的 app/views/papers/_paper.html.slim：
  li.paper
    .title > a[href=/arxiv/<id>]      标题
    .authors > a                       作者
    .uid                               "Oct 19 2026 quant-ph arXiv:2610.22476v1"
    .scites-count > button.count       票数
"""

from __future__ import annotations

import re
from datetime import datetime
from html.parser import HTMLParser
from typing import Iterable, Optional

from ..http import HttpError, request
from ..models import Paper, normalize_arxiv_id
from ..util import get_logger, parse_date_loose, squash_ws, strip_html

log = get_logger(__name__)

SCIRATE_BASE = "https://scirate.com"


class ScirateUnavailable(RuntimeError):
    """所有抓取路径都失败。"""


class _PaperHTMLParser(HTMLParser):
    """从 Scirate 列表页 HTML 中按出现顺序提取论文。"""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.papers: list[dict] = []
        self._current: Optional[dict] = None
        self._stack: list[str] = []  # 当前标签栈（只记录关心的 div/li/a/button）
        self._field: Optional[str] = None
        self._field_depth = 0
        self._in_title_link = False
        self._in_author_link = False
        self._capture: list[str] = []
        self._authors: list[str] = []

    # --- 工具 ---
    @staticmethod
    def _classes(attrs) -> set[str]:
        for key, value in attrs:
            if key == "class" and value:
                return set(value.split())
        return set()

    @staticmethod
    def _attr(attrs, name: str) -> Optional[str]:
        for key, value in attrs:
            if key == name:
                return value
        return None

    def handle_starttag(self, tag: str, attrs) -> None:
        classes = self._classes(attrs)

        if tag == "li" and "paper" in classes:
            self._flush_current()
            self._current = {"title": "", "url": "", "owners": [], "scites": 0, "uid_text": ""}
            self._authors = []
            self._field = None
            self._in_title_link = False
            return

        if self._current is None:
            return

        if tag == "div":
            if "title" in classes:
                self._field, self._field_depth = "title", 1
            elif "authors" in classes:
                self._field, self._field_depth = "authors", 1
            elif "uid" in classes:
                self._field, self._field_depth = "uid", 1
            elif "scites-count" in classes:
                self._field, self._field_depth = "scites", 1
            elif self._field:
                self._field_depth += 1
            return

        if tag == "a" and self._field == "title":
            self._in_title_link = True
            href = self._attr(attrs, "href") or ""
            if self._current and not self._current["url"] and "/arxiv/" in href:
                self._current["url"] = SCIRATE_BASE + href if href.startswith("/") else href
            return

        if tag == "a" and self._field == "authors":
            self._in_author_link = True
            return

        if tag == "button" and self._field == "scites" and "count" in classes:
            self._capture = []
            return

    def handle_endtag(self, tag: str) -> None:
        if self._current is None:
            return
        if tag == "a":
            if self._in_title_link:
                text = squash_ws(strip_html("".join(self._capture)))
                if text and not self._current["title"]:
                    self._current["title"] = text
                self._capture = []
                self._in_title_link = False
            elif self._in_author_link:
                text = squash_ws(strip_html("".join(self._capture)))
                if text:
                    self._authors.append(text)
                self._capture = []
                self._in_author_link = False
            return
        if tag == "button" and self._field == "scites":
            text = squash_ws("".join(self._capture))
            m = re.search(r"\d+", text)
            if m and self._current is not None:
                self._current["scites"] = int(m.group(0))
            self._capture = []
            return
        if tag == "div":
            if self._field and self._field_depth > 0:
                self._field_depth -= 1
                if self._field_depth == 0:
                    if self._field == "uid":
                        self._capture = []
                    self._field = None
            return
        if tag == "li":
            self._flush_current()

    def handle_data(self, data: str) -> None:
        if self._current is None:
            return
        if self._field == "title":
            if self._in_title_link:
                self._capture.append(data)
        elif self._field == "authors":
            if self._in_author_link:
                self._capture.append(data)
        elif self._field == "uid":
            self._capture.append(data)
            self._current["uid_text"] = squash_ws("".join(self._capture))
        elif self._field == "scites":
            self._capture.append(data)

    def _flush_current(self) -> None:
        if not self._current:
            return
        cur = self._current
        self._current = None
        if cur.get("title"):
            cur["owners"] = self._authors
            self.papers.append(cur)


def parse_scirate_html(html: str) -> list[dict]:
    """解析 Scirate 列表页 HTML，返回按页面顺序排列的论文。"""
    parser = _PaperHTMLParser()
    try:
        parser.feed(html)
        parser.close()
    except Exception as exc:  # noqa: BLE001 - 容忍残缺 HTML
        log.warning("Scirate HTML 解析中断：%s", exc)
    # 兜底：某些页面结构下 li 闭合不规范，扫描遗留项
    return [p for p in parser.papers if p.get("title")]


_ARXIV_LINK = re.compile(r"(?:https?://(?:www\.)?scirate\.com)?/arxiv/(\d{4}\.\d{4,5}|[a-z\-]+(?:\.[A-Z]{2})?/\d{7})(?:v\d+)?")
_MD_LINK = re.compile(r"\[([^\]]{3,300})\]\(([^)\s]+)\)")


def parse_scirate_markdown(markdown: str) -> list[dict]:
    """解析 DeepSeek Fetch 返回的 Markdown。

    无法保证票数字段被保留，但页面顺序 == 票数排名，所以按 arXiv 链接首次出现的顺序提取即可。
    """
    papers: list[dict] = []
    seen: set[str] = set()
    for line in (markdown or "").splitlines():
        matches = list(_MD_LINK.finditer(line))
        if not matches:
            find = _ARXIV_LINK.search(line)
            if find:
                aid = normalize_arxiv_id(find.group(0))
                if aid and aid not in seen:
                    seen.add(aid)
                    papers.append({"title": "", "url": f"{SCIRATE_BASE}/arxiv/{aid}", "scites": 0,
                                   "uid_text": f"arXiv:{aid}"})
            continue
        for m in matches:
            text, href = m.group(1), m.group(2)
            find = _ARXIV_LINK.search(href) or _ARXIV_LINK.search(line)
            if not find:
                continue
            aid = normalize_arxiv_id(find.group(0))
            if not aid or aid in seen:
                continue
            seen.add(aid)
            # 标题链接一般文本较长；过滤 "Scite!"、"pdf" 之类的按钮文本
            title = squash_ws(strip_html(text))
            if len(title) < 8 or title.lower() in {"scite", "scite!", "unscite", "comments", "pdf"}:
                title = ""
            papers.append({
                "title": title,
                "url": f"{SCIRATE_BASE}/arxiv/{aid}",
                "scites": 0,
                "uid_text": f"arXiv:{aid}",
            })
            break  # 每行只取第一篇，避免把正文里的链接算进来
    return papers


def _rows_to_papers(rows: Iterable[dict], feed: str, top_n: int) -> list[Paper]:
    papers: list[Paper] = []
    for rank, row in enumerate(rows, start=1):
        if len(papers) >= top_n:
            break
        aid = normalize_arxiv_id(row.get("uid_text") or "") or normalize_arxiv_id(row.get("url") or "")
        if not aid:
            continue
        title = row.get("title") or ""
        if not title:
            # Markdown 路径没有标题时，用 arXiv ID 占位，之后由 arXiv 数据源合并补齐
            title = f"arXiv:{aid}"
        published = parse_date_loose(_extract_date(row.get("uid_text") or ""))
        paper = Paper(
            title=title,
            url=f"https://arxiv.org/abs/{aid}",
            arxiv_id=aid,
            source="scirate",
            authors=list(row.get("owners") or []),
            scites=int(row.get("scites") or 0),
            scirate_rank=rank,
            published=published,
            venue=f"scirate/{feed}",
        )
        papers.append(paper)
    return papers


def _extract_date(uid_text: str) -> Optional[str]:
    """uid 文本形如 "Oct 19 2026 quant-ph arXiv:2610.22476v1"。"""
    m = re.search(r"([A-Z][a-z]{2}\s+\d{1,2}\s+\d{4})", uid_text or "")
    return m.group(1) if m else None


def fetch_direct(feed: str, timeout: float) -> str:
    """直接访问 Scirate；被 Cloudflare 拦截时抛 HttpError(403)。"""
    url = f"{SCIRATE_BASE}/{feed}"
    return request(
        url,
        headers={
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            "Accept-Language": "en-US,en;q=0.9",
        },
        timeout=timeout,
        retries=1,
    )


def fetch_via_deepseek(feed: str, fetch_fn, timeout: float) -> str:
    """通过 DeepSeek Fetch API 抓取，返回页面 Markdown 正文。"""
    url = f"{SCIRATE_BASE}/{feed}"
    payload = fetch_fn(url)
    content = payload.get("content") or ""
    if not content.strip():
        raise ScirateUnavailable("DeepSeek Fetch 返回空正文")
    return content


def get_scirate_papers(
    feed: str = "quant-ph",
    top_n: int = 10,
    timeout: float = 30.0,
    fetch_fn=None,
    use_deepseek_fetch: bool = True,
) -> tuple[list[Paper], str]:
    """抓取 Scirate 当日榜单，返回 (论文列表, 实际使用的通道)。

    通道取值：direct / deepseek_fetch；全部失败时抛 ScirateUnavailable。
    """
    errors: list[str] = []

    # 路径 1：直连（本机出口未被拦时最快）
    try:
        html = fetch_direct(feed, timeout)
        rows = parse_scirate_html(html)
        if rows:
            papers = _rows_to_papers(rows, feed, top_n)
            if papers:
                log.info("Scirate 直连成功：%s 前 %d 篇", feed, len(papers))
                return papers, "direct"
        errors.append("直连成功但未解析出论文")
    except HttpError as exc:
        errors.append(f"直连失败 HTTP {exc.status}")
        log.warning("Scirate 直连失败（HTTP %s），尝试 DeepSeek Fetch", exc.status)
    except Exception as exc:  # noqa: BLE001
        errors.append(f"直连异常 {type(exc).__name__}: {exc}")
        log.warning("Scirate 直连异常：%s", exc)

    # 路径 2：DeepSeek Fetch（服务端抓取）
    if fetch_fn is not None and use_deepseek_fetch:
        try:
            markdown = fetch_via_deepseek(feed, fetch_fn, timeout)
            rows = parse_scirate_markdown(markdown)
            if rows:
                papers = _rows_to_papers(rows, feed, top_n)
                if papers:
                    log.info("Scirate 经 DeepSeek Fetch 成功：%s 前 %d 篇", feed, len(papers))
                    return papers, "deepseek_fetch"
            errors.append("DeepSeek Fetch 返回内容中未解析出论文")
        except Exception as exc:  # noqa: BLE001
            errors.append(f"DeepSeek Fetch 失败 {type(exc).__name__}: {exc}")
            log.warning("Scirate 经 DeepSeek Fetch 失败：%s", exc)

    raise ScirateUnavailable("；".join(errors) or "未知原因")
