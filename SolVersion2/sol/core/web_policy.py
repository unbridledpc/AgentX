from __future__ import annotations

import re
import urllib.parse
from dataclasses import dataclass
from typing import Iterable


@dataclass(frozen=True)
class WebPolicy:
    """Persistent web fetch/crawl policy (allowlist-first, fail-closed).

    This policy applies to network tools that retrieve remote content (web.fetch/web.crawl).
    web.search may return any URLs, but fetch/crawl are filtered by this policy.
    """

    allow_all_hosts: bool
    allowed_host_suffixes: tuple[str, ...]
    allowed_domains: tuple[str, ...]
    denied_domains: tuple[str, ...]


def normalize_host(host: str) -> str:
    return (host or "").strip().lower().rstrip(".")


def _normalize_domain_entry(value: str) -> str:
    v = (value or "").strip().lower().rstrip(".")
    if not v:
        return ""
    # Accept user input like "https://example.com/path" by extracting hostname.
    if "://" in v:
        try:
            v = normalize_host(urllib.parse.urlparse(v).hostname or "")
        except Exception:
            v = v
    # Strip any leading dot.
    v = v.lstrip(".")
    # Drop path fragments if user pasted "example.com/foo".
    v = v.split("/")[0]
    return v


_COMMON_TWO_PART_SUFFIXES: tuple[str, ...] = (
    "co.uk",
    "org.uk",
    "gov.uk",
    "ac.uk",
    "com.au",
    "net.au",
    "org.au",
    "co.jp",
)


def registrable_domain(host: str) -> str:
    """Best-effort eTLD+1 without external deps.

    This is intentionally conservative and not a full Public Suffix List implementation.
    """

    h = normalize_host(host)
    if not h:
        return ""
    # If already looks like an IPv4/IPv6 literal, treat as non-registrable.
    if re.fullmatch(r"\d{1,3}(?:\.\d{1,3}){3}", h) or ":" in h:
        return ""

    parts = [p for p in h.split(".") if p]
    if len(parts) < 2:
        return h
    last2 = ".".join(parts[-2:])
    last3 = ".".join(parts[-3:])
    if last2 in _COMMON_TWO_PART_SUFFIXES and len(parts) >= 3:
        return last3
    if last2.endswith(".uk") and last2 in _COMMON_TWO_PART_SUFFIXES and len(parts) >= 3:
        return last3
    return last2


def _matches_domain(host: str, domain: str) -> bool:
    h = normalize_host(host)
    d = _normalize_domain_entry(domain)
    if not h or not d:
        return False
    if h == d or h.endswith("." + d):
        return True
    # Also allow registrable-domain match for convenience.
    return registrable_domain(h) == d


def is_allowed_url(
    url: str,
    *,
    policy: WebPolicy,
    session_allowed_domains: Iterable[str] | None = None,
) -> tuple[bool, str]:
    u = (url or "").strip()
    if not u:
        return False, "Missing URL."
    try:
        parsed = urllib.parse.urlparse(u)
    except Exception:
        return False, "Malformed URL."
    if parsed.scheme not in ("http", "https"):
        return False, "Only http/https URLs are allowed."
    host = normalize_host(parsed.hostname or "")
    if not host:
        return False, "URL must include a hostname."

    denied = tuple(_normalize_domain_entry(x) for x in (policy.denied_domains or ()))
    for d in denied:
        if d and _matches_domain(host, d):
            return False, f"Domain denied by policy: {d}"

    # Session overrides allow a domain for this thread only. Denylist still wins.
    if session_allowed_domains:
        for d in session_allowed_domains:
            dd = _normalize_domain_entry(d)
            if dd and _matches_domain(host, dd):
                return True, f"Allowed by session override: {dd}"

    if policy.allow_all_hosts:
        return True, "Allowed (policy allow_all_hosts=true)."

    # Allow by suffix list (supports entries like "gov" -> ".gov").
    for suf in tuple(_normalize_domain_entry(x) for x in (policy.allowed_host_suffixes or ())):
        if not suf:
            continue
        if suf in ("gov", "edu"):
            if host.endswith("." + suf):
                return True, f"Allowed by suffix: .{suf}"
            continue
        if host == suf or host.endswith("." + suf):
            return True, f"Allowed by suffix: {suf}"

    # Allow by explicit domains.
    for dom in tuple(_normalize_domain_entry(x) for x in (policy.allowed_domains or ())):
        if dom and _matches_domain(host, dom):
            return True, f"Allowed by domain: {dom}"

    return False, "Domain not in allowlist."

