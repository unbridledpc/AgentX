from __future__ import annotations

import re
import urllib.parse
from dataclasses import dataclass
from typing import Literal


Trust = Literal["primary", "secondary", "unknown"]
Verdict = Literal["VERIFIED_PRIMARY", "VERIFIED_SECONDARY", "PARTIAL", "CONTRADICTED", "UNVERIFIED"]


@dataclass(frozen=True)
class EvidenceSource:
    url: str
    title: str | None
    trust: Trust
    fetched_at: float
    text_excerpt: str


@dataclass(frozen=True)
class ExtractedClaim:
    key: str
    value: str
    confidence: float
    source_url: str
    rationale: str


@dataclass(frozen=True)
class EvidenceBundle:
    query: str
    sources: list[EvidenceSource]
    claims: list[ExtractedClaim]
    contradictions: list[str]
    overall_confidence: float
    verdict: Verdict


_SECONDARY_HOST_SUFFIXES: tuple[str, ...] = (
    "wikipedia.org",
    "reuters.com",
    "apnews.com",
    "bbc.co.uk",
    "bbc.com",
)


def classify_trust(url: str) -> Trust:
    host = (urllib.parse.urlparse(url).hostname or "").lower().rstrip(".")
    if not host:
        return "unknown"
    if host.endswith(".gov") or "whitehouse.gov" in host or "usa.gov" in host:
        return "primary"
    if host.endswith("wikipedia.org") or any(host.endswith(s) for s in _SECONDARY_HOST_SUFFIXES):
        return "secondary"
    return "unknown"


def _base_confidence(trust: Trust) -> float:
    return {"primary": 0.75, "secondary": 0.55, "unknown": 0.35}[trust]


def _clamp01(x: float) -> float:
    return max(0.0, min(float(x), 1.0))


def _normalize_name(value: str) -> str:
    v = re.sub(r"\s+", " ", (value or "").strip())
    v = re.sub(r"^[^A-Za-z]+|[^A-Za-z]+$", "", v)
    return v.strip()


def extract_claims_rule_based(query: str, sources: list[EvidenceSource]) -> list[ExtractedClaim]:
    q = (query or "").strip().lower()
    out: list[ExtractedClaim] = []

    wants_potus = "potus" in q or ("president" in q and "united states" in q) or ("current president" in q)
    if not wants_potus:
        return out

    key = "us.president.current"
    strong_patterns: list[tuple[str, str]] = [
        (r"\bIncumbent\b\s*[:\-]?\s*([A-Z][A-Za-z.\-']+(?:\s+[A-Z][A-Za-z.\-']+){1,3})", "matched 'Incumbent' pattern"),
        (r"\bPresident of the United States\b.*?\bis\b\s*([A-Z][A-Za-z.\-']+(?:\s+[A-Z][A-Za-z.\-']+){1,3})", "matched 'President ... is' pattern"),
        (r"^President\s*[:\-]\s*([A-Z][A-Za-z.\-']+(?:\s+[A-Z][A-Za-z.\-']+){1,3})", "matched 'President:' header pattern"),
    ]

    for src in sources:
        # Wikipedia "List of ..." pages are frequently stale/ambiguous. Only extract if the page
        # explicitly states "President of the United States ... is <Name>" (more reliable than an infobox-like line).
        is_wiki_list = False
        try:
            host = (urllib.parse.urlparse(src.url).hostname or "").lower().rstrip(".")
            path = urllib.parse.urlparse(src.url).path or ""
            if host.endswith("wikipedia.org") and re.search(r"/wiki/list_of_", path, flags=re.IGNORECASE):
                is_wiki_list = True
        except Exception:
            is_wiki_list = False

        text = src.text_excerpt or ""
        for pat, rationale in strong_patterns:
            if is_wiki_list and ("Incumbent" in pat or pat.startswith("^President")):
                continue
            m = re.search(pat, text, flags=re.IGNORECASE | re.MULTILINE)
            if not m:
                continue
            name = _normalize_name(m.group(1) or "")
            if len(name.split()) < 2:
                continue
            conf = _base_confidence(src.trust)
            conf = _clamp01(min(0.95, conf + 0.15))
            out.append(
                ExtractedClaim(
                    key=key,
                    value=name,
                    confidence=conf,
                    source_url=src.url,
                    rationale=rationale,
                )
            )
            break

    return out


def build_bundle(
    *,
    query: str,
    sources: list[EvidenceSource],
    llm_claims: list[ExtractedClaim] | None = None,
) -> EvidenceBundle:
    claims = extract_claims_rule_based(query, sources)
    if not claims and llm_claims:
        claims = list(llm_claims)

    # Group per key/value.
    by_key: dict[str, dict[str, list[ExtractedClaim]]] = {}
    for c in claims:
        by_key.setdefault(c.key, {}).setdefault(c.value, []).append(c)

    contradictions: list[str] = []

    def agg_conf(claims_for_value: list[ExtractedClaim]) -> float:
        base = max((c.confidence for c in claims_for_value), default=0.0)
        # +0.10 per additional agreeing source
        base = min(0.99, base + 0.10 * max(0, len(claims_for_value) - 1))
        return _clamp01(base)

    top_consensus: tuple[str, str, float] | None = None  # key,value,conf
    for key, values in by_key.items():
        scored = [(val, agg_conf(vs), vs) for val, vs in values.items()]
        scored.sort(key=lambda t: t[1], reverse=True)
        if not scored:
            continue
        if len(scored) >= 2:
            a_val, a_conf, a_vs = scored[0]
            b_val, b_conf, b_vs = scored[1]
            if abs(a_conf - b_conf) < 0.15 and a_vs and b_vs:
                contradictions.append(f"Sources disagree on {key}: {a_val} vs {b_val}")
        if top_consensus is None or scored[0][1] > top_consensus[2]:
            top_consensus = (key, scored[0][0], scored[0][1])

    overall = top_consensus[2] if top_consensus else 0.0
    if contradictions:
        overall = min(overall, 0.49)

    # Determine verdict.
    verdict: Verdict = "UNVERIFIED"
    if contradictions:
        verdict = "CONTRADICTED"
    elif claims:
        # Determine if any consensus claim has primary/secondary support.
        primary_urls = {s.url for s in sources if s.trust == "primary"}
        secondary_urls = {s.url for s in sources if s.trust == "secondary"}
        primary_support = any(c.source_url in primary_urls for c in claims)
        secondary_support = any(c.source_url in secondary_urls for c in claims)
        if primary_support and overall >= 0.75:
            verdict = "VERIFIED_PRIMARY"
        elif secondary_support and overall >= 0.65:
            verdict = "VERIFIED_SECONDARY"
        else:
            verdict = "PARTIAL"

    return EvidenceBundle(
        query=query,
        sources=list(sources),
        claims=list(claims),
        contradictions=contradictions,
        overall_confidence=_clamp01(overall),
        verdict=verdict,
    )
