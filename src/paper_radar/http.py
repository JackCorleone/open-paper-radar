"""统一的 HTTP 层：超时、UA、指数退避重试、结构化错误。

只依赖标准库，保证在 GitHub Actions 和本机行为一致。
"""

from __future__ import annotations

import json
import os
import ssl
import time
import urllib.error
import urllib.request
from typing import Any, Mapping, Optional

from .util import get_logger

log = get_logger(__name__)

DEFAULT_UA = (
    "paper-radar/0.1 (daily arXiv digest; +https://github.com/) "
    "Python-urllib"
)

RETRY_STATUS = {408, 425, 429, 500, 502, 503, 504}

# 一些用 pkg 安装的 Python（如 macOS 上 python.org 的安装包）没有捆绑 CA 证书，
# 导致 SSL: CERTIFICATE_VERIFY_FAILED。这里自动回退到系统证书，GitHub Actions 不受影响。
_CA_CANDIDATES = (
    "/etc/ssl/cert.pem",
    "/opt/homebrew/etc/ca-certificates/cert.pem",
    "/opt/homebrew/etc/openssl@3/cert.pem",
    "/usr/local/etc/openssl/cert.pem",
    "/etc/pki/tls/certs/ca-bundle.crt",
    "/etc/ssl/certs/ca-certificates.crt",
)


def _ssl_context() -> ssl.SSLContext:
    context = ssl.create_default_context()
    if context.get_ca_certs():
        return context
    for candidate in _CA_CANDIDATES:
        if os.path.exists(candidate):
            try:
                return ssl.create_default_context(cafile=candidate)
            except ssl.SSLError:
                continue
    return context


class HttpError(RuntimeError):
    """HTTP 请求失败，保留状态码与响应体，便于上层做降级判断。"""

    def __init__(self, status: int, url: str, body: str = "", message: str = "") -> None:
        self.status = status
        self.url = url
        self.body = body
        detail = message or body[:300]
        super().__init__(f"HTTP {status} {url} -> {detail}")


def _build_request(
    url: str,
    method: str,
    payload: Mapping[str, Any] | str | None,
    headers: Optional[Mapping[str, str]],
    timeout: float,
) -> urllib.request.Request:
    data: bytes | None = None
    merged: dict[str, str] = {"User-Agent": DEFAULT_UA, "Accept": "*/*"}
    if payload is not None:
        if isinstance(payload, str):
            data = payload.encode("utf-8")
        else:
            data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
            merged.setdefault("Content-Type", "application/json")
    if headers:
        merged.update(headers)
    req = urllib.request.Request(url, data=data, headers=merged, method=method)
    return req


def request(
    url: str,
    method: str = "GET",
    payload: Mapping[str, Any] | str | None = None,
    headers: Optional[Mapping[str, str]] = None,
    timeout: float = 30.0,
    retries: int = 3,
    backoff: float = 2.0,
    max_retry_wait: float = 20.0,
) -> str:
    """发起请求并返回文本；对可重试状态码做指数退避。"""
    last_error: Exception | None = None
    for attempt in range(retries + 1):
        req = _build_request(url, method, payload, headers, timeout)
        try:
            with urllib.request.urlopen(req, timeout=timeout, context=_ssl_context()) as resp:
                charset = resp.headers.get_content_charset() or "utf-8"
                return resp.read().decode(charset, errors="replace")
        except urllib.error.HTTPError as exc:
            body = ""
            try:
                body = exc.read().decode("utf-8", errors="replace")
            except Exception:  # noqa: BLE001 - 读取错误体失败不影响主流程
                pass
            err = HttpError(exc.code, url, body)
            last_error = err
            if exc.code not in RETRY_STATUS or attempt >= retries:
                raise err from None
            wait = min(backoff ** attempt, max_retry_wait)
            log.warning("HTTP %s，%.1fs 后重试（%d/%d）：%s", exc.code, wait, attempt + 1, retries, url)
            time.sleep(wait)
        except (urllib.error.URLError, TimeoutError, OSError) as exc:
            last_error = exc
            if attempt >= retries:
                raise HttpError(0, url, str(exc), f"网络错误：{exc}") from None
            wait = min(backoff ** attempt, max_retry_wait)
            log.warning("网络错误 %s，%.1fs 后重试（%d/%d）", exc, wait, attempt + 1, retries)
            time.sleep(wait)
    raise HttpError(0, url, str(last_error), "重试耗尽")


def request_json(
    url: str,
    method: str = "GET",
    payload: Mapping[str, Any] | str | None = None,
    headers: Optional[Mapping[str, str]] = None,
    timeout: float = 60.0,
    retries: int = 3,
) -> Any:
    text = request(url, method=method, payload=payload, headers=headers, timeout=timeout, retries=retries)
    try:
        return json.loads(text)
    except json.JSONDecodeError as exc:
        raise HttpError(0, url, text[:500], f"响应不是合法 JSON：{exc}") from None
