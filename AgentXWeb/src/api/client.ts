import { config } from "../config";

export type StatusResponse = {
  ok: boolean;
  name: string;
  ts: number;
  auth_enabled?: boolean;
  chat_provider?: string;
  chat_model?: string;
  chat_ready?: boolean;
  chat_error?: string | null;
  available_chat_models?: Record<string, string[]>;
  ollama_base_url?: string;
  models_last_refresh?: number | null;
  models_refreshing?: boolean;
  models_error?: string | null;
  provider_endpoint_status?: string | null;
  provider_model_status?: string | null;
  provider_error_type?: string | null;
  provider_error_message?: string | null;
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
export type ResponseMode = "chat" | "spoken";
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

export type UnsafeStatusResponse = {
  ok: boolean;
  thread_id: string;
  unsafe_enabled: boolean;
  enabled_at?: string | null;
  enabled_by?: string | null;
  reason?: string | null;
  ts?: number;
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
export type ArtifactContextRequest = {
  source: "canvas" | "file" | "tool_output";
  type: "code" | "text" | "json" | "diff" | "output";
  language?: string | null;
  content?: string | null;
  path?: string | null;
  dirty?: boolean;
  title?: string | null;
  label?: string | null;
};
export type WebPolicySessionResponse = { ok: boolean; ts: number; audit_tail: AuditEntry[] };

export type ThreadSummary = { id: string; title: string; updated_at: number; chat_provider?: string | null; chat_model?: string | null };
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
  chat_provider?: string | null;
  chat_model?: string | null;
  messages: Message[];
};

export type LayoutSettings = {
  showSidebar?: boolean;
  showInspector?: boolean;
  showHeader?: boolean;
  showCodeCanvas?: boolean;
};

export const DEFAULT_LAYOUT_SETTINGS: Required<LayoutSettings> = {
  showSidebar: true,
  showInspector: true,
  showHeader: true,
  showCodeCanvas: true,
};

export function normalizeLayoutSettings(layout?: LayoutSettings | null): Required<LayoutSettings> {
  return {
    ...DEFAULT_LAYOUT_SETTINGS,
    ...(layout ?? {}),
  };
}

export type AgentXSettings = {
  showInspector?: boolean;
  inspectorWindow?: boolean;
  theme?: string;
  chatProvider?: string;
  chatModel?: string;
  ollamaBaseUrl?: string;
  ollamaRequestTimeoutS?: number;
  assistantDisplayName?: string;
  userDisplayName?: string;
  appearancePreset?: "agentx" | "midnight" | "ice";
  accentIntensity?: "soft" | "balanced" | "vivid";
  densityMode?: "compact" | "comfortable" | "airy";
  layout?: LayoutSettings;
};

export const DEFAULT_AGENTX_SETTINGS: Required<AgentXSettings> = {
  showInspector: false,
  inspectorWindow: false,
  theme: "win11-light",
  chatProvider: "stub",
  chatModel: "stub",
  ollamaBaseUrl: "http://127.0.0.1:11434",
  ollamaRequestTimeoutS: 60,
  assistantDisplayName: "AgentX",
  userDisplayName: "You",
  appearancePreset: "agentx",
  accentIntensity: "balanced",
  densityMode: "comfortable",
  layout: DEFAULT_LAYOUT_SETTINGS,
};

export type ProviderErrorDetail = {
  type: string;
  provider: string;
  model?: string;
  message: string;
  base_url?: string;
  detail?: string;
  status_code?: number;
  timeout_s?: number;
};

export class ApiError extends Error {
  status: number;
  detail: unknown;
  providerError: ProviderErrorDetail | null;

  constructor(message: string, options: { status: number; detail: unknown; providerError: ProviderErrorDetail | null }) {
    super(message);
    this.name = "ApiError";
    this.status = options.status;
    this.detail = options.detail;
    this.providerError = options.providerError;
  }
}

function isProviderErrorDetail(value: unknown): value is ProviderErrorDetail {
  if (!value || typeof value !== "object") return false;
  const obj = value as Record<string, unknown>;
  return typeof obj.type === "string" && typeof obj.provider === "string" && typeof obj.message === "string";
}

function extractProviderError(body: unknown): ProviderErrorDetail | null {
  if (isProviderErrorDetail(body)) return body;
  if (body && typeof body === "object" && isProviderErrorDetail((body as Record<string, unknown>).detail)) {
    return (body as { detail: ProviderErrorDetail }).detail;
  }
  return null;
}

export function formatProviderErrorMessage(detail: ProviderErrorDetail): string {
  switch (detail.type) {
    case "provider_unreachable":
      return detail.base_url
        ? `The selected Ollama server could not be reached at ${detail.base_url}.`
        : "The selected Ollama server could not be reached.";
    case "provider_timeout":
      return detail.timeout_s
        ? `The model request timed out after ${Math.round(detail.timeout_s)}s.`
        : "The model request timed out.";
    case "model_unavailable":
      return detail.model
        ? `The selected model (${detail.model}) is not available on the Ollama server.`
        : "The selected model is not available on the Ollama server.";
    case "provider_misconfigured":
      return detail.message || "The provider is misconfigured.";
    case "provider_http_error":
      return detail.message || "The provider returned an HTTP error.";
    default:
      return detail.message || "The provider request failed.";
  }
}

async function parseErrorBody(res: Response): Promise<unknown> {
  const text = await res.text();
  if (!text) return null;
  try {
    return JSON.parse(text);
  } catch {
    return text;
  }
}

function authSession(): { user?: unknown; token?: unknown } | null {
  try {
    const raw = localStorage.getItem("agentxweb.auth.v1");
    if (!raw) return null;
    return JSON.parse(raw) as { user?: unknown; token?: unknown };
  } catch {
    return null;
  }
}

function authHeaders(): Record<string, string> {
  const parsed = authSession();
  const token = typeof parsed?.token === "string" ? parsed.token.trim() : "";
  return token ? { Authorization: `Bearer ${token}` } : {};
}

function jsonHeaders(): Record<string, string> {
  return { "Content-Type": "application/json", ...authHeaders() };
}

async function handle<T>(res: Response): Promise<T> {
  if (!res.ok) {
    const body = await parseErrorBody(res);
    const providerError = extractProviderError(body);
    if (res.status === 401) {
      try {
        localStorage.removeItem("agentxweb.auth.v1");
        window.dispatchEvent(new Event("agentxweb:auth-invalid"));
      } catch {
        // ignore
      }
    }
    const message = providerError ? formatProviderErrorMessage(providerError) : `HTTP ${res.status}: ${typeof body === "string" ? body : JSON.stringify(body)}`;
    throw new ApiError(message, { status: res.status, detail: body, providerError });
  }
  return (await res.json()) as T;
}

export async function getStatus(signal?: AbortSignal): Promise<StatusResponse> {
  const res = await fetch(`${config.apiBase}/v1/status`, { signal, headers: authHeaders() });
  return handle(res);
}

export async function getStatusRefresh(signal?: AbortSignal): Promise<StatusResponse> {
  const res = await fetch(`${config.apiBase}/v1/status?refresh=1`, { signal, headers: authHeaders() });
  return handle(res);
}

export async function getSettings(): Promise<AgentXSettings> {
  const res = await fetch(`${config.apiBase}/v1/settings`, { headers: authHeaders() });
  return handle(res);
}

export async function saveSettings(settings: AgentXSettings): Promise<AgentXSettings> {
  const res = await fetch(`${config.apiBase}/v1/settings`, {
    method: "POST",
    headers: jsonHeaders(),
    body: JSON.stringify(settings),
  });
  return handle(res);
}

export async function sendChatMessage(
  message: string,
  threadId?: string,
  responseMode: ResponseMode = "chat",
  unsafeEnabled?: boolean,
  activeArtifact?: ArtifactContextRequest | null
): Promise<ChatResponse & { retrieved?: RetrievedChunk[] | null; audit_tail?: AuditEntry[] | null }> {
  const body: Record<string, unknown> = { message };
  if (threadId) body.thread_id = threadId;
  if (responseMode) body.response_mode = responseMode;
  if (typeof unsafeEnabled === "boolean") body.unsafe_enabled = unsafeEnabled;
  if (activeArtifact) body.active_artifact = activeArtifact;
  const res = await fetch(`${config.apiBase}/v1/chat`, {
    method: "POST",
    headers: jsonHeaders(),
    body: JSON.stringify(body)
  });
  return handle(res);
}

export async function getCapabilities(): Promise<CapabilitiesResponse> {
  const res = await fetch(`${config.apiBase}/v1/capabilities`, { headers: authHeaders() });
  return handle(res);
}

export async function getAuditTail(limit = 50): Promise<AuditTailResponse> {
  const res = await fetch(`${config.apiBase}/v1/audit?limit=${encodeURIComponent(String(limit))}`, { headers: authHeaders() });
  return handle(res);
}

export async function getMemoryStats(reason: string): Promise<MemoryStatsResponse> {
  const res = await fetch(`${config.apiBase}/v1/memory/stats?reason=${encodeURIComponent(reason)}`, { headers: authHeaders() });
  return handle(res);
}

export async function pruneMemoryEvents(threadId: string | null | undefined, olderThanDays: number, reason: string, dryRun = true): Promise<MemoryPruneResponse> {
  const res = await fetch(`${config.apiBase}/v1/memory/prune`, {
    method: "POST",
    headers: jsonHeaders(),
    body: JSON.stringify({ thread_id: threadId ?? null, older_than_days: olderThanDays, reason, dry_run: Boolean(dryRun) })
  });
  return handle(res);
}

export async function runTool(tool: string, args: Record<string, unknown>, reason: string, threadId?: string | null): Promise<ToolRunResponse> {
  const res = await fetch(`${config.apiBase}/v1/tool`, {
    method: "POST",
    headers: jsonHeaders(),
    body: JSON.stringify({ tool, args, reason, thread_id: threadId ?? null })
  });
  return handle(res);
}

export async function getToolsSchema(): Promise<ToolsSchemaResponse> {
  const res = await fetch(`${config.apiBase}/v1/tools/schema`, { headers: authHeaders() });
  return handle(res);
}

export async function getWebPolicy(threadId?: string): Promise<WebPolicyResponse> {
  const url = threadId ? `${config.apiBase}/v1/web/policy?thread_id=${encodeURIComponent(threadId)}` : `${config.apiBase}/v1/web/policy`;
  const res = await fetch(url, { headers: authHeaders() });
  return handle(res);
}

export async function updateWebPolicy(payload: WebPolicyUpdateRequest): Promise<WebPolicyUpdateResponse> {
  const res = await fetch(`${config.apiBase}/v1/web/policy/update`, {
    method: "POST",
    headers: jsonHeaders(),
    body: JSON.stringify(payload),
  });
  return handle(res);
}

export async function sessionAllowWebDomain(payload: WebPolicySessionAllowRequest): Promise<WebPolicySessionResponse> {
  const res = await fetch(`${config.apiBase}/v1/web/policy/session_allow`, {
    method: "POST",
    headers: jsonHeaders(),
    body: JSON.stringify(payload),
  });
  return handle(res);
}

export async function sessionClearWebDomains(payload: WebPolicySessionClearRequest): Promise<WebPolicySessionResponse> {
  const res = await fetch(`${config.apiBase}/v1/web/policy/session_clear`, {
    method: "POST",
    headers: jsonHeaders(),
    body: JSON.stringify(payload),
  });
  return handle(res);
}

export async function listIngestManifests(limit = 20): Promise<IngestManifestsResponse> {
  const res = await fetch(`${config.apiBase}/v1/memory/ingest/manifests?limit=${encodeURIComponent(String(limit))}`, { headers: authHeaders() });
  return handle(res);
}

export async function getIngestManifest(manifestId: string): Promise<IngestManifestResponse> {
  const res = await fetch(`${config.apiBase}/v1/memory/ingest/manifests/${encodeURIComponent(manifestId)}`, { headers: authHeaders() });
  return handle(res);
}

export async function listThreads(): Promise<ThreadSummary[]> {
  const res = await fetch(`${config.apiBase}/v1/threads`, { headers: authHeaders() });
  return handle(res);
}

export async function createThread(title?: string, modelSelection?: { chatProvider?: string; chatModel?: string }): Promise<Thread> {
  const res = await fetch(`${config.apiBase}/v1/threads`, {
    method: "POST",
    headers: jsonHeaders(),
    body: JSON.stringify({
      title,
      chat_provider: modelSelection?.chatProvider,
      chat_model: modelSelection?.chatModel,
    })
  });
  return handle(res);
}

export async function getThread(id: string): Promise<Thread> {
  const res = await fetch(`${config.apiBase}/v1/threads/${id}`, { headers: authHeaders() });
  return handle(res);
}

export async function appendThreadMessage(
  threadId: string,
  payload: { role: Message["role"]; content: string }
): Promise<Thread> {
  const res = await fetch(`${config.apiBase}/v1/threads/${threadId}/messages`, {
    method: "POST",
    headers: jsonHeaders(),
    body: JSON.stringify(payload)
  });
  return handle(res);
}

export async function updateThreadTitle(threadId: string, title: string): Promise<Thread> {
  const res = await fetch(`${config.apiBase}/v1/threads/${threadId}/title`, {
    method: "POST",
    headers: jsonHeaders(),
    body: JSON.stringify({ title })
  });
  return handle(res);
}

export async function updateThreadModel(threadId: string, chatProvider: string, chatModel: string): Promise<Thread> {
  const res = await fetch(`${config.apiBase}/v1/threads/${threadId}/model`, {
    method: "POST",
    headers: jsonHeaders(),
    body: JSON.stringify({ chat_provider: chatProvider, chat_model: chatModel })
  });
  return handle(res);
}

export async function deleteThread(threadId: string): Promise<{ ok: boolean }> {
  const res = await fetch(`${config.apiBase}/v1/threads/${threadId}`, { method: "DELETE", headers: authHeaders() });
  return handle(res);
}

export async function getUnsafeMode(threadId: string): Promise<UnsafeStatusResponse> {
  const res = await fetch(`${config.apiBase}/v1/agent/unsafe/${encodeURIComponent(threadId)}`, { headers: authHeaders() });
  return handle(res);
}

export async function enableUnsafeMode(threadId: string, reason: string): Promise<UnsafeStatusResponse> {
  const res = await fetch(`${config.apiBase}/v1/agent/unsafe/${encodeURIComponent(threadId)}/enable`, {
    method: "POST",
    headers: jsonHeaders(),
    body: JSON.stringify({ reason }),
  });
  return handle(res);
}

export async function disableUnsafeMode(threadId: string, reason?: string): Promise<UnsafeStatusResponse> {
  const res = await fetch(`${config.apiBase}/v1/agent/unsafe/${encodeURIComponent(threadId)}/disable`, {
    method: "POST",
    headers: jsonHeaders(),
    body: JSON.stringify({ reason: reason ?? null }),
  });
  return handle(res);
}
