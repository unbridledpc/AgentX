export const API_BASE = (() => {
  const rawValue = import.meta.env.VITE_SOL_API as string | undefined;
  const trimmed = (rawValue ?? "").trim();
  if (trimmed.length > 0) {
    return trimmed;
  }
  return "http://127.0.0.1:8420";
})();

export type StatusResponse = {
  ok: boolean;
  name: string;
  ts: number;
  chat_provider?: string;
  chat_model?: string;
  chat_ready?: boolean;
  chat_error?: string | null;
  available_chat_models?: Record<string, string[]>;
  models_last_refresh?: number | null;
  models_refreshing?: boolean;
  models_error?: string | null;
};


export type ChatResponse = {
  role: "assistant";
  content: string;
  ts: number;
  retrieved?: RetrievedChunk[] | null;
  audit_tail?: AuditEntry[] | null;
  sources?: { title: string; url: string; trust?: string }[] | null;
  verification_level?: string | null;
  verification?: { verdict: string; confidence: number; contradictions: string[] } | null;
  web?: { providers_used?: string[]; providers_failed?: { provider?: string; name?: string; error?: string }[]; fetch_blocked?: { url: string; reason: string }[] } | null;
};

export type RetrievedChunk = {
  text: string;
  source_id: string;
  ts: number;
  tags: string[];
  trust: string;
  score: number;
};

export type AuditEntry = {
  ts: number;
  mode: string;
  event: string;
  tool?: string | null;
  args?: Record<string, unknown> | null;
  reason?: string | null;
  duration_ms?: number | null;
  success?: boolean | null;
  summary?: string | null;
  error?: string | null;
  invocation_id?: string | null;
};

export type CapabilitiesResponse = {
  ok: boolean;
  ts: number;
  mode: string;
  supervised_only: boolean;
  allowed_roots: string[];
  denied_substrings: string[];
  denied_path_patterns: string[];
  max_delete_count: number;
  memory_enabled: boolean;
  memory_backend?: string | null;
  memory_db_path?: string | null;
  memory_events_path?: string | null;
};

export type AuditTailResponse = {
  ok: boolean;
  ts: number;
  entries: AuditEntry[];
};

export type MemoryStatsResponse = {
  ok: boolean;
  ts: number;
  stats: Record<string, unknown>;
};

export type MemoryPruneResponse = {
  ok: boolean;
  ts: number;
  result: Record<string, unknown>;
  audit_tail: AuditEntry[];
};

export type IngestManifestSummary = {
  id: string;
  ts?: number | null;
  start_url?: string | null;
  pages_visited?: number | null;
  pages_ingested?: number | null;
  docs_ingested?: number | null;
  errors_count?: number | null;
};

export type IngestManifestsResponse = {
  ok: boolean;
  ts: number;
  manifests: IngestManifestSummary[];
};

export type IngestManifestResponse = {
  ok: boolean;
  ts: number;
  manifest: Record<string, unknown>;
};

export type ToolRunResponse = {
  ok: boolean;
  ts: number;
  output?: unknown;
  error?: string | null;
  audit_tail: AuditEntry[];
};

export type ToolArgSchema = {
  name: string;
  type: string;
  required: boolean;
  description: string;
};

export type ToolSchema = {
  name: string;
  description: string;
  aliases?: string[];
  args: ToolArgSchema[];
};

export type ToolsSchemaResponse = {
  ok: boolean;
  ts: number;
  tools: ToolSchema[];
};

export type WebPolicyResponse = {
  ok: boolean;
  ts: number;
  allow_all_hosts: boolean;
  allowed_host_suffixes: string[];
  allowed_domains: string[];
  denied_domains: string[];
  session_overrides_count: number;
};

export type WebPolicyUpdateRequest = {
  allow_all_hosts?: boolean | null;
  allowed_domains_add?: string[];
  allowed_domains_remove?: string[];
  allowed_host_suffixes_add?: string[];
  allowed_host_suffixes_remove?: string[];
  denied_domains_add?: string[];
  denied_domains_remove?: string[];
  reason: string;
};

export type WebPolicyUpdateResponse = {
  ok: boolean;
  ts: number;
  result: Record<string, unknown>;
  audit_tail: AuditEntry[];
};

export type WebPolicySessionAllowRequest = { thread_id: string; domain: string; reason: string };
export type WebPolicySessionClearRequest = { thread_id: string; reason: string };
export type WebPolicySessionResponse = { ok: boolean; ts: number; audit_tail: AuditEntry[] };

export type ThreadSummary = {
  id: string;
  title: string;
  updated_at: number;
};

export type Message = {
  id: string;
  role: "user" | "assistant" | "system";
  content: string;
  ts: number;
};

export type Thread = {
  id: string;
  title: string;
  created_at: number;
  updated_at: number;
  messages: Message[];
};

export async function getStatus(signal?: AbortSignal, refresh?: boolean): Promise<StatusResponse> {
  const url = refresh ? `${API_BASE}/v1/status?refresh=1` : `${API_BASE}/v1/status`;
  const res = await fetch(url, { signal });
  if (!res.ok) throw new Error(`HTTP ${res.status}`);
  return await res.json();
}

export async function sendChatMessage(message: string, threadId?: string): Promise<ChatResponse> {
  const res = await fetch(`${API_BASE}/v1/chat`, {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
    },
    body: JSON.stringify(threadId ? { message, thread_id: threadId } : { message }),
  });
  if (!res.ok) {
    const body = await res.text();
    throw new Error(`HTTP ${res.status}: ${body}`);
  }
  return await res.json();
}

export async function getCapabilities(): Promise<CapabilitiesResponse> {
  const res = await fetch(`${API_BASE}/v1/capabilities`);
  return handleThreadResponse(res);
}

export async function getAuditTail(limit = 50): Promise<AuditTailResponse> {
  const res = await fetch(`${API_BASE}/v1/audit?limit=${encodeURIComponent(String(limit))}`);
  return handleThreadResponse(res);
}

export async function getMemoryStats(reason: string): Promise<MemoryStatsResponse> {
  const res = await fetch(`${API_BASE}/v1/memory/stats?reason=${encodeURIComponent(reason)}`);
  return handleThreadResponse(res);
}

export async function pruneMemoryEvents(olderThanDays: number, reason: string): Promise<MemoryPruneResponse> {
  const res = await fetch(`${API_BASE}/v1/memory/prune`, {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
    },
    body: JSON.stringify({ older_than_days: olderThanDays, reason }),
  });
  return handleThreadResponse(res);
}

export async function runTool(tool: string, args: Record<string, unknown>, reason: string): Promise<ToolRunResponse> {
  const res = await fetch(`${API_BASE}/v1/tool`, {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
    },
    body: JSON.stringify({ tool, args, reason }),
  });
  return handleThreadResponse(res);
}

export async function getToolsSchema(): Promise<ToolsSchemaResponse> {
  const res = await fetch(`${API_BASE}/v1/tools/schema`);
  return handleThreadResponse(res);
}

export async function getWebPolicy(threadId?: string): Promise<WebPolicyResponse> {
  const url = threadId ? `${API_BASE}/v1/web/policy?thread_id=${encodeURIComponent(threadId)}` : `${API_BASE}/v1/web/policy`;
  const res = await fetch(url);
  return handleThreadResponse(res);
}

export async function updateWebPolicy(payload: WebPolicyUpdateRequest): Promise<WebPolicyUpdateResponse> {
  const res = await fetch(`${API_BASE}/v1/web/policy/update`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  });
  return handleThreadResponse(res);
}

export async function sessionAllowWebDomain(payload: WebPolicySessionAllowRequest): Promise<WebPolicySessionResponse> {
  const res = await fetch(`${API_BASE}/v1/web/policy/session_allow`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  });
  return handleThreadResponse(res);
}

export async function sessionClearWebDomains(payload: WebPolicySessionClearRequest): Promise<WebPolicySessionResponse> {
  const res = await fetch(`${API_BASE}/v1/web/policy/session_clear`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  });
  return handleThreadResponse(res);
}

export async function listIngestManifests(limit = 20): Promise<IngestManifestsResponse> {
  const res = await fetch(`${API_BASE}/v1/memory/ingest/manifests?limit=${encodeURIComponent(String(limit))}`);
  return handleThreadResponse(res);
}

export async function getIngestManifest(manifestId: string): Promise<IngestManifestResponse> {
  const res = await fetch(`${API_BASE}/v1/memory/ingest/manifests/${encodeURIComponent(manifestId)}`);
  return handleThreadResponse(res);
}

async function handleThreadResponse<T>(res: Response): Promise<T> {
  if (!res.ok) {
    const body = await res.text();
    throw new Error(`HTTP ${res.status}: ${body}`);
  }
  return await res.json();
}

export async function listThreads(): Promise<ThreadSummary[]> {
  const res = await fetch(`${API_BASE}/v1/threads`);
  return handleThreadResponse(res);
}

export async function createThread(title?: string): Promise<Thread> {
  const res = await fetch(`${API_BASE}/v1/threads`, {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
    },
    body: JSON.stringify({ title }),
  });
  return handleThreadResponse(res);
}

export async function getThread(id: string): Promise<Thread> {
  const res = await fetch(`${API_BASE}/v1/threads/${id}`);
  return handleThreadResponse(res);
}

export async function appendThreadMessage(
  threadId: string,
  payload: { role: Message["role"]; content: string }
): Promise<Thread> {
  const res = await fetch(`${API_BASE}/v1/threads/${threadId}/messages`, {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
    },
    body: JSON.stringify(payload),
  });
  return handleThreadResponse(res);
}

export async function updateThreadTitle(id: string, title: string): Promise<Thread> {
  const res = await fetch(`${API_BASE}/v1/threads/${id}/title`, {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
    },
    body: JSON.stringify({ title }),
  });
  return handleThreadResponse(res);
}

export async function deleteThread(id: string): Promise<{ ok: boolean }> {
  const res = await fetch(`${API_BASE}/v1/threads/${id}`, { method: "DELETE" });
  return handleThreadResponse(res);
}
