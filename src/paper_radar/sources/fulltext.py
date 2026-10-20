"""arXiv 全文抓取与结构化解析。

用于「重点论文深度解读」：需要正文、作者机构、摘要。
抓取路径：
1. https://arxiv.org/html/<id>     新版 arXiv 的 HTML 全文（含 MathML，alttext 里有 LaTeX）
2. https://ar5iv.labs.arxiv.org/html/<id>  老论文的 ar5iv 渲染
3. 都失败则降级为摘要，深度解读会标注「基于摘要」
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from html.parser import HTMLParser
from typing import Optional

from ..http import HttpError, request
from ..util import get_logger, squash_ws, truncate

log = get_logger(__name__)

HTML_URL = "https://arxiv.org/html/{arxiv_id}"
AR5IV_URL = "https://ar5iv.labs.arxiv.org/html/{arxiv_id}"

# 这些章节不进入深度解读的输入
SKIP_SECTIONS = (
    "references",
    "bibliography",
    "acknowledg",
    "statements and declarations",
    "appendix",
    "supplementary",
)


@dataclass
class FullText:
    arxiv_id: str
    title: str = ""
    authors: list[dict] = field(default_factory=list)  # [{"name": str, "affiliations": [str]}]
    abstract: str = ""
    sections: list[dict] = field(default_factory=list)  # [{"heading": str, "text": str}]
    source: str = "none"  # arxiv_html | ar5iv | deepseek_fetch | none
    url: str = ""

    @property
    def has_body(self) -> bool:
        return bool(self.sections)

    def to_prompt_text(self, max_chars: int = 60000) -> str:
        """拼成给 LLM 的正文，按章节重要程度分配长度。"""
        parts: list[str] = []
        if self.abstract:
            parts.append("【摘要】\n" + self.abstract)
        if self.sections:
            for section in self.sections:
                heading = section.get("heading", "")
                text = section.get("text", "")
                if not text:
                    continue
                low = heading.lower()
                if any(k in low for k in ("introduction", "conclusion", "discussion")):
                    budget = 9000
                elif any(k in low for k in ("method", "result", "experiment", "analysis", "main")):
                    budget = 8000
                else:
                    budget = 4000
                parts.append(f"【{heading}】\n{truncate(text, budget)}")
                if sum(len(p) for p in parts) > max_chars:
                    parts.append("……（全文过长，后续章节已省略）")
                    break
        return truncate("\n\n".join(parts), max_chars)


class _ArxivHTMLParser(HTMLParser):
    """解析 arXiv HTML 全文页。MathML 的 alttext 属性里带 LaTeX，可直接还原公式。"""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.title = ""
        self.authors: list[dict] = []
        self.abstract = ""
        self.sections: list[dict] = []

        self._page = False
        # 作者
        self._in_authors = False
        self._cur_author: Optional[dict] = None
        self._mode: Optional[str] = None  # title | personname | affiliation
        self._buf: list[str] = []
        self._span_level = 0
        self._mode_level = 0
        # 摘要
        self._in_abstract = False
        self._abstract_buf: list[str] = []
        # 章节
        self._in_section = False
        self._section: Optional[dict] = None
        self._section_buf: list[str] = []
        self._heading_buf: Optional[list[str]] = None
        # 杂项
        self._skip_math = False

    # ---- 文本收集 ----
    def _append(self, text: str) -> None:
        if not text:
            return
        if self._heading_buf is not None:
            self._heading_buf.append(text)
        elif self._mode in ("title", "personname", "affiliation"):
            self._buf.append(text)
        elif self._in_abstract:
            self._abstract_buf.append(text)
        elif self._in_section:
            self._section_buf.append(text)

    # ---- 开始标签 ----
    def handle_starttag(self, tag: str, attrs) -> None:
        attr = dict(attrs)
        cls = attr.get("class") or ""

        if tag == "math":
            alttext = attr.get("alttext")
            if alttext and not self._skip_math:
                self._append(f"${alttext}$")
                self._skip_math = True
            return
        if self._skip_math:
            return

        if tag == "div" and "ltx_page_main" in cls:
            self._page = True
            return
        if not self._page:
            return

        if tag == "h1" and "ltx_title_document" in cls:
            self._mode, self._buf = "title", []
            return
        if tag == "div" and "ltx_authors" in cls:
            self._in_authors = True
            return
        if tag == "span":
            self._span_level += 1
            if "ltx_creator" in cls and "ltx_role_author" in cls:
                self._flush_author()
                self._cur_author = {"name": "", "affiliations": []}
            elif "ltx_personname" in cls:
                self._mode, self._buf = "personname", []
                self._mode_level = self._span_level
            elif "ltx_contact" in cls and "ltx_role_affiliation" in cls:
                self._mode, self._buf = "affiliation", []
                self._mode_level = self._span_level
            return
        if tag == "div" and "ltx_abstract" in cls:
            self._in_abstract, self._abstract_buf = True, []
            return
        if tag == "section" and "ltx_section" in cls:
            self._flush_section()
            self._section = {"heading": "", "text": ""}
            self._in_section, self._section_buf = True, []
            return
        if tag == "h2" and "ltx_title_section" in cls:
            self._heading_buf = []
            return
        if tag in ("p", "figcaption", "li", "tr") and (self._in_abstract or self._in_section):
            self._append("\n")

    # ---- 结束标签 ----
    def handle_endtag(self, tag: str) -> None:
        if tag == "math" and self._skip_math:
            self._skip_math = False
            return
        if self._skip_math:
            return

        if tag == "h1" and self._mode == "title":
            raw = _clean_text("".join(self._buf))
            # 去掉标题里 Thanks 之类的脚注
            self.title = re.split(r"\s*(?:Thanks?|Corresponding author)", raw)[0].strip()
            self._mode, self._buf = None, []
            return
        if tag == "div" and self._in_authors:
            self._flush_author()
            self._in_authors = False
            return
        if tag == "span":
            if self._mode == "personname" and self._span_level == self._mode_level:
                if self._cur_author is not None:
                    self._cur_author["name"] = _clean_text("".join(self._buf))
                self._mode, self._buf = None, []
            elif self._mode == "affiliation" and self._span_level == self._mode_level:
                text = _clean_text("".join(self._buf))
                text = re.sub(r"^Affiliation:\s*", "", text, flags=re.I).strip()
                # 机构名压成单行，否则会把 Markdown 表格撑断
                text = squash_ws(text)
                if text and self._cur_author is not None:
                    affs = self._cur_author["affiliations"]
                    if text not in affs:
                        affs.append(text)
                self._mode, self._buf = None, []
            self._span_level = max(0, self._span_level - 1)
            return
        if tag == "div" and self._in_abstract:
            text = _clean_text("".join(self._abstract_buf))
            self.abstract = re.sub(r"^Abstract\s*", "", text, flags=re.I).strip()
            self._in_abstract = False
            return
        if tag == "h2" and self._heading_buf is not None:
            if self._section is not None:
                self._section["heading"] = _clean_text("".join(self._heading_buf))
            self._heading_buf = None
            return
        if tag == "section" and self._in_section:
            self._flush_section()
            return

    def handle_data(self, data: str) -> None:
        if not self._skip_math:
            self._append(data)

    # ---- 收尾 ----
    def _flush_author(self) -> None:
        if self._cur_author and self._cur_author.get("name"):
            self.authors.append(self._cur_author)
        self._cur_author = None

    def _flush_section(self) -> None:
        if self._section is not None:
            heading = self._section.get("heading", "")
            text = _clean_text("".join(self._section_buf))
            if heading and text and not any(skip in heading.lower() for skip in SKIP_SECTIONS):
                self.sections.append({"heading": heading, "text": text})
        self._section = None
        self._in_section = False
        self._section_buf = []


def _clean_text(text: str) -> str:
    """压缩空白、清理不可见字符，保留公式两侧的自然空格。"""
    text = text.replace("\u200b", "")
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r" *\n *", "\n", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def parse_arxiv_html(html: str) -> FullText:
    parser = _ArxivHTMLParser()
    try:
        parser.feed(html)
        parser.close()
    except Exception as exc:  # noqa: BLE001 - 容忍残缺 HTML
        log.warning("arXiv HTML 解析中断：%s", exc)
    ft = FullText(
        arxiv_id="",
        title=parser.title,
        authors=parser.authors,
        abstract=parser.abstract,
        sections=parser.sections,
    )
    if not ft.title:
        m = re.search(r"<title>(.*?)</title>", html, re.S | re.I)
        if m:
            ft.title = squash_ws(re.sub(r"<[^>]+>", "", m.group(1)))
    return ft


def _looks_like_arxiv_html(html: str) -> bool:
    return "ltx_page_main" in html or "ltx_section" in html


def fetch_fulltext(
    arxiv_id: str,
    client=None,
    timeout: float = 45.0,
    max_chars: int = 60000,
) -> FullText:
    """抓取并解析论文全文；全部失败时返回 source='none' 的空对象。"""
    for name, url in (("arxiv_html", HTML_URL), ("ar5iv", AR5IV_URL)):
        target = url.format(arxiv_id=arxiv_id)
        try:
            html = request(target, headers={"Accept": "text/html"}, timeout=timeout, retries=1)
        except HttpError as exc:
            log.warning("%s 抓取失败（HTTP %s）：%s", name, exc.status, target)
            continue
        if not _looks_like_arxiv_html(html):
            log.warning("%s 返回的不是全文页（可能没有 HTML 版）：%s", name, target)
            continue
        ft = parse_arxiv_html(html)
        if ft.has_body:
            ft.arxiv_id = arxiv_id
            ft.source = name
            ft.url = target
            log.info("全文抓取成功（%s）：%s，%d 个章节", name, arxiv_id, len(ft.sections))
            return ft

    # 直连失败时用 DeepSeek Fetch 再试一次
    if client is not None and getattr(client, "available", False):
        for name, url in (("arxiv_html", HTML_URL), ("ar5iv", AR5IV_URL)):
            target = url.format(arxiv_id=arxiv_id)
            try:
                data = client.fetch(target)
            except Exception as exc:  # noqa: BLE001
                log.warning("DeepSeek Fetch %s 失败：%s", target, exc)
                continue
            md = data.get("content") or ""
            if len(md) > 3000:
                ft = FullText(
                    arxiv_id=arxiv_id,
                    title=data.get("title") or "",
                    sections=[{"heading": "全文（Markdown）", "text": md}],
                    source="deepseek_fetch",
                    url=target,
                )
                log.info("全文经 DeepSeek Fetch 抓取成功：%s", arxiv_id)
                return ft

    log.warning("全文抓取失败，降级为摘要：%s", arxiv_id)
    return FullText(arxiv_id=arxiv_id, source="none")
