from __future__ import annotations

import re
import time
import urllib.error
import urllib.request
from dataclasses import dataclass
from html import unescape
from html.parser import HTMLParser
from urllib.parse import urlparse, urljoin

from .errors import WebFetchError
from .policy import WebPolicy, validate_host, validate_resolved_ips, validate_url


@dataclass(frozen=True)
class FetchResult:
    url: str
    content_type: str
    text: str
    truncated: bool
    ts: float


class _TextExtractor(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self._chunks: list[str] = []
        self._skip_depth = 0

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag in ("script", "style", "noscript"):
            self._skip_depth += 1

    def handle_endtag(self, tag: str) -> None:
        if tag in ("script", "style", "noscript") and self._skip_depth > 0:
            self._skip_depth -= 1
        if tag in ("p", "br", "div", "li", "h1", "h2", "h3", "h4", "h5", "h6"):
            self._chunks.append("\n")

    def handle_data(self, data: str) -> None:
        if self._skip_depth > 0:
            return
        if not data:
            return
        self._chunks.append(data)

    def get_text(self) -> str:
        raw = "".join(self._chunks)
        raw = unescape(raw)
        raw = re.sub(r"[ \t]+\n", "\n", raw)
        raw = re.sub(r"\n{3,}", "\n\n", raw)
        raw = re.sub(r"[ \t]{2,}", " ", raw)
        return raw.strip()


def _read_limited(resp, *, max_bytes: int) -> tuple[bytes, bool]:
    buf = bytearray()
    truncated = False
    while True:
        chunk = resp.read(min(64 * 1024, max_bytes - len(buf)))
        if not chunk:
            break
        buf.extend(chunk)
        if len(buf) >= max_bytes:
            truncated = True
            break
    return bytes(buf), truncated


def _decode_bytes(raw: bytes, content_type: str) -> str:
    # Try declared charset if present.
    m = re.search(r"charset=([A-Za-z0-9._-]+)", content_type or "", re.IGNORECASE)
    if m:
        enc = m.group(1)
        try:
            return raw.decode(enc, errors="replace")
        except Exception:
            pass
    return raw.decode("utf-8", errors="replace")


def fetch_text(url: str, *, policy: WebPolicy) -> FetchResult:
    validate_url(url, policy=policy)
    parsed = urlparse(url)
    host = validate_host(parsed.hostname or "", policy=policy)
    validate_resolved_ips(host, policy=policy)

    current = url
    redirects = 0
    while True:
        req = urllib.request.Request(
            current,
            headers={
                "User-Agent": policy.user_agent,
                "Accept": "text/html, text/plain, application/json;q=0.9, */*;q=0.1",
            },
            method="GET",
        )
        try:
            with urllib.request.urlopen(req, timeout=policy.timeout_s) as resp:
                content_type = (resp.headers.get("Content-Type") or "").strip()
                status = getattr(resp, "status", 200)
                location = resp.headers.get("Location")
                raw, truncated = _read_limited(resp, max_bytes=max(1, int(policy.max_bytes)))
                final_url = getattr(resp, "geturl", lambda: current)()
        except urllib.error.HTTPError as e:
            body = e.read().decode("utf-8", errors="replace") if getattr(e, "fp", None) else ""
            raise WebFetchError(f"HTTP {e.code}: {body[:4000]}")
        except Exception as e:
            raise WebFetchError(f"Request failed: {e}")

        # Follow redirects ourselves so we can re-validate destination host/IP.
        if 300 <= int(status) < 400:
            if not location:
                break
            redirects += 1
            if redirects > max(0, int(policy.max_redirects)):
                raise WebFetchError("Too many redirects.")
            next_url = urljoin(current, location)
            validate_url(next_url, policy=policy)
            next_parsed = urlparse(next_url)
            next_host = validate_host(next_parsed.hostname or "", policy=policy)
            validate_resolved_ips(next_host, policy=policy)
            current = next_url
            continue

        text = _decode_bytes(raw, content_type)
        if "text/html" in (content_type or "").lower():
            try:
                parser = _TextExtractor()
                parser.feed(text)
                text_out = parser.get_text()
            except Exception:
                text_out = text
        else:
            text_out = text

        return FetchResult(
            url=str(final_url or current),
            content_type=content_type or "application/octet-stream",
            text=text_out,
            truncated=truncated,
            ts=time.time(),
        )
