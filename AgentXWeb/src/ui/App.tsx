import React, { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { createPortal } from "react-dom";
import {
  DEFAULT_AGENTX_SETTINGS,
  ToolSchema,
  AuditEntry,
  appendThreadMessage,
  createThread,
  getToolsSchema,
  generateDraft,
  importWorkbenchArchive,
  getWorkbenchReport,
  readFsText,
  getSettings,
  getStatus,
  getStatusRefresh,
  getThread,
  getUnsafeMode,
  RetrievedChunk,
  listThreads,
  listProjects,
  listScripts,
  createProject as createProjectRecord,
  updateProject as updateProjectRecord,
  deleteProject as deleteProjectRecord,
  createScript,
  updateScript,
  deleteScript,
  saveSettings,
  streamChatMessage,
  classifyJudgment,
  deleteThread,
  updateThreadTitle,
  updateThreadModel,
  updateThreadProject,
  Thread,
  ThreadSummary,
  UnsafeStatusResponse,
  ApiError,
  normalizeLayoutSettings,
  type ProjectRecord,
  type ScriptRecord,
  type ProviderErrorDetail,
  type AgentXSettings,
  type CodingPipelineRequest,
  type JudgmentClassifyResponse,
  type DraftGenerateResponse,
  type DraftMode,
} from "../api/client";
import { config } from "../config";
import { Panel } from "./components/Panel";
import { ScrollArea } from "./components/ScrollArea";
import { StatusPill } from "./components/StatusPill";
import { ThreadList } from "./components/ThreadList";
import { tokens } from "./tokens";
import { SettingsPage } from "./pages/SettingsPage";
import { CustomizationPage } from "./pages/CustomizationPage";
import { KnowledgePage } from "./pages/KnowledgePage";
import { MemoryPage } from "./pages/MemoryPage";
import { ModelsPage } from "./pages/ModelsPage";
import { ValidationPage } from "./pages/ValidationPage";
import { CodingZonePage } from "./pages/CodingZonePage";
import { HealthPage } from "./pages/HealthPage";
import { clearAuth, loadAuth, logout, tryLogin, type AuthState } from "./auth";
import { ChatMessage } from "./components/ChatMessage";
import { BrandBadge } from "./components/BrandBadge";
import { createClientId } from "./clientId";
import { AgentXDropdown, type AgentXDropdownOption } from "./components/AgentXDropdown";
import { theme } from "./theme";
import { CodeCanvas } from "./components/CodeCanvas";
import { GitHubUpdateTicker } from "./components/GitHubUpdateTicker";
import { TaskReflectionModal } from "./components/TaskReflectionModal";
import { TopStatusBar } from "./layout/TopStatusBar";
import { ModeRail, type DeckModeId } from "./layout/ModeRail";
import { ContextStackPanel } from "./layout/ContextStackPanel";
import { defaultCodeCanvasState, detectCodeCanvas, languageLabel, loadCodeCanvasState, normalizeCodeCanvasLanguage, saveCodeCanvasState, type CodeCanvasState } from "./codeCanvas";
import { applyPendingLayoutToSettings, clearPendingLayoutSave, loadPendingLayoutSave, pendingLayoutChangedEventName } from "./layoutPersistence";
import { buildSendFailureMessage, isAbortError, restoreDraftAfterSendFailure, restoreDraftAfterStop, rollbackOptimisticThread } from "./chatSend";

type ScriptModelLabelSource = {
  model_provider?: string | null;
  model_name?: string | null;
  modelProvider?: string | null;
  modelName?: string | null;
};

function scriptModelLabel(script: ScriptModelLabelSource): string {
  const provider = String(script.model_provider ?? script.modelProvider ?? "").trim();
  const model = String(script.model_name ?? script.modelName ?? "").trim();

  if (provider && model) return `${provider}: ${model}`;
  if (model) return model;
  if (provider) return provider;
  return "Unknown model";
}


type ScriptUtilitySource = {
  title?: string | null;
  language?: string | null;
  created_at?: string | number | null;
  updated_at?: string | number | null;
};

function scriptTimestamp(value: string | number | null | undefined): string {
  if (value === null || value === undefined || value === "") return "Unknown time";

  const raw = typeof value === "number" ? value : Number(value);
  const date = Number.isFinite(raw)
    ? new Date(raw < 1000000000000 ? raw * 1000 : raw)
    : new Date(String(value));

  if (Number.isNaN(date.getTime())) return "Unknown time";

  return new Intl.DateTimeFormat(undefined, {
    month: "short",
    day: "numeric",
    year: "numeric",
    hour: "numeric",
    minute: "2-digit",
  }).format(date);
}

function scriptExtension(language: string | null | undefined): string {
  const normalized = String(language ?? "").trim().toLowerCase();

  if (["python", "py"].includes(normalized)) return "py";
  if (["javascript", "js"].includes(normalized)) return "js";
  if (["typescript", "ts"].includes(normalized)) return "ts";
  if (["ruby", "rb"].includes(normalized)) return "rb";
  if (["cpp", "c++", "cc", "cxx"].includes(normalized)) return "cpp";
  if (["c"].includes(normalized)) return "c";
  if (["csharp", "c#"].includes(normalized)) return "cs";
  if (["java"].includes(normalized)) return "java";
  if (["go", "golang"].includes(normalized)) return "go";
  if (["php"].includes(normalized)) return "php";
  if (["sql"].includes(normalized)) return "sql";
  if (["json"].includes(normalized)) return "json";
  if (["yaml", "yml"].includes(normalized)) return "yml";
  if (["html"].includes(normalized)) return "html";
  if (["css"].includes(normalized)) return "css";
  if (["bash", "shell", "sh"].includes(normalized)) return "sh";
  if (["powershell", "ps1"].includes(normalized)) return "ps1";
  if (["markdown", "md"].includes(normalized)) return "md";

  return "txt";
}

function filenameForScript(script: ScriptUtilitySource): string {
  const title = String(script.title ?? "agentx-script")
    .trim()
    .toLowerCase()
    .replace(/[^a-z0-9._-]+/g, "-")
    .replace(/^-+|-+$/g, "")
    .slice(0, 80);

  return `${title || "agentx-script"}.${scriptExtension(script.language)}`;
}


function useMediaQuery(query: string) {
  const [matches, setMatches] = useState(() => {
    if (typeof window === "undefined" || typeof window.matchMedia !== "function") return false;
    return window.matchMedia(query).matches;
  });

  useEffect(() => {
    if (typeof window === "undefined" || typeof window.matchMedia !== "function") return;
    const media = window.matchMedia(query);
    const onChange = () => setMatches(media.matches);
    onChange();
    if (typeof media.addEventListener === "function") {
      media.addEventListener("change", onChange);
      return () => media.removeEventListener("change", onChange);
    }
    media.addListener(onChange);
    return () => media.removeListener(onChange);
  }, [query]);

  return matches;
}

function generateAutoTitle(message: string): string {
  const sanitized = message.replace(/[^\w\s]/g, " ").replace(/\s+/g, " ").trim();
  const words = sanitized.split(" ").filter(Boolean).slice(0, config.threadTitleWordLimit);
  if (words.length === 0) return config.threadTitleDefault;
  let candidate = words.join(" ");
  if (candidate.length > config.threadTitleMax) {
    candidate = `${candidate.slice(0, Math.max(1, config.threadTitleMax - 3))}...`;
  }
  return candidate;
}

function quoteMessage(content: string): string {
  const lines = content.replace(/\r\n/g, "\n").replace(/\r/g, "\n").split("\n");
  return `${lines.map((line) => `> ${line}`).join("\n")}\n\n`;
}

function buildCodeCanvasPrompt(payload: { scope: "selection" | "document"; content: string; language: string }): string {
  const subject = payload.scope === "selection" ? "selected code" : "entire code canvas";
  return [
    `Work with the ${subject}.`,
    `Detected language: ${payload.language}.`,
    "Explain changes, suggest improvements, or continue the implementation based on this code.",
    "",
    payload.content,
  ].join("\n");
}

function formatAttachmentSize(size: number): string {
  if (!Number.isFinite(size) || size <= 0) return "0 B";
  if (size < 1024) return `${Math.round(size)} B`;
  if (size < 1024 * 1024) return `${(size / 1024).toFixed(1)} KB`;
  return `${(size / (1024 * 1024)).toFixed(1)} MB`;
}

function buildComposerMessage(base: string, attachments: ComposerAttachment[], ragMode: ComposerRagMode): string {
  const lines: string[] = [];
  if (ragMode === "strict") {
    lines.push("Use local RAG knowledge first. If the answer is not present in local knowledge, say what is missing and do not invent references.");
  } else if (ragMode === "off") {
    lines.push("Do not use local RAG knowledge for this reply unless I explicitly ask for it later.");
  }
  if (attachments.length) {
    lines.push("Attached context:");
    for (const item of attachments) {
      lines.push(`- ${item.kind === "image" ? "Image" : "File"}: ${item.name} (${formatAttachmentSize(item.size)})`);
      if (item.content) {
        lines.push("```text");
        lines.push(item.content.slice(0, 8000));
        lines.push("```");
      }
    }
  }
  lines.push(base);
  return lines.filter(Boolean).join("\n\n");
}


function shortBuildSha(value: string): string {
  const trimmed = value.trim();
  return trimmed.length > 8 ? trimmed.slice(0, 8) : trimmed;
}

function AgentXVersionBadge() {
  const version = config.updateFeed.currentVersion || "local";
  const sha = shortBuildSha(config.updateFeed.currentSha || "");
  return (
    <div className="agentx-version-badge" title={`AgentX build ${version}${sha ? ` @ ${sha}` : ""}`}>
      AgentX {version}{sha ? ` @ ${sha}` : ""}
    </div>
  );
}

function buildActiveCanvasArtifact(canvas: CodeCanvasState) {
  if (!canvas.isOpen) return null;
  const content = (canvas.content || "").trim();
  if (!content) return null;
  return {
    source: "canvas" as const,
    type: "code" as const,
    language: canvas.language,
    content,
    dirty: canvas.isDirty,
    path: null,
    title: canvas.title,
    label: canvas.sourceMessageId,
  };
}

function isEditableElement(element: Element | null): boolean {
  if (!(element instanceof HTMLElement)) return false;
  if (element.isContentEditable) return true;
  const tag = element.tagName;
  return tag === "INPUT" || tag === "TEXTAREA" || tag === "SELECT";
}

type HandoffSuggestion = {
  provider: "ollama";
  model: string;
  originalPrompt: string;
  brainstorm: string;
  draftModel?: string | null;
  reviewModel?: string | null;
};

const CODING_HANDOFF_RE = /\b(code this|build this|create this|generate this|make (?:a |an )?(?:script|app|tool|program)|write (?:a |an )?(?:script|app|tool|program)|turn this into code|implement this|i would like you to code|i want you to code|can you code|create an? app|build an? app)\b/i;

const HEAVY_CODING_MODEL_PRIORITY = [
  "devstral-small-2:24b-4k-gpu",
  "devstral-small-2:24b-2k",
  "qwen2.5-coder:7b-4k-gpu",
  "qwen35-heretic-neocode:9b-q6-4k-gpu",
  "dolphincoder:15b-4k-gpu",
];

const FAST_DRAFT_MODEL_PRIORITY = [
  "qwen2.5-coder:7b-4k-gpu",
  "devstral-small-2:24b-4k-gpu",
  "devstral-small-2:24b-2k",
  "dolphincoder:7b-4k-gpu",
];

const REVIEW_MODEL_PRIORITY = [
  "devstral-small-2:24b-4k-gpu",
  "devstral-small-2:24b-2k",
  "qwen2.5-coder:7b-4k-gpu",
];

function shouldSuggestCodingHandoff(text: string): boolean {
  return CODING_HANDOFF_RE.test(text || "");
}

function pickPriorityModel(models: string[], priority: string[], currentModel = "", allowCurrent = false): string | null {
  const available = new Set(models || []);
  for (const model of priority) {
    if (available.has(model) && (allowCurrent || model !== currentModel)) return model;
  }
  return null;
}

function pickHeavyCodingModel(models: string[], currentModel: string): string | null {
  return pickPriorityModel(models, HEAVY_CODING_MODEL_PRIORITY, currentModel)
    ?? (models || []).find((model) => /devstral|coder|code/i.test(model) && model !== currentModel)
    ?? null;
}

function pickFastDraftModel(models: string[], reviewModel: string | null): string | null {
  return pickPriorityModel(models, FAST_DRAFT_MODEL_PRIORITY, reviewModel || "")
    ?? (models || []).find((model) => /qwen|coder|code/i.test(model) && model !== reviewModel)
    ?? null;
}

function pickReviewModel(models: string[], currentModel: string): string | null {
  return pickPriorityModel(models, REVIEW_MODEL_PRIORITY, currentModel, true)
    ?? pickHeavyCodingModel(models, currentModel);
}

function buildHandoffPrompt(suggestion: HandoffSuggestion): string {
  return [
    "Use the brainstorm/spec below and implement it now.",
    "Return production-ready code with proper fenced code blocks, preserved indentation, and brief run instructions.",
    "",
    "Original request:",
    suggestion.originalPrompt,
    "",
    "Brainstorm/spec from the previous assistant:",
    suggestion.brainstorm,
  ].join("\n");
}

function threadSelection(thread: Pick<Thread, "chat_provider" | "chat_model"> | null | undefined, fallback: { provider: string; model: string }) {
  const provider = (thread?.chat_provider || fallback.provider || "stub").trim().toLowerCase();
  const model = (thread?.chat_model || fallback.model || "stub").trim();
  return { provider, model };
}

function threadSummary(thread: Thread): ThreadSummary {
  return {
    id: thread.id,
    title: thread.title,
    updated_at: thread.updated_at,
    chat_provider: thread.chat_provider,
    chat_model: thread.chat_model,
    project_id: thread.project_id,
  };
}


type MessageFeedback = "like" | "dislike";
type MessageFeedbackMap = Record<string, MessageFeedback>;

type ComposerAttachment = {
  id: string;
  name: string;
  kind: "file" | "image";
  size: number;
  content?: string;
};

type ComposerRagMode = "auto" | "strict" | "off";

type DraftWorkspaceState = {
  open: boolean;
  loading: boolean;
  error: string | null;
  mode: DraftMode;
  data: DraftGenerateResponse | null;
};

function emptyDraftWorkspace(): DraftWorkspaceState {
  return { open: false, loading: false, error: null, mode: "explain_and_rewrite", data: null };
}

function languageFromName(name: string | null | undefined): string {
  const filename = String(name ?? "").toLowerCase();
  const ext = filename.includes(".") ? filename.split(".").pop() || "" : "";
  const map: Record<string, string> = {
    py: "python",
    lua: "lua",
    js: "javascript",
    ts: "typescript",
    html: "html",
    htm: "html",
    css: "css",
    xml: "xml",
    php: "php",
    java: "java",
    json: "json",
    yaml: "yaml",
    yml: "yaml",
    md: "markdown",
    sql: "sql",
    sh: "bash",
  };
  return map[ext] || "text";
}

function detectDraftLanguage(content: string, filename?: string | null): string {
  const byName = languageFromName(filename);
  if (byName !== "text") return byName;
  const sample = content.trimStart().slice(0, 500).toLowerCase();
  if (sample.startsWith("<?php")) return "php";
  if (sample.startsWith("<!doctype html") || sample.includes("<html")) return "html";
  if (sample.startsWith("<?xml")) return "xml";
  if (sample.includes("npchandler") || sample.includes("function oncreature")) return "lua";
  return "text";
}

function composerDraftSource(draftText: string, attachments: ComposerAttachment[]): { content: string; filename: string | null; language: string } {
  const textAttachment = attachments.find((item) => item.kind === "file" && String(item.content || "").trim());
  if (textAttachment) {
    const content = String(textAttachment.content || "").trim();
    return { content, filename: textAttachment.name, language: detectDraftLanguage(content, textAttachment.name) };
  }
  const content = draftText.trim();
  return { content, filename: null, language: detectDraftLanguage(content, null) };
}
const MESSAGE_FEEDBACK_KEY = "agentxweb.messageFeedback.v1";

function loadMessageFeedback(): MessageFeedbackMap {
  if (typeof window === "undefined") return {};
  try {
    const raw = window.localStorage.getItem(MESSAGE_FEEDBACK_KEY);
    if (!raw) return {};
    const parsed = JSON.parse(raw) as Record<string, unknown>;
    const result: MessageFeedbackMap = {};
    for (const [id, value] of Object.entries(parsed)) {
      if (value === "like" || value === "dislike") result[id] = value;
    }
    return result;
  } catch {
    return {};
  }
}

function saveMessageFeedback(feedback: MessageFeedbackMap): void {
  if (typeof window === "undefined") return;
  try {
    window.localStorage.setItem(MESSAGE_FEEDBACK_KEY, JSON.stringify(feedback));
  } catch {
    // ignore local feedback persistence failures
  }
}

function previousUserMessage(messages: Thread["messages"], messageId: string): string | null {
  const index = messages.findIndex((message) => message.id === messageId);
  if (index < 0) return null;
  for (let i = index - 1; i >= 0; i -= 1) {
    const message = messages[i];
    if (message.role === "user" && message.content.trim()) return message.content;
  }
  return null;
}

function messageScriptTitle(thread: Thread | null, messageId: string, fallback = "AgentX script"): string {
  const threadTitle = thread?.title && thread.title !== config.threadTitleDefault ? thread.title : fallback;
  return `${threadTitle} ${messageId.slice(0, 6)}`;
}

export function App() {
  const [auth, setAuth] = useState<AuthState | null>(() => loadAuth());
  const [authEnabled, setAuthEnabled] = useState<boolean | null>(null);
  const [activeView, setActiveView] = useState<"chat" | "settings" | "customization" | "scripts" | "coding" | "knowledge" | "models" | "health" | "validation" | "workspaces">("chat");
  const [activeDeckMode, setActiveDeckMode] = useState<DeckModeId>("command");
  const [deckLayoutPrefs, setDeckLayoutPrefs] = useState(() => ({
    showModeRail: window.localStorage.getItem("agentx.deck.showModeRail") !== "false",
    showContextStack: window.localStorage.getItem("agentx.deck.showContextStack") !== "false",
  }));
  const [loginUser, setLoginUser] = useState("agentx");
  const [loginPass, setLoginPass] = useState("");
  const [loginBusy, setLoginBusy] = useState(false);
  const [loginError, setLoginError] = useState<string | null>(null);

  const [statusOk, setStatusOk] = useState(false);
  const [statusName, setStatusName] = useState("Offline");
  const [statusError, setStatusError] = useState<string | null>(null);
  const [chatProvider, setChatProvider] = useState("stub");
  const [chatModel, setChatModel] = useState("stub");
  const [availableModels, setAvailableModels] = useState<Record<string, string[]>>({});
  const [modelsRefreshing, setModelsRefreshing] = useState(false);
  const [modelsError, setModelsError] = useState<string | null>(null);
  const [ollamaBaseUrl, setOllamaBaseUrl] = useState("http://127.0.0.1:11434");
  const [ollamaEndpoints, setOllamaEndpoints] = useState<Record<string, { base_url?: string; reachable?: boolean; error?: string | null; error_type?: string | null; models?: string[]; gpu_pin?: string | null }>>({});
  const [modelsLastRefresh, setModelsLastRefresh] = useState<number | null>(null);
  const [providerEndpointStatus, setProviderEndpointStatus] = useState<string | null>(null);
  const [providerModelStatus, setProviderModelStatus] = useState<string | null>(null);
  const [lastProviderError, setLastProviderError] = useState<ProviderErrorDetail | null>(null);
  const [appSettings, setAppSettings] = useState<AgentXSettings>(DEFAULT_AGENTX_SETTINGS);
  const [pendingLayoutSync, setPendingLayoutSync] = useState(() => loadPendingLayoutSave());
  const sessionReady = authEnabled === false || Boolean(auth);

  const lastServerSelectionRef = useRef<{ provider: string; model: string }>({ provider: "stub", model: "stub" });
  const selectionPersistRef = useRef<Promise<void> | null>(null);
  const modelDropdownOpenRef = useRef(false);

  const [threads, setThreads] = useState<ThreadSummary[]>([]);
  const [activeThread, setActiveThread] = useState<Thread | null>(null);
  const [loadingThreads, setLoadingThreads] = useState(false);
  const [sending, setSending] = useState(false);
  const activeSendAbortRef = useRef<AbortController | null>(null);
  const [lastRetrieved, setLastRetrieved] = useState<RetrievedChunk[]>([]);
  const [lastAuditTail, setLastAuditTail] = useState<AuditEntry[]>([]);
  const [lastVerificationLevel, setLastVerificationLevel] = useState<string | null>(null);
  const [lastVerification, setLastVerification] = useState<{ verdict: string; confidence: number; contradictions: string[] } | null>(null);
  const [lastWebMeta, setLastWebMeta] = useState<
    {
      providers_used?: string[];
      providers_failed?: { provider?: string; name?: string; error?: string }[];
      fetch_blocked?: { url: string; reason: string }[];
    } | null
  >(null);
  const [unsafeStatus, setUnsafeStatus] = useState<UnsafeStatusResponse | null>(null);
  const [codeCanvas, setCodeCanvas] = useState<CodeCanvasState>(() => defaultCodeCanvasState());
  const [projects, setProjects] = useState<ProjectRecord[]>([]);
  const [activeProjectId, setActiveProjectId] = useState<string | null>(null);
  const activeProject = useMemo(() => projects.find((project) => project.id === activeProjectId) ?? null, [activeProjectId, projects]);
  const [projectMenu, setProjectMenu] = useState<{ id: string; x: number; y: number } | null>(null);

  useEffect(() => {
    if (!projectMenu) return;

    const onProjectMenuEscape = (event: KeyboardEvent) => {
      if (event.key === "Escape") {
        event.preventDefault();
        event.stopPropagation();
        setProjectMenu(null);
      }
    };

    window.addEventListener("keydown", onProjectMenuEscape, true);

    return () => {
      window.removeEventListener("keydown", onProjectMenuEscape, true);
    };
  }, [projectMenu]);
  const [scripts, setScripts] = useState<ScriptRecord[]>([]);
  const [scriptQuery, setScriptQuery] = useState("");
  const [activeScriptId, setActiveScriptId] = useState<string | null>(null);
  const activeScript = useMemo(() => scripts.find((script) => script.id === activeScriptId) ?? scripts[0] ?? null, [activeScriptId, scripts]);
  const [scriptDraft, setScriptDraft] = useState<{ title: string; content: string; language: string }>({ title: "", content: "", language: "text" });
  const [messageFeedback, setMessageFeedback] = useState<MessageFeedbackMap>(() => loadMessageFeedback());
  const [handoffSuggestion, setHandoffSuggestion] = useState<HandoffSuggestion | null>(null);

  const [draft, setDraft] = useState("");
  const [judgmentPreview, setJudgmentPreview] = useState<JudgmentClassifyResponse | null>(null);
  const [judgmentPreviewError, setJudgmentPreviewError] = useState<string | null>(null);
  const [judgmentPreviewLoading, setJudgmentPreviewLoading] = useState(false);
  const [judgmentAutoRouteEnabled, setJudgmentAutoRouteEnabled] = useState(() => {
    try {
      return window.localStorage.getItem("agentx.judgment.autoRoute.v1") === "true";
    } catch {
      return false;
    }
  });
  const [composerMenuOpen, setComposerMenuOpen] = useState(false);
  const [taskReflectionOpen, setTaskReflectionOpen] = useState(false);

  useEffect(() => {
    if (!composerMenuOpen) return;

    const closeComposerMenu = (event: MouseEvent) => {
      const target = event.target as HTMLElement | null;

      if (
        target?.closest(".agentx-composer-menu") ||
        target?.closest(".agentx-composer-plus") ||
        target?.closest(".agentx-composer-plus-wrap")
      ) {
        return;
      }

      setComposerMenuOpen(false);
    };

    const closeComposerMenuOnEscape = (event: KeyboardEvent) => {
      if (event.key === "Escape") {
        event.preventDefault();
        event.stopPropagation();
        setComposerMenuOpen(false);
      }
    };

    document.addEventListener("mousedown", closeComposerMenu, true);
    document.addEventListener("keydown", closeComposerMenuOnEscape, true);

    return () => {
      document.removeEventListener("mousedown", closeComposerMenu, true);
      document.removeEventListener("keydown", closeComposerMenuOnEscape, true);
    };
  }, [composerMenuOpen]);
  const [composerAttachments, setComposerAttachments] = useState<ComposerAttachment[]>([]);
  const [composerRagMode, setComposerRagMode] = useState<ComposerRagMode>("auto");
  const [draftWorkspace, setDraftWorkspace] = useState<DraftWorkspaceState>(() => emptyDraftWorkspace());
  const fileInputRef = useRef<HTMLInputElement | null>(null);
  const archiveInputRef = useRef<HTMLInputElement | null>(null);
  const imageInputRef = useRef<HTMLInputElement | null>(null);
  const textareaRef = useRef<HTMLTextAreaElement | null>(null);

  useEffect(() => {
    const value = draft.trim();
    if (!value || activeView !== "chat" || !statusOk) {
      setJudgmentPreview(null);
      setJudgmentPreviewError(null);
      setJudgmentPreviewLoading(false);
      return;
    }

    const controller = new AbortController();
    const timer = window.setTimeout(() => {
      setJudgmentPreviewLoading(true);
      setJudgmentPreviewError(null);
      void classifyJudgment(
        value,
        activeThread?.messages?.length ?? 0,
        Boolean(lastProviderError),
        controller.signal
      )
        .then((result: JudgmentClassifyResponse) => {
          setJudgmentPreview(result);
          setJudgmentPreviewError(null);
        })
        .catch((error: unknown) => {
          if ((error as Error)?.name === "AbortError") return;
          setJudgmentPreview(null);
          setJudgmentPreviewError((error as Error)?.message || "Judgment unavailable");
        })
        .finally(() => {
          if (!controller.signal.aborted) setJudgmentPreviewLoading(false);
        });
    }, 450);

    return () => {
      window.clearTimeout(timer);
      controller.abort();
    };
  }, [activeThread?.messages?.length, activeView, draft, lastProviderError, statusOk]);

  const feedRef = useRef<HTMLDivElement | null>(null);
  const nearBottomRef = useRef(true);
  const scrollRafRef = useRef<number | null>(null);
  const lastAutoScrolledKeyRef = useRef<string | null>(null);
  const lastThreadForScrollRef = useRef<string | null>(null);
  const [showJumpToLatest, setShowJumpToLatest] = useState(false);
  const focusRafRef = useRef<number | null>(null);
  const [tools, setTools] = useState<ToolSchema[] | null>(null);
  const [toolError, setToolError] = useState<string | null>(null);
  const [toolSuggestions, setToolSuggestions] = useState<
    { display: string; canonical: string; tool: ToolSchema }[]
  >([]);
  const [toolHighlight, setToolHighlight] = useState(0);
  const [selectedTool, setSelectedTool] = useState<ToolSchema | null>(null);
  const toolSchemaLoadedRef = useRef(false);

  const isMobile = useMediaQuery("(max-width: 767px)");
  const [navOpen, setNavOpen] = useState(false);
  const requestedLayout = useMemo(() => normalizeLayoutSettings(appSettings.layout), [appSettings.layout]);
  const layoutSettings = useMemo(() => {
    const layout = requestedLayout;
    if (isMobile && layout.showSidebar && !layout.showHeader) {
      return { ...layout, showHeader: true };
    }
    return layout;
  }, [isMobile, requestedLayout]);
  const layoutGuards = useMemo(
    () => ({
      headerForcedVisible: isMobile && requestedLayout.showSidebar && !requestedLayout.showHeader,
      inspectorUnavailableReason: isMobile
        ? "Inspector is hidden on mobile layouts."
        : !config.showInspector
          ? "Inspector is disabled in this runtime."
          : null,
      codeCanvasInactive: !codeCanvas.isOpen,
    }),
    [codeCanvas.isOpen, isMobile, requestedLayout.showHeader, requestedLayout.showSidebar]
  );

  const onAfterNavAction = useCallback(() => {
    if (isMobile) setNavOpen(false);
  }, [isMobile]);

  useEffect(() => {
    setCodeCanvas(loadCodeCanvasState());
  }, []);

  useEffect(() => {
    saveCodeCanvasState(codeCanvas);
  }, [codeCanvas]);

  useEffect(() => {
    saveMessageFeedback(messageFeedback);
  }, [messageFeedback]);

  useEffect(() => {
    if (!isMobile) setNavOpen(false);
  }, [isMobile]);

  useEffect(() => {
    if (!layoutSettings.showSidebar) {
      setNavOpen(false);
    }
  }, [layoutSettings.showSidebar]);

  useEffect(() => {
    if (!layoutSettings.showCodeCanvas && codeCanvas.isOpen) {
      setCodeCanvas((prev) => ({ ...prev, isOpen: false, viewMode: "docked" }));
    }
  }, [codeCanvas.isOpen, layoutSettings.showCodeCanvas]);

  useEffect(() => {
    if (!navOpen) return;
    const onKeyDown = (event: KeyboardEvent) => {
      if (event.key === "Escape") setNavOpen(false);
    };
    window.addEventListener("keydown", onKeyDown);
    return () => window.removeEventListener("keydown", onKeyDown);
  }, [navOpen]);

  useEffect(() => {
    return () => {
      if (focusRafRef.current !== null) {
        window.cancelAnimationFrame(focusRafRef.current);
      }
    };
  }, []);

  useEffect(() => {
    const tid = activeThread?.id ?? null;
    if (!sessionReady || !tid) {
      setUnsafeStatus(null);
      return;
    }
    let canceled = false;
    void (async () => {
      try {
        const res = await getUnsafeMode(tid);
        if (!canceled) setUnsafeStatus(res);
      } catch {
        if (!canceled) setUnsafeStatus(null);
      }
    })();
    return () => {
      canceled = true;
    };
  }, [activeThread?.id, sessionReady]);

  const visibleThreads = useMemo(() => {
    if (!activeProjectId) return threads;
    return threads.filter((t) => t.project_id === activeProjectId);
  }, [activeProjectId, threads]);

  const modelOptions = useMemo(() => {
    const openai = Array.isArray(availableModels.openai) ? availableModels.openai : [];
    const ollama = Array.isArray(availableModels.ollama) ? availableModels.ollama : [];
    const selectedKey = `${(chatProvider || "stub").toLowerCase()}:${chatModel || "stub"}`;
    const keys = new Set<string>();
    for (const id of openai) keys.add(`openai:${id}`);
    for (const id of ollama) keys.add(`ollama:${id}`);
    return {
      openai,
      ollama,
      selectedKey,
      isSelectedValid: keys.has(selectedKey) || selectedKey === "stub:stub",
      refreshing: modelsRefreshing,
      error: modelsError,
    };
  }, [availableModels, chatModel, chatProvider, modelsError, modelsRefreshing]);

  const assistantDisplayName = (appSettings.assistantDisplayName || DEFAULT_AGENTX_SETTINGS.assistantDisplayName).trim() || DEFAULT_AGENTX_SETTINGS.assistantDisplayName;
  const userDisplayName = (appSettings.userDisplayName || DEFAULT_AGENTX_SETTINGS.userDisplayName).trim() || DEFAULT_AGENTX_SETTINGS.userDisplayName;
  const appearancePreset = appSettings.appearancePreset || DEFAULT_AGENTX_SETTINGS.appearancePreset;
  const accentIntensity = appSettings.accentIntensity || DEFAULT_AGENTX_SETTINGS.accentIntensity;
  const densityMode = appSettings.densityMode || DEFAULT_AGENTX_SETTINGS.densityMode;
  const showInspector = layoutSettings.showInspector && config.showInspector && !isMobile;

  const chatModelDropdownOptions = useMemo<AgentXDropdownOption[]>(() => {
    const options: AgentXDropdownOption[] = [];
    if (!modelOptions.isSelectedValid) {
      options.push({
        value: modelOptions.selectedKey,
        label:
          chatProvider === "ollama"
            ? `Unavailable Ollama selection (${ollamaBaseUrl})`
            : `Unknown: ${(chatProvider || "").toLowerCase()}/${chatModel}`,
      });
    }
    options.push({ value: "__label_openai__", label: "OpenAI", disabled: true });
    if (modelOptions.openai.length === 0) {
      options.push({
        value: "openai:__none__",
        label: modelOptions.refreshing ? "Loading..." : "No OpenAI models",
        disabled: true,
      });
    } else {
      options.push(...modelOptions.openai.map((model) => ({ value: `openai:${model}`, label: model })));
    }
    options.push({ value: "__label_ollama__", label: "Ollama", disabled: true });
    if (modelOptions.ollama.length === 0) {
      options.push({
        value: "ollama:__none__",
        label: modelOptions.refreshing ? "Loading..." : modelsError ? `Ollama unavailable (${ollamaBaseUrl})` : "No Ollama models",
        disabled: true,
      });
    } else {
      options.push(...modelOptions.ollama.map((model) => ({ value: `ollama:${model}`, label: model })));
    }
    if (chatProvider === "stub" && chatModel === "stub") {
      options.push({ value: "stub:stub", label: "No model selected", disabled: true });
    }
    return options;
  }, [chatModel, chatProvider, modelOptions.isSelectedValid, modelOptions.ollama, modelOptions.openai, modelOptions.refreshing, modelOptions.selectedKey, modelsError, ollamaBaseUrl]);

  const loadAppSettings = useCallback(async () => {
    if (authEnabled === null) {
      return;
    }
    if (authEnabled && !auth) {
      setAppSettings(DEFAULT_AGENTX_SETTINGS);
      setPendingLayoutSync(loadPendingLayoutSave());
      return;
    }
    try {
      const settings = await getSettings();
      const pending = loadPendingLayoutSave();
      setPendingLayoutSync(pending);
      setAppSettings(applyPendingLayoutToSettings({ ...DEFAULT_AGENTX_SETTINGS, ...settings, layout: normalizeLayoutSettings(settings.layout) }, pending));
    } catch (e) {
      console.error("Failed to load app settings", e);
      const pending = loadPendingLayoutSave();
      setPendingLayoutSync(pending);
      setAppSettings(applyPendingLayoutToSettings(DEFAULT_AGENTX_SETTINGS, pending));
    }
  }, [auth, authEnabled]);

  const applySettings = useCallback((settings: AgentXSettings) => {
    const next = {
      ...DEFAULT_AGENTX_SETTINGS,
      ...settings,
      layout: normalizeLayoutSettings(settings.layout),
    };
    setAppSettings(next);
    setChatProvider(next.chatProvider || "stub");
    setChatModel(next.chatModel || "stub");
    setOllamaBaseUrl(next.ollamaBaseUrl || DEFAULT_AGENTX_SETTINGS.ollamaBaseUrl);
    lastServerSelectionRef.current = {
      provider: next.chatProvider || "stub",
      model: next.chatModel || "stub",
    };
  }, []);

  useEffect(() => {
    void loadAppSettings();
  }, [loadAppSettings]);

  useEffect(() => {
    const controller = new AbortController();
    const tick = async () => {
      try {
        const res = await getStatus(controller.signal);
        setStatusOk(res.ok);
        setStatusName(res.name || "Connected");
        setAuthEnabled(res.auth_enabled !== false);
        const serverProvider = res.chat_provider ?? "stub";
        const serverModel = res.chat_model ?? "stub";
        const last = lastServerSelectionRef.current;
        if (!activeThread?.id) {
          setChatProvider((prev) => (prev === last.provider ? serverProvider : prev));
          setChatModel((prev) => (prev === last.model ? serverModel : prev));
        }
        lastServerSelectionRef.current = { provider: serverProvider, model: serverModel };
        if (!modelDropdownOpenRef.current) {
          setAvailableModels(res.available_chat_models ?? {});
          setModelsRefreshing(Boolean(res.models_refreshing));
          setModelsError(res.models_error ?? null);
        }
        setOllamaBaseUrl(res.ollama_base_url ?? "http://127.0.0.1:11434");
        setOllamaEndpoints(res.ollama_endpoints ?? {});
        setModelsLastRefresh(res.models_last_refresh ?? null);
        setProviderEndpointStatus(res.provider_endpoint_status ?? null);
        setProviderModelStatus(res.provider_model_status ?? null);
        setLastProviderError(
          res.provider_error_type && res.provider_error_message
            ? {
                type: res.provider_error_type,
                provider: serverProvider,
                model: serverModel,
                message: res.provider_error_message,
                base_url: res.ollama_base_url ?? undefined,
              }
            : null
        );
        setStatusError(null);
      } catch (e) {
        setStatusOk(false);
        setStatusName("Offline");
        setStatusError(e instanceof Error ? e.message : String(e));
      }
    };
    void tick();
    const id = setInterval(tick, 2000);
    return () => {
      clearInterval(id);
      controller.abort();
    };
  }, [activeThread?.id]);

  useEffect(() => {
    if (authEnabled !== false || !auth) return;
    clearAuth();
    setAuth(null);
    setLoginPass("");
    setLoginError(null);
  }, [auth, authEnabled]);

  useEffect(() => {
    if (!statusOk || !sessionReady) {
      if (!sessionReady) {
        setThreads([]);
        setActiveThread(null);
      }
      return;
    }
    setLoadingThreads(true);
    let cancelled = false;
    (async () => {
      try {
        const list = await listThreads();
        if (cancelled) return;
        setThreads(list);
      } finally {
        if (!cancelled) setLoadingThreads(false);
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [sessionReady, statusOk]);


  useEffect(() => {
    if (!statusOk || !sessionReady) {
      if (!sessionReady) setProjects([]);
      return;
    }
    let cancelled = false;
    void (async () => {
      try {
        const list = await listProjects();
        if (!cancelled) setProjects(list);
      } catch (e) {
        if (!cancelled) console.error("Failed to load projects", e);
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [sessionReady, statusOk]);

  useEffect(() => {
    if (!statusOk || !sessionReady) {
      if (!sessionReady) setScripts([]);
      return;
    }
    let cancelled = false;
    void (async () => {
      try {
        const list = await listScripts({ query: scriptQuery });
        if (!cancelled) setScripts(list);
      } catch (e) {
        if (!cancelled) console.error("Failed to load scripts", e);
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [scriptQuery, sessionReady, statusOk]);

  useEffect(() => {
    if (!activeScript) {
      setScriptDraft({ title: "", content: "", language: "text" });
      return;
    }
    setActiveScriptId((current) => current ?? activeScript.id);
    setScriptDraft({ title: activeScript.title, content: activeScript.content, language: activeScript.language });
  }, [activeScript?.id]);

  useEffect(() => {
    const onAuthInvalid = () => {
      if (authEnabled === false) {
        clearAuth();
        return;
      }
      clearAuth();
      setAuth(null);
      setActiveThread(null);
      setThreads([]);
      setLoginPass("");
      setLoginError("Session expired. Sign in again.");
    };
    window.addEventListener("agentxweb:auth-invalid", onAuthInvalid);
    return () => window.removeEventListener("agentxweb:auth-invalid", onAuthInvalid);
  }, [authEnabled]);

  useEffect(() => {
    const onPendingLayoutChanged = () => setPendingLayoutSync(loadPendingLayoutSave());
    const eventName = pendingLayoutChangedEventName();
    window.addEventListener(eventName, onPendingLayoutChanged);
    return () => window.removeEventListener(eventName, onPendingLayoutChanged);
  }, []);

  const setSystemMessage = useCallback((content: string) => {
    setActiveThread((prev) => {
      if (!prev) return prev;
      return {
        ...prev,
        messages: [
          ...prev.messages,
          { id: `sys-${Date.now()}`, role: "system", content, ts: Date.now() / 1000 }
        ],
        updated_at: Date.now() / 1000
      };
    });
  }, []);

  const focusComposer = useCallback(
    ({ force = false }: { force?: boolean } = {}) => {
      const target = textareaRef.current;
      if (!target) return;
      if (activeView !== "chat" || !sessionReady || !statusOk || navOpen || sending) return;
      if (target.disabled) return;
      if (document.querySelector(".agentx-dropdown--open, .agentx-context-menu")) return;

      const activeElement = document.activeElement;
      if (!force) {
        if (isMobile) return;
        if (activeElement === target) return;
        if (activeElement && activeElement !== document.body && isEditableElement(activeElement)) return;
      }

      target.focus({ preventScroll: true });
    },
    [activeView, isMobile, navOpen, sending, sessionReady, statusOk]
  );

  const scheduleComposerFocus = useCallback(
    (options?: { force?: boolean }) => {
      if (focusRafRef.current !== null) {
        window.cancelAnimationFrame(focusRafRef.current);
      }
      focusRafRef.current = window.requestAnimationFrame(() => {
        focusRafRef.current = null;
        focusComposer(options);
      });
    },
    [focusComposer]
  );

  const quoteIntoComposer = useCallback((content: string) => {
    setDraft((prev) => `${quoteMessage(content)}${prev ? prev.trimStart() : ""}`);
    scheduleComposerFocus({ force: true });
  }, [scheduleComposerFocus]);

  const persistChatSelection = useCallback(
    async (provider: string, model: string) => {
      if (!statusOk) {
        setSystemMessage("Offline - cannot change model selection until the API is reachable.");
        return;
      }
      const p = (provider || "stub").trim().toLowerCase();
      const m = (model || "stub").trim();
      if (p === "openai" && modelOptions.openai.length > 0 && !modelOptions.openai.includes(m)) {
        setSystemMessage("That OpenAI model is not in the discovered list. Pick a valid model.");
        return;
      }
      if (p === "ollama" && modelOptions.ollama.length > 0 && !modelOptions.ollama.includes(m)) {
        setSystemMessage("That Ollama model is not in the discovered list. Pick a valid model.");
        return;
      }
      if (p === "ollama" && modelOptions.ollama.length === 0) {
        setSystemMessage(`Configured Ollama endpoint could not be used for model discovery: ${ollamaBaseUrl}`);
        return;
      }
      try {
        if (activeThread?.id) {
          const updated = await updateThreadModel(activeThread.id, p, m);
          setActiveThread(updated);
          setThreads((prev) => prev.map((thread) => (thread.id === updated.id ? threadSummary(updated) : thread)));
        } else {
          const current = await getSettings();
          await saveSettings({ ...current, chatProvider: p, chatModel: m, ollamaBaseUrl });
        }
      } catch (e) {
        console.error("Failed to persist chat selection", e);
        setSystemMessage(activeThread?.id ? "Failed to save this chat's model selection." : "Failed to save default model selection.");
      }
    },
    [activeThread?.id, modelOptions.openai, modelOptions.ollama, ollamaBaseUrl, setSystemMessage, statusOk]
  );

  const createProject = useCallback(async () => {
    if (!statusOk) {
      setSystemMessage("Offline - cannot create projects until the API is reachable.");
      return;
    }
    const name = (window.prompt("Project name?") ?? "").trim();
    if (!name) return;
    try {
      const project = await createProjectRecord(name);
      setProjects((prev) => [project, ...prev.filter((item) => item.id !== project.id)]);
      setActiveProjectId(project.id);
      setActiveView("chat");
      onAfterNavAction();
    } catch (e) {
      console.error("Failed to create project", e);
      setSystemMessage("Project create failed.");
    }
  }, [onAfterNavAction, setSystemMessage, statusOk]);

  const renameProject = useCallback(async (project: ProjectRecord) => {
    if (!statusOk) {
      setSystemMessage("Offline - cannot rename projects until the API is reachable.");
      return;
    }

    const currentName = project.name || "Untitled Project";
    const nextName = window.prompt("Rename project", currentName)?.trim();

    if (!nextName || nextName === currentName) return;

    try {
      const updated = await updateProjectRecord(project.id, { name: nextName });
      setProjects((prev) => prev.map((item) => (item.id === updated.id ? updated : item)));
      setSystemMessage(`Project renamed to "${updated.name}".`);
    } catch (e) {
      console.error("rename project failed", e);
      setSystemMessage("Project rename failed.");
    }
  }, [statusOk, setSystemMessage]);

  const deleteProject = useCallback(async (project: ProjectRecord) => {
    if (!statusOk) {
      setSystemMessage("Offline - cannot delete projects until the API is reachable.");
      return;
    }

    const confirmed = window.confirm(`Delete project "${project.name}"? Chats will not be deleted, but the project grouping will be removed.`);
    if (!confirmed) return;

    try {
      await deleteProjectRecord(project.id);
      setProjects((prev) => prev.filter((item) => item.id !== project.id));
      setThreads((prev) => prev.map((thread) => thread.project_id === project.id ? { ...thread, project_id: null } : thread));
      setActiveThread((prev) => prev?.project_id === project.id ? { ...prev, project_id: null } : prev);
      setActiveProjectId((prev) => prev === project.id ? null : prev);
      setSystemMessage(`Project "${project.name}" deleted.`);
    } catch (e) {
      console.error("delete project failed", e);
      setSystemMessage("Project delete failed.");
    }
  }, [statusOk, setSystemMessage]);

  const assignActiveThreadToProject = useCallback(async (projectId: string | null) => {
    if (!activeThread?.id) {
      setSystemMessage("Open a chat first, then assign it to a project.");
      return;
    }
    try {
      const updated = await updateThreadProject(activeThread.id, projectId);
      setActiveThread(updated);
      setThreads((prev) => [threadSummary(updated), ...prev.filter((thread) => thread.id !== updated.id)]);
    } catch (e) {
      console.error("Failed to assign project", e);
      setSystemMessage("Failed to assign this chat to the project.");
    }
  }, [activeThread?.id, setSystemMessage]);

  const upsertScriptState = useCallback((script: ScriptRecord) => {
    setScripts((prev) => [script, ...prev.filter((item) => item.id !== script.id)]);
    setActiveScriptId(script.id);
  }, []);

  const saveGeneratedScript = useCallback(async (payload: { title: string; language: string; content: string; sourceThreadId?: string | null; sourceMessageId?: string | null }) => {
    try {
      const script = await createScript({
        title: payload.title,
        language: payload.language,
        content: payload.content,
        model_provider: chatProvider,
        model_name: chatModel,
        source_thread_id: payload.sourceThreadId ?? null,
        source_message_id: payload.sourceMessageId ?? null,
        tags: [payload.language, chatProvider, chatModel].filter(Boolean),
      });
      upsertScriptState(script);
    } catch (e) {
      console.error("Failed to save generated script", e);
    }
  }, [chatModel, chatProvider, upsertScriptState]);

  const openScriptInCanvas = useCallback((script: ScriptRecord) => {
    const language = normalizeCodeCanvasLanguage(script.language);
    setCodeCanvas((prev) => ({
      ...prev,
      isOpen: true,
      content: script.content,
      language,
      title: script.title,
      isDirty: false,
      sourceMessageId: script.source_message_id ?? script.id,
      viewMode: prev.viewMode === "fullscreen" ? "fullscreen" : "docked",
      sources: {
        ...prev.sources,
        [script.source_message_id ?? script.id]: {
          content: script.content,
          language,
          title: script.title,
        },
      },
    }));
    setActiveView("chat");
  }, []);

  const insertScriptIntoChat = useCallback((script: ScriptRecord) => {
    setDraft((prev) => `${prev ? `${prev.trimEnd()}

` : ""}Here is ${script.title}:

\`\`\`${script.language}
${script.content}
\`\`\``);
    setActiveView("chat");
    scheduleComposerFocus({ force: true });
  }, [scheduleComposerFocus]);

  const exportScriptFile = useCallback((script: ScriptRecord) => {
    const blob = new Blob([script.content], { type: "text/plain;charset=utf-8" });
    const url = URL.createObjectURL(blob);
    const link = document.createElement("a");
    link.href = url;
    link.download = filenameForScript(script);
    document.body.appendChild(link);
    link.click();
    link.remove();
    URL.revokeObjectURL(url);
  }, []);

  const saveScriptEdits = useCallback(async () => {
    if (!activeScript) return;
    try {
      const updated = await updateScript(activeScript.id, {
        title: scriptDraft.title.trim() || activeScript.title,
        language: scriptDraft.language.trim() || activeScript.language,
        content: scriptDraft.content,
      });
      upsertScriptState(updated);
      setSystemMessage("Script saved.");
    } catch (e) {
      console.error("Failed to save script", e);
      setSystemMessage("Script save failed.");
    }
  }, [activeScript, scriptDraft.content, scriptDraft.language, scriptDraft.title, setSystemMessage, upsertScriptState]);

  const removeScript = useCallback(async (script: ScriptRecord) => {
    if (!window.confirm(`Delete script '${script.title}'?`)) return;
    try {
      await deleteScript(script.id);
      setScripts((prev) => prev.filter((item) => item.id !== script.id));
      setActiveScriptId((current) => current === script.id ? null : current);
    } catch (e) {
      console.error("Failed to delete script", e);
      setSystemMessage("Script delete failed.");
    }
  }, [activeThread?.id, setSystemMessage]);

  const selectThread = useCallback(async (id: string) => {
    if (!statusOk) return;
    const thread = await getThread(id);
    setActiveThread(thread);
    const selection = threadSelection(thread, { provider: lastServerSelectionRef.current.provider, model: lastServerSelectionRef.current.model });
    setChatProvider(selection.provider);
    setChatModel(selection.model);
    onAfterNavAction();
    scheduleComposerFocus({ force: true });
  }, [onAfterNavAction, scheduleComposerFocus, statusOk]);

  const newChat = useCallback(async () => {
    if (!statusOk) return;
    const t = await createThread(undefined, { chatProvider, chatModel, projectId: activeProjectId });
    setActiveThread(t);
    const selection = threadSelection(t, { provider: chatProvider, model: chatModel });
    setChatProvider(selection.provider);
    setChatModel(selection.model);
    setThreads((prev) => [threadSummary(t), ...prev.filter((x) => x.id !== t.id)]);
    onAfterNavAction();
    scheduleComposerFocus({ force: true });
  }, [activeProjectId, chatModel, chatProvider, onAfterNavAction, scheduleComposerFocus, statusOk]);

  const deleteChat = useCallback(
    async (threadId: string) => {
      if (!statusOk) {
        setSystemMessage("Offline - cannot delete threads until the API is reachable.");
        return;
      }
      try {
        await deleteThread(threadId);
        setThreads((prev) => prev.filter((t) => t.id !== threadId));
        setActiveThread((prev) => (prev?.id === threadId ? null : prev));
      } catch (e) {
        console.error("Failed to delete thread", e);
        setSystemMessage("Thread delete failed.");
      }
    },
    [setSystemMessage, statusOk]
  );

  const renameChat = useCallback(
    async (threadId: string, title: string) => {
      if (!statusOk) {
        setSystemMessage("Offline - cannot rename threads until the API is reachable.");
        return;
      }
      const trimmed = title.trim();
      if (!trimmed) return;
      const before = threads.find((t) => t.id === threadId)?.title ?? config.threadTitleDefault;
      setThreads((prev) => prev.map((t) => (t.id === threadId ? { ...t, title: trimmed } : t)));
      try {
        const updated = await updateThreadTitle(threadId, trimmed);
        setThreads((prev) => [
          threadSummary(updated),
          ...prev.filter((t) => t.id !== updated.id),
        ]);
        setActiveThread((prev) => (prev?.id === updated.id ? updated : prev));
      } catch (e) {
        console.error("Failed to rename thread", e);
        setThreads((prev) => prev.map((t) => (t.id === threadId ? { ...t, title: before } : t)));
        setSystemMessage("Thread rename failed.");
      }
    },
    [setSystemMessage, statusOk, threads]
  );

  const updateCodeCanvas = useCallback((update: Partial<CodeCanvasState>) => {
    setCodeCanvas((prev) => ({ ...prev, ...update }));
  }, []);

  const closeCodeCanvas = useCallback(() => {
    setCodeCanvas((prev) => ({ ...prev, isOpen: false, viewMode: "docked" }));
  }, []);

  const openCodeCanvasFromReply = useCallback(
    (payload: { code: string; language: CodeCanvasState["language"]; sourceMessageId: string; title: string; companion: CodeCanvasState["companions"][string]; shouldOpen?: boolean }) => {
      setCodeCanvas((prev) => ({
        ...prev,
        isOpen: payload.shouldOpen ?? true,
        content: payload.code,
        language: payload.language,
        sourceMessageId: payload.sourceMessageId,
        title: payload.title,
        isDirty: false,
        viewMode: prev.viewMode === "fullscreen" ? "fullscreen" : "docked",
        companions: {
          ...prev.companions,
          [payload.sourceMessageId]: payload.companion,
        },
        sources: {
          ...prev.sources,
          [payload.sourceMessageId]: {
            content: payload.code,
            language: payload.language,
            title: payload.title,
          },
        },
      }));
    },
    []
  );

  const reopenCodeCanvas = useCallback((messageId: string) => {
    setCodeCanvas((prev) => {
      const source = prev.sources[messageId];
      if (!source) return prev;
      return {
        ...prev,
        isOpen: true,
        sourceMessageId: messageId,
        content: source.content,
        language: source.language,
        title: source.title,
        isDirty: false,
      };
    });
  }, []);

  const sendCodeCanvasSelectionToChat = useCallback(
    (payload: { scope: "selection" | "document"; content: string; language: string }) => {
      setDraft(buildCodeCanvasPrompt(payload));
      setActiveView("chat");
      setCodeCanvas((prev) => ({ ...prev, isOpen: true, viewMode: "docked" }));
      scheduleComposerFocus({ force: true });
    },
    [scheduleComposerFocus]
  );

  const refreshModels = useCallback(async () => {
    try {
      const res = await getStatusRefresh();
      setAvailableModels(res.available_chat_models ?? {});
      setOllamaEndpoints(res.ollama_endpoints ?? {});
      setModelsLastRefresh(res.models_last_refresh ?? null);
      setModelsRefreshing(Boolean(res.models_refreshing));
      setModelsError(res.models_error ?? null);
      setOllamaBaseUrl(res.ollama_base_url ?? "http://127.0.0.1:11434");
      setStatusOk(res.ok);
      setStatusName(res.name || "Connected");
      setStatusError(null);
    } catch (e) {
      setStatusOk(false);
      setStatusName("Offline");
      setStatusError(e instanceof Error ? e.message : String(e));
    }
  }, []);

  const handleSettingsSaved = useCallback((settings: AgentXSettings) => {
    setPendingLayoutSync(loadPendingLayoutSave());
    applySettings(settings);
  }, [applySettings]);

  useEffect(() => {
    if (!sessionReady || !statusOk || !pendingLayoutSync) return;
    let cancelled = false;
    void (async () => {
      try {
        const saved = await saveSettings({ ...appSettings, layout: pendingLayoutSync.layout });
        if (cancelled) return;
        clearPendingLayoutSave();
        setPendingLayoutSync(null);
        handleSettingsSaved(saved);
      } catch (e) {
        if (!cancelled) {
          console.error("Pending layout sync failed", e);
        }
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [appSettings, handleSettingsSaved, pendingLayoutSync, sessionReady, statusOk]);

  const scrollToLatest = useCallback((behavior: ScrollBehavior = "auto") => {
    const el = feedRef.current;
    if (!el || typeof window === "undefined") return;

    if (scrollRafRef.current !== null) {
      window.cancelAnimationFrame(scrollRafRef.current);
    }

    scrollRafRef.current = window.requestAnimationFrame(() => {
      scrollRafRef.current = null;
      const target = Math.max(0, el.scrollHeight - el.clientHeight);
      el.scrollTo({ top: target, behavior });
      nearBottomRef.current = true;
      setShowJumpToLatest(false);
    });
  }, []);

  const resumeAutoScroll = useCallback((behavior: ScrollBehavior = "smooth") => {
    nearBottomRef.current = true;
    setShowJumpToLatest(false);
    scrollToLatest(behavior);
  }, [scrollToLatest]);

  const onFeedScroll = useCallback(() => {
    const el = feedRef.current;
    if (!el) return;
    const remaining = el.scrollHeight - el.scrollTop - el.clientHeight;
    const isNearBottom = remaining <= 160;
    nearBottomRef.current = isNearBottom;
    setShowJumpToLatest(!isNearBottom);
  }, []);

  const latestMessageScrollKey = useMemo(() => {
    const messages = activeThread?.messages ?? [];
    const last = messages[messages.length - 1];
    return [
      activeView,
      activeThread?.id ?? "none",
      messages.length,
      last?.id ?? "none",
      last?.content?.length ?? 0,
      sending ? "sending" : "idle",
    ].join(":");
  }, [activeThread?.id, activeThread?.messages, activeView, sending]);

  useEffect(() => {
    if (activeView !== "chat") return;
    if (lastThreadForScrollRef.current !== (activeThread?.id ?? null)) {
      lastThreadForScrollRef.current = activeThread?.id ?? null;
      nearBottomRef.current = true;
      setShowJumpToLatest(false);
      lastAutoScrolledKeyRef.current = latestMessageScrollKey;
      scrollToLatest("auto");
      return;
    }
    if (!nearBottomRef.current) return;
    if (lastAutoScrolledKeyRef.current === latestMessageScrollKey) return;
    lastAutoScrolledKeyRef.current = latestMessageScrollKey;
    scrollToLatest(sending ? "auto" : "smooth");
  }, [activeThread?.id, latestMessageScrollKey, activeView, scrollToLatest, sending]);

  useEffect(() => {
    return () => {
      if (scrollRafRef.current !== null && typeof window !== "undefined") {
        window.cancelAnimationFrame(scrollRafRef.current);
      }
    };
  }, []);

  useEffect(() => {
    if (activeView !== "chat") return;
    scheduleComposerFocus();
  }, [activeThread?.id, activeView, scheduleComposerFocus]);

  const stopSending = useCallback(() => {
    const controller = activeSendAbortRef.current;
    if (!controller || controller.signal.aborted) return;
    controller.abort();
  }, []);

  const addComposerFiles = useCallback(async (files: FileList | null, kind: "file" | "image") => {
    if (!files?.length) return;
    const next: ComposerAttachment[] = [];
    for (const file of Array.from(files).slice(0, 6)) {
      let content = "";
      if (kind === "file" && file.size <= 500_000) {
        try {
          content = await file.text();
        } catch {
          content = "";
        }
      }
      next.push({ id: createClientId("attachment"), name: file.name, kind, size: file.size, content });
    }
    setComposerAttachments((prev) => [...prev, ...next].slice(-8));
    setComposerMenuOpen(false);
  }, []);


  useEffect(() => {
    const handleWorkspaceAskFix = (event: MessageEvent) => {
      const data = event.data as { type?: string; prompt?: string; path?: string } | null;
      if (!data || data.type !== "agentx:ask-fix-file") return;
      const prompt = String(data.prompt || "").trim();
      if (!prompt) return;
      setDraft((prev) => prev.trim() ? `${prev.trim()}\n\n${prompt}` : prompt);
      setActiveView("chat");
      setSystemMessage(`Workspace fix request loaded${data.path ? ` for ${data.path}` : ""}. Review it, then press Send.`);
      requestAnimationFrame(() => textareaRef.current?.focus());
    };
    window.addEventListener("message", handleWorkspaceAskFix);
    return () => window.removeEventListener("message", handleWorkspaceAskFix);
  }, [setSystemMessage]);

  const removeComposerAttachment = useCallback((id: string) => {
    setComposerAttachments((prev) => prev.filter((item) => item.id !== id));
  }, []);


function rememberAgentXWorkspacePatchResponse(content: string) {
  const text = String(content || "");
  const hasPatch =
    /###\s*Replacement Content\s*```/i.test(text) ||
    /\*\*Replacement Content\*\*\s*```/i.test(text) ||
    /agentx-workspace-patch/i.test(text);

  if (!hasPatch) return;

  try {
    window.localStorage.setItem("agentx.lastAssistantPatch", text);
    window.localStorage.setItem("agentx.pendingPatchResponse", text);
    window.sessionStorage.setItem("agentx.lastAssistantPatch", text);
    window.sessionStorage.setItem("agentx.pendingPatchResponse", text);
    window.dispatchEvent(new CustomEvent("agentx-workspace-patch-response", { detail: { content: text } }));
  } catch {
    // Ignore storage failures; Workspaces can still use manual paste fallback.
  }
}



function rememberAgentXLatestPatchResponse(content: string) {
  const text = String(content || "");
  if (!text.trim()) return;

  const payload = JSON.stringify({
    ts: Date.now(),
    content: text,
  });

  try {
    // Always keep the latest assistant response so Workspaces can preload any patch text,
    // even plain text such as "Title: This is\nheader: Sample!".
    window.localStorage.setItem("agentx.latestAssistantResponse", payload);
    window.sessionStorage.setItem("agentx.latestAssistantResponse", payload);

    // Keep legacy names too, so existing Workspaces import buttons keep working.
    window.localStorage.setItem("agentx.lastAssistantPatch", text);
    window.localStorage.setItem("agentx.pendingPatchResponse", text);
    window.sessionStorage.setItem("agentx.lastAssistantPatch", text);
    window.sessionStorage.setItem("agentx.pendingPatchResponse", text);

    window.dispatchEvent(new CustomEvent("agentx-workspace-patch-response", { detail: { content: text, ts: Date.now() } }));
  } catch {
    // Storage can fail in private mode; Workspaces still has manual paste fallback.
  }
}


  const importWorkbenchArchives = useCallback(async (files: FileList | null) => {
    const file = files?.[0];
    if (!file) return;
    setComposerMenuOpen(false);

    const name = file.name
      .replace(/\.(zip|rar|7z|tar|tgz|tar\.gz)$/i, "")
      .replace(/[^a-z0-9._-]+/gi, "-")
      .replace(/^-+|-+$/g, "") || "server-import";

    setSystemMessage(`Workbench: preparing chat workspace for ${file.name}...`);

    try {
      let thread = activeThread;

      if (!thread?.id) {
        thread = await createThread(undefined, {
          chatProvider,
          chatModel,
          projectId: activeProjectId,
        });
        setThreads((prev) => [thread!, ...prev.filter((item) => item.id !== thread!.id)]);
        setActiveThread(thread);
      }

      const threadId = thread.id;
      setSystemMessage(`Workbench: uploading and analyzing ${file.name} for this chat...`);

      const result = await importWorkbenchArchive(file, name, threadId);
      const reportPath = result.final_report_path || "";
      let report = "";

      if (reportPath) {
        try {
          const reportResult = await getWorkbenchReport(reportPath);
          report = reportResult.content || "";
        } catch (err) {
          report = `Report generated at: ${reportPath}\n\nCould not fetch report text: ${err instanceof Error ? err.message : String(err)}`;
        }
      }

      const summary = result.summary || {};
      const projectId = result.project?.project_id || name;
      const content = [
        `# Workbench Analysis Complete: ${file.name}`,
        "",
        `Project: ${projectId}`,
        `Thread: ${threadId}`,
        `Report: ${reportPath || "not returned"}`,
        result.thread_workspace ? `Workspace attached: yes` : `Workspace attached: no`,
        "",
        "## Summary",
        `- Total files: ${summary.total_files ?? "unknown"}`,
        `- Analyzed files: ${summary.analyzed_files ?? "unknown"}`,
        `- Syntax errors: ${summary.syntax_errors ?? "unknown"}`,
        `- Risk findings: ${summary.risk_findings ?? "unknown"}`,
        `- Converted/server completion findings: ${summary.conversion_findings ?? "unknown"}`,
        `- Stub/empty findings: ${summary.stub_findings ?? "unknown"}`,
        "",
        report ? "## Full Report" : "",
        report,
      ].filter(Boolean).join("\n");

      const workbenchMessage = {
        id: createClientId("workbench"),
        role: "assistant" as const,
        content,
        ts: Date.now() / 1000,
      };

      setActiveThread((prev) => {
        const base = prev?.id === threadId ? prev : thread!;
        return {
          ...base,
          messages: [...(base.messages || []), workbenchMessage],
          updated_at: Date.now() / 1000,
        };
      });

      setThreads((prev) => prev.map((item) => item.id === threadId ? {
        ...item,
        updated_at: Date.now() / 1000,
      } : item));

      setSystemMessage(`Workbench analysis finished and attached to this chat for ${file.name}.`);
    } catch (err) {
      setSystemMessage(`Workbench import failed: ${err instanceof Error ? err.message : String(err)}`);
    } finally {
      if (archiveInputRef.current) archiveInputRef.current.value = "";
    }
  }, [activeThread, chatProvider, chatModel, activeProjectId, setSystemMessage]);

  // agentx-workbench-global-drop
  useEffect(() => {
    const isArchive = (file: File) => /\.(zip|rar|7z|tar|tgz|tar\.gz)$/i.test(file.name);
    const onDragOver = (event: DragEvent) => {
      const files = event.dataTransfer?.files;
      if (files && files.length > 0 && Array.from(files).some(isArchive)) {
        event.preventDefault();
      }
    };
    const onDrop = (event: DragEvent) => {
      const files = event.dataTransfer?.files;
      if (!files || files.length === 0 || !Array.from(files).some(isArchive)) return;
      event.preventDefault();
      void importWorkbenchArchives(files);
    };
    window.addEventListener("dragover", onDragOver);
    window.addEventListener("drop", onDrop);
    return () => {
      window.removeEventListener("dragover", onDragOver);
      window.removeEventListener("drop", onDrop);
    };
  }, [importWorkbenchArchives]);

  const insertFileSearchPrompt = useCallback(() => {
    setDraft((prev) => {
      const prefix = "Search my allowed local project files for: ";
      return prev.trim() ? `${prev}\n\n${prefix}` : prefix;
    });
    setComposerMenuOpen(false);
    requestAnimationFrame(() => textareaRef.current?.focus());
  }, []);


  const attachAllowedPath = useCallback(async () => {
    const raw = window.prompt("Enter an allowed local file path to attach into this chat:", "");
    const path = String(raw || "").trim();
    setComposerMenuOpen(false);
    if (!path) return;
    try {
      const res = await readFsText(path, activeThread?.id ?? null);
      const content = String(res.content || "");
      setComposerAttachments((prev) => [
        ...prev,
        {
          id: createClientId("attachment"),
          name: res.path || path,
          kind: "file" as const,
          size: res.bytes || content.length,
          content,
        },
      ].slice(-8));
      setDraft((prev) => prev.includes(`@${path}`) ? prev : (prev.trim() ? `${prev.trim()}\n\n@${path}` : `@${path}`));
      setSystemMessage(`Attached local file: ${res.path || path}`);
    } catch (err) {
      setSystemMessage(`Could not attach ${path}: ${err instanceof Error ? err.message : String(err)}`);
    } finally {
      requestAnimationFrame(() => textareaRef.current?.focus());
    }
  }, [activeThread?.id, setSystemMessage]);

  const openDraftWorkspace = useCallback(async (mode: DraftMode) => {
    const source = composerDraftSource(draft, composerAttachments);
    if (!source.content.trim()) {
      setSystemMessage("Add text/code to the composer or attach a readable file before opening Draft Workspace.");
      setComposerMenuOpen(false);
      requestAnimationFrame(() => textareaRef.current?.focus());
      return;
    }
    setComposerMenuOpen(false);
    setDraftWorkspace({ open: true, loading: true, error: null, mode, data: null });
    try {
      const data = await generateDraft({ mode, filename: source.filename, language: source.language, content: source.content });
      setDraftWorkspace({ open: true, loading: false, error: null, mode, data });
    } catch (err) {
      const message = err instanceof Error ? err.message : String(err);
      setDraftWorkspace({ open: true, loading: false, error: message, mode, data: null });
    }
  }, [composerAttachments, draft, setSystemMessage]);

  const closeDraftWorkspace = useCallback(() => {
    setDraftWorkspace((prev) => ({ ...prev, open: false, loading: false }));
  }, []);

  const copyDraftSection = useCallback(async (value: string, label: string) => {
    try {
      await navigator.clipboard.writeText(value || "");
      setSystemMessage(`${label} copied to clipboard.`);
    } catch {
      setSystemMessage(`Could not copy ${label.toLowerCase()} to clipboard.`);
    }
  }, [setSystemMessage]);

  const sendDraftToChat = useCallback(() => {
    const data = draftWorkspace.data;
    if (!data) return;
    const content = [
      `Draft: ${data.title}`,
      "",
      data.explanation ? `Explanation:\n${data.explanation}` : "",
      data.improved ? `Improved version:\n\`\`\`${data.language}\n${data.improved}\n\`\`\`` : "",
      data.notes?.length ? `Notes:\n${data.notes.map((note) => `- ${note}`).join("\n")}` : "",
    ].filter(Boolean).join("\n\n");
    setDraft(content);
    closeDraftWorkspace();
    requestAnimationFrame(() => textareaRef.current?.focus());
  }, [closeDraftWorkspace, draftWorkspace.data]);

  const saveDraftAsScript = useCallback(async () => {
    const data = draftWorkspace.data;
    if (!data) return;
    const content = data.improved?.trim() || data.original;
    try {
      const script = await createScript({
        title: data.title || "Draft Workspace Script",
        language: data.language || "text",
        content,
        tags: ["draft-workspace"],
        thread_id: activeThread?.id ?? null,
        model_provider: data.model_provider ?? chatProvider,
        model_name: data.model_name ?? chatModel,
      });
      setScripts((prev) => [script, ...prev.filter((item) => item.id !== script.id)]);
      setActiveScriptId(script.id);
      setActiveView("scripts");
      setSystemMessage("Draft saved to Scripts.");
      closeDraftWorkspace();
    } catch (err) {
      setSystemMessage(err instanceof Error ? err.message : String(err));
    }
  }, [activeThread?.id, chatModel, chatProvider, closeDraftWorkspace, draftWorkspace.data, setSystemMessage]);


  const send = useCallback(async (
    overrideText?: string,
    overrideSelection?: { provider: string; model: string; suppressHandoff?: boolean; codingPipeline?: CodingPipelineRequest | null; assistantLabel?: string; preserveCurrentSelection?: boolean }
  ) => {
    const rawText = (overrideText ?? draft).trim();
    const text = buildComposerMessage(rawText, composerAttachments, composerRagMode).trim();
    if (!text || sending) return;

    if (!statusOk) {
      setSystemMessage("Offline - cannot send messages until the API is reachable.");
      return;
    }

    if (judgmentAutoRouteEnabled && !overrideSelection && judgmentPreview?.route === "BLOCK") {
      setSystemMessage("Judgment blocked this send because it looks destructive or high risk.");
      return;
    }

    const judgmentRouteSelection = (() => {
      if (!judgmentAutoRouteEnabled || overrideSelection || !judgmentPreview?.ok) return null;
      if (!appSettings.ollamaMultiEndpointEnabled) return null;

      const route = judgmentPreview.route;
      const model =
        route === "FAST"
          ? appSettings.ollamaFastModel
          : route === "DEEP" || route === "RECOVER"
            ? appSettings.ollamaHeavyModel
            : "";

      const trimmedModel = String(model || "").trim();
      if (!trimmedModel) return null;
      if (modelOptions.ollama.length > 0 && !modelOptions.ollama.includes(trimmedModel)) return null;

      return {
        provider: "ollama",
        model: trimmedModel,
        assistantLabel: `${trimmedModel} · ${route}`,
        preserveCurrentSelection: true,
        suppressHandoff: false,
        codingPipeline: null,
      };
    })();

    const effectiveSelection = overrideSelection || judgmentRouteSelection;

    // Prevent obvious model/provider mismatches (most common source of 502s).
    const provider = (effectiveSelection?.provider || chatProvider || "stub").toLowerCase();
    const effectiveModel = (effectiveSelection?.model || chatModel || "stub").trim();
    if (provider === "openai" && modelOptions.openai.length > 0 && !modelOptions.openai.includes(effectiveModel)) {
      setSystemMessage("Selected OpenAI model is not in the discovered list. Pick a valid model from the dropdown.");
      return;
    }
    if (provider === "ollama" && modelOptions.ollama.length > 0 && !modelOptions.ollama.includes(effectiveModel)) {
      setSystemMessage("Selected Ollama model is not in the discovered list. Pick a valid model from the dropdown.");
      return;
    }
    if (provider === "ollama" && modelOptions.ollama.length === 0) {
      setSystemMessage(`Configured Ollama endpoint could not be reached or returned no models: ${ollamaBaseUrl}`);
      return;
    }

    if (selectionPersistRef.current) {
      try {
        await selectionPersistRef.current;
      } catch {
        // ignore
      } finally {
        selectionPersistRef.current = null;
      }
    }

    const shouldPersistSelection = Boolean(effectiveSelection && !effectiveSelection.preserveCurrentSelection);

    if (shouldPersistSelection) {
      setChatProvider(provider);
      setChatModel(effectiveModel);
    }

    let thread = activeThread;
    if (thread && shouldPersistSelection) {
      try {
        thread = await updateThreadModel(thread.id, provider, effectiveModel);
        setActiveThread(thread);
        setThreads((prev) => prev.map((item) => (item.id === thread!.id ? threadSummary(thread!) : item)));
      } catch {
        setSystemMessage("Failed to switch this chat to the handoff model.");
        return;
      }
    }
    if (!thread) {
      thread = await createThread(undefined, { chatProvider: provider, chatModel: effectiveModel, projectId: activeProjectId });
      setActiveThread(thread);
      setThreads((prev) => [threadSummary(thread!), ...prev]);
    }

    const wasEmpty = thread.messages.length === 0;
    const wasDefaultTitle = !thread.title || thread.title === config.threadTitleDefault;

    setDraft("");
    setComposerAttachments([]);
    setHandoffSuggestion(null);
    scheduleComposerFocus({ force: true });

    const localUser = { id: createClientId("message"), role: "user" as const, content: text, ts: Date.now() / 1000 };
    resumeAutoScroll("auto");
    setActiveThread((prev) => (prev ? { ...prev, messages: [...prev.messages, localUser] } : prev));

    setSending(true);
    let userMessagePersisted = false;
    let assistantReplyReceived = false;
    try {
      const t1 = await appendThreadMessage(thread.id, { role: "user", content: text });
      userMessagePersisted = true;
      setActiveThread(t1);
      setThreads((prev) => [threadSummary(t1), ...prev.filter((x) => x.id !== t1.id)]);

      if (wasEmpty && wasDefaultTitle) {
        const title = generateAutoTitle(text);
        setThreads((prev) => prev.map((x) => (x.id === t1.id ? { ...x, title } : x)));
        try {
          const t2 = await updateThreadTitle(t1.id, title);
          setActiveThread(t2);
          setThreads((prev) => [threadSummary(t2), ...prev.filter((x) => x.id !== t2.id)]);
        } catch {
          // ignore title failure in web client; thread still works
        }
      }

      const controller = new AbortController();
      activeSendAbortRef.current = controller;
      const activeModelLabel = effectiveSelection?.assistantLabel || effectiveModel || "AgentX";
      const localAssistant = {
        id: createClientId("assistant"),
        role: "assistant" as const,
        content: `${activeModelLabel} is thinking...`,
        ts: Date.now() / 1000,
        response_metrics: null,
        quality_gate: null,
      };
      setActiveThread((prev) => (prev ? { ...prev, messages: [...prev.messages, localAssistant] } : prev));
      resumeAutoScroll("auto");

      let streamedContent = "";
      const reply = await streamChatMessage({
        message: text,
        threadId: t1.id,
        responseMode: "chat",
        unsafeEnabled: Boolean(unsafeStatus?.unsafe_enabled),
        activeArtifact: buildActiveCanvasArtifact(codeCanvas),
        codingPipeline: effectiveSelection?.codingPipeline ?? null,
        signal: controller.signal,
        onEvent: (event) => {
          if (event.event === "delta") {
            streamedContent += event.content;
            const nextContent = streamedContent || `${activeModelLabel} is responding...`;
            setActiveThread((prev) =>
              prev
                ? {
                    ...prev,
                    messages: prev.messages.map((message) =>
                      message.id === localAssistant.id ? { ...message, content: nextContent } : message
                    ),
                  }
                : prev
            );
          }
          if (event.event === "done") {
            rememberAgentXLatestPatchResponse(event.content || "");
            streamedContent = event.content;
            setActiveThread((prev) =>
              prev
                ? {
                    ...prev,
                    messages: prev.messages.map((message) =>
                      message.id === localAssistant.id ? { ...message, content: event.content, response_metrics: event.response_metrics ?? null, quality_gate: event.quality_gate ?? null, rag_used: event.rag_used ?? null, rag_hit_count: event.rag_hit_count ?? null, rag_sources: event.rag_sources ?? null } : message
                    ),
                  }
                : prev
            );
          }
        },
      });
      assistantReplyReceived = true;
      setLastProviderError(null);
      setLastRetrieved(Array.isArray(reply.retrieved) ? reply.retrieved : []);
      setLastAuditTail(Array.isArray(reply.audit_tail) ? reply.audit_tail : []);
      setLastVerificationLevel(typeof reply.verification_level === "string" ? reply.verification_level : null);
      setLastVerification(reply.verification ?? null);
      setLastWebMeta(reply.web ?? null);
      const t3 = await appendThreadMessage(t1.id, { role: "assistant", content: reply.content, response_metrics: reply.response_metrics ?? null, quality_gate: reply.quality_gate ?? null, rag_used: reply.rag_used ?? null, rag_hit_count: reply.rag_hit_count ?? null, rag_sources: reply.rag_sources ?? null });
      setActiveThread(t3);
      setThreads((prev) => [threadSummary(t3), ...prev.filter((x) => x.id !== t3.id)]);
      const assistantMessage = t3.messages[t3.messages.length - 1];
      const canvasDetection = assistantMessage
        ? detectCodeCanvas({
            prompt: text,
            content: reply.content,
            messageId: assistantMessage.id,
            threadTitle: t3.title,
          })
        : null;
      if (canvasDetection?.shouldOpen && assistantMessage) {
        openCodeCanvasFromReply({
          code: canvasDetection.code,
          language: canvasDetection.language,
          sourceMessageId: assistantMessage.id,
          title: canvasDetection.title,
          companion: canvasDetection.companion,
          shouldOpen: layoutSettings.showCodeCanvas,
        });
        void saveGeneratedScript({
          title: canvasDetection.title,
          language: canvasDetection.language,
          content: canvasDetection.code,
          sourceThreadId: t3.id,
          sourceMessageId: assistantMessage.id,
        });
      }
      if (!effectiveSelection?.suppressHandoff && shouldSuggestCodingHandoff(text)) {
        const targetModel = pickHeavyCodingModel(modelOptions.ollama, effectiveModel);
        if (targetModel) {
          const reviewModel = pickReviewModel(modelOptions.ollama, effectiveModel) ?? targetModel;
          const draftModel = pickFastDraftModel(modelOptions.ollama, reviewModel);
          setHandoffSuggestion({
            provider: "ollama",
            model: targetModel,
            originalPrompt: text,
            brainstorm: reply.content,
            draftModel,
            reviewModel,
          });
        }
      }
    } catch (e) {
      if (isAbortError(e)) {
        setActiveThread((prev) => {
          const rolledBack = rollbackOptimisticThread(prev, localUser.id, userMessagePersisted);
          return rolledBack
            ? { ...rolledBack, messages: rolledBack.messages.filter((message) => !message.id.startsWith("assistant-")) }
            : rolledBack;
        });
        setDraft((current) => restoreDraftAfterStop(text, current));
        setSystemMessage("Response stopped. Edit the composer and send again when you are ready.");
        return;
      }
      const msg = e instanceof Error ? e.message : String(e);
      if (e instanceof ApiError && e.providerError) {
        setLastProviderError(e.providerError);
      }
      setActiveThread((prev) => {
        const rolledBack = rollbackOptimisticThread(prev, localUser.id, userMessagePersisted);
        return rolledBack
          ? { ...rolledBack, messages: rolledBack.messages.filter((message) => !message.id.startsWith("assistant-")) }
          : rolledBack;
      });
      setDraft(restoreDraftAfterSendFailure(text, userMessagePersisted));
      setSystemMessage(buildSendFailureMessage({ errorMessage: msg, userMessagePersisted, assistantReplyReceived }));
    } finally {
      activeSendAbortRef.current = null;
      setSending(false);
    }
  }, [
    activeProjectId,
    activeThread,
    chatModel,
    chatProvider,
    codeCanvas,
    appSettings.ollamaFastModel,
    appSettings.ollamaHeavyModel,
    appSettings.ollamaMultiEndpointEnabled,
    composerAttachments,
    composerRagMode,
    draft,
    judgmentAutoRouteEnabled,
    judgmentPreview,
    modelOptions.openai,
    modelOptions.ollama,
    layoutSettings.showCodeCanvas,
    openCodeCanvasFromReply,
    resumeAutoScroll,
    saveGeneratedScript,
    scheduleComposerFocus,
    sending,
    setSystemMessage,
    statusOk,
  ]);



  const acceptHandoffSuggestion = useCallback(() => {
    if (!handoffSuggestion || sending) return;
    const prompt = buildHandoffPrompt(handoffSuggestion);
    const selection = { provider: handoffSuggestion.provider, model: handoffSuggestion.model, suppressHandoff: true };
    setHandoffSuggestion(null);
    void send(prompt, selection);
  }, [handoffSuggestion, send, sending]);

  const acceptCollaborativeCodingSuggestion = useCallback(() => {
    if (!handoffSuggestion || sending) return;
    const draftModel = (appSettings.ollamaMultiEndpointEnabled ? appSettings.ollamaFastModel : "") || handoffSuggestion.draftModel || "qwen2.5-coder:7b-4k-gpu";
    const reviewModel = (appSettings.ollamaMultiEndpointEnabled ? appSettings.ollamaHeavyModel : "") || handoffSuggestion.reviewModel || handoffSuggestion.model || "devstral-small-2:24b-4k-gpu";
    const prompt = buildHandoffPrompt(handoffSuggestion);
    const selection = {
      provider: handoffSuggestion.provider,
      model: reviewModel,
      suppressHandoff: true,
      assistantLabel: `${draftModel} → ${reviewModel}`,
      preserveCurrentSelection: true,
      codingPipeline: {
        mode: "draft_review",
        draft_model: draftModel,
        review_model: reviewModel,
      } satisfies CodingPipelineRequest,
    };
    setHandoffSuggestion(null);
    void send(prompt, selection);
  }, [appSettings.ollamaFastModel, appSettings.ollamaHeavyModel, appSettings.ollamaMultiEndpointEnabled, handoffSuggestion, send, sending]);

  const editMessageIntoComposer = useCallback((content: string) => {
    setDraft(content);
    setActiveView("chat");
    scheduleComposerFocus({ force: true });
  }, [scheduleComposerFocus]);

  const retryMessage = useCallback((messageId: string) => {
    if (sending) {
      setSystemMessage("Wait for the current response to finish or stop it before retrying.");
      return;
    }
    if (!activeThread) return;
    const message = activeThread.messages.find((item) => item.id === messageId);
    const prompt = message?.role === "user" ? message.content : previousUserMessage(activeThread.messages, messageId);
    if (!prompt?.trim()) {
      setSystemMessage("Could not find a user prompt to retry from this message.");
      return;
    }
    void send(prompt);
  }, [activeThread, send, sending, setSystemMessage]);

  const continueConversation = useCallback(() => {
    if (sending) {
      setSystemMessage("Wait for the current response to finish or stop it before continuing.");
      return;
    }
    void send("Continue from where you left off.");
  }, [send, sending, setSystemMessage]);

  const setMessageFeedbackValue = useCallback((messageId: string, feedback: MessageFeedback) => {
    setMessageFeedback((prev) => {
      const next = { ...prev };
      if (next[messageId] === feedback) {
        delete next[messageId];
      } else {
        next[messageId] = feedback;
      }
      return next;
    });
  }, []);

  const saveMessageAsScript = useCallback(async (messageId: string) => {
    if (!activeThread) return;
    const message = activeThread.messages.find((item) => item.id === messageId);
    if (!message || message.role !== "assistant") return;

    const source = codeCanvas.sources[messageId];
    if (source?.content.trim()) {
      await saveGeneratedScript({
        title: source.title,
        language: source.language,
        content: source.content,
        sourceThreadId: activeThread.id,
        sourceMessageId: messageId,
      });
      setSystemMessage("Saved response code to Scripts.");
      return;
    }

    const detected = detectCodeCanvas({
      prompt: previousUserMessage(activeThread.messages, messageId) ?? activeThread.title,
      content: message.content,
      messageId,
      threadTitle: activeThread.title,
    });

    if (!detected?.code.trim()) {
      setSystemMessage("No script/code block was found in that response.");
      return;
    }

    await saveGeneratedScript({
      title: detected.title || messageScriptTitle(activeThread, messageId),
      language: detected.language,
      content: detected.code,
      sourceThreadId: activeThread.id,
      sourceMessageId: messageId,
    });
    openCodeCanvasFromReply({
      code: detected.code,
      language: detected.language,
      sourceMessageId: messageId,
      title: detected.title,
      companion: detected.companion,
      shouldOpen: false,
    });
    setSystemMessage("Saved response code to Scripts.");
  }, [activeThread, codeCanvas.sources, openCodeCanvasFromReply, saveGeneratedScript, setSystemMessage]);

  const addActiveChatToProject = useCallback(async () => {
    if (!activeThread?.id) {
      setSystemMessage("Open a chat before adding it to a project.");
      return;
    }

    let targetProjectId = activeThread.project_id ?? activeProjectId;
    let projectName = projects.find((project) => project.id === targetProjectId)?.name ?? "project";

    if (!targetProjectId) {
      const defaultName = projects.length === 1 ? projects[0].name : "";
      const entered = (window.prompt(
        projects.length
          ? `Add this chat to which project? Existing: ${projects.map((project) => project.name).join(", ")}`
          : "Project name to create?",
        defaultName,
      ) ?? "").trim();
      if (!entered) return;

      let project = projects.find((item) => item.name.toLowerCase() === entered.toLowerCase()) ?? null;
      if (!project) {
        project = await createProjectRecord(entered);
        setProjects((prev) => [project!, ...prev.filter((item) => item.id !== project!.id)]);
      }
      targetProjectId = project.id;
      projectName = project.name;
    }

    const updated = await updateThreadProject(activeThread.id, targetProjectId);
    setActiveThread(updated);
    setThreads((prev) => [threadSummary(updated), ...prev.filter((thread) => thread.id !== updated.id)]);
    setActiveProjectId(targetProjectId);
    setSystemMessage(`Added this chat to ${projectName}.`);
  }, [activeProjectId, activeThread, projects, setSystemMessage]);

  const fetchTools = useCallback(async () => {
    if (toolSchemaLoadedRef.current) return;
    toolSchemaLoadedRef.current = true;
    try {
      const res = await getToolsSchema();
      setTools(res.tools ?? []);
      setToolError(null);
    } catch (e) {
      toolSchemaLoadedRef.current = false;
      setTools(null);
      setToolError(e instanceof Error ? e.message : String(e));
    }
  }, []);

  const parseToolPartial = useCallback((value: string) => {
    const trimmed = value.trimStart();
    if (!trimmed.startsWith("/tool")) return null;
    const after = trimmed.slice(5);
    const m = after.match(/^\s+([^\s{]*)/);
    const partial = (m?.[1] ?? "").trim();
    return { partial };
  }, []);

  const applyToolSuggestion = useCallback(
    (suggestion: { display: string; canonical: string; tool: ToolSchema }) => {
      const value = draft;
      const trimmedStart = value.trimStart();
      if (!trimmedStart.startsWith("/tool")) return;
      const prefixIndex = value.indexOf("/tool");
      const after = value.slice(prefixIndex + 5);
      const match = after.match(/^(\s+)([^\s{]*)/);
      const leadingWs = match?.[1] ?? " ";
      const currentToken = match?.[2] ?? "";
      const tokenStart = prefixIndex + 5 + leadingWs.length;
      const tokenEnd = tokenStart + currentToken.length;
      const next = value.slice(0, tokenStart) + suggestion.canonical + value.slice(tokenEnd);
      setDraft(next);
      setSelectedTool(suggestion.tool);
      setToolSuggestions([]);
      setToolHighlight(0);
      scheduleComposerFocus({ force: true });
    },
    [draft, scheduleComposerFocus]
  );

  const buildToolTemplate = useCallback((tool: ToolSchema) => {
    const obj: Record<string, unknown> = {};
    for (const arg of tool.args ?? []) {
      if (!arg.required && arg.name !== "reason") continue;
      switch (arg.type) {
        case "string":
          obj[arg.name] = "";
          break;
        case "boolean":
          obj[arg.name] = false;
          break;
        case "integer":
        case "number":
          obj[arg.name] = 0;
          break;
        case "array":
          obj[arg.name] = [];
          break;
        case "object":
          obj[arg.name] = {};
          break;
        default:
          obj[arg.name] = null;
      }
    }
    return JSON.stringify(obj, null, 2);
  }, []);

  const insertToolTemplate = useCallback(() => {
    if (!selectedTool) return;
    const value = draft;
    const trimmedStart = value.trimStart();
    if (!trimmedStart.startsWith("/tool")) return;
    if (value.includes("{")) return;
    const template = buildToolTemplate(selectedTool);
    setDraft(`${value.trimEnd()} ${template}`);
    scheduleComposerFocus({ force: true });
  }, [buildToolTemplate, draft, scheduleComposerFocus, selectedTool]);

  const onComposerKeyDown = useCallback(
    (e: React.KeyboardEvent<HTMLTextAreaElement>) => {
      if (toolSuggestions.length > 0) {
        if (e.key === "ArrowDown") {
          e.preventDefault();
          setToolHighlight((i) => Math.min(toolSuggestions.length - 1, i + 1));
          return;
        }
        if (e.key === "ArrowUp") {
          e.preventDefault();
          setToolHighlight((i) => Math.max(0, i - 1));
          return;
        }
        if (e.key === "Escape") {
          e.preventDefault();
          setToolSuggestions([]);
          setToolHighlight(0);
          return;
        }
        if (e.key === "Enter" || e.key === "Tab") {
          const pick = toolSuggestions[toolHighlight];
          if (pick) {
            e.preventDefault();
            applyToolSuggestion(pick);
            return;
          }
        }
      }
      if (e.key === "Enter" && !e.shiftKey) {
        e.preventDefault();
        if (sending) {
          stopSending();
          return;
        }
        void send();
      }
    },
    [applyToolSuggestion, send, sending, stopSending, toolHighlight, toolSuggestions]
  );

  useEffect(() => {
    const info = parseToolPartial(draft);
    if (!info) {
      setToolSuggestions([]);
      setSelectedTool(null);
      return;
    }
    if (!tools) {
      void fetchTools();
      return;
    }
    const q = info.partial.toLowerCase();
    const items: { display: string; canonical: string; tool: ToolSchema }[] = [];
    for (const tool of tools) {
      items.push({ display: tool.name, canonical: tool.name, tool });
      for (const alias of tool.aliases ?? []) {
        if (alias && alias !== tool.name) items.push({ display: alias, canonical: tool.name, tool });
      }
    }
    const filtered = q
      ? items.filter((i) => i.display.toLowerCase().includes(q) || i.canonical.toLowerCase().includes(q))
      : items;
    const unique = new Set<string>();
    const deduped = filtered.filter((i) => {
      const key = `${i.display}=>${i.canonical}`;
      if (unique.has(key)) return false;
      unique.add(key);
      return true;
    });
    deduped.sort((a, b) => a.display.localeCompare(b.display));
    setToolSuggestions(deduped.slice(0, 30));
    setToolHighlight(0);
  }, [draft, fetchTools, parseToolPartial, tools]);

  const doLogin = useCallback(async () => {
    if (loginBusy) return;
    setLoginBusy(true);
    setLoginError(null);
    try {
      const state = await tryLogin(loginUser, loginPass);
      if (!state) {
        setLoginError("Invalid credentials.");
        return;
      }
      setAuth(state);
      setLoginPass("");
    } catch (e) {
      console.error("login failed", e);
      setLoginError(e instanceof Error ? e.message : String(e));
    } finally {
      setLoginBusy(false);
    }
  }, [loginBusy, loginPass, loginUser]);

  const signOut = useCallback(() => {
    void logout(auth);
    setAuth(null);
    setLoginPass("");
    setLoginError(null);
    setActiveView("chat");
    setActiveThread(null);
    setThreads([]);
  }, [auth]);

  const renderScriptsView = () => {
    const languages = Array.from(new Set(scripts.map((script) => script.language).filter(Boolean))).sort();
    return (
      <div className="mt-3 grid min-h-0 flex-1 gap-3 overflow-hidden lg:grid-cols-[340px_1fr]">
        <Panel className="flex min-h-0 flex-col gap-3 p-4">
          <div>
            <div className={tokens.smallLabel}>Scripts Library</div>
            <div className="mt-1 text-sm text-slate-400">Every generated code artifact AgentX saves for later reuse.</div>
          </div>
          <input
            className={tokens.input}
            value={scriptQuery}
            onChange={(event) => setScriptQuery(event.target.value)}
            placeholder="Search scripts, model, language, or content..."
          />
          <div className="flex flex-wrap gap-2 text-xs text-slate-400">
            <span>{scripts.length} saved</span>
            {languages.slice(0, 6).map((language) => (
              <span key={language} className="agentx-pill px-2 py-1">{languageLabel(language)}</span>
            ))}
          </div>
          <ScrollArea className="min-h-0 flex-1 pr-1">
            <div className="space-y-2">
              {scripts.length === 0 ? (
                <div className="rounded-2xl border border-slate-800 bg-slate-950/70 p-4 text-sm text-slate-400">
                  No scripts saved yet. Ask AgentX to create code and it will appear here automatically.
                </div>
              ) : (
                scripts.map((script) => (
                  <button
                    key={script.id}
                    type="button"
                    className={[
                      "w-full rounded-2xl border p-3 text-left transition",
                      activeScript?.id === script.id
                        ? "border-cyan-400/35 bg-slate-900/90 text-cyan-50 shadow-[0_14px_30px_rgba(8,145,178,0.16)]"
                        : "border-slate-800 bg-slate-950/75 text-slate-200 hover:border-cyan-400/25 hover:bg-slate-900/75",
                    ].join(" ")}
                    onClick={() => setActiveScriptId(script.id)}
                  >
                    <div className="flex items-center justify-between gap-2">
                      <span className="truncate text-sm font-semibold">{script.title}</span>
                      <span className="agentx-pill px-2 py-1 text-[10px]">{languageLabel(script.language)}</span>
                    </div>
                    <div className="mt-1 flex flex-wrap gap-x-3 gap-y-1 text-xs text-slate-500">
                      <span>{scriptModelLabel(script)}</span>
                      <span>{scriptTimestamp(script.created_at)}</span>
                    </div>
                  </button>
                ))
              )}
            </div>
          </ScrollArea>
        </Panel>

        <Panel className="flex min-h-0 flex-col gap-3 p-4">
          {activeScript ? (
            <>
              <div className="flex flex-wrap items-start justify-between gap-3">
                <div className="min-w-0">
                  <div className={tokens.smallLabel}>Script Details</div>
                  <div className="mt-1 text-sm text-slate-400">
                    {languageLabel(activeScript.language)} · {scriptModelLabel(activeScript)} · {scriptTimestamp(activeScript.created_at)}
                  </div>
                </div>
                <div className="flex flex-wrap gap-2">
                  <button className={tokens.buttonUtility} type="button" onClick={() => navigator.clipboard.writeText(activeScript.content)}>Copy</button>
                  <button className={tokens.buttonUtility} type="button" onClick={() => exportScriptFile(activeScript)}>Export</button>
                  <button className={tokens.buttonUtility} type="button" onClick={() => insertScriptIntoChat(activeScript)}>Insert into chat</button>
                  <button className={tokens.buttonUtility} type="button" onClick={() => openScriptInCanvas(activeScript)}>Open canvas</button>
                  <button className={tokens.buttonDanger} type="button" onClick={() => void removeScript(activeScript)}>Delete</button>
                </div>
              </div>
              <div className="grid gap-3 md:grid-cols-[1fr_180px]">
                <label className="grid gap-1 text-sm">
                  <span className={tokens.smallLabel}>Title</span>
                  <input className={tokens.input} value={scriptDraft.title} onChange={(event) => setScriptDraft((prev) => ({ ...prev, title: event.target.value }))} />
                </label>
                <label className="grid gap-1 text-sm">
                  <span className={tokens.smallLabel}>Language</span>
                  <input className={tokens.input} value={scriptDraft.language} onChange={(event) => setScriptDraft((prev) => ({ ...prev, language: event.target.value }))} />
                </label>
              </div>
              <textarea
                className={[tokens.textarea, "min-h-[420px] flex-1 font-mono text-xs leading-5"].join(" ")}
                value={scriptDraft.content}
                onChange={(event) => setScriptDraft((prev) => ({ ...prev, content: event.target.value }))}
                spellCheck={false}
              />
              <div className="flex items-center justify-between gap-3">
                <div className="text-xs text-slate-500">
                  Source chat: {activeScript.source_thread_id ? activeScript.source_thread_id.slice(0, 8) : "unknown"}
                  {activeScript.updated_at !== activeScript.created_at ? ` · Edited ${scriptTimestamp(activeScript.updated_at)}` : ""}
                </div>
                <button className={tokens.button} type="button" onClick={() => void saveScriptEdits()} disabled={!scriptDraft.content.trim() || !scriptDraft.title.trim()}>
                  Save script
                </button>
              </div>
            </>
          ) : (
            <div className="flex min-h-[360px] items-center justify-center rounded-3xl border border-dashed border-slate-800 bg-slate-950/50 p-8 text-center text-sm text-slate-400">
              Select a script from the library, or ask AgentX to generate code.
            </div>
          )}
        </Panel>
      </div>
    );
  };

  useEffect(() => {
    const onDeckLayoutChanged = () => {
      setDeckLayoutPrefs({
        showModeRail: window.localStorage.getItem("agentx.deck.showModeRail") !== "false",
        showContextStack: window.localStorage.getItem("agentx.deck.showContextStack") !== "false",
      });
    };
    window.addEventListener("agentx-deck-layout-changed", onDeckLayoutChanged);
    return () => window.removeEventListener("agentx-deck-layout-changed", onDeckLayoutChanged);
  }, []);

  const showCommandDeck = !isMobile;
  const showModeRail = !isMobile && deckLayoutPrefs.showModeRail;
  const showContextStack = !isMobile && deckLayoutPrefs.showContextStack;

  const commandDeckStatusItems = [
    { label: "API", value: statusOk ? "online" : "offline", state: statusOk ? "ok" as const : "bad" as const },
    {
      label: "Ollama",
      value: providerEndpointStatus || (statusOk ? "ready" : "offline"),
      state: statusOk && providerEndpointStatus !== "unreachable" ? "ok" as const : "warn" as const,
    },
    { label: "Memory", value: "project", state: "ok" as const },
    { label: "GitHub", value: "tracked", state: "ok" as const },
  ];

  const commandDeckModes = [
    { id: "command" as const, label: "Command", icon: "⌁", title: "Chat and command surface" },
    { id: "drafts" as const, label: "Drafts", icon: "✎", title: "Open Draft Workspace" },
    { id: "memory" as const, label: "Memory", icon: "◈", title: "Knowledge and project memory" },
    { id: "scripts" as const, label: "Scripts", icon: "◇", title: "Saved code artifacts" },
    { id: "coding" as const, label: "Coding", icon: "⌨", title: "Coding Zone scratch runner" },
    { id: "models" as const, label: "Models", icon: "◎", title: "Model and Ollama settings" },
    { id: "health" as const, label: "Health", icon: "✦", title: "System health and runtime diagnostics" },
    { id: "validation" as const, label: "Validate", icon: "✓", title: "Run workspace validation presets" },
    { id: "workspaces" as const, label: "Workspaces", icon: "▣", title: "Uploaded archives and sandbox workspaces" },
    { id: "github" as const, label: "GitHub", icon: "⎇", title: "GitHub status and update controls" },
    { id: "settings" as const, label: "Settings", icon: "⋯", title: "Settings" },
  ];

  const selectDeckMode = (id: DeckModeId) => {
    setActiveDeckMode(id);
    if (id === "command") {
      setActiveView("chat");
      return;
    }
    if (id === "drafts") {
      setActiveView("chat");
      void openDraftWorkspace("open");
      return;
    }
    if (id === "memory") {
      setActiveView("knowledge");
      return;
    }
    if (id === "scripts") {
      setActiveView("scripts");
      return;
    }
    if (id === "coding") {
      setActiveView("coding");
      return;
    }
    if (id === "models") {
      setActiveView("models");
      return;
    }
    if (id === "health") {
      setActiveView("health");
      return;
    }
    if (id === "validation") {
      setActiveView("validation");
      return;
    }
    if (id === "workspaces") {
      setActiveView("workspaces");
      return;
    }
    setActiveView("settings");
  };

  const renderSidebar = (variant: "desktop" | "overlay") => {
    const headerRight =
      variant === "overlay" ? (
        <button className={[tokens.button, "!px-2 !py-1 !text-xs"].join(" ")} onClick={() => setNavOpen(false)}>
          Close
        </button>
        ) : (
          <StatusPill ok={statusOk} label="API" />
      );

    const body = (
      <>
        <Panel className="rounded-[1.4rem] p-3">
          <div
            className="flex items-center justify-between"
            onContextMenu={(e) => {
              e.preventDefault();
              createProject();
              onAfterNavAction();
            }}
            title="Right click to create a project"
          >
            <div className={tokens.smallLabel}>Projects</div>
            <button
              className={[tokens.button, "agentx-sidebar-action"].join(" ")}
              onClick={() => {
                createProject();
                onAfterNavAction();
              }}
              disabled={false}
            >
              New
            </button>
          </div>
          <div className="mt-2 space-y-2">
            <button
              className={[
                "w-full rounded-xl border px-3 py-2 text-left text-sm font-medium transition",
                !activeProjectId ? "border-cyan-400/30 bg-slate-900 text-cyan-50 shadow-[0_10px_24px_rgba(8,145,178,0.12)]" : "border-slate-800 bg-slate-950/70 text-slate-200 hover:bg-slate-900/80",
              ].join(" ")}
              onClick={() => {
                setActiveProjectId(null);
                onAfterNavAction();
              }}
            >
              All chats
            </button>
            <ScrollArea className="max-h-44 pr-1">
              <div className="space-y-2">
                {projects.length === 0 ? (
                  <div className="text-xs text-slate-500">No projects yet.</div>
                ) : (
                  projects.map((p) => (
                    <button
                      key={p.id}
                      className={[
                        "w-full rounded-xl border px-3 py-2 text-left text-sm font-medium transition",
                        activeProjectId === p.id
                          ? "border-cyan-400/30 bg-slate-900 text-cyan-50 shadow-[0_10px_24px_rgba(8,145,178,0.12)]"
                          : "border-slate-800 bg-slate-950/70 text-slate-200 hover:bg-slate-900/80",
                      ].join(" ")}
                      onClick={() => {
                        setActiveProjectId(p.id);
                        onAfterNavAction();
                      }}
                      onDoubleClick={(event) => {
                        event.preventDefault();
                        event.stopPropagation();
                        void renameProject(p);
                      }}
                      onContextMenu={(event) => {
                        event.preventDefault();
                        event.stopPropagation();
                        setProjectMenu({ id: p.id, x: event.clientX, y: event.clientY });
                      }}
                      title="Click to select. Double-click or right-click to rename/delete."
                    >
                      <span className="truncate">{p.name}</span>
                      {activeThread?.project_id !== p.id ? (
                        <span
                          className="mt-1 block text-[10px] text-slate-500"
                          onClick={(event) => {
                            event.stopPropagation();
                            void assignActiveThreadToProject(p.id);
                          }}
                        >
                          Assign active chat
                        </span>
                      ) : null}
                    </button>
                  ))
                )}
              </div>
            </ScrollArea>
          </div>
        </Panel>

        <Panel className="rounded-[1.4rem] bg-slate-950/54 p-3 text-sm">
          <div className="flex items-center justify-between gap-3">
            <div className={tokens.smallLabel}>Chats</div>
            <button className={[tokens.button, "agentx-sidebar-action"].join(" ")} onClick={() => void newChat()} disabled={!statusOk || loadingThreads}>
              New Chat
            </button>
          </div>
          <div className="mt-3 min-h-0 flex-1">
            <ScrollArea className="max-h-[420px] pr-1">
              <ThreadList
                threads={visibleThreads}
                activeId={activeThread?.id ?? null}
                onSelect={(id) => void selectThread(id)}
                onRename={(id, title) => void renameChat(id, title)}
                onDelete={(id) => void deleteChat(id)}
                disabled={!statusOk}
              />
            </ScrollArea>
          </div>
        </Panel>

        <Panel className="rounded-[1.4rem] bg-slate-950/54 p-3 text-sm agentx-settings-menu">
          <div className="flex items-center justify-between gap-3">
            <div className={tokens.smallLabel}>Menu</div>
            {authEnabled && auth ? (
              <button className={tokens.button} onClick={signOut} title="Sign out">
                Sign out
              </button>
            ) : null}
          </div>
          <div className="mt-2 grid gap-2">
            <button
              className={[
                "w-full rounded-xl border px-3 py-2 text-left text-sm font-medium transition",
                activeView === "chat" ? "border-cyan-400/30 bg-slate-900 text-cyan-50" : "border-slate-800 bg-slate-950/70 text-slate-200 hover:bg-slate-900/80",
              ].join(" ")}
              onClick={() => {
                setActiveView("chat");
                onAfterNavAction();
              }}
              title="Open chats"
            >
              ☰ Chats
            </button>
            <button
              className={[
                "w-full rounded-xl border px-3 py-2 text-left text-sm font-medium transition",
                activeView === "scripts" ? "border-cyan-400/30 bg-slate-900 text-cyan-50" : "border-slate-800 bg-slate-950/70 text-slate-200 hover:bg-slate-900/80",
              ].join(" ")}
              onClick={() => {
                setActiveView("scripts");
                onAfterNavAction();
              }}
              title="Open saved scripts"
            >
              ◇ Scripts {scripts.length ? <span className="text-xs text-slate-500">({scripts.length})</span> : null}
            </button>
            <button
              className={[
                "w-full rounded-xl border px-3 py-2 text-left text-sm font-medium transition",
                activeView === "knowledge" ? "border-cyan-400/30 bg-slate-900 text-cyan-50" : "border-slate-800 bg-slate-950/70 text-slate-200 hover:bg-slate-900/80",
              ].join(" ")}
              onClick={() => {
                setActiveView("knowledge");
                onAfterNavAction();
              }}
              title="Open local RAG knowledge manager"
            >
              ◈ Knowledge
            </button>
            <button
              className={[
                "w-full rounded-xl border px-3 py-2 text-left text-sm font-medium transition",
                activeView === "workspaces" ? "border-cyan-400/30 bg-slate-900 text-cyan-50" : "border-slate-800 bg-slate-950/70 text-slate-200 hover:bg-slate-900/80",
              ].join(" ")}
              onClick={() => {
                setActiveView("workspaces");
                onAfterNavAction();
              }}
              title="Open uploaded archives and sandbox workspaces"
            >
              ▣ Workspaces
            </button>
            <button
              className={[
                "w-full rounded-xl border px-3 py-2 text-left text-sm font-medium transition",
                activeView === "settings" || activeView === "customization"
                  ? "border-cyan-400/30 bg-slate-900 text-cyan-50"
                  : "border-slate-800 bg-slate-950/70 text-slate-200 hover:bg-slate-900/80",
              ].join(" ")}
              onClick={() => {
                setActiveView("settings");
                onAfterNavAction();
              }}
              title="Settings and customization"
            >
              ⋯ Settings
            </button>
          </div>
          {authEnabled === false ? <div className="mt-2 text-xs text-slate-500">Local mode active</div> : null}
          {authEnabled !== false && auth ? <div className="mt-2 text-xs text-slate-500">Signed in as {auth.user}</div> : null}
        </Panel>

        {!statusOk && (
          <div className="rounded-xl border border-amber-400/20 bg-amber-500/10 px-3 py-2 text-xs text-amber-100">
            Offline. {statusError ? `Last error: ${statusError}` : ""}
          </div>
        )}
      </>
    );

    if (variant === "overlay") {
      return (
        <Panel className="agentx-sidebar-panel flex h-full min-h-0 flex-col gap-3 p-3">
          <div className="flex items-center justify-between rounded-xl border border-slate-800/90 bg-slate-950/75 p-3 text-sm font-semibold text-slate-100">
            <div className="flex min-w-0 items-center gap-3">
              <BrandBadge compact />
              <StatusPill ok={statusOk} label="API" compact />
            </div>
            {headerRight}
          </div>
          <ScrollArea className="min-h-0 flex-1 pr-1">
            <div className="space-y-3">{body}</div>
          </ScrollArea>
        </Panel>
      );
    }

    return (
      <Panel className="agentx-sidebar-panel flex min-h-0 flex-col gap-3 p-3">
        <div className="flex items-center justify-between rounded-xl border border-slate-800/90 bg-slate-950/75 p-3 text-sm font-semibold text-slate-100">
          <div className="flex items-center gap-3">
            <BrandBadge compact />
          </div>
          {headerRight}
        </div>
        {body}
      </Panel>
    );
  };

  return (
    <div
      className={theme.shell.app}
      data-appearance-preset={appearancePreset}
      data-accent-intensity={accentIntensity}
      data-density-mode={densityMode}
    >
      {authEnabled === true && !auth ? (
        <div className="fixed inset-0 z-[60] flex items-center justify-center bg-slate-950/92 p-4 backdrop-blur-sm">
          <Panel className="w-full max-w-md p-5">
            <div className="flex items-center gap-3">
              <BrandBadge />
            </div>
            <div className="mt-4 text-lg font-semibold text-slate-50">Sign In</div>
            <div className="mt-1 text-sm text-slate-400">Sign in to access the local control surface.</div>

            {loginError ? (
              <div className="mt-3 rounded-xl border border-rose-400/25 bg-rose-500/10 p-3 text-sm text-rose-100">
                {loginError}
              </div>
            ) : null}

            <div className="mt-4 grid gap-3">
              <label className="grid gap-1 text-sm">
                <span className="text-xs font-semibold text-slate-400">User</span>
                <input
                  className={tokens.input}
                  value={loginUser}
                  onChange={(e) => setLoginUser(e.target.value)}
                  autoComplete="username"
                />
              </label>
              <label className="grid gap-1 text-sm">
                <span className="text-xs font-semibold text-slate-400">Password</span>
                <input
                  className={tokens.input}
                  value={loginPass}
                  onChange={(e) => setLoginPass(e.target.value)}
                  type="password"
                  autoComplete="current-password"
                  onKeyDown={(e) => {
                    if (e.key === "Enter") {
                      e.preventDefault();
                      void doLogin();
                    }
                  }}
                />
              </label>

              <button className={tokens.button} disabled={loginBusy} onClick={() => void doLogin()}>
                {loginBusy ? "Signing in..." : "Sign in"}
              </button>

              <div className="text-xs text-slate-500">
                API: <span className="font-mono">{config.apiBase}</span>
              </div>
            </div>
          </Panel>
        </div>
      ) : null}

      {showCommandDeck ? (
        <div className="agentx-command-deck-shell-top">
          <TopStatusBar
            title="AgentX Command Deck"
            subtitle={activeProject ? `Project: ${activeProject.name}` : "Local-first AI command surface"}
            items={commandDeckStatusItems}
            rightSlot={<span className="agentx-command-deck-model">{chatProvider}:{chatModel || "select model"}</span>}
          />
          <GitHubUpdateTicker />
        </div>
      ) : null}

      {isMobile && navOpen && layoutSettings.showSidebar ? (
        <div
          className="fixed inset-0 z-40 bg-black/30"
          onClick={() => setNavOpen(false)}
          role="button"
          tabIndex={-1}
          aria-label="Close navigation"
        />
      ) : null}

      {isMobile && layoutSettings.showSidebar ? (
        <div
          className={[
            "fixed inset-y-0 left-0 z-50 w-[min(92vw,320px)] p-4 transition-transform",
            navOpen ? "translate-x-0" : "-translate-x-full",
          ].join(" ")}
          aria-hidden={!navOpen}
        >
          {renderSidebar("overlay")}
        </div>
      ) : null}
      <div
        className={[
          "grid h-full min-h-0 min-w-0",
          tokens.gutter,
          tokens.gap,
          isMobile
            ? "grid-cols-1"
            : layoutSettings.showSidebar && showModeRail && showContextStack
              ? "grid-cols-[76px_300px_minmax(0,1fr)_320px]"
              : layoutSettings.showSidebar && showModeRail
                ? "grid-cols-[76px_300px_minmax(0,1fr)]"
                : showModeRail && showContextStack
                  ? "grid-cols-[76px_minmax(0,1fr)_320px]"
                  : showModeRail
                    ? "grid-cols-[76px_minmax(0,1fr)]"
                    : layoutSettings.showSidebar && showContextStack
                      ? "grid-cols-[300px_minmax(0,1fr)_320px]"
                      : layoutSettings.showSidebar
                        ? "grid-cols-[300px_minmax(0,1fr)]"
                        : showContextStack
                          ? "grid-cols-[minmax(0,1fr)_320px]"
                          : "grid-cols-1",
        ].join(" ")}
      >
        {showModeRail ? <ModeRail modes={commandDeckModes} activeId={activeDeckMode} onSelect={selectDeckMode} /> : null}
        {!isMobile && layoutSettings.showSidebar ? renderSidebar("desktop") : null}

        <Panel className={theme.shell.mainPanel}>
          {layoutSettings.showHeader ? (
          <>
          <div className={theme.shell.topBar}>
            <div className="flex min-w-0 items-start gap-2">
              {isMobile && layoutSettings.showSidebar ? (
                <button
                  className={[tokens.button, "!px-2 !py-1 !text-xs"].join(" ")}
                  onClick={() => setNavOpen(true)}
                  aria-label="Open navigation"
                  title="Open navigation"
                >
                  ☰
                </button>
              ) : null}
              <div className="min-w-0">
                <div className="flex items-center gap-3">
                  <BrandBadge compact />
                  <div className="min-w-0">
                    <div className={theme.copy.title}>
                      {activeView === "settings" || activeView === "customization"
                        ? "Settings"
                        : activeView === "scripts"
                          ? "Scripts"
                          : activeView === "knowledge"
                            ? "Knowledge"
                            : activeView === "validation"
                              ? "Validation"
                              : activeThread
                            ? activeThread.title || config.threadTitleDefault
                            : "Chat"}
                      {activeProject ? <span className="text-xs font-normal text-slate-500">{` - ${activeProject.name}`}</span> : null}
                    </div>
                    <div className={theme.copy.muted}>
                      {activeView === "settings" || activeView === "customization"
                        ? "Provider, appearance, layout, and local behavior."
                        : activeView === "scripts"
                          ? "Saved code artifacts from every AgentX generation."
                          : activeView === "knowledge"
                            ? "Ingest URLs, project folders, and game files into local RAG."
                            : activeView === "validation"
                              ? "Run safe validation presets against AgentX workspaces."
                              : `Direct channel into ${assistantDisplayName}.`}
                    </div>
                  </div>
                </div>
              </div>
            </div>
            <div className="agentx-topbar__controls">
              {isMobile ? <StatusPill ok={statusOk} label="API" /> : null}
              <button
                className={tokens.buttonSecondary}
                type="button"
                onClick={() => setActiveView(activeView === "settings" || activeView === "customization" ? "chat" : "settings")}
                title="Settings and customization"
              >
                ⋯
              </button>
              {activeView === "chat" ? (
                <label className="agentx-topbar__field text-xs text-slate-400">
                  <span>Model:</span>
                  <AgentXDropdown
                    value={modelOptions.selectedKey}
                    options={chatModelDropdownOptions}
                    disabled={!statusOk}
                    placeholder="Select model"
                    className="agentx-model-dropdown"
                    fitToOptions={false}
                    onOpenChange={(open) => {
                      modelDropdownOpenRef.current = open;
                    }}
                    onChange={(nextValue) => {
                      const [provider, ...rest] = nextValue.split(":");
                      const model = rest.join(":");
                      setChatProvider(provider);
                      setChatModel(model);
                      selectionPersistRef.current = persistChatSelection(provider, model);
                    }}
                  />
                  <button
                    className={tokens.button}
                    disabled={!statusOk}
                    onClick={() => void refreshModels()}
                    title="Refresh model list"
                  >
                    Refresh
                  </button>
                  {layoutSettings.showCodeCanvas && codeCanvas.sourceMessageId ? (
                    <button
                      className={tokens.buttonSecondary}
                      type="button"
                      onClick={() => reopenCodeCanvas(codeCanvas.sourceMessageId!)}
                    >
                      {codeCanvas.isOpen ? "Canvas" : "Open Canvas"}
                    </button>
                  ) : null}
                </label>
              ) : null}
            </div>
          </div>
                    </>
          ) : null}

          {activeView === "settings" || activeView === "customization" ? (
            <div className="mt-3 grid min-h-0 flex-1 gap-3 overflow-hidden lg:grid-cols-[minmax(0,0.95fr)_minmax(0,1.05fr)]">
              <SettingsPage
                statusOk={statusOk}
                status={{
                  chat_provider: chatProvider,
                  chat_model: chatModel,
                  available_chat_models: availableModels,
                  ollama_base_url: ollamaBaseUrl,
                  ollama_endpoints: ollamaEndpoints,
                  models_last_refresh: modelsLastRefresh,
                  models_error: modelsError,
                  models_refreshing: modelsRefreshing,
                }}
                settings={appSettings}
                onSettingsSaved={handleSettingsSaved}
                onSystemMessage={setSystemMessage}
              />
              <CustomizationPage
                statusOk={statusOk}
                settings={appSettings}
                layoutGuards={layoutGuards}
                onSettingsChange={applySettings}
                onSettingsSaved={handleSettingsSaved}
                onSystemMessage={setSystemMessage}
              />
            </div>
          ) : activeView === "knowledge" ? (
            <MemoryPage onSystemMessage={setSystemMessage} />
          ) : activeView === "workspaces" ? (
            <div className="min-h-0 flex-1 overflow-hidden rounded-[1.45rem] border border-slate-800 bg-slate-950/70">
              <iframe
                title="AgentX Workspaces"
                src="/workspaces.html"
                className="h-full min-h-[72vh] w-full border-0"
              />
            </div>
          ) : activeView === "models" ? (
            <ModelsPage
              statusOk={statusOk}
              status={{
                chat_provider: chatProvider,
                chat_model: chatModel,
                available_chat_models: availableModels,
                ollama_base_url: ollamaBaseUrl,
                ollama_endpoints: ollamaEndpoints,
                models_error: modelsError,
                models_refreshing: modelsRefreshing,
                models_last_refresh: modelsLastRefresh,
              }}
              settings={appSettings}
              onUseModel={(provider, model) => {
                setChatProvider(provider);
                setChatModel(model);
                selectionPersistRef.current = persistChatSelection(provider, model);
              }}
              onRefreshModels={() => void refreshModels()}
              onSystemMessage={setSystemMessage}
            />
          ) : activeView === "health" ? (
            <HealthPage statusOk={statusOk} onSystemMessage={setSystemMessage} />
          ) : activeView === "validation" ? (
            <ValidationPage statusOk={statusOk} onSystemMessage={setSystemMessage} />
          ) : activeView === "coding" ? (
            <CodingZonePage
              statusOk={statusOk}
              onSystemMessage={setSystemMessage}
              onAskAgentX={(prompt) => {
                setDraft(prompt);
                setActiveView("chat");
                setActiveDeckMode("command");
              }}
            />
          ) : activeView === "scripts" ? (
            renderScriptsView()
          ) : (
            <div className={["mt-3 flex min-h-0 flex-1 gap-3", codeCanvas.isOpen ? "agentx-chat-with-canvas" : ""].join(" ")}>
              <div className={["flex min-h-0 flex-1 flex-col", codeCanvas.isOpen && codeCanvas.viewMode === "fullscreen" ? "agentx-chat-pane--hidden" : ""].join(" ")}>
                {unsafeStatus?.unsafe_enabled ? (
                  <div className="mb-3 rounded-2xl border border-rose-400/25 bg-rose-500/10 px-3 py-2 text-sm font-semibold text-rose-100">
                    ⚠ UNSAFE MODE ENABLED — filesystem + destructive actions unrestricted for this thread
                  </div>
                ) : null}
                <div
                  ref={feedRef}
                  onScroll={onFeedScroll}
                  className={theme.shell.feed}
                >
                  {activeThread?.messages?.length ? (
                    <div className="agentx-feed__stack">
                      {(() => {
                        const lastAssistantId = [...activeThread.messages].reverse().find((x) => x.role === "assistant")?.id ?? null;
                        return activeThread.messages.map((m, index) => {
                          const isLastAssistant = m.role === "assistant" && m.id === lastAssistantId;
                          const prev = activeThread.messages[index - 1];
                          const next = activeThread.messages[index + 1];
                          const companion = codeCanvas.companions[m.id] ?? null;
                          return (
                            <ChatMessage
                              key={m.id}
                              message={m}
                              isLastAssistant={isLastAssistant}
                              verification={lastVerification}
                              onQuote={quoteIntoComposer}
                              onEdit={editMessageIntoComposer}
                              onRetry={() => retryMessage(m.id)}
                              onContinue={m.role === "assistant" ? continueConversation : null}
                              onFeedback={m.role === "assistant" ? (feedback) => setMessageFeedbackValue(m.id, feedback) : null}
                              feedback={messageFeedback[m.id] ?? null}
                              onSaveScript={m.role === "assistant" ? () => void saveMessageAsScript(m.id) : null}
                              onAddToProject={m.role === "assistant" ? () => void addActiveChatToProject() : null}
                              startsGroup={!prev || prev.role !== m.role}
                              endsGroup={!next || next.role !== m.role}
                              assistantLabel={assistantDisplayName}
                              userLabel={userDisplayName}
                              codeCanvasMeta={companion ? { language: companion.language, lineCount: companion.lineCount, title: companion.title } : null}
                              onOpenCodeCanvas={companion && layoutSettings.showCodeCanvas ? () => reopenCodeCanvas(m.id) : null}
                              showQualityGateReport={appSettings.modelBehavior?.showQualityGateReport ?? true}
                            />
                          );
                        });
                      })()}
                      {sending ? (
                        <div className="agentx-responding" aria-live="polite">
                          <div className="agentx-message-row__rail" aria-hidden="true">
                            <div className="agentx-message-avatar agentx-message-avatar--assistant">
                              {assistantDisplayName.trim().charAt(0).toUpperCase() || "N"}
                            </div>
                          </div>
                          <div className="agentx-responding__body">
                            <div className="agentx-responding__bubble">
                              <span className="agentx-responding__dots" aria-hidden="true">
                                <span />
                                <span />
                                <span />
                              </span>
                              <span className="agentx-responding__text">{`${assistantDisplayName} is responding...`}</span>
                            </div>
                          </div>
                        </div>
                      ) : null}
                    </div>
                  ) : (
                    <div className="agentx-feed-empty flex min-h-[220px] items-center justify-center rounded-[1.25rem] px-6 text-center text-sm text-slate-400">
                      <div className="agentx-feed-empty__card">
                        <div className="agentx-feed-empty__eyebrow">Conversation Ready</div>
                        <div className="agentx-feed-empty__title">{assistantDisplayName} is ready.</div>
                        <div className="agentx-feed-empty__copy">
                          {`Start a new chat with ${assistantDisplayName}, or select an existing one from the left.`}
                        </div>
                      </div>
                    </div>
                  )}
                  {showJumpToLatest ? (
                    <button
                      type="button"
                      className="agentx-jump-latest"
                      onClick={() => resumeAutoScroll("smooth")}
                    >
                      ↓ Jump to latest
                    </button>
                  ) : null}
                </div>

                <div className={theme.shell.composer}>
                  {handoffSuggestion ? (
                    <div className="agentx-handoff-card">
                      <div>
                        <div className="agentx-handoff-card__title">Coding intent detected</div>
                        <div className="agentx-handoff-card__copy">
                          Use <strong>{handoffSuggestion.model}</strong> directly, or let <strong>{handoffSuggestion.draftModel || "Qwen"}</strong> draft and <strong>{handoffSuggestion.reviewModel || handoffSuggestion.model}</strong> review/finalize.
                        </div>
                      </div>
                      <div className="agentx-handoff-card__actions">
                        <button className={tokens.button} type="button" disabled={sending} onClick={acceptCollaborativeCodingSuggestion}>
                          Draft + Review
                        </button>
                        <button className={tokens.buttonSecondary} type="button" disabled={sending} onClick={acceptHandoffSuggestion}>
                          Heavy Coding Only
                        </button>
                        <button className={tokens.buttonSecondary} type="button" onClick={() => setHandoffSuggestion(null)}>
                          Dismiss
                        </button>
                      </div>
                    </div>
                  ) : null}
                  <input
                    ref={fileInputRef}
                    type="file"
                    className="hidden"
                    multiple
                    onChange={(event) => void addComposerFiles(event.currentTarget.files, "file")}
                  />
                  <input
                    ref={archiveInputRef}
                    type="file"
                    className="hidden"
                    accept=".zip,.rar,.7z,.tar,.tgz,.tar.gz,application/zip,application/x-rar-compressed,application/x-7z-compressed"
                    onChange={(event) => void importWorkbenchArchives(event.currentTarget.files)}
                  />
                  <input
                    ref={imageInputRef}
                    type="file"
                    className="hidden"
                    multiple
                    accept="image/*"
                    onChange={(event) => void addComposerFiles(event.currentTarget.files, "image")}
                  />
                  {draft.trim() ? (
                    <div className="mb-2 flex flex-wrap items-center gap-2 rounded-2xl border border-slate-800 bg-slate-950/70 px-3 py-2 text-xs text-slate-300">
                      <span className="font-semibold text-slate-200">Judgment:</span>
                      {judgmentPreviewLoading ? (
                        <span className="text-slate-500">checking...</span>
                      ) : judgmentPreview ? (
                        <>
                          <span className={[
                            "rounded-full px-2 py-0.5 font-bold",
                            judgmentPreview.route === "BLOCK" ? "bg-rose-500/15 text-rose-200" :
                            judgmentPreview.route === "DEEP" || judgmentPreview.route === "RECOVER" ? "bg-violet-500/15 text-violet-200" :
                            judgmentPreview.route === "HOLD" ? "bg-amber-500/15 text-amber-200" :
                            "bg-emerald-500/15 text-emerald-200"
                          ].join(" ")}>
                            {judgmentPreview.route}
                          </span>
                          <span>-&gt; {judgmentPreview.endpoint || "none"}</span>
                          <span className="text-slate-500">{Math.round(judgmentPreview.confidence * 100)}%</span>
                          <span className="min-w-0 flex-1 truncate text-slate-400" title={judgmentPreview.reason}>{judgmentPreview.reason}</span>
                          <button
                            type="button"
                            className={[
                              "rounded-full border px-2 py-0.5 text-[11px] font-semibold",
                              judgmentAutoRouteEnabled
                                ? "border-cyan-400/45 bg-cyan-400/10 text-cyan-100"
                                : "border-slate-700 bg-slate-900/70 text-slate-400"
                            ].join(" ")}
                            onClick={() => setJudgmentAutoRouteEnabled((value) => !value)}
                            title="When enabled, AgentX will use the judgment preview to choose fast/heavy for this send without changing the selected dropdown model."
                          >
                            Auto Route: {judgmentAutoRouteEnabled ? "on" : "off"}
                          </button>
                        </>
                      ) : judgmentPreviewError ? (
                        <span className="text-amber-200">{judgmentPreviewError}</span>
                      ) : (
                        <span className="text-slate-500">ready</span>
                      )}
                    </div>
                  ) : null}
                  <div className="agentx-composer-toolbar">
                    <button
                      type="button"
                      className="agentx-reflect-task-button"
                      disabled={!statusOk || !activeThread}
                      onClick={() => setTaskReflectionOpen(true)}
                      title="Review this task and promote durable project knowledge"
                    >
                      Reflect Task
                    </button>
                    <div className="agentx-composer-plus-wrap">
                      <button
                        type="button"
                        className="agentx-composer-plus"
                        onClick={() => setComposerMenuOpen((open) => !open)}
                        disabled={!statusOk || sending}
                        aria-label="Add context"
                      >
                        +
                      </button>
                      {composerMenuOpen ? (
                        <div className="agentx-composer-menu">
                          <button type="button" onClick={() => { setComposerMenuOpen(false); fileInputRef.current?.click(); }}>Attach file</button>
                          <button type="button" onClick={() => void attachAllowedPath()}>Attach @file path</button>
                          <button type="button" onClick={() => { setComposerMenuOpen(false); archiveInputRef.current?.click(); }}>Upload server archive</button>
                          <button type="button" onClick={() => { setComposerMenuOpen(false); imageInputRef.current?.click(); }}>Attach picture</button>
                          <button type="button" onClick={() => { setComposerMenuOpen(false); insertFileSearchPrompt(); }}>Search for a file</button>
                          <button type="button" onClick={() => { setComposerMenuOpen(false); void openDraftWorkspace("open"); }}>Open as Draft</button>
                          <button type="button" onClick={() => { setComposerMenuOpen(false); void openDraftWorkspace("explain"); }}>Explain as Draft</button>
                          <button type="button" onClick={() => { setComposerMenuOpen(false); void openDraftWorkspace("rewrite"); }}>Rewrite as Draft</button>
                          <button type="button" onClick={() => { setComposerMenuOpen(false); void openDraftWorkspace("explain_and_rewrite"); }}>Explain + Rewrite Draft</button>
                          <button type="button" onClick={() => { setComposerMenuOpen(false); setComposerRagMode((mode) => mode === "strict" ? "auto" : "strict"); }}>RAG: {composerRagMode === "strict" ? "Strict" : "Auto"}</button>
                          <button type="button" onClick={() => { setComposerMenuOpen(false); setComposerRagMode((mode) => mode === "off" ? "auto" : "off"); }}>Local RAG: {composerRagMode === "off" ? "Off" : "On"}</button>
                        </div>
                      ) : null}
                    </div>
                    <div className="agentx-composer-context">
                      <span className={composerRagMode === "strict" ? "agentx-composer-context__rag agentx-composer-context__rag--strict" : composerRagMode === "off" ? "agentx-composer-context__rag agentx-composer-context__rag--off" : "agentx-composer-context__rag"}>
                        RAG: {composerRagMode}
                      </span>
                      {composerAttachments.map((item) => (
                        <button key={item.id} type="button" className="agentx-composer-chip" onClick={() => removeComposerAttachment(item.id)} title="Remove attachment">
                          {item.kind === "image" ? "Picture" : "File"}: {item.name} ×
                        </button>
                      ))}
                    </div>
                  </div>
                  <textarea
                    ref={textareaRef}
                    value={draft}
                    onChange={(e) => setDraft(e.target.value)}
                    placeholder={statusOk ? `Message ${assistantDisplayName}...` : "Offline - cannot send"}
                    disabled={!statusOk}
                    rows={3}
                    className={tokens.textarea}
                    onFocus={() => void fetchTools()}
                    onKeyDown={onComposerKeyDown}
                  />
                  {draft.trimStart().startsWith("/tool") && toolError ? (
                    <div className="text-xs text-rose-700">Tool schema unavailable: {toolError}</div>
                  ) : null}
                  {draft.trimStart().startsWith("/tool") && toolSuggestions.length > 0 ? (
                    <div className="max-h-56 overflow-auto rounded-2xl border border-slate-800 bg-slate-950/92 shadow-[0_18px_40px_rgba(2,8,23,0.32)]">
                      {toolSuggestions.map((s, idx) => (
                        <button
                          key={`${s.display}=>${s.canonical}`}
                          type="button"
                          className={[
                            "w-full text-left px-3 py-2 text-sm",
                            idx === toolHighlight ? "bg-slate-900/90" : "bg-slate-950/90 hover:bg-slate-900/80",
                          ].join(" ")}
                          onMouseEnter={() => setToolHighlight(idx)}
                          onClick={() => applyToolSuggestion(s)}
                        >
                          <div className="flex items-center justify-between gap-2">
                            <span className="font-medium text-slate-100">{s.display}</span>
                            {s.display !== s.canonical ? (
                              <span className="text-xs text-slate-500">→ {s.canonical}</span>
                            ) : null}
                          </div>
                          {s.tool.description ? <div className="text-xs text-slate-500">{s.tool.description}</div> : null}
                        </button>
                      ))}
                    </div>
                  ) : null}
                  {draft.trimStart().startsWith("/tool") && selectedTool ? (
                    <div className="rounded-2xl border border-slate-800 bg-slate-950/72 p-3 text-xs text-slate-300">
                      <div className="flex items-center justify-between gap-2">
                        <div className="font-semibold">{selectedTool.name}</div>
                        <button className={tokens.button} type="button" onClick={insertToolTemplate}>
                          Insert JSON template
                        </button>
                      </div>
                      {selectedTool.description ? (
                        <div className="mt-1 text-slate-600">{selectedTool.description}</div>
                      ) : null}
                      <div className="mt-2 space-y-1">
                        {selectedTool.args.map((a) => (
                          <div key={a.name} className="flex items-center justify-between gap-2">
                            <div>
                              <span className="font-semibold">{a.name}</span>{" "}
                              <span className="text-slate-500">({a.type})</span>{" "}
                              {a.required ? <span className="text-rose-600">*</span> : null}
                            </div>
                            <div className="text-slate-500">{a.description}</div>
                          </div>
                        ))}
                      </div>
                    </div>
                  ) : null}
                  <div className="flex items-center justify-between gap-3">
                    <div className="text-xs text-slate-500">{sending ? "Enter or Stop to cancel response" : "Enter to send - Shift+Enter for newline"}</div>
                    <button
                      className={[sending ? tokens.buttonDanger : tokens.button, "agentx-send-button min-w-[96px]"].join(" ")}
                      onClick={() => (sending ? stopSending() : void send())}
                      disabled={!statusOk || (!sending && !draft.trim())}
                    >
                      {sending ? "Stop" : "Send"}
                    </button>
                  </div>
                </div>
              </div>

              {layoutSettings.showCodeCanvas && codeCanvas.isOpen ? (
                <CodeCanvas
                  canvas={codeCanvas}
                  onUpdate={updateCodeCanvas}
                  onClose={closeCodeCanvas}
                  onSendSelection={sendCodeCanvasSelectionToChat}
                />
              ) : null}
            </div>
          )}
        </Panel>

        {showContextStack ? (
          <ContextStackPanel
            threadTitle={activeThread?.title || null}
            projectName={activeProject?.name || null}
            provider={chatProvider}
            model={chatModel}
            apiOk={statusOk}
            endpointStatus={providerEndpointStatus}
            memoryEnabled={true}
            draftOpen={draftWorkspace.open}
            attachedCount={composerAttachments.length}
            retrievedCount={lastRetrieved.length}
            gitStatus="unknown"
          />
        ) : null}
      </div>


      {projectMenu
        ? createPortal(
            <div
              className="agentx-project-context-menu-layer"
              onClick={() => setProjectMenu(null)}
              onContextMenu={(event) => {
                event.preventDefault();
                setProjectMenu(null);
              }}
            >
              <div
                className="agentx-project-context-menu agentx-context-menu"
                style={{ left: projectMenu.x, top: projectMenu.y }}
                onClick={(event) => event.stopPropagation()}
                onContextMenu={(event) => event.preventDefault()}
              >
                <button
                  className={`${tokens.buttonSecondary} w-full justify-start`}
                  type="button"
                  onClick={() => {
                    const project = projects.find((item) => item.id === projectMenu.id);
                    setProjectMenu(null);
                    if (project) void renameProject(project);
                  }}
                >
                  Rename
                </button>
                <button
                  className={`${tokens.buttonDanger} w-full justify-start`}
                  type="button"
                  onClick={() => {
                    const project = projects.find((item) => item.id === projectMenu.id);
                    setProjectMenu(null);
                    if (project) void deleteProject(project);
                  }}
                >
                  Delete
                </button>
              </div>
            </div>,
            document.body
          )
        : null}


      <TaskReflectionModal
        open={taskReflectionOpen}
        statusOk={statusOk}
        threadTitle={activeThread?.title || null}
        projectName={activeProject?.name || null}
        model={chatModel}
        messages={(activeThread?.messages || []).map((message) => ({ role: message.role, content: message.content }))}
        onClose={() => setTaskReflectionOpen(false)}
        onSaved={setSystemMessage}
      />

      {draftWorkspace.open ? (
        <div className="agentx-draft-workspace" role="dialog" aria-modal="true" aria-label="Draft Workspace">
          <div className="agentx-draft-workspace__panel">
            <div className="agentx-draft-workspace__header">
              <div>
                <div className="agentx-draft-workspace__eyebrow">Draft Workspace</div>
                <h2>{draftWorkspace.data?.title || "Preparing draft..."}</h2>
                <p>{draftWorkspace.data ? `${draftWorkspace.data.language} • ${draftWorkspace.data.model_provider || "local"}${draftWorkspace.data.model_name ? `:${draftWorkspace.data.model_name}` : ""}` : `Mode: ${draftWorkspace.mode}`}</p>
              </div>
              <button type="button" className={tokens.buttonSecondary} onClick={closeDraftWorkspace}>Close</button>
            </div>
            {draftWorkspace.loading ? (
              <div className="agentx-draft-workspace__loading">Generating draft...</div>
            ) : draftWorkspace.error ? (
              <div className="agentx-draft-workspace__error">{draftWorkspace.error}</div>
            ) : draftWorkspace.data ? (
              <div className="agentx-draft-workspace__body">
                <section>
                  <div className="agentx-draft-workspace__section-head"><h3>Original</h3><button type="button" onClick={() => void copyDraftSection(draftWorkspace.data?.original || "", "Original")}>Copy</button></div>
                  <pre>{draftWorkspace.data.original}</pre>
                </section>
                <section>
                  <div className="agentx-draft-workspace__section-head"><h3>Explanation</h3><button type="button" onClick={() => void copyDraftSection(draftWorkspace.data?.explanation || "", "Explanation")}>Copy</button></div>
                  <div className="agentx-draft-workspace__text">{draftWorkspace.data.explanation || "No explanation generated."}</div>
                </section>
                <section>
                  <div className="agentx-draft-workspace__section-head"><h3>Improved Version</h3><button type="button" onClick={() => void copyDraftSection(draftWorkspace.data?.improved || "", "Improved version")}>Copy</button></div>
                  <pre>{draftWorkspace.data.improved || "No rewrite generated for this mode."}</pre>
                </section>
                <section>
                  <h3>Notes</h3>
                  <ul>{(draftWorkspace.data.notes || []).map((note, idx) => <li key={`${idx}-${note}`}>{note}</li>)}</ul>
                </section>
              </div>
            ) : null}
            <div className="agentx-draft-workspace__footer">
              <button type="button" className={tokens.buttonSecondary} onClick={sendDraftToChat} disabled={!draftWorkspace.data}>Send to Chat</button>
              <button type="button" className={tokens.button} onClick={() => void saveDraftAsScript()} disabled={!draftWorkspace.data}>Save as Script</button>
            </div>
          </div>
        </div>
      ) : null}
      <AgentXVersionBadge />
    </div>
  );
}
