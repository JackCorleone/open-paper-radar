"""日报 PDF 生成。

依赖是可选的：只有装了 `weasyprint`（转 PDF）和 `markdown`（md→html）才会生成，
没装时静默跳过，不影响主流程。GitHub Actions 里会在运行前安装这两个包和中文字体。

PDF 输出到 docs/reports/YYYY-MM-DD.pdf，配合 GitHub Pages 提供下载链接。
"""

from __future__ import annotations

import os
from datetime import date
from pathlib import Path
from typing import Optional

from .util import ensure_dir, env, get_logger

log = get_logger(__name__)

_HTML_TEMPLATE = """<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="utf-8">
<title>{title}</title>
<style>
@page {{ size: A4; margin: 1.6cm 1.5cm; }}
body {{
  font-family: "Noto Sans CJK SC", "Noto Sans SC", "Source Han Sans SC",
               "PingFang SC", "Microsoft YaHei", sans-serif;
  font-size: 10.5pt; line-height: 1.65; color: #222; max-width: 100%;
}}
h1 {{ font-size: 19pt; border-bottom: 2px solid #2c3e50; padding-bottom: 6px; margin-top: 0; }}
h2 {{ font-size: 14.5pt; color: #1a4d80; margin-top: 22px; border-bottom: 1px solid #e3e8ee; padding-bottom: 3px; }}
h3 {{ font-size: 12.5pt; margin-top: 18px; color: #1f3b57; }}
h4 {{ font-size: 11.5pt; margin-top: 14px; }}
p {{ margin: 6px 0; }}
table {{ border-collapse: collapse; width: 100%; margin: 8px 0; font-size: 9.5pt; }}
th, td {{ border: 1px solid #cfd6dd; padding: 4px 7px; text-align: left; vertical-align: top; }}
th {{ background: #eef2f6; }}
blockquote {{ border-left: 3px solid #b8c4d0; margin: 8px 0; padding: 2px 12px; color: #555; background: #fafbfc; }}
a {{ color: #0b5cad; text-decoration: none; word-break: break-all; }}
code {{ background: #f2f4f6; padding: 1px 4px; border-radius: 3px; font-size: 9.5pt; }}
pre {{ background: #f6f8fa; padding: 8px; border-radius: 4px; white-space: pre-wrap; }}
ul, ol {{ margin: 6px 0 6px 18px; }}
li {{ margin: 2px 0; }}
hr {{ border: none; border-top: 1px solid #ddd; margin: 16px 0; }}
.footer {{ color: #888; font-size: 9pt; margin-top: 20px; }}
</style>
</head>
<body>
{body}
</body>
</html>
"""


def _deps_available() -> bool:
    try:
        import markdown  # noqa: F401
        import weasyprint  # noqa: F401
    except Exception:  # noqa: BLE001
        return False
    return True


def markdown_to_html(md_text: str) -> str:
    import markdown

    return markdown.markdown(
        md_text,
        extensions=["tables", "fenced_code", "sane_lists", "nl2br"],
    )


def pdf_reports_dir(root: Path) -> Path:
    custom = env("RADAR_PDF_DIR")
    if custom:
        return Path(custom).expanduser()
    return root / "docs" / "reports"


def generate_pdf(markdown_text: str, out_path: Path, title: str = "量子论文雷达") -> Optional[Path]:
    """把日报 Markdown 渲染成 PDF；依赖缺失或失败时返回 None。"""
    if not _deps_available():
        log.info("未安装 weasyprint/markdown，跳过 PDF 生成")
        return None
    try:
        from weasyprint import HTML
    except Exception as exc:  # noqa: BLE001
        log.warning("weasyprint 不可用，跳过 PDF：%s", exc)
        return None

    try:
        # PDF 里也把 LaTeX 转成 Unicode，避免公式以源码形式出现；原始 LaTeX 保留在 .md 里
        from .render import latex_to_plain

        plain_markdown = latex_to_plain(markdown_text)
        body = markdown_to_html(plain_markdown)
        html = _HTML_TEMPLATE.format(title=title, body=body)
        ensure_dir(str(out_path.parent))
        HTML(string=html).write_pdf(str(out_path))
        log.info("PDF 日报已生成：%s（%.0f KB）", out_path, out_path.stat().st_size / 1024)
        return out_path
    except Exception as exc:  # noqa: BLE001
        log.warning("PDF 生成失败：%s", exc)
        return None


def pdf_public_url(run_date: date, base_url: Optional[str] = None) -> Optional[str]:
    """构造 PDF 的公网下载地址（GitHub Pages）。"""
    base = base_url or env("RADAR_PDF_BASE_URL")
    if not base:
        repo = os.environ.get("GITHUB_REPOSITORY") or ""
        if "/" in repo:
            owner, name = repo.split("/", 1)
            # GitHub Pages 域名统一小写
            base = f"https://{owner.lower()}.github.io/{name}"
    if not base:
        return None
    return f"{base.rstrip('/')}/reports/{run_date.isoformat()}.pdf"
