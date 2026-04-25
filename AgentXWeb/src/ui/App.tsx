import React, { useCallback, useEffect, useMemo, useRef, useState } from "react";
import {
  DEFAULT_AGENTX_SETTINGS,
  ToolSchema,
  AuditEntry,
  appendThreadMessage,
  createThread,
  getToolsSchema,
  getSettings,
  getStatus,
  getStatusRefresh,
  getThread,
  getUnsafeMode,
  RetrievedChunk,
  listThreads,
  saveSettings,
  sendChatMessage,
  deleteThread,
  updateThreadTitle,
  updateThreadModel,
  Thread,
  ThreadSummary,
  UnsafeStatusResponse,
  ApiError,
  normalizeLayoutSettings,
  type ProviderErrorDetail,
  type AgentXSettings,
} from "../api/client";
import { config } from "../config";
import { Panel } from "./components/Panel";
import { ScrollArea } from "./components/ScrollArea";
import { StatusPill } from "./components/StatusPill";
import { ThreadList } from "./components/ThreadList";
import { tokens } from "./tokens";
import { useProjects } from "./components/Projects";
import { SettingsPage } from "./pages/SettingsPage";
import { CustomizationPage } from "./pages/CustomizationPage";
import { clearAuth, loadAuth, logout, tryLogin, type AuthState } from "./auth";
import { InspectorPanel } from "./components/InspectorPanel";
import { ChatMessage } from "./components/ChatMessage";
import { BrandBadge } from "./components/BrandBadge";
import { createClientId } from "./clientId";
import { AgentXDropdown, type AgentXDropdownOption } from "./components/AgentXDropdown";
import { theme } from "./theme";
import { CodeCanvas } from "./components/CodeCanvas";
import { defaultCodeCanvasState, detectCodeCanvas, loadCodeCanvasState, saveCodeCanvasState, type CodeCanvasState } from "./codeCanvas";
import { applyPendingLayoutToSettings, clearPendingLayoutSave, loadPendingLayoutSave, pendingLayoutChangedEventName } from "./layoutPersistence";
import { buildSendFailureMessage, isAbortError, restoreDraftAfterSendFailure, restoreDraftAfterStop, rollbackOptimisticThread } from "./chatSend";

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
  };
}

export function App() {
  const [auth, setAuth] = useState<AuthState | null>(() => loadAuth());
  const [authEnabled, setAuthEnabled] = useState<boolean | null>(null);
  const [activeView, setActiveView] = useState<"chat" | "settings" | "customization">("chat");
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
  const [providerEndpointStatus, setProviderEndpointStatus] = useState<string | null>(null);
  const [providerModelStatus, setProviderModelStatus] = useState<string | null>(null);
  const [lastProviderError, setLastProviderError] = useState<ProviderErrorDetail | null>(null);
  const [appSettings, setAppSettings] = useState<AgentXSettings>(DEFAULT_AGENTX_SETTINGS);
  const [pendingLayoutSync, setPendingLayoutSync] = useState(() => loadPendingLayoutSave());
  const sessionReady = authEnabled === false || Boolean(auth);

  const lastServerSelectionRef = useRef<{ provider: string; model: string }>({ provider: "stub", model: "stub" });
  const selectionPersistRef = useRef<Promise<void> | null>(null);

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
  const { projects, activeProjectId, activeProject, setActiveProjectId, createProject } = useProjects();
  const threadProjectMapRef = useRef<Record<string, string>>({});

  const [draft, setDraft] = useState("");
  const textareaRef = useRef<HTMLTextAreaElement | null>(null);
  const feedRef = useRef<HTMLDivElement | null>(null);
  const nearBottomRef = useRef(true);
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
    try {
      threadProjectMapRef.current = JSON.parse(localStorage.getItem(config.threadProjectMapKey) ?? "{}");
    } catch {
      threadProjectMapRef.current = {};
    }
  }, []);

  useEffect(() => {
    setCodeCanvas(loadCodeCanvasState());
  }, []);

  useEffect(() => {
    saveCodeCanvasState(codeCanvas);
  }, [codeCanvas]);

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

  const persistThreadProjectMap = useCallback(() => {
    localStorage.setItem(config.threadProjectMapKey, JSON.stringify(threadProjectMapRef.current));
  }, []);

  const visibleThreads = useMemo(() => {
    if (!activeProjectId) return threads;
    const map = threadProjectMapRef.current;
    return threads.filter((t) => map[t.id] === activeProjectId);
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
    options.push({ value: "__label_stub__", label: "Stub", disabled: true });
    options.push({ value: "stub:stub", label: "stub" });
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
        setAvailableModels(res.available_chat_models ?? {});
        setModelsRefreshing(Boolean(res.models_refreshing));
        setModelsError(res.models_error ?? null);
        setOllamaBaseUrl(res.ollama_base_url ?? "http://127.0.0.1:11434");
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
    const t = await createThread(undefined, { chatProvider, chatModel });
    setActiveThread(t);
    const selection = threadSelection(t, { provider: chatProvider, model: chatModel });
    setChatProvider(selection.provider);
    setChatModel(selection.model);
    setThreads((prev) => [threadSummary(t), ...prev.filter((x) => x.id !== t.id)]);
    if (activeProjectId) {
      threadProjectMapRef.current[t.id] = activeProjectId;
      persistThreadProjectMap();
    }
    onAfterNavAction();
    scheduleComposerFocus({ force: true });
  }, [activeProjectId, chatModel, chatProvider, onAfterNavAction, persistThreadProjectMap, scheduleComposerFocus, statusOk]);

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
        delete threadProjectMapRef.current[threadId];
        persistThreadProjectMap();
      } catch (e) {
        console.error("Failed to delete thread", e);
        setSystemMessage("Thread delete failed.");
      }
    },
    [persistThreadProjectMap, setSystemMessage, statusOk]
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

  const onFeedScroll = useCallback(() => {
    const el = feedRef.current;
    if (!el) return;
    const remaining = el.scrollHeight - el.scrollTop - el.clientHeight;
    nearBottomRef.current = remaining <= 120;
  }, []);

  const scrollToBottomIfNear = useCallback(() => {
    const el = feedRef.current;
    if (!el) return;
    if (!nearBottomRef.current) return;
    el.scrollTop = el.scrollHeight;
  }, []);

  useEffect(() => {
    scrollToBottomIfNear();
  }, [activeThread?.messages.length, scrollToBottomIfNear]);

  useEffect(() => {
    if (activeView !== "chat") return;
    scheduleComposerFocus();
  }, [activeThread?.id, activeView, scheduleComposerFocus]);

  const stopSending = useCallback(() => {
    const controller = activeSendAbortRef.current;
    if (!controller || controller.signal.aborted) return;
    controller.abort();
  }, []);

  const send = useCallback(async () => {
    const text = draft.trim();
    if (!text || sending) return;

    if (!statusOk) {
      setSystemMessage("Offline - cannot send messages until the API is reachable.");
      return;
    }

    // Prevent obvious model/provider mismatches (most common source of 502s).
    const provider = (chatProvider || "stub").toLowerCase();
    if (provider === "openai" && modelOptions.openai.length > 0 && !modelOptions.openai.includes(chatModel)) {
      setSystemMessage("Selected OpenAI model is not in the discovered list. Pick a valid model from the dropdown.");
      return;
    }
    if (provider === "ollama" && modelOptions.ollama.length > 0 && !modelOptions.ollama.includes(chatModel)) {
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

    let thread = activeThread;
    if (!thread) {
      thread = await createThread(undefined, { chatProvider, chatModel });
      setActiveThread(thread);
      setThreads((prev) => [threadSummary(thread!), ...prev]);
      if (activeProjectId) {
        threadProjectMapRef.current[thread.id] = activeProjectId;
        persistThreadProjectMap();
      }
    }

    const wasEmpty = thread.messages.length === 0;
    const wasDefaultTitle = !thread.title || thread.title === config.threadTitleDefault;

    setDraft("");
    scheduleComposerFocus({ force: true });

    const localUser = { id: createClientId("message"), role: "user" as const, content: text, ts: Date.now() / 1000 };
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
      const reply = await sendChatMessage(
        text,
        t1.id,
        "chat",
        Boolean(unsafeStatus?.unsafe_enabled),
        buildActiveCanvasArtifact(codeCanvas),
        controller.signal
      );
      assistantReplyReceived = true;
      setLastProviderError(null);
      setLastRetrieved(Array.isArray(reply.retrieved) ? reply.retrieved : []);
      setLastAuditTail(Array.isArray(reply.audit_tail) ? reply.audit_tail : []);
      setLastVerificationLevel(typeof reply.verification_level === "string" ? reply.verification_level : null);
      setLastVerification(reply.verification ?? null);
      setLastWebMeta(reply.web ?? null);
      const t3 = await appendThreadMessage(t1.id, { role: "assistant", content: reply.content });
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
      }
    } catch (e) {
      if (isAbortError(e)) {
        setActiveThread((prev) => rollbackOptimisticThread(prev, localUser.id, userMessagePersisted));
        setDraft((current) => restoreDraftAfterStop(text, current));
        setSystemMessage("Response stopped. Edit the composer and send again when you are ready.");
        return;
      }
      const msg = e instanceof Error ? e.message : String(e);
      if (e instanceof ApiError && e.providerError) {
        setLastProviderError(e.providerError);
      }
      setActiveThread((prev) => rollbackOptimisticThread(prev, localUser.id, userMessagePersisted));
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
    draft,
    modelOptions.openai,
    modelOptions.ollama,
    layoutSettings.showCodeCanvas,
    openCodeCanvasFromReply,
    persistThreadProjectMap,
    scheduleComposerFocus,
    sending,
    setSystemMessage,
    statusOk,
  ]);

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
              className={tokens.button}
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
                    >
                      <span className="truncate">{p.name}</span>
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
            <button className={tokens.button} onClick={() => void newChat()} disabled={!statusOk || loadingThreads}>
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

        <Panel className="rounded-[1.4rem] bg-slate-950/54 p-3 text-sm">
          <div className="flex items-center justify-between gap-3">
            <div className={tokens.smallLabel}>Pages</div>
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
            >
              Chat
            </button>
            <button
              className={[
                "w-full rounded-xl border px-3 py-2 text-left text-sm font-medium transition",
                activeView === "settings"
                  ? "border-cyan-400/30 bg-slate-900 text-cyan-50"
                  : "border-slate-800 bg-slate-950/70 text-slate-200 hover:bg-slate-900/80",
              ].join(" ")}
              onClick={() => {
                setActiveView("settings");
                onAfterNavAction();
              }}
            >
              Settings
            </button>
            <button
              className={[
                "w-full rounded-xl border px-3 py-2 text-left text-sm font-medium transition",
                activeView === "customization"
                  ? "border-cyan-400/30 bg-slate-900 text-cyan-50"
                  : "border-slate-800 bg-slate-950/70 text-slate-200 hover:bg-slate-900/80",
              ].join(" ")}
              onClick={() => {
                setActiveView("customization");
                onAfterNavAction();
              }}
            >
              Customization
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
        <Panel className="flex h-full min-h-0 flex-col gap-3 p-3">
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
      <Panel className="flex min-h-0 flex-col gap-3 p-3">
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
            : layoutSettings.showSidebar && showInspector
              ? "grid-cols-[300px_1fr_360px]"
              : layoutSettings.showSidebar
                ? "grid-cols-[300px_1fr]"
                : showInspector
                  ? "grid-cols-[1fr_360px]"
                  : "grid-cols-1",
        ].join(" ")}
      >
        {!isMobile && layoutSettings.showSidebar ? renderSidebar("desktop") : null}

        <Panel className={theme.shell.mainPanel}>
          {layoutSettings.showHeader ? (
          <div className={theme.shell.topBar}>
            <div className="flex min-w-0 items-start gap-2">
              {isMobile && layoutSettings.showSidebar ? (
                <button
                  className={[tokens.button, "!px-2 !py-1 !text-xs"].join(" ")}
                  onClick={() => setNavOpen(true)}
                  aria-label="Open navigation"
                  title="Open navigation"
                >
                  Menu
                </button>
              ) : null}
              <div className="min-w-0">
                <div className="flex items-center gap-3">
                  <BrandBadge compact />
                  <div className="min-w-0">
                    <div className={theme.copy.title}>
                      {activeView === "settings"
                        ? "Settings"
                        : activeView === "customization"
                          ? "Customization"
                        : activeThread
                          ? activeThread.title || config.threadTitleDefault
                          : "Chat"}
                      {activeProject ? <span className="text-xs font-normal text-slate-500">{` - ${activeProject.name}`}</span> : null}
                    </div>
                    <div className={theme.copy.muted}>
                      {activeView === "settings"
                        ? "Refine local settings and model behavior."
                        : activeView === "customization"
                          ? "Shape identity and appearance without touching model configuration."
                          : `Direct channel into ${assistantDisplayName}.`}
                    </div>
                  </div>
                </div>
              </div>
            </div>
            <div className="agentx-topbar__controls">
              {isMobile ? <StatusPill ok={statusOk} label="API" /> : null}
              {activeView === "chat" ? (
                <label className="agentx-topbar__field text-xs text-slate-400">
                  <span>Model:</span>
                  <AgentXDropdown
                    value={modelOptions.selectedKey}
                    options={chatModelDropdownOptions}
                    disabled={!statusOk}
                    placeholder="Select model"
                    className="max-w-full"
                    fitToOptions
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
          ) : null}

          {activeView === "settings" ? (
            <div className="mt-3 min-h-0 flex-1">
              <SettingsPage
                statusOk={statusOk}
                status={{
                  chat_provider: chatProvider,
                  chat_model: chatModel,
                  available_chat_models: availableModels,
                  ollama_base_url: ollamaBaseUrl,
                  models_error: modelsError,
                  models_refreshing: modelsRefreshing,
                }}
                settings={appSettings}
                onSettingsSaved={handleSettingsSaved}
                onSystemMessage={setSystemMessage}
              />
            </div>
          ) : activeView === "customization" ? (
            <div className="mt-3 min-h-0 flex-1">
              <CustomizationPage
                statusOk={statusOk}
                settings={appSettings}
                layoutGuards={layoutGuards}
                onSettingsChange={applySettings}
                onSettingsSaved={handleSettingsSaved}
                onSystemMessage={setSystemMessage}
              />
            </div>
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
                              startsGroup={!prev || prev.role !== m.role}
                              endsGroup={!next || next.role !== m.role}
                              assistantLabel={assistantDisplayName}
                              userLabel={userDisplayName}
                              displayContent={companion ? companion.summary : undefined}
                              codeCanvasMeta={companion ? { language: companion.language, lineCount: companion.lineCount, title: companion.title } : null}
                              onOpenCodeCanvas={companion && layoutSettings.showCodeCanvas ? () => reopenCodeCanvas(m.id) : null}
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
                </div>

                <div className={theme.shell.composer}>
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

        {showInspector ? (
          <InspectorPanel
            statusOk={statusOk}
            statusName={statusName}
            chatProvider={chatProvider}
            chatModel={chatModel}
            providerEndpointStatus={providerEndpointStatus}
            providerModelStatus={providerModelStatus}
            lastProviderError={lastProviderError}
            retrieved={lastRetrieved}
            auditTail={lastAuditTail}
            verificationLevel={lastVerificationLevel}
            verification={lastVerification}
            webMeta={lastWebMeta}
            activeThreadId={activeThread?.id ?? null}
            unsafeStatus={unsafeStatus}
            onUnsafeStatus={setUnsafeStatus}
          />
        ) : null}
      </div>
    </div>
  );
}
