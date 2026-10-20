"""跨天去重状态。

GitHub Actions 是无状态的，所以状态文件必须提交回仓库（workflow 里会 git commit），
或者挂到 actions/cache。本项目选择提交回仓库，简单可查。
"""

from __future__ import annotations

import json
import os
from datetime import date, datetime, timedelta, timezone

from .models import Paper
from .util import ensure_dir, get_logger

log = get_logger(__name__)

STATE_VERSION = 1
KEEP_DAYS = 180


class SeenStore:
    """记录已经推送过的论文，避免第二天重复推送。"""

    def __init__(self, path: str) -> None:
        self.path = path
        self._seen: dict[str, str] = {}
        self._updated_at: str = ""
        self.load()

    def load(self) -> None:
        if not os.path.exists(self.path):
            return
        try:
            with open(self.path, encoding="utf-8") as fh:
                data = json.load(fh)
            seen = data.get("seen") or {}
            if isinstance(seen, dict):
                self._seen = {str(k): str(v) for k, v in seen.items()}
            self._updated_at = str(data.get("updated_at") or "")
        except (json.JSONDecodeError, OSError) as exc:
            log.warning("读取去重状态失败（当作空状态）：%s", exc)
            self._seen = {}

    def is_seen(self, paper: Paper) -> bool:
        return paper.dedup_key in self._seen

    def first_seen(self, paper: Paper) -> str | None:
        return self._seen.get(paper.dedup_key)

    def mark(self, paper: Paper, run_date: date | None = None) -> None:
        self._seen[paper.dedup_key] = (run_date or date.today()).isoformat()

    def mark_many(self, papers: list[Paper], run_date: date | None = None) -> None:
        for paper in papers:
            self.mark(paper, run_date)

    def prune(self, keep_days: int = KEEP_DAYS) -> int:
        """删除过旧记录，返回删除条数。"""
        cutoff = (datetime.now(timezone.utc) - timedelta(days=keep_days)).date()
        old = []
        for key, value in self._seen.items():
            try:
                seen_date = date.fromisoformat(value)
            except ValueError:
                old.append(key)
                continue
            if seen_date < cutoff:
                old.append(key)
        for key in old:
            del self._seen[key]
        return len(old)

    def save(self) -> None:
        ensure_dir(os.path.dirname(self.path) or ".")
        payload = {
            "version": STATE_VERSION,
            "updated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "count": len(self._seen),
            "seen": dict(sorted(self._seen.items())),
        }
        tmp = self.path + ".tmp"
        with open(tmp, "w", encoding="utf-8") as fh:
            json.dump(payload, fh, ensure_ascii=False, indent=1)
            fh.write("\n")
        os.replace(tmp, self.path)

    def __len__(self) -> int:
        return len(self._seen)
