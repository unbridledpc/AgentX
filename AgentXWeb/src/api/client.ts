import { config } from "../config";


export type RagStatusResponse = {
  enabled: boolean;
  db_path: string;
  doc_count: number;
  chunk_count: number;
};

export type RagSource = {
  doc_id: string;
  title: string;
  source: string;
  created_at: number;
  updated_at: number;
  chunk_count: number;
  meta: Record<string, unknown>;
};

export type RagSourcesResponse = { ok: boolean; sources: RagSource[] };
export type RagIngestResult = { ok: boolean; doc_id: string; title: string; source: string; chunks: number; chars: number; truncated: boolean; status: RagStatusResponse };
export type RagQueryHit = { doc_id: string; chunk_id: string; title: string; source: string; snippet: string; content: string; score?: number | null };
export type RagQueryResponse = { hits: RagQueryHit[] };

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
  ollama_endpoints?: Record<string, { base_url?: string; reachable?: boolean; error?: string | null; error_type?: string | null; models?: string[]; gpu_pin?: string | null }>;
  models_last_refresh?: number | null;
  models_refreshing?: boolean;
  models_error?: string | null;
  provider_endpoint_status?: string | null;
  provider_model_status?: string | null;
  provider_error_type?: string | null;
  provider_error_message?: string | null;
};
export type ResponseMetrics = {
  duration_ms: number;
  first_token_ms?: number | null;
  provider?: string | null;
  model?: string | null;
  response_kind?: "chat" | "code" | string;
  input_chars?: number;
  output_chars?: number;
  completed_at?: number;
};

export type QualityGateReport = {
  status?: "passed" | "repaired" | "warning" | "failed" | string;
  passed?: boolean;
  language?: string | null;
  repair_attempted?: boolean;
  repaired?: boolean;
  initial_failures?: string[];
  failures?: string[];
  fixed_failures?: string[];
  warnings?: string[];
  checks_passed?: number;
  checks_failed?: number;
  checks_fixed?: number;
  checks_warned?: number;
  draft_model?: string | null;
  review_model?: string | null;
};

export type RagSourceRef = { title: string; url: string; trust?: string };

export type ChatResponse = {
  role: "assistant";
  content: string;
  ts: number;
  retrieved?: RetrievedChunk[] | null;
  audit_tail?: AuditEntry[] | null;
  sources?: RagSourceRef[] | null;
  rag_used?: boolean;
  rag_hit_count?: number;
  rag_sources?: RagSourceRef[] | null;
  verification_level?: string | null;
  verification?: { verdict: string; confidence: number; contradictions: string[] } | null;
  web?: { providers_used?: string[]; providers_failed?: { provider?: string; name?: string; error?: string }[]; fetch_blocked?: { url: string; reason: string }[] } | null;
  response_metrics?: ResponseMetrics | null;
  quality_gate?: QualityGateReport | null;
};

export type ChatStreamEvent =
  | { event: "meta"; provider?: string; model?: string; ts?: number; stage?: string; draft_model?: string; review_model?: string; quality_gate?: QualityGateReport | null }
  | { event: "delta"; content: string }
  | ((ChatResponse & { event: "done" }) & { retrieved?: RetrievedChunk[] | null; audit_tail?: AuditEntry[] | null })
  | { event: "error"; message: string; detail?: unknown; status_code?: number };
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

export type CodingPipelineRequest = {
  mode: "single" | "draft_review" | "collaborative";
  draft_model?: string | null;
  review_model?: string | null;
};

export type WebPolicySessionResponse = { ok: boolean; ts: number; audit_tail: AuditEntry[] };

export type ThreadSummary = { id: string; title: string; updated_at: number; chat_provider?: string | null; chat_model?: string | null; project_id?: string | null };
export type Message = {
  id: string;
  role: "user" | "assistant" | "system";
  content: string;
  ts: number;
  response_metrics?: ResponseMetrics | null;
  quality_gate?: QualityGateReport | null;
  rag_used?: boolean | null;
  rag_hit_count?: number | null;
  rag_sources?: RagSourceRef[] | null;
};
export type Thread = {
  id: string;
  title: string;
  created_at: number;
  updated_at: number;
  chat_provider?: string | null;
  chat_model?: string | null;
  project_id?: string | null;
  messages: Message[];
};


export type ProjectRecord = {
  id: string;
  name: string;
  description: string;
  created_at: number;
  updated_at: number;
};

export type ScriptRecord = {
  id: string;
  title: string;
  language: string;
  content: string;
  model_provider?: string | null;
  model_name?: string | null;
  source_thread_id?: string | null;
  source_message_id?: string | null;
  created_at: number;
  updated_at: number;
  tags: string[];
};

export type LayoutSettings = {
  showSidebar?: boolean;
  showInspector?: boolean;
  showHeader?: boolean;
  showCodeCanvas?: boolean;
};

export type ModelBehaviorSettings = {
  enabled?: boolean;
  codingContractEnabled?: boolean;
  collaborativeReviewerContractEnabled?: boolean;
  requireFencedCode?: boolean;
  preferStandardLibrary?: boolean;
  windowsAwareExamples?: boolean;
  autoRepairEnabled?: boolean;
  showQualityGateReport?: boolean;
  globalInstructions?: string;
  codingContract?: string;
  collaborativeReviewerContract?: string;
};

export const DEFAULT_LAYOUT_SETTINGS: Required<LayoutSettings> = {
  showSidebar: true,
  showInspector: true,
  showHeader: true,
  showCodeCanvas: true,
};

export const DEFAULT_MODEL_BEHAVIOR_SETTINGS: Required<ModelBehaviorSettings> = {
  enabled: true,
  codingContractEnabled: true,
  collaborativeReviewerContractEnabled: true,
  requireFencedCode: true,
  preferStandardLibrary: true,
  windowsAwareExamples: true,
  autoRepairEnabled: true,
  showQualityGateReport: true,
  globalInstructions: `You are AgentX. Answer directly and helpfully.
Do not invent fake USER/ASSISTANT dialogue.
When the user asks for a file, export, report, or script, make sure the output actually implements that request.`,
  codingContract: `When writing code:
- Provide complete, runnable code.
- Use proper fenced code blocks with the language name.
- Do not write "Copy code."
- Preserve indentation exactly.
- Prefer the standard library unless the user asks for dependencies.
- For CLI scripts, prefer argparse.
- Validate user-provided paths and inputs.
- Handle PermissionError and OSError where file access is involved.
- If the user asks for CSV/export/report/file output, the code must implement that output.
- Include a short run example, using Windows paths when the user appears to be on Windows.
- Do not invent fake USER/ASSISTANT dialogue.`,
  collaborativeReviewerContract: `Collaborative Coding Reviewer Contract

Purpose:
You are the reviewer/finalizer in a collaborative coding pipeline. Another model may have produced a draft. The draft is only a starting point. The original user request is the source of truth.

Core reviewer rules:
- Return one complete final answer, not a review memo.
- Do not return the draft unchanged.
- Even if the draft looks correct, improve it where the checklist requires stronger output.
- Preserve correct draft functionality while fixing bugs, missing requirements, weak structure, bad assumptions, unsafe behavior, and poor UX.
- Compare the final code against every explicit user requirement before answering.
- Do not silently downgrade the request. For example, if the user asks to "monitor" a folder, do not provide only a one-time scan.
- Remove literal labels like "Copy code", fake transcripts, duplicate code, placeholder-only solutions, and hardcoded placeholder paths.
- Prefer built-in language/platform tools and the standard library unless the user requests dependencies.
- Keep the explanation short and practical after the final code.
- Ensure the explanation matches the code. Do not claim the code does something it does not do.
- Include a practical Windows-friendly run example when relevant.

Quality gate awareness:
- The system may run deterministic quality checks after your review.
- If a repair pass lists quality gate failures, fix every listed failure before returning the final answer.
- Do not argue with the quality gate. Repair the code and return one complete improved answer.
- If the gate flags a third-party dependency, replace it with standard-library code unless the user explicitly requested that dependency.

Requirement verification:
- Before finalizing, check every explicit noun and verb in the user request.
- If the user asks for CSV/export/report/file output, the final code must implement that output.
- If the user asks to monitor, implement continuous monitoring/polling or use a file-watcher library only if dependencies are allowed.
- If avoiding third-party dependencies, implement a safe polling loop with an interval argument.
- If the user asks for moving/deleting/renaming files, add safety controls when practical, such as --dry-run.
- Verify loop logic routes each item to the correct destination exactly once.
- Ensure every CLI argument is actually used in the implementation.
- Do not keep fake, invented, or unnecessary dependencies from a draft.
- Do not treat workflow labels like "Draft Review", "Heavy Coding", "AgentX", or "review mode" as software packages.

General CLI/script rules:
- Use CLI arguments instead of interactive prompts unless the user specifically asks for interactive input.
- Include clear help text.
- Validate user-provided paths and inputs before doing work.
- Handle file access errors and output/write errors.
- Return a non-zero exit code on fatal errors when appropriate.
- For destructive or file-moving operations, include --dry-run when practical.
- For generated reports, handle output path creation and write failures.
- Avoid overwriting files unless explicitly requested or protected by a safe collision strategy.

Python rules:
- Use argparse for CLI tools.
- Use pathlib where it improves readability.
- Put imports at the top unless there is a clear reason not to.
- Use parser.error() or sys.exit(1) for fatal CLI errors instead of raw uncaught exceptions.
- Handle PermissionError and OSError around file access.
- Handle CSV/report write errors.
- Avoid broad "except Exception" unless there is a clear reason.
- Do not mix pathlib.Path-only attributes with os.DirEntry objects. If using os.scandir(), wrap entries with Path(entry.path) before using .suffix, .stem, or other pathlib properties.
- Prefer Path.iterdir() or Path.rglob() when the code already uses pathlib.

Python folder organization / monitoring rules:
- Prefer a standard-library polling loop for monitoring unless the user explicitly asks for a filesystem watcher or allows dependencies.
- If the user asks to monitor, implement a continuous loop or polling interval.
- Add --interval for polling frequency.
- Add --dry-run when moving/deleting files.
- Make recursive scanning optional with --recursive when useful.
- Handle KeyboardInterrupt gracefully.
- Use a clear destination root folder, preferably --dest-root.
- Create destination/category folders automatically when needed.
- Move each file based on its own extension, not by scanning once per category.
- Do not infer extension mappings from files already inside destination folders unless the user explicitly asks for that behavior.
- If extension mappings are configurable, use explicit mappings like ".jpg=images" or built-in sensible defaults.
- If using --interval, pass it into the monitoring loop and sleep for that value.
- Avoid scanning/moving files from destination/category folders if destinations are inside the source tree.
- When skipping destination/category folders, compare resolved paths, not just folder names.
- Handle destination filename conflicts by generating a unique destination path instead of silently skipping or overwriting.
- For event-based or polling monitors, check file stability before moving to avoid moving partially written files.
- Do not call the result "production-ready" unless it includes dry-run, collision handling, input validation, destination safety, file-stability handling, and clear fatal error behavior.

PowerShell rules:
- Use param() instead of Read-Host unless interactive mode is requested.
- Add -OutputPath when exporting files.
- Use Test-Path for input paths.
- Use try/catch around file operations.
- Use Write-Error for fatal failures and Write-Warning for skipped files.
- Include an example PowerShell run command.
- Avoid unnecessary Import-Module for built-in cmdlets.
- Prefer built-in cmdlets like Get-FileHash instead of custom hash functions.
- Do not shadow built-in cmdlet names with custom functions.
- Use -LiteralPath for filesystem paths from user input, Get-ChildItem results, or discovered files.
- Use -ErrorAction Stop on PowerShell commands inside try/catch blocks.
- Wrap Export-Csv in its own try/catch and report output/write failures clearly.
- Handle empty/default output directories correctly.
- Avoid invalid or made-up PowerShell operators/aliases such as "-jo".
- Avoid using array += inside large loops when practical; use List[object] for scalable output collections.
- In PowerShell pipeline loops, do not rely on $_ inside catch blocks to refer to the original file object; store the file path in a named variable before try/catch.

PowerShell duplicate-file scanner rules:
- Use Get-FileHash -LiteralPath with an explicit algorithm such as SHA256.
- Group files by hash correctly.
- Include all files in duplicate groups, including the first/reference file.
- Include Hash, Filename, FullPath, SizeBytes, SizeGB, ModifiedTime, and DuplicateCount when relevant.
- Calculate duplicate group count separately from duplicate file entry count.
- If no duplicates are found, print a clear message.
- Handle inaccessible files with warnings and continue when practical.
- Export duplicate results with Export-Csv, not Add-Content or manually joined strings.

Final self-check before answering:
- Does the final code satisfy every explicit user requirement?
- Does it avoid placeholder paths?
- Does it validate inputs?
- Does it handle expected file and output errors?
- Does it avoid overwriting data unexpectedly?
- Does it use the requested language/platform correctly?
- Are all CLI arguments used?
- Does the run example match the actual CLI?
- Is the explanation accurate and not exaggerated?`,
};

export function normalizeLayoutSettings(layout?: LayoutSettings | null): Required<LayoutSettings> {
  return {
    ...DEFAULT_LAYOUT_SETTINGS,
    ...(layout ?? {}),
  };
}

export function normalizeModelBehaviorSettings(modelBehavior?: ModelBehaviorSettings | null): Required<ModelBehaviorSettings> {
  return {
    ...DEFAULT_MODEL_BEHAVIOR_SETTINGS,
    ...(modelBehavior ?? {}),
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
  ollamaMultiEndpointEnabled?: boolean;
  ollamaFastBaseUrl?: string;
  ollamaHeavyBaseUrl?: string;
  ollamaFastModel?: string;
  ollamaHeavyModel?: string;
  ollamaDraftEndpoint?: "default" | "fast" | "heavy";
  ollamaReviewEndpoint?: "default" | "fast" | "heavy";
  ollamaRepairEndpoint?: "default" | "fast" | "heavy";
  ollamaFastGpuPin?: string;
  ollamaHeavyGpuPin?: string;
  assistantDisplayName?: string;
  userDisplayName?: string;
  appearancePreset?: "agentx" | "midnight" | "ice" | "emerald" | "violet" | "amber";
  accentIntensity?: "soft" | "balanced" | "vivid";
  densityMode?: "compact" | "comfortable" | "airy";
  layout?: LayoutSettings;
  modelBehavior?: ModelBehaviorSettings;
};

export const DEFAULT_AGENTX_SETTINGS: Required<AgentXSettings> = {
  showInspector: false,
  inspectorWindow: false,
  theme: "win11-light",
  chatProvider: "stub",
  chatModel: "stub",
  ollamaBaseUrl: "http://127.0.0.1:11434",
  ollamaRequestTimeoutS: 60,
  ollamaMultiEndpointEnabled: false,
  ollamaFastBaseUrl: "http://127.0.0.1:11434",
  ollamaHeavyBaseUrl: "http://127.0.0.1:11435",
  ollamaFastModel: "qwen2.5-coder:7b-4k-gpu",
  ollamaHeavyModel: "devstral-small-2:24b-4k-gpu",
  ollamaDraftEndpoint: "fast",
  ollamaReviewEndpoint: "heavy",
  ollamaRepairEndpoint: "heavy",
  ollamaFastGpuPin: "1",
  ollamaHeavyGpuPin: "0",
  assistantDisplayName: "AgentX",
  userDisplayName: "You",
  appearancePreset: "agentx",
  accentIntensity: "balanced",
  densityMode: "comfortable",
  layout: DEFAULT_LAYOUT_SETTINGS,
  modelBehavior: DEFAULT_MODEL_BEHAVIOR_SETTINGS,
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
  activeArtifact?: ArtifactContextRequest | null,
  codingPipeline?: CodingPipelineRequest | null,
  signal?: AbortSignal
): Promise<ChatResponse & { retrieved?: RetrievedChunk[] | null; audit_tail?: AuditEntry[] | null }> {
  const body: Record<string, unknown> = { message };
  if (threadId) body.thread_id = threadId;
  if (responseMode) body.response_mode = responseMode;
  if (typeof unsafeEnabled === "boolean") body.unsafe_enabled = unsafeEnabled;
  if (activeArtifact) body.active_artifact = activeArtifact;
  if (codingPipeline) body.coding_pipeline = codingPipeline;
  const res = await fetch(`${config.apiBase}/v1/chat`, {
    method: "POST",
    headers: jsonHeaders(),
    body: JSON.stringify(body),
    signal,
  });
  return handle(res);
}

export async function streamChatMessage(
  args: {
    message: string;
    threadId?: string;
    responseMode?: ResponseMode;
    unsafeEnabled?: boolean;
    activeArtifact?: ArtifactContextRequest | null;
    codingPipeline?: CodingPipelineRequest | null;
    signal?: AbortSignal;
    onEvent: (event: ChatStreamEvent) => void;
  }
): Promise<ChatResponse & { retrieved?: RetrievedChunk[] | null; audit_tail?: AuditEntry[] | null }> {
  const body: Record<string, unknown> = { message: args.message };
  if (args.threadId) body.thread_id = args.threadId;
  if (args.responseMode) body.response_mode = args.responseMode;
  if (typeof args.unsafeEnabled === "boolean") body.unsafe_enabled = args.unsafeEnabled;
  if (args.activeArtifact) body.active_artifact = args.activeArtifact;
  if (args.codingPipeline) body.coding_pipeline = args.codingPipeline;

  const res = await fetch(`${config.apiBase}/v1/chat/stream`, {
    method: "POST",
    headers: jsonHeaders(),
    body: JSON.stringify(body),
    signal: args.signal,
  });

  if (!res.ok || !res.body) {
    return handle(res);
  }

  const reader = res.body.getReader();
  const decoder = new TextDecoder();
  let buffer = "";
  let finalResponse: (ChatResponse & { retrieved?: RetrievedChunk[] | null; audit_tail?: AuditEntry[] | null }) | null = null;

  const consumeLine = (line: string) => {
    const trimmed = line.trim();
    if (!trimmed) return;
    const event = JSON.parse(trimmed) as ChatStreamEvent;
    args.onEvent(event);
    if (event.event === "error") {
      const detail = event.detail as ProviderErrorDetail | undefined;
      throw new ApiError(event.message || "Streaming chat failed", { status: event.status_code ?? 502, detail: event.detail ?? null, providerError: detail ?? null });
    }
    if (event.event === "done") {
      finalResponse = event;
    }
  };

  while (true) {
    const { done, value } = await reader.read();
    if (done) break;
    buffer += decoder.decode(value, { stream: true });
    let newlineIndex = buffer.indexOf("\n");
    while (newlineIndex >= 0) {
      const line = buffer.slice(0, newlineIndex);
      buffer = buffer.slice(newlineIndex + 1);
      consumeLine(line);
      newlineIndex = buffer.indexOf("\n");
    }
  }
  buffer += decoder.decode();
  if (buffer.trim()) consumeLine(buffer);

  if (!finalResponse) {
    throw new ApiError("Streaming chat ended without a final response", { status: 502, detail: null, providerError: null });
  }
  return finalResponse;
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


export async function getRagStatus(): Promise<RagStatusResponse> {
  const res = await fetch(`${config.apiBase}/v1/rag/status`, { headers: authHeaders() });
  return handle(res);
}

export async function listRagSources(params: { query?: string; limit?: number } = {}): Promise<RagSourcesResponse> {
  const search = new URLSearchParams();
  if (params.query) search.set("query", params.query);
  if (params.limit) search.set("limit", String(params.limit));
  const qs = search.toString();
  const res = await fetch(`${config.apiBase}/v1/rag/sources${qs ? `?${qs}` : ""}`, { headers: authHeaders() });
  return handle(res);
}

export async function ingestRagUrl(payload: { url: string; title?: string; collection?: string; tags?: string[]; max_chars?: number }): Promise<RagIngestResult> {
  const res = await fetch(`${config.apiBase}/v1/rag/url`, {
    method: "POST",
    headers: jsonHeaders(),
    body: JSON.stringify(payload),
  });
  return handle(res);
}

export async function ingestRagFolder(payload: { path: string; collection?: string; tags?: string[]; max_files?: number; max_bytes?: number; extensions?: string[] }): Promise<RagStatusResponse> {
  const res = await fetch(`${config.apiBase}/v1/rag/folder`, {
    method: "POST",
    headers: jsonHeaders(),
    body: JSON.stringify(payload),
  });
  return handle(res);
}

export async function queryRag(payload: { query: string; k?: number }): Promise<RagQueryResponse> {
  const res = await fetch(`${config.apiBase}/v1/rag/query`, {
    method: "POST",
    headers: jsonHeaders(),
    body: JSON.stringify(payload),
  });
  return handle(res);
}

export async function deleteRagSource(docId: string): Promise<{ ok: boolean; deleted: boolean; status: RagStatusResponse }> {
  const res = await fetch(`${config.apiBase}/v1/rag/sources/${encodeURIComponent(docId)}`, { method: "DELETE", headers: authHeaders() });
  return handle(res);
}

export async function listThreads(): Promise<ThreadSummary[]> {
  const res = await fetch(`${config.apiBase}/v1/threads`, { headers: authHeaders() });
  return handle(res);
}

export async function createThread(title?: string, modelSelection?: { chatProvider?: string; chatModel?: string; projectId?: string | null }): Promise<Thread> {
  const res = await fetch(`${config.apiBase}/v1/threads`, {
    method: "POST",
    headers: jsonHeaders(),
    body: JSON.stringify({
      title,
      chat_provider: modelSelection?.chatProvider,
      chat_model: modelSelection?.chatModel,
      project_id: modelSelection?.projectId ?? null,
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
  payload: { role: Message["role"]; content: string; response_metrics?: ResponseMetrics | null; quality_gate?: QualityGateReport | null; rag_used?: boolean | null; rag_hit_count?: number | null; rag_sources?: RagSourceRef[] | null }
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


export async function updateThreadProject(threadId: string, projectId: string | null): Promise<Thread> {
  const res = await fetch(`${config.apiBase}/v1/threads/${threadId}/project`, {
    method: "POST",
    headers: jsonHeaders(),
    body: JSON.stringify({ project_id: projectId })
  });
  return handle(res);
}

export async function listProjects(): Promise<ProjectRecord[]> {
  const res = await fetch(`${config.apiBase}/v1/projects`, { headers: authHeaders() });
  return handle(res);
}

export async function createProject(name: string, description = ""): Promise<ProjectRecord> {
  const res = await fetch(`${config.apiBase}/v1/projects`, {
    method: "POST",
    headers: jsonHeaders(),
    body: JSON.stringify({ name, description })
  });
  return handle(res);
}

export async function updateProject(projectId: string, payload: { name?: string; description?: string }): Promise<ProjectRecord> {
  const res = await fetch(`${config.apiBase}/v1/projects/${projectId}`, {
    method: "PATCH",
    headers: jsonHeaders(),
    body: JSON.stringify(payload)
  });
  return handle(res);
}

export async function deleteProject(projectId: string): Promise<{ ok: boolean }> {
  const res = await fetch(`${config.apiBase}/v1/projects/${projectId}`, { method: "DELETE", headers: authHeaders() });
  return handle(res);
}

export async function listScripts(params: { query?: string; language?: string; model?: string; threadId?: string } = {}): Promise<ScriptRecord[]> {
  const search = new URLSearchParams();
  if (params.query) search.set("query", params.query);
  if (params.language) search.set("language", params.language);
  if (params.model) search.set("model", params.model);
  if (params.threadId) search.set("thread_id", params.threadId);
  const qs = search.toString();
  const res = await fetch(`${config.apiBase}/v1/scripts${qs ? `?${qs}` : ""}`, { headers: authHeaders() });
  return handle(res);
}

export async function createScript(payload: {
  title: string;
  language: string;
  content: string;
  model_provider?: string | null;
  model_name?: string | null;
  source_thread_id?: string | null;
  source_message_id?: string | null;
  tags?: string[];
}): Promise<ScriptRecord> {
  const res = await fetch(`${config.apiBase}/v1/scripts`, {
    method: "POST",
    headers: jsonHeaders(),
    body: JSON.stringify(payload)
  });
  return handle(res);
}

export async function updateScript(scriptId: string, payload: { title?: string; language?: string; content?: string; tags?: string[] }): Promise<ScriptRecord> {
  const res = await fetch(`${config.apiBase}/v1/scripts/${scriptId}`, {
    method: "PATCH",
    headers: jsonHeaders(),
    body: JSON.stringify(payload)
  });
  return handle(res);
}

export async function deleteScript(scriptId: string): Promise<{ ok: boolean }> {
  const res = await fetch(`${config.apiBase}/v1/scripts/${scriptId}`, { method: "DELETE", headers: authHeaders() });
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
