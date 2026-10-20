"""命令行入口：抓取 → 去重 → 精读 → 渲染 → 推送。

用法：
    PYTHONPATH=src python3 -m paper_radar run
    PYTHONPATH=src python3 -m paper_radar run --dry-run --no-llm
"""

from __future__ import annotations

import argparse
import sys
from datetime import date
from typing import Optional

from .config import Config, ConfigError, load_config
from .deepseek import DeepSeekClient
from .llm import score_papers
from .models import Paper
from .rank import ai_hot, final_rank, merge_papers, prefilter, tag_directions
from .pdf import generate_pdf, pdf_public_url, pdf_reports_dir
from .render import render_markdown, render_wechat, render_wechat_html
from .sources import arxiv, scirate, web_search
from .state import SeenStore
from .util import ensure_dir, get_logger, now_tz, setup_logging

log = get_logger(__name__)


def parse_args(argv: Optional[list[str]] = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        prog="paper-radar",
        description="每日量子论文雷达：Scirate 热榜 + arXiv 新论文 + DeepSeek 搜索，LLM 精读后微信推送。",
    )
    parser.add_argument("command", nargs="?", default="run", choices=["run"], help="子命令（默认 run）")
    parser.add_argument("--config", default=None, help="配置文件路径，默认 config/topics.json")
    parser.add_argument("--date", default=None, help="覆盖运行日期（YYYY-MM-DD），用于补跑")
    parser.add_argument("--dry-run", action="store_true", help="只渲染不推送、不写状态")
    parser.add_argument("--no-llm", action="store_true", help="跳过 LLM 精读")
    parser.add_argument("--no-notify", action="store_true", help="生成日报但不推送")
    parser.add_argument("--no-state", action="store_true", help="不读写去重状态")
    parser.add_argument("--no-deep-dive", action="store_true", help="跳过重点论文的全文深度解读")
    parser.add_argument("--verbose", "-v", action="store_true", help="输出调试日志")
    return parser.parse_args(argv)


def _run_scirate(cfg: Config, client: DeepSeekClient, scan: list[dict], warnings: list[str]) -> list[Paper]:
    conf = cfg.topics.get("scirate") or {}
    if not conf.get("enabled", True):
        return []
    top_n = int((cfg.report_cfg or {}).get("scirate_top_n", 10))
    timeout = float(conf.get("timeout_seconds", 30))
    fetch_fn = client.fetch if client.available else None
    papers: list[Paper] = []
    for feed in conf.get("feeds") or ["quant-ph"]:
        try:
            found, channel = scirate.get_scirate_papers(
                feed=feed, top_n=top_n, timeout=timeout, fetch_fn=fetch_fn,
                use_deepseek_fetch=bool(conf.get("use_deepseek_fetch", False)),
            )
            papers.extend(found)
            channel_label = "直连" if channel == "direct" else "DeepSeek Fetch"
            scan.append({"name": f"Scirate {feed}", "ok": True, "status": f"（{channel_label}）", "count": f"{len(found)} 篇"})
        except scirate.ScirateUnavailable as exc:
            log.warning("Scirate %s 不可用：%s", feed, exc)
            scan.append({"name": f"Scirate {feed}", "ok": False, "status": "Cloudflare 拦截/抓取失败", "count": "0"})
            warnings.append("Scirate 社区票数不可达，热榜改为按模型评分排序")
    return papers


def _run_arxiv(cfg: Config, scan: list[dict], warnings: list[str]) -> list[Paper]:
    conf = cfg.topics.get("arxiv") or {}
    if not conf.get("enabled", True):
        return []
    categories = conf.get("categories") or ["quant-ph"]
    max_results = int(conf.get("max_results", 200))
    lookback = int(conf.get("lookback_hours", 72))
    papers = arxiv.get_arxiv_papers(categories, max_results=max_results, lookback_hours=lookback)
    ok = bool(papers)
    scan.append(
        {
            "name": "arXiv " + "/".join(categories),
            "ok": ok,
            "status": f"（{lookback}h 内）" if ok else "API 限流且列表页失败",
            "count": f"{len(papers)} 篇",
        }
    )
    if not ok:
        warnings.append("arXiv 数据源不可用")
    return papers


def _run_search(cfg: Config, client: DeepSeekClient, scan: list[dict], warnings: list[str], run_date: date) -> list[Paper]:
    conf = cfg.topics.get("search") or {}
    if not conf.get("enabled", True):
        return []
    queries = conf.get("queries") or []
    if not client.available:
        scan.append({"name": "DeepSeek 搜索", "ok": False, "status": "未配置 API Key", "count": "0"})
        return []
    papers = web_search.search_papers(client, queries, base_date=run_date)
    scan.append(
        {
            "name": "DeepSeek 搜索",
            "ok": bool(queries),
            "status": f"（{len(queries)} 组查询）",
            "count": f"{len(papers)} 条",
        }
    )
    if not papers:
        warnings.append("DeepSeek 搜索没有返回结果")
    return papers


def _save_report(cfg: Config, run_date: date, markdown: str) -> str:
    ensure_dir(str(cfg.reports_dir))
    path = cfg.reports_dir / f"{run_date.isoformat()}.md"
    path.write_text(markdown, encoding="utf-8")
    return str(path)


def run(cfg: Config, args: argparse.Namespace) -> int:
    now = now_tz()
    run_date = date.fromisoformat(args.date) if args.date else now.date()
    log.info("开始运行：%s（时区 %s）", run_date.isoformat(), cfg.timezone_name)

    llm_conf = cfg.llm_cfg
    client = DeepSeekClient(
        api_key=cfg.api_key,
        base_url=cfg.base_url,
        timeout=float(llm_conf.get("timeout_seconds", 180)),
        model=str(llm_conf.get("model", "deepseek-chat")),
    )
    if not client.available:
        log.warning("未配置 DEEPSEEK_API_KEY：将跳过 Search / Fetch / LLM 精读，仅用规则排序")
    if args.no_llm:
        log.info("已禁用 LLM 精读（--no-llm）")

    warnings: list[str] = []
    scan: list[dict] = []

    # --- 抓取 ---
    scirate_papers = _run_scirate(cfg, client, scan, warnings)
    arxiv_papers = _run_arxiv(cfg, scan, warnings)
    search_papers = _run_search(cfg, client, scan, warnings, run_date)

    merged = merge_papers([scirate_papers, arxiv_papers, search_papers])
    tag_directions(merged, cfg.directions)
    log.info(
        "合并去重：Scirate %d + arXiv %d + 搜索 %d -> %d 篇",
        len(scirate_papers),
        len(arxiv_papers),
        len(search_papers),
        len(merged),
    )

    # --- 去重状态 ---
    if args.no_state:
        store = None
        new_papers = list(merged)
    else:
        store = SeenStore(str(cfg.state_file))
        new_papers = [p for p in merged if not store.is_seen(p)]
    log.info("新增（未推送过）：%d 篇 / 状态库 %d 条", len(new_papers), len(store) if store else 0)

    # --- LLM 精读（只处理新论文，控制成本）---
    candidates: list[Paper] = []
    if new_papers and not args.no_llm:
        candidates = prefilter(
            new_papers,
            cfg.keywords,
            max_candidates=int(llm_conf.get("max_candidates", 24)),
            scirate_top_n=int((cfg.report_cfg or {}).get("scirate_top_n", 10)),
        )
        log.info("规则预筛：%d 篇候选进入 LLM 精读", len(candidates))
        score_papers(
            client,
            candidates,
            focus=cfg.focus + (" " + cfg.focus_hint if cfg.focus_hint else ""),
            run_date=run_date,
            batch_size=int(llm_conf.get("batch_size", 8)),
            temperature=float(llm_conf.get("temperature", 0.2)),
        )
    elif new_papers and args.no_llm:
        candidates = []

    # --- 排序分组 ---
    report_conf = cfg.report_cfg
    max_items = int(report_conf.get("max_items", 14))
    scirate_top_n = int(report_conf.get("scirate_top_n", 10))
    groups = final_rank(
        all_papers=merged,
        new_papers=new_papers,
        keywords=cfg.keywords,
        max_items=max_items,
        scirate_top_n=scirate_top_n,
    )

    # --- Scirate 不可达时用 AI 热榜兜底 ---
    hot_source = "scirate"
    if not groups["scirate_hot"]:
        pool_all = list(new_papers)
        pool_keys = {p.dedup_key for p in pool_all}
        for paper in merged:
            if paper.dedup_key not in pool_keys:
                pool_all.append(paper)
                pool_keys.add(paper.dedup_key)
        fallback_hot = ai_hot(pool_all, top_n=scirate_top_n)
        if not fallback_hot:
            # 没有 LLM 分（比如当天没有新论文）时，退化为规则综合分排序
            ranked = sorted(pool_all, key=lambda p: p.combined_score, reverse=True)
            fallback_hot = ranked[:scirate_top_n]
            for rank, paper in enumerate(fallback_hot, start=1):
                paper.scirate_rank = rank
        if fallback_hot:
            groups["scirate_hot"] = fallback_hot
            hot_source = "ai"
            hot_keys = {p.dedup_key for p in fallback_hot}
            groups["highlights"] = [p for p in groups["highlights"] if p.dedup_key not in hot_keys]
            groups["worth_scanning"] = [p for p in groups["worth_scanning"] if p.dedup_key not in hot_keys]
            log.info("Scirate 不可达，已用 AI 评分生成今日热榜：%d 篇", len(fallback_hot))

    # --- 重点论文深度解读（抓全文 + LLM 三段式简报）---
    deep_dives: list[Paper] = []
    dd_conf = cfg.topics.get("deep_dive") or {}
    if (
        dd_conf.get("enabled", True)
        and not args.no_llm
        and not getattr(args, "no_deep_dive", False)
        and client.available
    ):
        from .deep_dive import deep_dive as make_deep_dive
        from .deep_dive import select_deep_dive
        from .sources.fulltext import fetch_fulltext

        # 候选池：今日精选 + 热榜里尚未推送过的论文
        pool: list[Paper] = list(groups["highlights"])
        seen_keys = {p.dedup_key for p in pool}
        for paper in groups["scirate_hot"]:
            if paper.dedup_key in seen_keys:
                continue
            if store is not None and store.is_seen(paper):
                continue
            pool.append(paper)
            seen_keys.add(paper.dedup_key)
        # 再补入所有「有方向标签、已打分、有 arXiv ID」的新论文，尽量填满方向配额
        for paper in new_papers:
            if paper.dedup_key in seen_keys:
                continue
            if paper.llm_score is None or not paper.arxiv_id or not paper.direction:
                continue
            pool.append(paper)
            seen_keys.add(paper.dedup_key)
        dd_candidates = select_deep_dive(
            pool,
            per_direction=dd_conf.get("per_direction") or {},
            fallback_min_score=float(dd_conf.get("min_llm_score", 7.0)),
        )
        log.info("深度解读候选：%d 篇", len(dd_candidates))
        for paper in dd_candidates:
            assert paper.arxiv_id
            fulltext = fetch_fulltext(
                paper.arxiv_id,
                client=client,
                timeout=float(dd_conf.get("timeout_seconds", 300)),
            )
            analysis = make_deep_dive(
                client,
                paper,
                fulltext,
                focus=cfg.focus,
                max_fulltext_chars=int(dd_conf.get("max_fulltext_chars", 50000)),
                max_tokens=int(dd_conf.get("max_tokens", 3200)),
            )
            if analysis:
                paper.deep_dive = analysis
                deep_dives.append(paper)
        # 已做深度解读的论文不再在「今日精选」重复出现
        dd_keys = {p.dedup_key for p in deep_dives}
        groups["highlights"] = [p for p in groups["highlights"] if p.dedup_key not in dd_keys]

    # --- 渲染 ---
    total_shown = (
        len(deep_dives)
        + len(groups["scirate_hot"])
        + len(groups["highlights"])
        + len(groups["worth_scanning"])
    )
    ctx = {
        "date": run_date,
        "title": report_conf.get("title", "量子论文雷达"),
        "subtitle": report_conf.get("subtitle", ""),
        "scan": scan,
        "new_count": len(new_papers),
        "candidate_count": len(candidates) if (client.available and not args.no_llm) else 0,
        "llm_calls": client.stats().get("chat_calls", 0),
        "warnings": warnings,
        "scirate_hot": groups["scirate_hot"],
        "hot_source": hot_source,
        "deep_dives": deep_dives,
        "highlights": groups["highlights"],
        "worth_scanning": groups["worth_scanning"],
        "generated_at": now.strftime("%Y-%m-%d %H:%M %Z"),
        "stats_line": f"本次扫描 {len(merged)} 篇，展示 {total_shown} 篇，新增 {len(new_papers)} 篇",
    }
    markdown = render_markdown(ctx)
    wechat = render_wechat(ctx)
    report_path = _save_report(cfg, run_date, markdown)
    log.info("日报已保存：%s", report_path)

    # --- 生成 PDF（微信里排版受限，PDF 提供完整渲染）---
    pdf_path = generate_pdf(
        markdown,
        pdf_reports_dir(cfg.root) / f"{run_date.isoformat()}.pdf",
        title=f"{report_conf.get('title', '量子论文雷达')} {run_date.isoformat()}",
    )
    pdf_url = pdf_public_url(run_date) if pdf_path else None
    ctx["pdf_url"] = pdf_url
    if pdf_path:
        if pdf_url:
            log.info("PDF 下载链接：%s", pdf_url)
        else:
            log.info("PDF 已生成但未配置公网地址（设置 RADAR_PDF_BASE_URL 可生成下载链接）")

    # --- 推送 ---
    notify_result = None
    should_notify = not args.dry_run and not args.no_notify and total_shown > 0
    if args.dry_run:
        log.info("dry-run：跳过推送")
    elif args.no_notify:
        log.info("--no-notify：跳过推送")
    elif total_shown == 0:
        log.info("今日没有可展示的论文，跳过推送")
    else:
        from . import notify

        provider = notify.detect_provider(str((cfg.notify_cfg or {}).get("provider", "auto")))
        if provider is None:
            log.warning("没有配置任何推送渠道，消息未发送（日报已保存到 reports/）")
        else:
            title = f"{report_conf.get('title', '量子论文雷达')} · {run_date.month:02d}-{run_date.day:02d}"
            # PushPlus 用 HTML 模板：换行和链接都可控，LaTeX 已转成 Unicode
            if provider == "pushplus":
                content = render_wechat_html(ctx)
                notify_result = notify.send(
                    title=title, content=content, provider=provider,
                    summary=f"新增 {len(new_papers)} 篇，展示 {total_shown} 篇", html=True,
                )
            else:
                notify_result = notify.send(
                    title=title, content=wechat, provider=provider,
                    summary=f"新增 {len(new_papers)} 篇，展示 {total_shown} 篇",
                )
            if notify_result.ok:
                log.info("推送成功：%s", notify_result.provider)
            else:
                log.error("推送失败（%s）：%s", notify_result.provider, notify_result.detail)
                warnings.append(f"推送失败：{notify_result.detail}")

    # --- 更新状态（只有真正推送成功或明确不推送时才记录）---
    state_saved = False
    if store is not None and not args.dry_run:
        delivered = args.no_notify or (notify_result is not None and notify_result.ok) or total_shown == 0
        if delivered:
            store.mark_many(new_papers, run_date)
            removed = store.prune()
            store.save()
            state_saved = True
            log.info("状态已更新：新增 %d 条，清理 %d 条，当前 %d 条", len(new_papers), removed, len(store))
        else:
            log.warning("推送未成功，今天的新论文不写入状态，明天会重试")

    # --- 汇总 ---
    log.info(
        "完成：深度解读 %d / 热榜 %d / 精选 %d / 扫读 %d；API 调用 search=%d fetch=%d chat=%d；状态保存=%s",
        len(deep_dives),
        len(groups["scirate_hot"]),
        len(groups["highlights"]),
        len(groups["worth_scanning"]),
        client.stats().get("search_calls", 0),
        client.stats().get("fetch_calls", 0),
        client.stats().get("chat_calls", 0),
        state_saved,
    )
    if args.dry_run:
        print("\n" + "=" * 72 + "\n" + wechat + "\n" + "=" * 72)
    return 0


def main(argv: Optional[list[str]] = None) -> int:
    args = parse_args(argv)
    setup_logging(args.verbose)
    try:
        cfg = load_config(args.config)
    except ConfigError as exc:
        log.error("配置错误：%s", exc)
        return 2
    try:
        return run(cfg, args)
    except KeyboardInterrupt:
        log.warning("用户中断")
        return 130
    except Exception as exc:  # noqa: BLE001 - 顶层兜底，保证退出码可读
        log.exception("运行失败：%s", exc)
        return 1


if __name__ == "__main__":
    sys.exit(main())
