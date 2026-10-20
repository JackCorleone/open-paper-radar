"""配置加载：config/topics.json + 环境变量。"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

from .util import env, get_logger

log = get_logger(__name__)

DEFAULT_CONFIG_REL = Path("config") / "topics.json"


class ConfigError(RuntimeError):
    """配置缺失或格式错误。"""


def project_root() -> Path:
    """定位项目根目录。

    源码布局是 <root>/src/paper_radar/config.py，因此向上两级。
    允许用 RADAR_ROOT 覆盖（例如安装成包后）。
    """
    override = env("RADAR_ROOT")
    if override:
        return Path(override).expanduser().resolve()
    return Path(__file__).resolve().parents[2]


@dataclass
class Config:
    root: Path
    topics: dict
    config_path: Path
    api_key: str = ""
    base_url: str = "https://api.deepseek.com"
    state_file: Path = None  # type: ignore[assignment]
    reports_dir: Path = None  # type: ignore[assignment]
    timezone: str = "Asia/Shanghai"

    # --- 便捷访问 ---
    @property
    def report_cfg(self) -> dict:
        return self.topics.get("report") or {}

    @property
    def focus(self) -> str:
        focus = self.topics.get("focus") or {}
        return focus.get("description") or "量子信息与量子机器学习"

    @property
    def focus_hint(self) -> str:
        focus = self.topics.get("focus") or {}
        return focus.get("must_read_hint") or ""

    @property
    def keywords(self) -> dict:
        return self.topics.get("keywords") or {}

    @property
    def directions(self) -> list[dict]:
        return self.topics.get("directions") or []

    @property
    def llm_cfg(self) -> dict:
        return self.topics.get("llm") or {}

    @property
    def notify_cfg(self) -> dict:
        return self.topics.get("notify") or {}

    @property
    def timezone_name(self) -> str:
        return self.topics.get("timezone") or "Asia/Shanghai"


def load_config(path: Optional[str] = None) -> Config:
    root = project_root()
    config_path = Path(path).expanduser() if path else root / DEFAULT_CONFIG_REL
    if not config_path.is_absolute():
        config_path = (root / config_path).resolve()
    if not config_path.exists():
        raise ConfigError(f"找不到配置文件：{config_path}")

    try:
        topics = json.loads(config_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise ConfigError(f"配置文件不是合法 JSON：{config_path} -> {exc}") from None

    state_env = env("RADAR_STATE_FILE")
    reports_env = env("RADAR_REPORTS_DIR")
    state_file = Path(state_env).expanduser() if state_env else root / "data" / "state" / "seen.json"
    reports_dir = Path(reports_env).expanduser() if reports_env else root / "reports"

    return Config(
        root=root,
        topics=topics,
        config_path=config_path,
        api_key=env("DEEPSEEK_API_KEY") or "",
        base_url=env("DEEPSEEK_BASE_URL") or "https://api.deepseek.com",
        state_file=state_file,
        reports_dir=reports_dir,
        timezone=topics.get("timezone") or "Asia/Shanghai",
    )
