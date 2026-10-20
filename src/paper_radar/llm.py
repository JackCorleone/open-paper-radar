"""LLM 精读打分：调用 DeepSeek Chat 给候选论文打分并写「为什么值得看」。

成本控制：
- 只对规则预筛后的 top N 候选调用
- 分批请求（默认每批 8 篇）
- 摘要截断到 800 字符
一次运行通常 2~3 次 chat 请求，成本约几厘钱。
"""

from __future__ import annotations

import json
from datetime import date
from typing import Optional

from .deepseek import DeepSeekClient, DeepSeekError, extract_json
from .models import Paper
from .util import chunked, get_logger, replace_date_placeholders, truncate

log = get_logger(__name__)

SYSTEM_PROMPT = """你是一位量子信息方向的研究助理，每天帮研究员从论文流里挑出真正值得花时间读的工作。

判断原则：
1. 关注方法本身的新颖性、结论的可靠性、对研究员关注方向的启发（方向见用户消息）。作者或机构的名气不加分。
2. 标题里的热门词不等于有价值；摘要里没有具体方法或结论的，宁可打低分。
3. 纯综述、纯实验平台介绍、和量子计算无关的论文，除非明确与关注方向相关，否则不给高分。
4. 评分要有区分度，不要全部打 7 分。
5. 对量子算法类论文：复杂度结果是否真的更优、下界是否严格、常数与对数因子是否交代清楚，是判断价值的关键。只在经典算法上做微小改进、或只有启发式实验的，不要给高分。
6. 对量子储备池计算 / 量子机器学习类论文：关注是否有可检验的结论（记忆容量、泛化界、噪声下的表现、与经典基线的严格对比），而不是只展示单个任务上的数值结果。

输出格式：只输出一个 JSON 对象，形如
{"papers": [{"id": 1, "score": 8.5, "reason": "……", "tags": ["……"]}]}
其中 score 为 0-10 的数字；reason 为 40-90 字中文，说清「做了什么 + 为什么值得/不值得读」；tags 为 2-4 个短标签。
不要输出 JSON 以外的任何内容。"""


def build_user_prompt(papers: list[Paper], focus: str, run_date: date) -> str:
    items = []
    for idx, paper in enumerate(papers, start=1):
        signals: dict = {"sources": sorted(paper.sources)}
        if paper.scirate_rank is not None:
            signals["scirate_rank"] = paper.scirate_rank
            signals["scites"] = paper.scites
        if paper.search_score is not None:
            signals["search_score"] = round(paper.search_score, 2)
        if paper.venue:
            signals["venue"] = truncate(paper.venue, 60)
        items.append(
            {
                "id": idx,
                "title": paper.title,
                "abstract": truncate(paper.abstract or "（无摘要，仅有标题）", 800),
                "signals": signals,
            }
        )
    payload = json.dumps(items, ensure_ascii=False, indent=1)
    return (
        f"今天是 {run_date.isoformat()}。研究员的关注方向：{focus}。\n\n"
        f"以下是今日候选论文（JSON 数组）：\n{payload}\n\n"
        "请逐篇评分并给出理由，id 必须与输入一一对应，返回 {\"papers\": [...]} 形式的 JSON。"
    )


def _coerce_score(value) -> Optional[float]:
    try:
        score = float(value)
    except (TypeError, ValueError):
        return None
    return max(0.0, min(10.0, score))


def _apply_batch(papers: list[Paper], items: list[dict]) -> int:
    """把模型返回的评分写回 papers，返回成功匹配的条数。"""
    matched = 0
    for item in items:
        if not isinstance(item, dict):
            continue
        try:
            idx = int(item.get("id"))
        except (TypeError, ValueError):
            continue
        if idx < 1 or idx > len(papers):
            continue
        paper = papers[idx - 1]
        score = _coerce_score(item.get("score"))
        if score is None:
            continue
        paper.llm_score = score
        reason = str(item.get("reason") or "").strip()
        paper.llm_reason = truncate(reason, 200)
        tags = item.get("tags") or []
        if isinstance(tags, list):
            paper.tags = [str(t).strip() for t in tags if str(t).strip()][:4]
        matched += 1
    return matched


def score_papers(
    client: Optional[DeepSeekClient],
    papers: list[Paper],
    focus: str,
    run_date: date,
    batch_size: int = 8,
    temperature: float = 0.2,
    max_tokens: int = 2500,
) -> bool:
    """给候选论文打 LLM 分。返回是否至少成功了一次。"""
    if not papers:
        return False
    if not client or not client.available:
        log.info("未配置 API Key，跳过 LLM 精读")
        return False

    any_success = False
    for batch_no, batch in enumerate(chunked(papers, max(1, batch_size)), start=1):
        messages = [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": build_user_prompt(batch, focus, run_date)},
        ]
        data = None
        for attempt in (1, 2):
            try:
                raw = client.chat(messages, temperature=temperature, max_tokens=max_tokens)
                data = extract_json(raw)
                break
            except (DeepSeekError, ValueError) as exc:
                log.warning("LLM 第 %d 批第 %d 次失败：%s", batch_no, attempt, exc)
                if attempt == 1:
                    messages.append(
                        {
                            "role": "user",
                            "content": "上次输出无法解析。请只输出合法 JSON 对象 {\"papers\": [...]}，不要任何其他文字。",
                        }
                    )
        if data is None:
            continue
        items = data.get("papers") if isinstance(data, dict) else data
        if not isinstance(items, list):
            log.warning("LLM 第 %d 批返回结构异常：%s", batch_no, str(data)[:200])
            continue
        matched = _apply_batch(batch, items)
        log.info("LLM 第 %d 批：%d/%d 篇评分成功", batch_no, matched, len(batch))
        any_success = any_success or matched > 0
    return any_success
