import React, { useCallback, useEffect, useMemo, useState } from "react";
import { config } from "../../config";
import {
  AuditEntry,
  CapabilitiesResponse,
  IngestManifestSummary,
  ProviderErrorDetail,
  UnsafeStatusResponse,
  disableUnsafeMode,
  enableUnsafeMode,
  getAuditTail,
  getCapabilities,
  getUnsafeMode,
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
} from "../../api/client";
import { NexusDropdown } from "./NexusDropdown";
import { Panel } from "./Panel";
import { ScrollArea } from "./ScrollArea";
import { tokens } from "../tokens";

type Props = {
  statusOk: boolean;
  statusName: string;
  chatProvider: string;
  chatModel: string;
  providerEndpointStatus?: string | null;
  providerModelStatus?: string | null;
  lastProviderError?: ProviderErrorDetail | null;
  retrieved: RetrievedChunk[];
  auditTail: AuditEntry[];
  verificationLevel?: string | null;
  verification?: { verdict: string; confidence: number; contradictions: string[] } | null;
  webMeta?: { providers_used?: string[]; providers_failed?: { provider?: string; name?: string; error?: string }[]; fetch_blocked?: { url: string; reason: string }[] } | null;
  activeThreadId?: string | null;
  unsafeStatus?: UnsafeStatusResponse | null;
  onUnsafeStatus?: (st: UnsafeStatusResponse | null) => void;
};

const sectionSurface = "rounded-xl border border-slate-800/90 bg-slate-950/60 p-2";
const sectionItem = "flex items-center justify-between gap-2 rounded-xl border border-slate-800/90 bg-slate-950/78 px-3 py-2 text-xs";
const summaryText = "cursor-pointer text-xs font-semibold text-slate-200";
const darkInput = tokens.input;
export function InspectorPanel({ statusOk, statusName, chatProvider, chatModel, providerEndpointStatus, providerModelStatus, lastProviderError, retrieved, auditTail, verificationLevel, verification, webMeta, activeThreadId, unsafeStatus, onUnsafeStatus }: Props) {
  const [cap, setCap] = useState<CapabilitiesResponse | null>(null);
  const [capError, setCapError] = useState<string | null>(null);
  const [audit, setAudit] = useState<AuditEntry[]>([]);
  const [auditError, setAuditError] = useState<string | null>(null);
  const [auditFilter, setAuditFilter] = useState("");
  const [memory, setMemory] = useState<MemoryStatsResponse | null>(null);
  const [memoryError, setMemoryError] = useState<string | null>(null);
  const [pruneDays, setPruneDays] = useState(30);
  const [pruneReason, setPruneReason] = useState("");
  const [pruneDryRun, setPruneDryRun] = useState(true);

  const [unsafe, setUnsafe] = useState<UnsafeStatusResponse | null>(unsafeStatus ?? null);
  const [unsafeError, setUnsafeError] = useState<string | null>(null);
  const [unsafeEnableReason, setUnsafeEnableReason] = useState("");
  const [unsafeDisableReason, setUnsafeDisableReason] = useState("");
  const [unsafeBusy, setUnsafeBusy] = useState(false);
  const [webPolicy, setWebPolicy] = useState<{
    allow_all_hosts: boolean;
    allowed_host_suffixes: string[];
    allowed_domains: string[];
    denied_domains: string[];
    session_overrides_count: number;
  } | null>(null);
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
      const res = await getCapabilities();
      setCap(res);
    } catch (e) {
      setCap(null);
      setCapError(e instanceof Error ? e.message : String(e));
    }
  }, []);

  const refreshAudit = useCallback(async () => {
    try {
      setAuditError(null);
      const res = await getAuditTail(50);
      setAudit(res.entries ?? []);
    } catch (e) {
      setAudit([]);
      setAuditError(e instanceof Error ? e.message : String(e));
    }
  }, []);

  const refreshMemory = useCallback(async () => {
    try {
      setMemoryError(null);
      const res = await getMemoryStats("Refresh memory stats in Inspector.");
      setMemory(res);
    } catch (e) {
      setMemory(null);
      setMemoryError(e instanceof Error ? e.message : String(e));
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
      setWebPolicy(null);
      setWebPolicyError(e instanceof Error ? e.message : String(e));
    }
  }, [activeThreadId]);

  const refreshIngestManifests = useCallback(async () => {
    try {
      setIngestError(null);
      const res = await listIngestManifests(20);
      setIngestManifests(Array.isArray(res.manifests) ? res.manifests : []);
    } catch (e) {
      setIngestManifests([]);
      setIngestError(e instanceof Error ? e.message : String(e));
    }
  }, []);

  const loadManifest = useCallback(async (id: string) => {
    try {
      setSelectedManifestError(null);
      setSelectedManifest(null);
      const res = await getIngestManifest(id);
      setSelectedManifest(res.manifest ?? null);
    } catch (e) {
      setSelectedManifest(null);
      setSelectedManifestError(e instanceof Error ? e.message : String(e));
    }
  }, []);

  const refreshUnsafe = useCallback(async () => {
    const tid = (activeThreadId || "").trim();
    if (!tid) {
      setUnsafe(null);
      onUnsafeStatus?.(null);
      return;
    }
    try {
      setUnsafeError(null);
      const res = await getUnsafeMode(tid);
      setUnsafe(res);
      onUnsafeStatus?.(res);
    } catch (e) {
      setUnsafe(null);
      onUnsafeStatus?.(null);
      setUnsafeError(e instanceof Error ? e.message : String(e));
    }
  }, [activeThreadId, onUnsafeStatus]);

  useEffect(() => {
    void refreshCapabilities();
    void refreshAudit();
    void refreshMemory();
    void refreshWebPolicy();
    void refreshIngestManifests();
    void refreshUnsafe();
  }, [refreshAudit, refreshCapabilities, refreshMemory, refreshWebPolicy, refreshIngestManifests, refreshUnsafe]);

  useEffect(() => {
    setUnsafe(unsafeStatus ?? null);
  }, [unsafeStatus]);

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
    <Panel className="nexus-inspector flex min-h-0 flex-col gap-3 p-3">
      <div className="flex items-center justify-between gap-2 rounded-xl border border-slate-800/90 bg-slate-950/72 px-3 py-2">
        <div>
          <div className={tokens.smallLabel}>Inspector</div>
          <div className="mt-1 text-xs text-slate-400">Runtime visibility and thread controls</div>
        </div>
        <div className="text-[11px] text-slate-500">
          Last action:{" "}
          <span className={lastActionOk === false ? "text-rose-300" : lastActionOk === true ? "text-emerald-300" : ""}>
            {lastActionOk === null ? "n/a" : lastActionOk ? "ok" : "error"}
          </span>
        </div>
      </div>
      <ScrollArea className="min-h-0 flex-1 pr-1">
        <div className="space-y-3">
          <Panel className="nexus-inspector-card p-3">
            <div className={tokens.smallLabel}>Connection</div>
            <div className="nexus-kv mt-3 text-sm">
              <div>
                <div className="nexus-kv-label">API</div>
                <div className="nexus-kv-value font-mono text-[13px]">{config.apiBase}</div>
              </div>
              <div>
                <div className="nexus-kv-label">Status</div>
                <div className="nexus-kv-value">{statusOk ? statusName : "Offline"}</div>
              </div>
              <div>
                <div className="nexus-kv-label">Chat</div>
                <div className="nexus-kv-value">{`${chatProvider} / ${chatModel}`}</div>
              </div>
              {chatProvider === "ollama" ? (
                <>
                  <div>
                    <div className="nexus-kv-label">Provider</div>
                    <div className="nexus-kv-value">ollama</div>
                  </div>
                  <div>
                    <div className="nexus-kv-label">Endpoint</div>
                    <div className="nexus-kv-value">{providerEndpointStatus ?? "unknown"}</div>
                  </div>
                  <div>
                    <div className="nexus-kv-label">Model</div>
                    <div className="nexus-kv-value">{providerModelStatus ?? "unknown"}</div>
                  </div>
                  {lastProviderError ? (
                    <div className="rounded-xl border border-rose-400/20 bg-rose-500/10 px-3 py-2 text-xs text-rose-200">
                      Last provider error: {lastProviderError.type} {lastProviderError.message ? `- ${lastProviderError.message}` : ""}
                    </div>
                  ) : null}
                </>
              ) : null}
              <div>
                <div className="nexus-kv-label">Verification</div>
                <span className="nexus-pill inline-flex rounded-full px-2.5 py-1 text-[11px]">
                  {verificationSummary}
                </span>
              </div>
              {providersUsed.length ? (
                <div>
                  <div className="nexus-kv-label">Search providers</div>
                  <div className="nexus-kv-value">{providersUsed.join(", ")}</div>
                </div>
              ) : null}
              {providersFailed.length ? (
                <div className="rounded-xl border border-rose-400/20 bg-rose-500/10 px-3 py-2 text-xs text-rose-200">
                  Providers failed:{" "}
                  {providersFailed
                    .map((p) => `${p.provider ?? p.name ?? "?"}: ${p.error ?? "error"}`)
                    .join(" | ")}
                </div>
              ) : null}
              {fetchBlocked.length ? (
                <details className="mt-2">
                  <summary className={summaryText}>
                    Fetch blocked ({fetchBlocked.length})
                  </summary>
                  <div className="mt-2 space-y-1 text-xs text-slate-300">
                    {fetchBlocked.slice(0, 10).map((b) => (
                      <div key={b.url} className="rounded-xl border border-slate-800 bg-slate-950/80 p-2">
                        <div className="break-all font-medium">{b.url}</div>
                        <div className="mt-1 text-slate-500">{b.reason}</div>
                      </div>
                    ))}
                  </div>
                </details>
              ) : null}
              {verification?.contradictions?.length ? (
                <div className="text-xs text-amber-200">Contradictions: {verification.contradictions.length}</div>
              ) : null}
            </div>
          </Panel>

          <Panel className="nexus-inspector-card p-3">
            <div className="flex items-center justify-between gap-2">
              <div className={tokens.smallLabel}>Unsafe Mode</div>
              <button className={tokens.button} onClick={() => void refreshUnsafe()} disabled={unsafeBusy}>
                Refresh
              </button>
            </div>
            <div className="mt-2 text-sm text-slate-300">
              <div>
                <span className="font-semibold">Status:</span>{" "}
                <span className={unsafe?.unsafe_enabled ? "text-rose-300 font-semibold" : "text-slate-400"}>
                  {unsafe?.unsafe_enabled ? "ON" : "OFF"}
                </span>
              </div>
              {unsafe?.unsafe_enabled ? (
                <div className="mt-2 text-xs text-slate-400">
                  enabled_at={unsafe.enabled_at ?? ""} enabled_by={unsafe.enabled_by ?? ""}
                </div>
              ) : null}
              {unsafe?.unsafe_enabled && unsafe.reason ? <div className="mt-1 text-xs text-slate-400">reason={unsafe.reason}</div> : null}
              {unsafeError ? <div className="mt-2 text-xs text-rose-300">{unsafeError}</div> : null}
              {!activeThreadId ? <div className="mt-2 text-xs text-slate-500">Select a thread to manage unsafe mode.</div> : null}
            </div>

            {activeThreadId ? (
              <div className="mt-3 space-y-2">
                <div className={sectionSurface}>
                  <div className="text-xs font-semibold text-slate-200">Enable (requires reason)</div>
                  <input
                    value={unsafeEnableReason}
                    onChange={(e) => setUnsafeEnableReason(e.target.value)}
                    className={`mt-2 ${darkInput}`}
                    placeholder="Reason..."
                  />
                  <button
                    className={`${tokens.button} mt-2 w-full disabled:opacity-50`}
                    disabled={unsafeBusy || unsafe?.unsafe_enabled || !unsafeEnableReason.trim()}
                    onClick={() => {
                      void (async () => {
                        const tid = (activeThreadId || "").trim();
                        if (!tid) return;
                        setUnsafeBusy(true);
                        setUnsafeError(null);
                        try {
                          const res = await enableUnsafeMode(tid, unsafeEnableReason.trim());
                          setUnsafe(res);
                          onUnsafeStatus?.(res);
                          setUnsafeEnableReason("");
                        } catch (e) {
                          setUnsafeError(e instanceof Error ? e.message : String(e));
                        } finally {
                          setUnsafeBusy(false);
                        }
                      })();
                    }}
                  >
                    Enable UNSAFE mode
                  </button>
                </div>

                <div className={sectionSurface}>
                  <div className="text-xs font-semibold text-slate-200">Disable</div>
                  <input
                    value={unsafeDisableReason}
                    onChange={(e) => setUnsafeDisableReason(e.target.value)}
                    className={`mt-2 ${darkInput}`}
                    placeholder="Reason (optional)..."
                  />
                  <button
                    className={`${tokens.button} mt-2 w-full disabled:opacity-50`}
                    disabled={unsafeBusy || !unsafe?.unsafe_enabled}
                    onClick={() => {
                      void (async () => {
                        const tid = (activeThreadId || "").trim();
                        if (!tid) return;
                        setUnsafeBusy(true);
                        setUnsafeError(null);
                        try {
                          const res = await disableUnsafeMode(tid, unsafeDisableReason.trim() || undefined);
                          setUnsafe(res);
                          onUnsafeStatus?.(res);
                          setUnsafeDisableReason("");
                        } catch (e) {
                          setUnsafeError(e instanceof Error ? e.message : String(e));
                        } finally {
                          setUnsafeBusy(false);
                        }
                      })();
                    }}
                  >
                    Disable UNSAFE mode
                  </button>
                </div>
              </div>
            ) : null}
          </Panel>

          <Panel className="nexus-inspector-card p-3">
            <div className="flex items-center justify-between gap-2">
              <div className={tokens.smallLabel}>Capabilities</div>
              <button className={tokens.button} onClick={() => void refreshCapabilities()}>
                Refresh
              </button>
            </div>
            {capError ? <div className="mt-2 text-xs text-rose-300">{capError}</div> : null}
            {cap ? (
              <div className="mt-2 space-y-1 text-sm text-slate-300">
                <div>
                  <span className="font-semibold">Mode:</span> {cap.mode} (unattended disabled)
                </div>
                <div>
                  <span className="font-semibold">Allowed roots:</span>{" "}
                  {cap.allowed_roots?.length ? cap.allowed_roots.join(", ") : "none"}
                </div>
                <div>
                  <span className="font-semibold">Memory:</span> {cap.memory_enabled ? cap.memory_backend : "disabled"}
                </div>
              </div>
            ) : (
              <div className="mt-2 text-sm text-slate-500">Unavailable</div>
            )}
          </Panel>

          <Panel className="nexus-inspector-card p-3">
            <div className="flex items-center justify-between gap-2">
              <div className={tokens.smallLabel}>Web Policy</div>
              <button className={tokens.button} onClick={() => void refreshWebPolicy()}>
                Refresh
              </button>
            </div>
            {webPolicyError ? <div className="mt-2 text-xs text-rose-300">{webPolicyError}</div> : null}
            {webPolicy ? (
              <div className="mt-2 space-y-2 text-sm text-slate-300">
                <div className="text-xs">
                  <span className="font-semibold">Session overrides:</span> {webPolicy.session_overrides_count}
                </div>
                <label className="flex items-center gap-2 text-xs text-slate-300">
                  <input
                    type="checkbox"
                    checked={webPolicy.allow_all_hosts}
                    onChange={(e) => setWebPolicy((prev) => (prev ? { ...prev, allow_all_hosts: e.target.checked } : prev))}
                  />
                  Allow all hosts (fetch/crawl) — not recommended
                </label>
                <input
                  value={policyReason}
                  onChange={(e) => setPolicyReason(e.target.value)}
                  className={darkInput}
                  placeholder="Reason (required)..."
                />
                <div className="grid grid-cols-1 gap-2">
                  <div className={sectionSurface}>
                    <div className="text-xs font-semibold text-slate-200">Allowed domains</div>
                    <div className="mt-2 flex gap-2">
                      <input
                        value={addAllowedDomain}
                        onChange={(e) => setAddAllowedDomain(e.target.value)}
                        className={`min-w-0 flex-1 ${darkInput}`}
                        placeholder="example.com"
                      />
                      <button
                        className={`${tokens.button} disabled:opacity-50`}
                        disabled={!policyReason.trim() || !addAllowedDomain.trim()}
                        onClick={() => {
                          void (async () => {
                            await updateWebPolicy({ allowed_domains_add: [addAllowedDomain.trim()], reason: policyReason.trim() });
                            setAddAllowedDomain("");
                            void refreshWebPolicy();
                            void refreshAudit();
                          })().catch((e) => console.error(e));
                        }}
                      >
                        Add
                      </button>
                    </div>
                    <div className="mt-2 space-y-1">
                      {webPolicy.allowed_domains.map((d) => (
                        <div key={d} className={sectionItem}>
                          <div className="min-w-0 break-all text-slate-200">{d}</div>
                          <button
                            className={`${tokens.button} disabled:opacity-50`}
                            disabled={!policyReason.trim()}
                            onClick={() => {
                              void (async () => {
                                await updateWebPolicy({ allowed_domains_remove: [d], reason: policyReason.trim() });
                                void refreshWebPolicy();
                                void refreshAudit();
                              })().catch((e) => console.error(e));
                            }}
                          >
                            Remove
                          </button>
                        </div>
                      ))}
                    </div>
                  </div>

                  <div className={sectionSurface}>
                    <div className="text-xs font-semibold text-slate-200">Allowed suffixes</div>
                    <div className="mt-2 flex gap-2">
                      <input
                        value={addAllowedSuffix}
                        onChange={(e) => setAddAllowedSuffix(e.target.value)}
                        className={`min-w-0 flex-1 ${darkInput}`}
                        placeholder="gov"
                      />
                      <button
                        className={`${tokens.button} disabled:opacity-50`}
                        disabled={!policyReason.trim() || !addAllowedSuffix.trim()}
                        onClick={() => {
                          void (async () => {
                            await updateWebPolicy({ allowed_host_suffixes_add: [addAllowedSuffix.trim()], reason: policyReason.trim() });
                            setAddAllowedSuffix("");
                            void refreshWebPolicy();
                            void refreshAudit();
                          })().catch((e) => console.error(e));
                        }}
                      >
                        Add
                      </button>
                    </div>
                    <div className="mt-2 space-y-1">
                      {webPolicy.allowed_host_suffixes.map((suf) => (
                        <div key={suf} className={sectionItem}>
                          <div className="min-w-0 break-all text-slate-200">{suf}</div>
                          <button
                            className={`${tokens.button} disabled:opacity-50`}
                            disabled={!policyReason.trim()}
                            onClick={() => {
                              void (async () => {
                                await updateWebPolicy({ allowed_host_suffixes_remove: [suf], reason: policyReason.trim() });
                                void refreshWebPolicy();
                                void refreshAudit();
                              })().catch((e) => console.error(e));
                            }}
                          >
                            Remove
                          </button>
                        </div>
                      ))}
                    </div>
                  </div>

                  <div className={sectionSurface}>
                    <div className="text-xs font-semibold text-slate-200">Denied domains</div>
                    <div className="mt-2 flex gap-2">
                      <input
                        value={addDeniedDomain}
                        onChange={(e) => setAddDeniedDomain(e.target.value)}
                        className={`min-w-0 flex-1 ${darkInput}`}
                        placeholder="facebook.com"
                      />
                      <button
                        className={`${tokens.button} disabled:opacity-50`}
                        disabled={!policyReason.trim() || !addDeniedDomain.trim()}
                        onClick={() => {
                          void (async () => {
                            await updateWebPolicy({ denied_domains_add: [addDeniedDomain.trim()], reason: policyReason.trim() });
                            setAddDeniedDomain("");
                            void refreshWebPolicy();
                            void refreshAudit();
                          })().catch((e) => console.error(e));
                        }}
                      >
                        Add
                      </button>
                    </div>
                    <div className="mt-2 space-y-1">
                      {webPolicy.denied_domains.map((d) => (
                        <div key={d} className={sectionItem}>
                          <div className="min-w-0 break-all text-slate-200">{d}</div>
                          <button
                            className={`${tokens.button} disabled:opacity-50`}
                            disabled={!policyReason.trim()}
                            onClick={() => {
                              void (async () => {
                                await updateWebPolicy({ denied_domains_remove: [d], reason: policyReason.trim() });
                                void refreshWebPolicy();
                                void refreshAudit();
                              })().catch((e) => console.error(e));
                            }}
                          >
                            Remove
                          </button>
                        </div>
                      ))}
                    </div>
                  </div>

                  <div className={sectionSurface}>
                    <div className="text-xs font-semibold text-slate-200">Allow domain for this thread</div>
                    <input
                      value={sessionDomain}
                      onChange={(e) => setSessionDomain(e.target.value)}
                      className={`mt-2 ${darkInput}`}
                      placeholder="tibia.fandom.com"
                    />
                    <input
                      value={sessionReason}
                      onChange={(e) => setSessionReason(e.target.value)}
                      className={`mt-2 ${darkInput}`}
                      placeholder="Reason (required)..."
                    />
                    <div className="mt-2 flex gap-2">
                      <button
                        className={`${tokens.button} flex-1 disabled:opacity-50`}
                        disabled={!activeThreadId || !sessionDomain.trim() || !sessionReason.trim()}
                        onClick={() => {
                          if (!activeThreadId) return;
                          void (async () => {
                            await sessionAllowWebDomain({ thread_id: activeThreadId, domain: sessionDomain.trim(), reason: sessionReason.trim() });
                            setSessionDomain("");
                            setSessionReason("");
                            void refreshWebPolicy();
                            void refreshAudit();
                          })().catch((e) => console.error(e));
                        }}
                      >
                        Allow (session)
                      </button>
                      <button
                        className={`${tokens.button} flex-1 disabled:opacity-50`}
                        disabled={!activeThreadId || !sessionReason.trim()}
                        onClick={() => {
                          if (!activeThreadId) return;
                          void (async () => {
                            await sessionClearWebDomains({ thread_id: activeThreadId, reason: sessionReason.trim() });
                            void refreshWebPolicy();
                            void refreshAudit();
                          })().catch((e) => console.error(e));
                        }}
                      >
                        Clear (session)
                      </button>
                    </div>
                    {!activeThreadId ? <div className="mt-2 text-xs text-slate-500">No active thread selected.</div> : null}
                  </div>
                </div>
              </div>
            ) : (
              <div className="mt-2 text-sm text-slate-500">Unavailable</div>
            )}
          </Panel>

          <Panel className="nexus-inspector-card p-3">
            <div className="flex items-center justify-between gap-2">
              <div className={tokens.smallLabel}>Ingestion</div>
              <button className={tokens.button} onClick={() => void refreshIngestManifests()}>
                Refresh
              </button>
            </div>

            <div className={`mt-2 ${sectionSurface}`}>
              <div className="text-xs font-semibold text-slate-200">Start Tibia monsters ingest</div>
              <input
                value={ingestStartUrl}
                onChange={(e) => setIngestStartUrl(e.target.value)}
                className={`mt-2 ${darkInput}`}
                placeholder="https://tibia.fandom.com/wiki/Monsters"
              />
              <div className="mt-2 flex gap-2">
                <input
                  value={ingestMaxPages}
                  onChange={(e) => setIngestMaxPages(Number(e.target.value || 0))}
                  className={`w-24 ${tokens.inputNumber}`}
                  type="number"
                  min={1}
                  max={200}
                />
                <input
                  value={ingestReason}
                  onChange={(e) => setIngestReason(e.target.value)}
                  className={`min-w-0 flex-1 ${darkInput}`}
                  placeholder="Reason (required)..."
                />
              </div>
              <button
                className={`${tokens.button} mt-2 w-full disabled:opacity-50`}
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
                        ingestReason.trim(),
                        activeThreadId
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
              {ingestRunError ? <div className="mt-2 text-xs text-rose-300">{ingestRunError}</div> : null}
            </div>

            <div className={`mt-2 ${sectionSurface}`}>
              <div className="text-xs font-semibold text-slate-200">Ingest URL</div>
              <input
                value={ingestStartUrl}
                onChange={(e) => setIngestStartUrl(e.target.value)}
                className={`mt-2 ${darkInput}`}
                placeholder="https://example.com/docs"
              />
              <div className="mt-2 flex gap-2">
                <NexusDropdown
                  value={ingestUrlMode}
                  options={[
                    { value: "auto", label: "auto" },
                    { value: "single", label: "single" },
                    { value: "crawl", label: "crawl" },
                  ]}
                  placeholder="Mode"
                  className="w-28"
                  onChange={(nextValue) => setIngestUrlMode((nextValue as "auto" | "single" | "crawl") || "auto")}
                />
                <input
                  value={ingestMaxPages}
                  onChange={(e) => setIngestMaxPages(Number(e.target.value || 0))}
                  className={`w-24 ${tokens.inputNumber}`}
                  type="number"
                  min={1}
                  max={200}
                />
                <input
                  value={ingestUrlMaxDepth}
                  onChange={(e) => setIngestUrlMaxDepth(Number(e.target.value || 0))}
                  className={`w-20 ${tokens.inputNumber}`}
                  type="number"
                  min={0}
                  max={5}
                />
              </div>
              <input
                value={ingestReason}
                onChange={(e) => setIngestReason(e.target.value)}
                className={`mt-2 ${darkInput}`}
                placeholder="Reason (required)..."
              />
              <button
                className={`${tokens.button} mt-2 w-full disabled:opacity-50`}
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
                        ingestReason.trim(),
                        activeThreadId
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
              {ingestRunError ? <div className="mt-2 text-xs text-rose-300">{ingestRunError}</div> : null}
            </div>

            <details className={`mt-2 ${sectionSurface}`}>
              <summary className={summaryText}>Recent manifests ({ingestManifests.length})</summary>
              {ingestError ? <div className="mt-2 text-xs text-rose-300">{ingestError}</div> : null}
              {ingestManifests.length === 0 ? (
                <div className="mt-2 text-sm text-slate-500">No manifests found yet.</div>
              ) : (
                <div className="mt-2 space-y-2">
                  {ingestManifests.map((m) => (
                    <button
                      key={m.id}
                      className="w-full rounded-xl border border-slate-800/90 bg-slate-950/78 px-3 py-2 text-left text-xs transition hover:border-cyan-300/22 hover:bg-slate-900/82"
                      onClick={() => {
                        setSelectedManifestId(m.id);
                        void loadManifest(m.id);
                      }}
                    >
                      <div className="flex items-center justify-between gap-2">
                        <div className="min-w-0 truncate font-semibold text-slate-200">{m.id}</div>
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
              <details className={`mt-2 ${sectionSurface}`} open>
                <summary className={summaryText}>Manifest details</summary>
                {selectedManifestError ? <div className="mt-2 text-xs text-rose-300">{selectedManifestError}</div> : null}
                {selectedManifest ? (
                  <>
                    {manifestRepoDetails ? (
                      <div className="mt-2 rounded-xl border border-slate-800/90 bg-slate-950/78 p-2 text-[11px] text-slate-300">
                        <div className="font-semibold text-slate-200">Repo ingest</div>
                        <div className="mt-1 text-slate-400">
                          listing_method=<span className="font-mono">{manifestRepoDetails.listingMethod || "unknown"}</span>
                        </div>
                        <div className="mt-1 text-slate-400">
                          files_fetched=<span className="font-mono">{String(manifestRepoDetails.filesFetched)}</span>{" "}
                          files_filtered_out=<span className="font-mono">{String(manifestRepoDetails.filesFilteredOut)}</span>{" "}
                          files_failed=<span className="font-mono">{String(manifestRepoDetails.filesFailed)}</span>
                        </div>
                        {manifestRepoDetails.repoPaths.length ? (
                          <div className="mt-2">
                            <div className="font-semibold text-slate-200">First ingested repo paths</div>
                            <pre className="mt-1 max-h-32 overflow-auto whitespace-pre-wrap rounded-lg border border-slate-800/90 bg-slate-950/86 p-2 font-mono text-[10px] text-slate-300">
                              {manifestRepoDetails.repoPaths.join("\n")}
                            </pre>
                          </div>
                        ) : null}
                      </div>
                    ) : null}
                    {manifestPolicySuggestions.length ? (
                      <div className="mt-2 rounded-xl border border-slate-800/90 bg-slate-950/78 p-2 text-[11px] text-slate-300">
                        <div className="font-semibold text-slate-200">Web policy suggestions</div>
                        <div className="mt-1 text-slate-500">Provide a Web Policy reason (above) to enable one-click allow.</div>
                        <div className="mt-2 space-y-2">
                          {manifestPolicySuggestions.map((s) => (
                            <div key={s.domain} className="flex items-center justify-between gap-2">
                              <div className="min-w-0">
                                <div className="font-mono text-slate-200">{s.domain}</div>
                                {s.reason ? <div className="mt-1 truncate text-slate-500">{s.reason}</div> : null}
                              </div>
                              <button
                                className={`${tokens.button} disabled:opacity-50`}
                                disabled={!policyReason.trim()}
                                onClick={() => {
                                  void (async () => {
                                    await updateWebPolicy({ allowed_domains_add: [s.domain], reason: policyReason.trim() });
                                    void refreshWebPolicy();
                                    void refreshAudit();
                                  })().catch((e) => console.error(e));
                                }}
                              >
                                Allow
                              </button>
                            </div>
                          ))}
                        </div>
                      </div>
                    ) : null}
                    <pre className="mt-2 max-h-64 overflow-auto whitespace-pre-wrap rounded-xl border border-slate-800/90 bg-slate-950/86 p-2 text-[11px] text-slate-300">
                      {JSON.stringify(selectedManifest, null, 2)}
                    </pre>
                  </>
                ) : (
                  <div className="mt-2 text-sm text-slate-500">Loading…</div>
                )}
              </details>
            ) : null}

            <div className="mt-2 text-[11px] text-slate-500">API: <code>{config.apiBase}</code></div>
          </Panel>

          <details className="rounded-2xl border border-slate-800/90 bg-slate-950/74 p-3">
            <summary className={tokens.smallLabel}>Retrieved context ({retrieved.length})</summary>
            {retrieved.length === 0 ? (
              <div className="mt-2 text-sm text-slate-500">No retrieved context for the last reply.</div>
            ) : (
              <div className="mt-3 space-y-3">
                {retrieved.map((ch, idx) => (
                  <div key={`${ch.source_id}-${idx}`} className="rounded-xl border border-slate-800/90 bg-slate-950/76 p-3">
                    <div className="flex items-center justify-between gap-2">
                      <div className="text-xs font-semibold text-slate-200">
                        {ch.trust.toUpperCase()} score={ch.score.toFixed(3)}
                      </div>
                      <div className="text-[10px] text-slate-400">{new Date(ch.ts * 1000).toLocaleTimeString()}</div>
                    </div>
                    <div className="mt-1 text-[11px] text-slate-500">{ch.source_id}</div>
                    <div className="mt-2 whitespace-pre-wrap text-sm text-slate-300">{ch.text}</div>
                  </div>
                ))}
              </div>
            )}
          </details>

          <Panel className="nexus-inspector-card p-3">
            <div className="flex items-center justify-between gap-2">
              <div className={tokens.smallLabel}>Audit (tail)</div>
              <button className={tokens.button} onClick={() => void refreshAudit()}>
                Refresh
              </button>
            </div>
            <input
              value={auditFilter}
              onChange={(e) => setAuditFilter(e.target.value)}
              className={`mt-2 ${darkInput}`}
              placeholder="Filter by tool/event..."
            />
            {auditError ? <div className="mt-2 text-xs text-rose-300">{auditError}</div> : null}
            <div className="mt-2 space-y-2">
              {filteredAudit.slice(-50).map((e, idx) => (
                <div key={`${e.invocation_id ?? idx}`} className="rounded-xl border border-slate-800/90 bg-slate-950/76 p-2 text-xs text-slate-300">
                  <div className="flex items-center justify-between gap-2">
                    <div className="font-semibold text-slate-200">{e.tool ?? e.event}</div>
                    <div className="text-[10px] text-slate-400">{new Date(e.ts * 1000).toLocaleTimeString()}</div>
                  </div>
                  {e.reason ? <div className="mt-1 text-slate-500">{e.reason}</div> : null}
                  {e.success === false && e.error ? <div className="mt-1 text-rose-300">{e.error}</div> : null}
                </div>
              ))}
            </div>
          </Panel>

          <Panel className="nexus-inspector-card p-3">
            <div className="flex items-center justify-between gap-2">
              <div className={tokens.smallLabel}>Memory</div>
              <button className={tokens.button} onClick={() => void refreshMemory()}>
                Refresh
              </button>
            </div>
            {memoryError ? <div className="mt-2 text-xs text-rose-300">{memoryError}</div> : null}
            {memory ? (
              <div className="mt-2 space-y-1 text-sm text-slate-300">
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
              <div className="mt-2 text-sm text-slate-500">Unavailable</div>
            )}

            <div className={`mt-3 ${sectionSurface}`}>
              <div className="text-xs font-semibold text-slate-200">Prune events</div>
              <div className="mt-2 flex gap-2">
                <input
                  value={pruneDays}
                  onChange={(e) => setPruneDays(Number(e.target.value || 0))}
                  className={`w-20 ${tokens.inputNumber}`}
                  type="number"
                  min={1}
                  max={3650}
                />
                <input
                  value={pruneReason}
                  onChange={(e) => setPruneReason(e.target.value)}
                  className={`min-w-0 flex-1 ${darkInput}`}
                  placeholder="Reason (required)..."
                />
              </div>
              <label className="mt-2 flex items-center gap-2 text-xs text-slate-400">
                <input type="checkbox" checked={pruneDryRun} onChange={(e) => setPruneDryRun(e.target.checked)} />
                Dry run (no deletion)
              </label>
              <button
                className={`${tokens.button} mt-2 w-full disabled:opacity-50`}
                disabled={!pruneReason.trim()}
                onClick={() => {
                  void (async () => {
                    try {
                      await pruneMemoryEvents(activeThreadId ?? null, pruneDays, pruneReason.trim(), pruneDryRun);
                      setPruneReason("");
                      void refreshAudit();
                      void refreshMemory();
                    } catch (e) {
                      console.error("Prune failed", e);
                    }
                  })();
                }}
              >
                {pruneDryRun ? "Preview prune" : "Prune"}
              </button>
            </div>
          </Panel>
        </div>
      </ScrollArea>
    </Panel>
  );
}
