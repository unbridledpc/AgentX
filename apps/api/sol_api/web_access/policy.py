from __future__ import annotations

import ipaddress
import socket
from dataclasses import dataclass
from urllib.parse import urlparse

from .errors import WebAccessDenied


@dataclass(frozen=True)
class WebPolicy:
    enabled: bool
    allow_all_hosts: bool
    allowed_host_suffixes: tuple[str, ...]
    block_private_networks: bool
    timeout_s: float
    max_bytes: int
    user_agent: str
    max_redirects: int
    max_search_results: int


def _normalize_host(host: str) -> str:
    return (host or "").strip().lower().rstrip(".")


def validate_url(url: str, *, policy: WebPolicy) -> str:
    if not policy.enabled:
        raise WebAccessDenied("Web access is disabled (SOL_WEB_ENABLED=false).")
    parsed = urlparse((url or "").strip())
    if parsed.scheme not in ("http", "https"):
        raise WebAccessDenied("Only http/https URLs are allowed.")
    if not parsed.netloc:
        raise WebAccessDenied("URL must include a hostname.")
    return url


def validate_host(hostname: str, *, policy: WebPolicy) -> str:
    host = _normalize_host(hostname)
    if not host:
        raise WebAccessDenied("Missing hostname.")

    if policy.allow_all_hosts:
        return host

    for suffix in policy.allowed_host_suffixes:
        s = _normalize_host(suffix)
        if not s:
            continue
        if host == s or host.endswith("." + s):
            return host
    raise WebAccessDenied("Host is not in SOL_WEB_ALLOWED_HOSTS and SOL_WEB_ALLOW_ALL=false.")


def validate_resolved_ips(hostname: str, *, policy: WebPolicy) -> None:
    if not policy.block_private_networks:
        return
    try:
        infos = socket.getaddrinfo(hostname, None)
    except Exception:
        # If we can't resolve, let the fetch fail explicitly later.
        return

    for info in infos:
        addr = info[4][0]
        try:
            ip = ipaddress.ip_address(addr)
        except Exception:
            continue
        if ip.is_private or ip.is_loopback or ip.is_link_local or ip.is_reserved or ip.is_multicast:
            raise WebAccessDenied("Resolved IP is not allowed (private/loopback/reserved).")

