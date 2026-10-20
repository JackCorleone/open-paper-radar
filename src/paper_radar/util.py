"""通用工具：日志、日期、文本清洗、分块。"""

from __future__ import annotations

import html
import logging
import os
import re
import sys
from datetime import date, datetime, timedelta, timezone
from typing import Iterable, Iterator, TypeVar

T = TypeVar("T")

DEFAULT_TZ = timezone(timedelta(hours=8))  # Asia/Shanghai，无夏令时


def setup_logging(verbose: bool = False) -> None:
    """配置标准错误输出日志，GitHub Actions 里也能直接看到。"""
    level = logging.DEBUG if verbose else logging.INFO
    logging.basicConfig(
        level=level,
        format="%(asctime)s %(levelname)-7s %(message)s",
        datefmt="%H:%M:%S",
        stream=sys.stderr,
        force=True,
    )


def get_logger(name: str) -> logging.Logger:
    return logging.getLogger(name)


def now_tz() -> datetime:
    """当前时间（优先使用 TZ 环境变量指定的时区）。"""
    return datetime.now(timezone.utc).astimezone(local_tz())


def local_tz() -> timezone:
    name = os.environ.get("RADAR_TZ", "Asia/Shanghai")
    if name in ("Asia/Shanghai", "UTC+8", "PRC"):
        return DEFAULT_TZ
    return DEFAULT_TZ


def today() -> date:
    return now_tz().date()


def replace_date_placeholders(text: str, base: date | None = None) -> str:
    """把配置里的 {today}、{date_minus_N} 替换成实际日期。"""
    if not text:
        return text
    base = base or today()

    def _fmt(d: date) -> str:
        return d.isoformat()

    text = text.replace("{today}", _fmt(base))
    for n in range(0, 31):
        text = text.replace(f"{{date_minus_{n}}}", _fmt(base - timedelta(days=n)))
    # 兼容 {yesterday}
    text = text.replace("{yesterday}", _fmt(base - timedelta(days=1)))
    # 兼容 {last_week}
    text = text.replace("{last_week}", _fmt(base - timedelta(days=7)))
    return text


def strip_html(text: str) -> str:
    """去掉 HTML 标签并反转义实体，用于清洗摘要。"""
    if not text:
        return ""
    text = re.sub(r"(?is)<(script|style).*?</\1>", " ", text)
    text = re.sub(r"(?i)<br\s*/?>", "\n", text)
    text = re.sub(r"(?i)</p>", "\n", text)
    text = re.sub(r"<[^>]+>", "", text)
    text = html.unescape(text)
    text = re.sub(r"[ \t\u00a0]+", " ", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def squash_ws(text: str) -> str:
    """把换行和连续空白压成单个空格，适合做短摘要。"""
    return re.sub(r"\s+", " ", text or "").strip()


def truncate(text: str, limit: int, ellipsis: str = "…") -> str:
    text = text or ""
    if len(text) <= limit:
        return text
    return text[: max(0, limit - len(ellipsis))].rstrip() + ellipsis


def chunked(items: Iterable[T], size: int) -> Iterator[list[T]]:
    """把可迭代对象切成长度为 size 的块。"""
    buf: list[T] = []
    for item in items:
        buf.append(item)
        if len(buf) >= size:
            yield buf
            buf = []
    if buf:
        yield buf


def parse_date_loose(value: str | None) -> datetime | None:
    """宽松解析 RFC 3339 / 常见日期字符串。"""
    if not value:
        return None
    raw = value.strip()
    candidates = [raw]
    if raw.endswith("Z"):
        candidates.append(raw[:-1] + "+00:00")
    for cand in candidates:
        try:
            dt = datetime.fromisoformat(cand)
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)
            return dt
        except ValueError:
            continue
    for fmt in ("%Y-%m-%d", "%Y/%m/%d", "%Y-%m-%dT%H:%M:%S", "%d %b %Y", "%b %d %Y"):
        try:
            return datetime.strptime(raw, fmt).replace(tzinfo=timezone.utc)
        except ValueError:
            continue
    return None


def ensure_dir(path: str) -> str:
    os.makedirs(path, exist_ok=True)
    return path


def env(name: str, default: str | None = None) -> str | None:
    value = os.environ.get(name)
    if value is None or value.strip() == "":
        return default
    return value.strip()


def env_bool(name: str, default: bool = False) -> bool:
    value = env(name)
    if value is None:
        return default
    return value.lower() in ("1", "true", "yes", "on")
