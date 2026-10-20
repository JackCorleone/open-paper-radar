#!/usr/bin/env python3
"""环境体检：逐项检查 key、数据源连通性、Scirate 抓取路径和推送渠道。

用法：
    python3 scripts/check.py

不生成日报、不推送，只做连通性验证，适合首次配置后确认。
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))


def load_dotenv(path: Path) -> None:
    if not path.exists():
        return
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        key, value = key.strip(), value.strip().strip('"').strip("'")
        if key and key not in os.environ:
            os.environ[key] = value


def ok(msg: str) -> None:
    print(f"  ✅ {msg}")


def warn(msg: str) -> None:
    print(f"  ⚠️  {msg}")


def fail(msg: str) -> None:
    print(f"  ❌ {msg}")


def main() -> int:
    load_dotenv(ROOT / ".env")

    from paper_radar.config import load_config
    from paper_radar.deepseek import DeepSeekClient
    from paper_radar.notify import detect_provider
    from paper_radar.sources import arxiv, scirate
    import logging

    from paper_radar.util import setup_logging

    setup_logging(False)
    # 体检只关心结果，把内部模块的 INFO/WARNING 日志压掉
    logging.getLogger().setLevel(logging.ERROR)
    cfg = load_config()

    print(f"\n项目目录：{cfg.root}")
    print(f"配置文件：{cfg.config_path}")
    print(f"研究方向：{cfg.focus[:60]}…\n")

    problems = 0

    # 1. DeepSeek Key
    print("[1/6] DeepSeek API Key")
    client = DeepSeekClient(cfg.api_key, cfg.base_url, timeout=30)
    if not client.available:
        fail("未配置 DEEPSEEK_API_KEY（复制 .env.example 为 .env 并填写）")
        problems += 1
    else:
        ok(f"已配置（{cfg.api_key[:6]}…{cfg.api_key[-4:]}）")
        try:
            results = client.search("quantum reservoir computing", count=3)
            ok(f"Search API 可用，返回 {len(results)} 条结果（本次调用计费 1 次）")
        except Exception as exc:  # noqa: BLE001
            fail(f"Search API 调用失败：{exc}")
            problems += 1

    # 2. Scirate 抓取路径
    print("\n[2/6] Scirate 抓取（三条路径依次降级）")
    fetch_fn = client.fetch if client.available else None
    try:
        timeout = float((cfg.topics.get("scirate") or {}).get("timeout_seconds", 30))
        papers, channel = scirate.get_scirate_papers("quant-ph", top_n=10, timeout=timeout, fetch_fn=fetch_fn)
        label = {"direct": "直连", "deepseek_fetch": "DeepSeek Fetch"}.get(channel, channel)
        ok(f"抓取成功（通道：{label}），拿到 {len(papers)} 篇，第 1 名：{papers[0].title[:50]}")
        print(f"      第 1 名链接：{papers[0].url}")
    except Exception as exc:  # noqa: BLE001
        fail(f"Scirate 抓取失败：{exc}")
        warn("日报会降级为「arXiv + AI 排序」，不影响整体运行，但热榜区块会缺失")
        problems += 1

    # 3. arXiv
    print("\n[3/6] arXiv 数据源")
    conf = cfg.topics.get("arxiv") or {}
    arxiv_papers = []
    try:
        arxiv_papers = arxiv.get_arxiv_papers(
            conf.get("categories") or ["quant-ph"],
            max_results=30,
            lookback_hours=int(conf.get("lookback_hours", 72)),
        )
        if arxiv_papers:
            ok(f"可用，近 {conf.get('lookback_hours', 72)}h 内抓到 {len(arxiv_papers)} 篇")
        else:
            warn("没有抓到论文（可能是周末 arXiv 不更新，或 API 限流）")
    except Exception as exc:  # noqa: BLE001
        fail(f"arXiv 不可用：{exc}")
        problems += 1

    # 4. 全文抓取（深度解读链路）
    print("\n[4/6] 论文全文抓取（深度解读依赖）")
    from paper_radar.sources.fulltext import fetch_fulltext

    if not arxiv_papers:
        warn("没有候选论文，跳过全文抓取检查")
    else:
        target = next((p for p in arxiv_papers if p.arxiv_id), None)
        if target and target.arxiv_id:
            try:
                ft = fetch_fulltext(target.arxiv_id, client=client if client.available else None, timeout=45)
                if ft.has_body:
                    ok(f"全文可用（来源：{ft.source}），{target.arxiv_id} 解析出 {len(ft.sections)} 个章节"
                       f"、{len(ft.authors)} 位作者")
                else:
                    warn(f"{target.arxiv_id} 没有可用的 HTML 全文，深度解读会降级为「基于摘要」")
            except Exception as exc:  # noqa: BLE001
                fail(f"全文抓取异常：{exc}")
                problems += 1
        else:
            warn("候选论文没有 arXiv ID，跳过")

    # 5. 推送渠道
    print("\n[5/6] 推送渠道")
    preferred = (cfg.notify_cfg or {}).get("provider", "auto")
    provider = detect_provider(preferred)
    if provider:
        ok(f"已配置：{provider}")
        print("      提示：正式运行会真的发消息；想先看内容用 scripts/run.py --dry-run")
    else:
        fail("没有配置任何推送渠道（推荐填 PUSHPLUS_TOKEN）")
        problems += 1

    # 6. 状态文件
    print("\n[6/6] 去重状态")
    if cfg.state_file.exists():
        ok(f"已存在：{cfg.state_file}（{cfg.state_file.stat().st_size} 字节）")
    else:
        warn(f"尚未创建：{cfg.state_file}（首次正式运行后生成）")

    print()
    if problems == 0:
        print("全部检查通过，可以正式运行：python3 scripts/run.py\n")
        return 0
    print(f"有 {problems} 项需要处理，见上方 ❌ / ⚠️ 提示。\n")
    return 1


if __name__ == "__main__":
    sys.exit(main())
