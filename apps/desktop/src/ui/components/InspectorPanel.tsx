import React from "react";
import { useCallback, useEffect, useMemo, useState } from "react";
import {
  AuditEntry,
  CapabilitiesResponse,
  IngestManifestSummary,
  getAuditTail,
  getCapabilities,
  getWebPolicy,
  getMemoryStats,
  getIngestManifest,
  MemoryStatsResponse,
  sessionAllowWebDomain,
  sessionClearWebDomains,
  listIngestManifests,
  updateWebPolicy,
  pruneMemoryEvents,
  RetrievedChunk,
  runTool,
  StatusResponse,
} from "../../api/client";
import { Panel } from "./Panel";
import { ScrollArea } from "./ScrollArea";

type Props = {
  status: StatusResponse | null;
  lastCheck: number | null;
  lastError: string | null;
  apiBase: string;
  retrieved: RetrievedChunk[];
  auditTail: AuditEntry[];
  verificationLevel?: string | null;
  verification?: { verdict: string; confidence: number; contradictions: string[] } | null;
  webMeta?: { providers_used?: string[]; providers_failed?: { provider?: string; name?: string; error?: string }[]; fetch_blocked?: { url: string; reason: string }[] } | null;
  activeThreadId?: string | null;
};

export function InspectorPanel({ status, lastCheck, lastError, apiBase, retrieved, auditTail, verificationLevel, verification, webMeta, activeThreadId }: Props) {
  const chatProvider = status?.chat_provider ?? "stub";
  const chatModel = status?.chat_model ?? "stub";
  const chatReady = status?.chat_ready ?? true;
  const chatError = status?.chat_error ?? null;
  const modelsRefreshing = status?.models_refreshing ?? false;
  const modelsLastRefresh = status?.models_last_refresh ?? null;
  const modelsError = status?.models_error ?? null;
  const availableModels = status?.available_chat_models ?? {};
  const openaiCount = Array.isArray(availableModels.openai) ? availableModels.openai.length : 0;
  const ollamaCount = Array.isArray(availableModels.ollama) ? availableModels.ollama.length : 0;

  const [capabilities, setCapabilities] = useState<CapabilitiesResponse | null>(null);
  const [capError, setCapError] = useState<string | null>(null);
  const [memory, setMemory] = useState<MemoryStatsResponse | null>(null);
  const [memoryError, setMemoryError] = useState<string | null>(null);
  const [audit, setAudit] = useState<AuditEntry[]>([]);
  const [auditError, setAuditError] = useState<string | null>(null);
  const [auditFilter, setAuditFilter] = useState("");
  const [pruneDays, setPruneDays] = useState(30);
  const [pruneReason, setPruneReason] = useState("");

  const [webPolicy, setWebPolicy] = useState<
    | {
        allow_all_hosts: boolean;
        allowed_host_suffixes: string[];
        allowed_domains: string[];
        denied_domains: string[];
        session_overrides_count: number;
      }
    | null
  >(null);
  const [webPolicyError, setWebPolicyError] = useState<string | null>(null);
  const [policyReason, setPolicyReason] = useState("");
  const [addAllowedDomain, setAddAllowedDomain] = useState("");
  const [addAllowedSuffix, setAddAllowedSuffix] = useState("");
  const [addDeniedDomain, setAddDeniedDomain] = useState("");
  const [sessionDomain, setSessionDomain] = useState("");
  const [sessionReason, setSessionReason] = useState("");

  const [ingestManifests, setIngestManifests] = useState<IngestManifestSummary[]>([]);
  const [ingestError, setIngestError] = useState<string | null>(null);
  const [selectedManifestId, setSelectedManifestId] = useState<string | null>(null);
  const [selectedManifest, setSelectedManifest] = useState<Record<string, unknown> | null>(null);
  const [selectedManifestError, setSelectedManifestError] = useState<string | null>(null);
  const [ingestStartUrl, setIngestStartUrl] = useState("https://tibia.fandom.com/wiki/Monsters");
  const [ingestMaxPages, setIngestMaxPages] = useState(50);
  const [ingestReason, setIngestReason] = useState("");
  const [ingestBusy, setIngestBusy] = useState(false);
  const [ingestRunError, setIngestRunError] = useState<string | null>(null);
  const [ingestUrlMode, setIngestUrlMode] = useState<"auto" | "single" | "crawl">("auto");
  const [ingestUrlMaxDepth, setIngestUrlMaxDepth] = useState(2);

  const manifestPolicySuggestions = useMemo(() => {
    const m = selectedManifest;
    if (!m) return [];
    const blocked = (m as any).blocked;
    if (!Array.isArray(blocked)) return [];
    const out: { domain: string; url?: string; reason?: string }[] = [];
    const seen = new Set<string>();
    for (const b of blocked) {
      if (!b || typeof b !== "object") continue;
      const sugg = (b as any).suggestion;
      if (!sugg || typeof sugg !== "object") continue;
      if ((sugg as any).action !== "allow_domain") continue;
      const domain = String((sugg as any).domain ?? "").trim();
      if (!domain || seen.has(domain)) continue;
      seen.add(domain);
      out.push({ domain, url: String((b as any).url ?? ""), reason: String((b as any).reason ?? "") });
    }
    return out;
  }, [selectedManifest]);

  const manifestRepoDetails = useMemo(() => {
    const m = selectedManifest;
    if (!m) return null;
    const repo = (m as any).repo;
    if (!repo || typeof repo !== "object") return null;
    const listingMethod = String((repo as any).listing_method ?? "").trim();
    const stats = (repo as any).listing_stats;
    const filesFetched = Number((stats as any)?.files_fetched ?? 0);
    const filesFilteredOut = Number((stats as any)?.files_filtered_out ?? 0);
    const filesFailed = Number((stats as any)?.files_failed ?? 0);
    const pages = (m as any).pages;
    const repoPaths: string[] = [];
    if (Array.isArray(pages)) {
      for (const p of pages) {
        if (!p || typeof p !== "object") continue;
        const pr = (p as any).repo;
        const path = pr && typeof pr === "object" ? String((pr as any).path ?? "").trim() : "";
        if (path) repoPaths.push(path);
        if (repoPaths.length >= 10) break;
      }
    }
    return { listingMethod, filesFetched, filesFilteredOut, filesFailed, repoPaths };
  }, [selectedManifest]);

  const refreshCapabilities = useCallback(async () => {
    try {
      setCapError(null);
      const cap = await getCapabilities();
      setCapabilities(cap);
    } catch (e) {
      const msg = e instanceof Error ? e.message : String(e);
      setCapError(msg);
      setCapabilities(null);
    }
  }, []);

  const refreshAudit = useCallback(async () => {
    try {
      setAuditError(null);
      const res = await getAuditTail(50);
      setAudit(res.entries ?? []);
    } catch (e) {
      const msg = e instanceof Error ? e.message : String(e);
      setAuditError(msg);
      setAudit([]);
    }
  }, []);

  const refreshMemory = useCallback(async () => {
    try {
      setMemoryError(null);
      const res = await getMemoryStats("Refresh memory stats in Inspector.");
      setMemory(res);
    } catch (e) {
      const msg = e instanceof Error ? e.message : String(e);
      setMemoryError(msg);
      setMemory(null);
    }
  }, []);

  const refreshWebPolicy = useCallback(async () => {
    try {
      setWebPolicyError(null);
      const res = await getWebPolicy(activeThreadId ?? undefined);
      setWebPolicy({
        allow_all_hosts: Boolean(res.allow_all_hosts),
        allowed_host_suffixes: Array.isArray(res.allowed_host_suffixes) ? res.allowed_host_suffixes : [],
        allowed_domains: Array.isArray(res.allowed_domains) ? res.allowed_domains : [],
        denied_domains: Array.isArray(res.denied_domains) ? res.denied_domains : [],
        session_overrides_count: Number(res.session_overrides_count ?? 0),
      });
    } catch (e) {
      const msg = e instanceof Error ? e.message : String(e);
      setWebPolicyError(msg);
      setWebPolicy(null);
    }
  }, [activeThreadId]);

  const refreshIngestManifests = useCallback(async () => {
    try {
      setIngestError(null);
      const res = await listIngestManifests(20);
      setIngestManifests(Array.isArray(res.manifests) ? res.manifests : []);
    } catch (e) {
      const msg = e instanceof Error ? e.message : String(e);
      setIngestError(msg);
      setIngestManifests([]);
    }
  }, []);

  const loadManifest = useCallback(async (id: string) => {
    try {
      setSelectedManifestError(null);
      setSelectedManifest(null);
      const res = await getIngestManifest(id);
      setSelectedManifest(res.manifest ?? null);
    } catch (e) {
      const msg = e instanceof Error ? e.message : String(e);
      setSelectedManifestError(msg);
      setSelectedManifest(null);
    }
  }, []);

  useEffect(() => {
    void refreshCapabilities();
    void refreshAudit();
    void refreshMemory();
    void refreshWebPolicy();
    void refreshIngestManifests();
  }, [refreshAudit, refreshCapabilities, refreshMemory, refreshWebPolicy, refreshIngestManifests]);

  const filteredAudit = useMemo(() => {
    const q = auditFilter.trim().toLowerCase();
    if (!q) return audit;
    return audit.filter((e) => (e.tool ?? "").toLowerCase().includes(q) || (e.event ?? "").toLowerCase().includes(q));
  }, [audit, auditFilter]);

  const lastAudit = auditTail.length ? auditTail[auditTail.length - 1] : null;
  const lastActionOk = lastAudit?.success ?? null;
  const verificationLabel = (verificationLevel || "").trim() || "UNVERIFIED";
  const verificationSummary =
    verification && typeof verification.confidence === "number"
      ? `${verification.verdict} (${Math.round(verification.confidence * 100)}%)`
      : verificationLabel;
  const providersUsed = Array.isArray(webMeta?.providers_used) ? (webMeta?.providers_used ?? []) : [];
  const providersFailed = Array.isArray(webMeta?.providers_failed) ? (webMeta?.providers_failed ?? []) : [];
  const fetchBlocked = Array.isArray(webMeta?.fetch_blocked) ? (webMeta?.fetch_blocked ?? []) : [];

  return (
    <Panel className="flex min-h-0 flex-col gap-3 p-3">
      <div className="flex items-center justify-between gap-2">
        <div className="text-sm font-semibold">Inspector</div>
        <div className="text-[11px] text-slate-500">
          Last action:{" "}
          <span className={lastActionOk === false ? "text-rose-700" : lastActionOk === true ? "text-emerald-700" : ""}>
            {lastActionOk === null ? "n/a" : lastActionOk ? "ok" : "error"}
          </span>
        </div>
      </div>
      <ScrollArea className="min-h-0 flex-1">
        <div className="flex flex-col gap-3">
          <div className="rounded-xl border border-slate-200 bg-white p-3 text-sm">
            <div className="text-xs font-semibold uppercase tracking-wide text-slate-500">Connection</div>
            <div className="mt-2 space-y-1 text-slate-700">
              <div>
                <span className="font-semibold">API:</span> <code className="text-emerald-700">{apiBase}</code>
              </div>
              <div>
                <span className="font-semibold">Chat:</span> {`${chatProvider} / ${chatModel}`}
              </div>
              <div>
                <span className="font-semibold">Chat Ready:</span> {chatReady ? "yes" : "no"}
              </div>
              <div>
                <span className="font-semibold">Verification:</span>{" "}
                <span className="rounded-md border border-slate-200 bg-slate-50 px-2 py-[1px] text-[11px] text-slate-700">
                  {verificationSummary}
                </span>
              </div>
              {providersUsed.length ? (
                <div>
                  <span className="font-semibold">Search providers:</span> {providersUsed.join(", ")}
                </div>
              ) : null}
              {providersFailed.length ? (
                <div className="text-xs text-rose-700">
                  Providers failed:{" "}
                  {providersFailed
                    .map((p) => `${p.provider ?? p.name ?? "?"}: ${p.error ?? "error"}`)
                    .join(" | ")}
                </div>
              ) : null}
              {fetchBlocked.length ? (
                <details className="mt-2">
                  <summary className="cursor-pointer text-xs font-semibold text-slate-700">
                    Fetch blocked ({fetchBlocked.length})
                  </summary>
                  <div className="mt-2 space-y-1 text-xs text-slate-700">
                    {fetchBlocked.slice(0, 10).map((b) => (
                      <div key={b.url} className="rounded-lg border border-slate-200 bg-slate-50/50 p-2">
                        <div className="break-all font-medium">{b.url}</div>
                        <div className="mt-1 text-slate-500">{b.reason}</div>
                      </div>
                    ))}
                  </div>
                </details>
              ) : null}
              {verification?.contradictions?.length ? (
                <div className="text-xs text-amber-700">Contradictions: {verification.contradictions.length}</div>
              ) : null}
              {chatError && <div className="text-xs text-rose-700">{chatError}</div>}
            </div>
          </div>

          <div className="rounded-xl border border-slate-200 bg-white p-3 text-sm">
            <div className="flex items-center justify-between gap-2">
              <div className="text-xs font-semibold uppercase tracking-wide text-slate-500">Capabilities</div>
              <button
                type="button"
                className="rounded-lg border border-slate-200 bg-white px-2 py-1 text-[11px] hover:bg-slate-50"
                onClick={() => void refreshCapabilities()}
              >
                Refresh
              </button>
            </div>
            {capError ? <div className="mt-2 text-xs text-rose-700">{capError}</div> : null}
            {capabilities ? (
              <div className="mt-2 space-y-2 text-xs text-slate-700">
                <div>
                  <span className="font-semibold">Mode:</span> {capabilities.mode} (unattended disabled)
                </div>
                <div>
                  <span className="font-semibold">Allowed roots:</span>{" "}
                  {capabilities.allowed_roots?.length ? capabilities.allowed_roots.join(", ") : "none"}
                </div>
                <div>
                  <span className="font-semibold">Memory:</span>{" "}
                  {capabilities.memory_enabled ? `${capabilities.memory_backend}` : "disabled"}
                </div>
              </div>
            ) : (
              <div className="mt-2 text-xs text-slate-500">Unavailable</div>
            )}
          </div>

          <div className="rounded-xl border border-slate-200 bg-white p-3 text-sm">
            <div className="flex items-center justify-between gap-2">
              <div className="text-xs font-semibold uppercase tracking-wide text-slate-500">Web Policy</div>
              <button
                type="button"
                className="rounded-lg border border-slate-200 bg-white px-2 py-1 text-[11px] hover:bg-slate-50"
                onClick={() => void refreshWebPolicy()}
              >
                Refresh
              </button>
            </div>
            {webPolicyError ? <div className="mt-2 text-xs text-rose-700">{webPolicyError}</div> : null}
            {webPolicy ? (
              <div className="mt-2 space-y-2 text-xs text-slate-700">
                <div>
                  <span className="font-semibold">Session overrides:</span> {webPolicy.session_overrides_count}
                </div>
                <label className="flex items-center gap-2">
                  <input
                    type="checkbox"
                    checked={webPolicy.allow_all_hosts}
                    onChange={(e) => setWebPolicy((prev) => (prev ? { ...prev, allow_all_hosts: e.target.checked } : prev))}
                  />
                  Allow all hosts (fetch/crawl) — not recommended
                </label>

                <div className="rounded-lg border border-slate-200 bg-slate-50/50 p-2">
                  <div className="font-semibold text-slate-700">Reason (required)</div>
                  <input
                    value={policyReason}
                    onChange={(e) => setPolicyReason(e.target.value)}
                    className="mt-2 w-full rounded-lg border border-slate-200 bg-white px-2 py-1 text-xs outline-none focus:border-slate-400"
                    placeholder="Why are you changing web policy?"
                  />
                </div>

                <details className="rounded-lg border border-slate-200 bg-slate-50/50 p-2">
                  <summary className="cursor-pointer font-semibold text-slate-700">Allowed domains</summary>
                  <div className="mt-2 flex gap-2">
                    <input
                      value={addAllowedDomain}
                      onChange={(e) => setAddAllowedDomain(e.target.value)}
                      className="min-w-0 flex-1 rounded-lg border border-slate-200 bg-white px-2 py-1 text-xs outline-none focus:border-slate-400"
                      placeholder="example.com"
                    />
                    <button
                      type="button"
                      className="rounded-lg border border-slate-200 bg-white px-2 py-1 text-[11px] hover:bg-slate-50 disabled:opacity-50"
                      disabled={!policyReason.trim() || !addAllowedDomain.trim()}
                      onClick={() => {
                        void (async () => {
                          await updateWebPolicy({ allowed_domains_add: [addAllowedDomain.trim()], reason: policyReason.trim() });
                          setAddAllowedDomain("");
                          void refreshWebPolicy();
                          void refreshAudit();
                        })().catch((e) => console.error("Policy update failed", e));
                      }}
                    >
                      Add
                    </button>
                  </div>
                  <div className="mt-2 space-y-1">
                    {webPolicy.allowed_domains.map((d) => (
                      <div key={d} className="flex items-center justify-between gap-2 rounded-lg border border-slate-200 bg-white px-2 py-1">
                        <div className="min-w-0 break-all">{d}</div>
                        <button
                          type="button"
                          className="rounded-md border border-slate-200 bg-white px-2 py-0.5 text-[11px] hover:bg-slate-50 disabled:opacity-50"
                          disabled={!policyReason.trim()}
                          onClick={() => {
                            void (async () => {
                              await updateWebPolicy({ allowed_domains_remove: [d], reason: policyReason.trim() });
                              void refreshWebPolicy();
                              void refreshAudit();
                            })().catch((e) => console.error("Policy update failed", e));
                          }}
                        >
                          Remove
                        </button>
                      </div>
                    ))}
                  </div>
                </details>

                <details className="rounded-lg border border-slate-200 bg-slate-50/50 p-2">
                  <summary className="cursor-pointer font-semibold text-slate-700">Allowed suffixes</summary>
                  <div className="mt-2 flex gap-2">
                    <input
                      value={addAllowedSuffix}
                      onChange={(e) => setAddAllowedSuffix(e.target.value)}
                      className="min-w-0 flex-1 rounded-lg border border-slate-200 bg-white px-2 py-1 text-xs outline-none focus:border-slate-400"
                      placeholder="gov"
                    />
                    <button
                      type="button"
                      className="rounded-lg border border-slate-200 bg-white px-2 py-1 text-[11px] hover:bg-slate-50 disabled:opacity-50"
                      disabled={!policyReason.trim() || !addAllowedSuffix.trim()}
                      onClick={() => {
                        void (async () => {
                          await updateWebPolicy({ allowed_host_suffixes_add: [addAllowedSuffix.trim()], reason: policyReason.trim() });
                          setAddAllowedSuffix("");
                          void refreshWebPolicy();
                          void refreshAudit();
                        })().catch((e) => console.error("Policy update failed", e));
                      }}
                    >
                      Add
                    </button>
                  </div>
                  <div className="mt-2 space-y-1">
                    {webPolicy.allowed_host_suffixes.map((suf) => (
                      <div key={suf} className="flex items-center justify-between gap-2 rounded-lg border border-slate-200 bg-white px-2 py-1">
                        <div className="min-w-0 break-all">{suf}</div>
                        <button
                          type="button"
                          className="rounded-md border border-slate-200 bg-white px-2 py-0.5 text-[11px] hover:bg-slate-50 disabled:opacity-50"
                          disabled={!policyReason.trim()}
                          onClick={() => {
                            void (async () => {
                              await updateWebPolicy({ allowed_host_suffixes_remove: [suf], reason: policyReason.trim() });
                              void refreshWebPolicy();
                              void refreshAudit();
                            })().catch((e) => console.error("Policy update failed", e));
                          }}
                        >
                          Remove
                        </button>
                      </div>
                    ))}
                  </div>
                </details>

                <details className="rounded-lg border border-slate-200 bg-slate-50/50 p-2">
                  <summary className="cursor-pointer font-semibold text-slate-700">Denied domains</summary>
                  <div className="mt-2 flex gap-2">
                    <input
                      value={addDeniedDomain}
                      onChange={(e) => setAddDeniedDomain(e.target.value)}
                      className="min-w-0 flex-1 rounded-lg border border-slate-200 bg-white px-2 py-1 text-xs outline-none focus:border-slate-400"
                      placeholder="facebook.com"
                    />
                    <button
                      type="button"
                      className="rounded-lg border border-slate-200 bg-white px-2 py-1 text-[11px] hover:bg-slate-50 disabled:opacity-50"
                      disabled={!policyReason.trim() || !addDeniedDomain.trim()}
                      onClick={() => {
                        void (async () => {
                          await updateWebPolicy({ denied_domains_add: [addDeniedDomain.trim()], reason: policyReason.trim() });
                          setAddDeniedDomain("");
                          void refreshWebPolicy();
                          void refreshAudit();
                        })().catch((e) => console.error("Policy update failed", e));
                      }}
                    >
                      Add
                    </button>
                  </div>
                  <div className="mt-2 space-y-1">
                    {webPolicy.denied_domains.map((d) => (
                      <div key={d} className="flex items-center justify-between gap-2 rounded-lg border border-slate-200 bg-white px-2 py-1">
                        <div className="min-w-0 break-all">{d}</div>
                        <button
                          type="button"
                          className="rounded-md border border-slate-200 bg-white px-2 py-0.5 text-[11px] hover:bg-slate-50 disabled:opacity-50"
                          disabled={!policyReason.trim()}
                          onClick={() => {
                            void (async () => {
                              await updateWebPolicy({ denied_domains_remove: [d], reason: policyReason.trim() });
                              void refreshWebPolicy();
                              void refreshAudit();
                            })().catch((e) => console.error("Policy update failed", e));
                          }}
                        >
                          Remove
                        </button>
                      </div>
                    ))}
                  </div>
                </details>

                <div className="rounded-lg border border-slate-200 bg-slate-50/50 p-2">
                  <div className="font-semibold text-slate-700">Allow domain for this thread</div>
                  <input
                    value={sessionDomain}
                    onChange={(e) => setSessionDomain(e.target.value)}
                    className="mt-2 w-full rounded-lg border border-slate-200 bg-white px-2 py-1 text-xs outline-none focus:border-slate-400"
                    placeholder="tibia.fandom.com"
                  />
                  <input
                    value={sessionReason}
                    onChange={(e) => setSessionReason(e.target.value)}
                    className="mt-2 w-full rounded-lg border border-slate-200 bg-white px-2 py-1 text-xs outline-none focus:border-slate-400"
                    placeholder="Reason (required)"
                  />
                  <div className="mt-2 flex gap-2">
                    <button
                      type="button"
                      className="flex-1 rounded-lg border border-slate-200 bg-white px-2 py-1 text-[11px] hover:bg-slate-50 disabled:opacity-50"
                      disabled={!activeThreadId || !sessionDomain.trim() || !sessionReason.trim()}
                      onClick={() => {
                        if (!activeThreadId) return;
                        void (async () => {
                          await sessionAllowWebDomain({ thread_id: activeThreadId, domain: sessionDomain.trim(), reason: sessionReason.trim() });
                          setSessionDomain("");
                          setSessionReason("");
                          void refreshWebPolicy();
                          void refreshAudit();
                        })().catch((e) => console.error("Session allow failed", e));
                      }}
                    >
                      Allow (session)
                    </button>
                    <button
                      type="button"
                      className="flex-1 rounded-lg border border-slate-200 bg-white px-2 py-1 text-[11px] hover:bg-slate-50 disabled:opacity-50"
                      disabled={!activeThreadId || !sessionReason.trim()}
                      onClick={() => {
                        if (!activeThreadId) return;
                        void (async () => {
                          await sessionClearWebDomains({ thread_id: activeThreadId, reason: sessionReason.trim() });
                          void refreshWebPolicy();
                          void refreshAudit();
                        })().catch((e) => console.error("Session clear failed", e));
                      }}
                    >
                      Clear (session)
                    </button>
                  </div>
                  {!activeThreadId ? <div className="mt-2 text-slate-500">No active thread selected.</div> : null}
                </div>
              </div>
            ) : (
              <div className="mt-2 text-xs text-slate-500">Unavailable</div>
            )}
          </div>

          <div className="rounded-xl border border-slate-200 bg-white p-3 text-sm">
            <div className="flex items-center justify-between gap-2">
              <div className="text-xs font-semibold uppercase tracking-wide text-slate-500">Ingestion</div>
              <button
                type="button"
                className="rounded-lg border border-slate-200 bg-white px-2 py-1 text-[11px] hover:bg-slate-50"
                onClick={() => void refreshIngestManifests()}
              >
                Refresh
              </button>
            </div>

            <div className="mt-2 rounded-lg border border-slate-200 bg-slate-50/50 p-2 text-xs text-slate-700">
              <div className="font-semibold text-slate-700">Start Tibia monsters ingest</div>
              <div className="mt-2 space-y-2">
                <input
                  value={ingestStartUrl}
                  onChange={(e) => setIngestStartUrl(e.target.value)}
                  className="w-full rounded-lg border border-slate-200 bg-white px-2 py-1 text-xs outline-none focus:border-slate-400"
                  placeholder="https://tibia.fandom.com/wiki/Monsters"
                />
                <div className="flex gap-2">
                  <input
                    value={ingestMaxPages}
                    onChange={(e) => setIngestMaxPages(Number(e.target.value || 0))}
                    className="w-24 rounded-lg border border-slate-200 bg-white px-2 py-1 text-xs outline-none focus:border-slate-400"
                    type="number"
                    min={1}
                    max={200}
                  />
                  <input
                    value={ingestReason}
                    onChange={(e) => setIngestReason(e.target.value)}
                    className="min-w-0 flex-1 rounded-lg border border-slate-200 bg-white px-2 py-1 text-xs outline-none focus:border-slate-400"
                    placeholder="Reason (required)"
                  />
                </div>
                <button
                  type="button"
                  className="w-full rounded-lg border border-slate-200 bg-white px-2 py-1 text-xs hover:bg-slate-50 disabled:opacity-50"
                  disabled={ingestBusy || !ingestReason.trim() || !ingestStartUrl.trim()}
                  onClick={() => {
                    void (async () => {
                      setIngestBusy(true);
                      setIngestRunError(null);
                      try {
                        await runTool(
                          "web.ingest_crawl",
                          {
                            start_url: ingestStartUrl.trim(),
                            max_pages: ingestMaxPages,
                            max_depth: 2,
                            delay_ms: 250,
                            include_patterns: ["/wiki/"],
                            exclude_patterns: ["\\?oldid=", "\\?diff=", "Special:", "File:", "Category:", "Template:"],
                            collection: "tibia",
                            extract_mode: "tibia_monster",
                            write_manifest: true,
                          },
                          ingestReason.trim()
                        );
                        setIngestReason("");
                        void refreshIngestManifests();
                        void refreshAudit();
                        void refreshMemory();
                      } catch (e) {
                        setIngestRunError(e instanceof Error ? e.message : String(e));
                      } finally {
                        setIngestBusy(false);
                      }
                    })();
                  }}
                >
                  {ingestBusy ? "Running…" : "Run"}
                </button>
                {ingestRunError ? <div className="text-rose-700">{ingestRunError}</div> : null}
              </div>
            </div>

            <div className="mt-2 rounded-lg border border-slate-200 bg-slate-50/50 p-2 text-xs text-slate-700">
              <div className="font-semibold text-slate-700">Ingest URL</div>
              <div className="mt-2 space-y-2">
                <input
                  value={ingestStartUrl}
                  onChange={(e) => setIngestStartUrl(e.target.value)}
                  className="w-full rounded-lg border border-slate-200 bg-white px-2 py-1 text-xs outline-none focus:border-slate-400"
                  placeholder="https://example.com/docs"
                />
                <div className="flex gap-2">
                  <select
                    value={ingestUrlMode}
                    onChange={(e) => setIngestUrlMode((e.target.value as any) || "auto")}
                    className="w-28 rounded-lg border border-slate-200 bg-white px-2 py-1 text-xs outline-none focus:border-slate-400"
                  >
                    <option value="auto">auto</option>
                    <option value="single">single</option>
                    <option value="crawl">crawl</option>
                  </select>
                  <input
                    value={ingestMaxPages}
                    onChange={(e) => setIngestMaxPages(Number(e.target.value || 0))}
                    className="w-24 rounded-lg border border-slate-200 bg-white px-2 py-1 text-xs outline-none focus:border-slate-400"
                    type="number"
                    min={1}
                    max={200}
                  />
                  <input
                    value={ingestUrlMaxDepth}
                    onChange={(e) => setIngestUrlMaxDepth(Number(e.target.value || 0))}
                    className="w-20 rounded-lg border border-slate-200 bg-white px-2 py-1 text-xs outline-none focus:border-slate-400"
                    type="number"
                    min={0}
                    max={5}
                  />
                </div>
                <input
                  value={ingestReason}
                  onChange={(e) => setIngestReason(e.target.value)}
                  className="w-full rounded-lg border border-slate-200 bg-white px-2 py-1 text-xs outline-none focus:border-slate-400"
                  placeholder="Reason (required)"
                />
                <button
                  type="button"
                  className="w-full rounded-lg border border-slate-200 bg-white px-2 py-1 text-xs hover:bg-slate-50 disabled:opacity-50"
                  disabled={ingestBusy || !ingestReason.trim() || !ingestStartUrl.trim()}
                  onClick={() => {
                    void (async () => {
                      setIngestBusy(true);
                      setIngestRunError(null);
                      try {
                        await runTool(
                          "web.ingest_url",
                          {
                            start_url: ingestStartUrl.trim(),
                            mode: ingestUrlMode,
                            max_pages: ingestMaxPages,
                            max_depth: ingestUrlMaxDepth,
                            delay_ms: 250,
                            include_patterns: [],
                            exclude_patterns: [],
                            respect_robots: true,
                          },
                          ingestReason.trim()
                        );
                        setIngestReason("");
                        void refreshIngestManifests();
                        void refreshAudit();
                        void refreshMemory();
                      } catch (e) {
                        setIngestRunError(e instanceof Error ? e.message : String(e));
                      } finally {
                        setIngestBusy(false);
                      }
                    })();
                  }}
                >
                  {ingestBusy ? "Running…" : "Run"}
                </button>
                {ingestRunError ? <div className="text-rose-700">{ingestRunError}</div> : null}
              </div>
            </div>

            <details className="mt-2 rounded-lg border border-slate-200 bg-slate-50/50 p-2">
              <summary className="cursor-pointer font-semibold text-slate-700">Recent manifests ({ingestManifests.length})</summary>
              {ingestError ? <div className="mt-2 text-xs text-rose-700">{ingestError}</div> : null}
              {ingestManifests.length === 0 ? (
                <div className="mt-2 text-xs text-slate-500">No manifests found yet.</div>
              ) : (
                <div className="mt-2 space-y-1">
                  {ingestManifests.map((m) => (
                    <button
                      key={m.id}
                      type="button"
                      className="w-full rounded-lg border border-slate-200 bg-white px-2 py-1 text-left text-xs hover:bg-slate-50"
                      onClick={() => {
                        setSelectedManifestId(m.id);
                        void loadManifest(m.id);
                      }}
                    >
                      <div className="flex items-center justify-between gap-2">
                        <div className="min-w-0 truncate font-semibold">{m.id}</div>
                        <div className="text-[10px] text-slate-400">{m.ts ? new Date(m.ts * 1000).toLocaleTimeString() : ""}</div>
                      </div>
                      <div className="mt-1 text-[11px] text-slate-500">
                        docs_ingested={String(m.docs_ingested ?? "")} pages={String(m.pages_ingested ?? "")} errors={String(m.errors_count ?? "")}
                      </div>
                      {m.start_url ? <div className="mt-1 break-all text-[10px] text-slate-500">{m.start_url}</div> : null}
                    </button>
                  ))}
                </div>
              )}
            </details>

            {selectedManifestId ? (
              <details className="mt-2 rounded-lg border border-slate-200 bg-slate-50/50 p-2" open>
                <summary className="cursor-pointer font-semibold text-slate-700">Manifest details</summary>
                {selectedManifestError ? <div className="mt-2 text-xs text-rose-700">{selectedManifestError}</div> : null}
                {selectedManifest ? (
                  <>
                    {manifestRepoDetails ? (
                      <div className="mt-2 rounded-lg border border-slate-200 bg-white p-2 text-[11px] text-slate-700">
                        <div className="font-semibold text-slate-700">Repo ingest</div>
                        <div className="mt-1 text-slate-600">
                          listing_method=<span className="font-mono">{manifestRepoDetails.listingMethod || "unknown"}</span>
                        </div>
                        <div className="mt-1 text-slate-600">
                          files_fetched=<span className="font-mono">{String(manifestRepoDetails.filesFetched)}</span>{" "}
                          files_filtered_out=<span className="font-mono">{String(manifestRepoDetails.filesFilteredOut)}</span>{" "}
                          files_failed=<span className="font-mono">{String(manifestRepoDetails.filesFailed)}</span>
                        </div>
                        {manifestRepoDetails.repoPaths.length ? (
                          <div className="mt-2">
                            <div className="font-semibold text-slate-700">First ingested repo paths</div>
                            <pre className="mt-1 max-h-32 overflow-auto whitespace-pre-wrap rounded-lg border border-slate-200 bg-slate-50 p-2 font-mono text-[10px] text-slate-700">
                              {manifestRepoDetails.repoPaths.join("\n")}
                            </pre>
                          </div>
                        ) : null}
                      </div>
                    ) : null}
                    {manifestPolicySuggestions.length ? (
                      <div className="mt-2 rounded-lg border border-slate-200 bg-white p-2 text-[11px] text-slate-700">
                        <div className="font-semibold text-slate-700">Web policy suggestions</div>
                        <div className="mt-1 text-slate-500">Provide a Web Policy reason (above) to enable one-click allow.</div>
                        <div className="mt-2 space-y-2">
                          {manifestPolicySuggestions.map((s) => (
                            <div key={s.domain} className="flex items-center justify-between gap-2">
                              <div className="min-w-0">
                                <div className="font-mono text-slate-700">{s.domain}</div>
                                {s.reason ? <div className="mt-1 truncate text-slate-500">{s.reason}</div> : null}
                              </div>
                              <button
                                type="button"
                                className="rounded-lg border border-slate-200 bg-white px-2 py-1 text-[11px] hover:bg-slate-50 disabled:opacity-50"
                                disabled={!policyReason.trim()}
                                onClick={() => {
                                  void (async () => {
                                    await updateWebPolicy({ allowed_domains_add: [s.domain], reason: policyReason.trim() });
                                    void refreshWebPolicy();
                                    void refreshAudit();
                                  })().catch((e) => console.error("Update policy failed", e));
                                }}
                              >
                                Allow
                              </button>
                            </div>
                          ))}
                        </div>
                      </div>
                    ) : null}
                    <pre className="mt-2 max-h-64 overflow-auto whitespace-pre-wrap rounded-lg border border-slate-200 bg-white p-2 text-[11px] text-slate-700">
                      {JSON.stringify(selectedManifest, null, 2)}
                    </pre>
                  </>
                ) : (
                  <div className="mt-2 text-xs text-slate-500">Loading…</div>
                )}
              </details>
            ) : null}
          </div>

          <details className="rounded-xl border border-slate-200 bg-white p-3 text-sm">
            <summary className="cursor-pointer text-xs font-semibold uppercase tracking-wide text-slate-500">
              Retrieved context ({retrieved.length})
            </summary>
            {retrieved.length === 0 ? (
              <div className="mt-2 text-xs text-slate-500">No retrieved context for the last reply.</div>
            ) : (
              <div className="mt-2 space-y-2 text-xs text-slate-700">
                {retrieved.map((ch, idx) => (
                  <div key={`${ch.source_id}-${idx}`} className="rounded-lg border border-slate-200 bg-slate-50/40 p-2">
                    <div className="flex items-center justify-between gap-2">
                      <div className="font-semibold">
                        {ch.trust.toUpperCase()} score={ch.score.toFixed(3)}
                      </div>
                      <div className="text-[10px] text-slate-400">{new Date(ch.ts * 1000).toLocaleTimeString()}</div>
                    </div>
                    <div className="mt-1 text-[11px] text-slate-500">{ch.source_id}</div>
                    <div className="mt-2 whitespace-pre-wrap text-xs">{ch.text}</div>
                  </div>
                ))}
              </div>
            )}
          </details>

          <div className="rounded-xl border border-slate-200 bg-white p-3 text-sm">
            <div className="flex items-center justify-between gap-2">
              <div className="text-xs font-semibold uppercase tracking-wide text-slate-500">Audit (tail)</div>
              <button
                type="button"
                className="rounded-lg border border-slate-200 bg-white px-2 py-1 text-[11px] hover:bg-slate-50"
                onClick={() => void refreshAudit()}
              >
                Refresh
              </button>
            </div>
            <div className="mt-2">
              <input
                value={auditFilter}
                onChange={(e) => setAuditFilter(e.target.value)}
                className="w-full rounded-lg border border-slate-200 bg-white px-2 py-1 text-xs outline-none focus:border-slate-400"
                placeholder="Filter by tool/event…"
              />
            </div>
            {auditError ? <div className="mt-2 text-xs text-rose-700">{auditError}</div> : null}
            <div className="mt-2 space-y-2">
              {filteredAudit.slice(-50).map((e, idx) => (
                <div key={`${e.invocation_id ?? idx}`} className="rounded-lg border border-slate-200 bg-slate-50/40 p-2 text-[11px] text-slate-700">
                  <div className="flex items-center justify-between gap-2">
                    <div className="font-semibold">{e.tool ?? e.event}</div>
                    <div className="text-[10px] text-slate-400">{new Date(e.ts * 1000).toLocaleTimeString()}</div>
                  </div>
                  <div className="mt-1 text-slate-500">{e.reason ?? ""}</div>
                  {e.success === false && e.error ? <div className="mt-1 text-rose-700">{e.error}</div> : null}
                </div>
              ))}
            </div>
          </div>

          <div className="rounded-xl border border-slate-200 bg-white p-3 text-sm">
            <div className="flex items-center justify-between gap-2">
              <div className="text-xs font-semibold uppercase tracking-wide text-slate-500">Memory</div>
              <button
                type="button"
                className="rounded-lg border border-slate-200 bg-white px-2 py-1 text-[11px] hover:bg-slate-50"
                onClick={() => void refreshMemory()}
              >
                Refresh
              </button>
            </div>
            {memoryError ? <div className="mt-2 text-xs text-rose-700">{memoryError}</div> : null}
            {memory ? (
              <div className="mt-2 space-y-1 text-xs text-slate-700">
                <div>
                  <span className="font-semibold">Docs:</span> {String(memory.stats.doc_count ?? "")}
                </div>
                <div>
                  <span className="font-semibold">Chunks:</span> {String(memory.stats.chunk_count ?? "")}
                </div>
                <div>
                  <span className="font-semibold">Events:</span> {String(memory.stats.events_count ?? "")}
                </div>
              </div>
            ) : (
              <div className="mt-2 text-xs text-slate-500">Unavailable</div>
            )}
            <div className="mt-3 rounded-lg border border-slate-200 bg-slate-50/50 p-2">
              <div className="text-xs font-semibold text-slate-700">Prune events</div>
              <div className="mt-2 flex gap-2">
                <input
                  value={pruneDays}
                  onChange={(e) => setPruneDays(Number(e.target.value || 0))}
                  className="w-20 rounded-lg border border-slate-200 bg-white px-2 py-1 text-xs outline-none focus:border-slate-400"
                  type="number"
                  min={1}
                  max={3650}
                />
                <input
                  value={pruneReason}
                  onChange={(e) => setPruneReason(e.target.value)}
                  className="min-w-0 flex-1 rounded-lg border border-slate-200 bg-white px-2 py-1 text-xs outline-none focus:border-slate-400"
                  placeholder="Reason (required)…"
                />
              </div>
              <button
                type="button"
                className="mt-2 w-full rounded-lg border border-slate-200 bg-white px-2 py-1 text-xs hover:bg-slate-50 disabled:opacity-50"
                disabled={!pruneReason.trim()}
                onClick={() => {
                  void (async () => {
                    try {
                      await pruneMemoryEvents(pruneDays, pruneReason.trim());
                      setPruneReason("");
                      void refreshAudit();
                      void refreshMemory();
                    } catch (e) {
                      console.error("Prune failed", e);
                    }
                  })();
                }}
              >
                Prune
              </button>
            </div>
          </div>

          <div className="rounded-xl border border-slate-200 bg-slate-50/70 p-3 text-xs text-slate-600">
            <div className="font-semibold text-sm text-slate-900">Status Debug</div>
            <div className="mt-2 space-y-1">
              <div>
                <span className="font-medium text-slate-800">API Base:</span>{" "}
                <code className="text-emerald-700">{apiBase}</code>
              </div>
              <div>
                <span className="font-medium text-slate-800">Chat Provider:</span> {chatProvider}
              </div>
              <div>
                <span className="font-medium text-slate-800">Chat Model:</span> {chatModel}
              </div>
              <div>
                <span className="font-medium text-slate-800">Chat Ready:</span> {chatReady ? "yes" : "no"}
              </div>
              {chatError && (
                <div>
                  <span className="font-medium text-slate-800">Chat Error:</span> {chatError}
                </div>
              )}
              <div>
                <span className="font-medium text-slate-800">Models:</span>{" "}
                {`openai=${openaiCount}, ollama=${ollamaCount}`}
              </div>
              <div>
                <span className="font-medium text-slate-800">Models Refreshing:</span>{" "}
                {modelsRefreshing ? "yes" : "no"}
              </div>
              <div>
                <span className="font-medium text-slate-800">Models Last Refresh:</span>{" "}
                {modelsLastRefresh ? new Date(modelsLastRefresh * 1000).toLocaleTimeString() : "never"}
              </div>
              {modelsError && (
                <div>
                  <span className="font-medium text-slate-800">Models Error:</span> {modelsError}
                </div>
              )}
              <div>
                <span className="font-medium text-slate-800">Last check:</span>{" "}
                {lastCheck ? new Date(lastCheck).toLocaleTimeString() : "pending"}
              </div>
              <div>
                <span className="font-medium text-slate-800">Last error:</span> {lastError ?? "None"}
              </div>
            </div>
          </div>
        </div>
      </ScrollArea>
    </Panel>
  );
}
