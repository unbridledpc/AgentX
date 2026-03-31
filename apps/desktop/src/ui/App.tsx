import React, { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { Panel } from "./components/Panel";
import { ScrollArea } from "./components/ScrollArea";
import { StatusPill } from "./components/StatusPill";
import {
  API_BASE,
  appendThreadMessage,
  createThread,
  getStatus,
  getThread,
  listThreads,
  deleteThread,
  sendChatMessage,
  StatusResponse,
  RetrievedChunk,
  AuditEntry,
  Thread,
  ThreadSummary,
  updateThreadTitle,
} from "../api/client";
import { ChatPage } from "./pages/ChatPage";
import { InspectorPanel } from "./components/InspectorPanel";
import { ThreadList } from "./components/ThreadList";
import { routeRegistry, defaultRouteId, RouteDefinition } from "./navRoutes";
import {
  getInspectorWindowEnabled,
  getShowInspectorSidebar,
  getChatModel,
  getChatProvider,
  subscribeInspectorWindow,
  subscribeShowInspectorSidebar,
  subscribeChatModel,
  subscribeChatProvider,
  setChatSelection,
} from "./prefs";
import { closeInspectorWindow, openInspectorWindow } from "./inspectorWindow";
import { THREAD_TITLE_DEFAULT, THREAD_TITLE_MAX, THREAD_TITLE_WORD_LIMIT } from "../config";

type RouteButtonProps = {
  active: boolean;
  onClick: () => void;
  label: string;
  description: string;
};

const generateLocalId = () =>
  typeof crypto !== "undefined" && crypto.randomUUID ? crypto.randomUUID() : `local-${Date.now()}`;

const generateAutoTitle = (input: string) => {
  const sanitized = input.replace(/[^\w\s]/g, " ");
  const normalized = sanitized.replace(/\s+/g, " ").trim();
  const words = normalized.split(" ").filter(Boolean).slice(0, THREAD_TITLE_WORD_LIMIT);
  if (words.length === 0) return THREAD_TITLE_DEFAULT;
  let candidate = words.join(" ");
  if (candidate.length > THREAD_TITLE_MAX) {
    candidate = `${candidate.slice(0, Math.max(1, THREAD_TITLE_MAX - 3))}...`;
  }
  return candidate;
};

export function App() {
  const [activeRouteId, setActiveRouteId] = useState(defaultRouteId);
  const [threads, setThreads] = useState<ThreadSummary[]>([]);
  const [activeThread, setActiveThread] = useState<Thread | null>(null);
  const [threadLoading, setThreadLoading] = useState(false);
  const [sendingMessage, setSendingMessage] = useState(false);
  const [navFilter, setNavFilter] = useState("");
  const [showInspector, setShowInspector] = useState(getShowInspectorSidebar());
  const [inspectorWindowEnabled, setInspectorWindowEnabledState] = useState(getInspectorWindowEnabled());
  const [chatProvider, setChatProviderState] = useState(getChatProvider());
  const [chatModel, setChatModelState] = useState(getChatModel());
  const [status, setStatus] = useState<StatusResponse | null>(null);
  const [lastCheck, setLastCheck] = useState<number | null>(null);
  const [lastError, setLastError] = useState<string | null>(null);
  const [lastRetrieved, setLastRetrieved] = useState<RetrievedChunk[]>([]);
  const [lastAuditTail, setLastAuditTail] = useState<AuditEntry[]>([]);
  const [lastVerificationLevel, setLastVerificationLevel] = useState<string | null>(null);
  const [lastVerification, setLastVerification] = useState<{ verdict: string; confidence: number; contradictions: string[] } | null>(null);
  const [lastWebMeta, setLastWebMeta] = useState<{ providers_used?: string[]; providers_failed?: { provider?: string; name?: string; error?: string }[]; fetch_blocked?: { url: string; reason: string }[] } | null>(null);

  const isConnected = status?.ok ?? false;
  const statusLabel = status?.name ?? (isConnected ? "Connected" : "Offline");
  const defaultThreadLoaded = useRef(false);

  const activeRoute: RouteDefinition = useMemo(() => {
    return routeRegistry.find((route) => route.id === activeRouteId) ?? routeRegistry[0];
  }, [activeRouteId]);

  const syncThreadSummary = useCallback((thread: Thread) => {
    setThreads((prev) => {
      const filtered = prev.filter((entry) => entry.id !== thread.id);
      return [{ id: thread.id, title: thread.title, updated_at: thread.updated_at }, ...filtered];
    });
  }, []);

  const setThreadTitleOptimistic = useCallback((threadId: string, title: string, updatedAt?: number) => {
    const ts = updatedAt ?? Date.now() / 1000;
    setThreads((prev) => {
      const filtered = prev.filter((entry) => entry.id !== threadId);
      return [{ id: threadId, title, updated_at: ts }, ...filtered];
    });
    setActiveThread((prev) => (prev?.id === threadId ? { ...prev, title, updated_at: ts } : prev));
  }, []);

  // NOTE: This must be initialized before any callbacks that capture it in deps.
  // Otherwise Vite/ESBuild can crash with a temporal-dead-zone error:
  // "Cannot access 'addSystemMessage' before initialization".
  const addSystemMessage = useCallback((content: string) => {
    setActiveThread((prev) => {
      if (!prev) return prev;
      const systemMessage = {
        id: `system-${Date.now()}`,
        role: "system" as const,
        content,
        ts: Date.now() / 1000,
      };
      return {
        ...prev,
        updated_at: Date.now() / 1000,
        messages: [...prev.messages, systemMessage],
      };
    });
  }, []);

  const handleThreadSelect = useCallback(
    async (threadId: string) => {
      setThreadLoading(true);
      try {
        const thread = await getThread(threadId);
        setActiveThread(thread);
        syncThreadSummary(thread);
      } catch (error) {
        console.error("Failed to load thread", error);
      } finally {
        setThreadLoading(false);
      }
    },
    [syncThreadSummary]
  );

  const handleThreadDelete = useCallback(
    async (threadId: string) => {
      if (!isConnected) {
        addSystemMessage("Offline - cannot delete threads until connection returns.");
        return;
      }
      const currentActive = activeThread?.id === threadId;
      try {
        await deleteThread(threadId);
        setThreads((prev) => prev.filter((t) => t.id !== threadId));
        if (currentActive) {
          setActiveThread(null);
        }
      } catch (error) {
        console.error("Failed to delete thread", error);
        addSystemMessage("Thread delete failed.");
      }
    },
    [activeThread, addSystemMessage, isConnected]
  );

  const handleNewThread = useCallback(async () => {
    if (!isConnected) return null;
    setThreadLoading(true);
    try {
      const thread = await createThread();
      setActiveThread(thread);
      syncThreadSummary(thread);
      defaultThreadLoaded.current = true;
      return thread;
    } catch (error) {
      console.error("Failed to create thread", error);
      return null;
    } finally {
      setThreadLoading(false);
    }
  }, [isConnected, syncThreadSummary]);

  const handleThreadRename = useCallback(
    async (threadId: string, title: string) => {
      const trimmedTitle = title.trim();
      if (!trimmedTitle) return;

      const beforeSummary = threads.find((entry) => entry.id === threadId);
      const beforeTitle =
        (activeThread?.id === threadId ? activeThread.title : beforeSummary?.title) ?? THREAD_TITLE_DEFAULT;
      const beforeUpdatedAt =
        (activeThread?.id === threadId ? activeThread.updated_at : beforeSummary?.updated_at) ?? Date.now() / 1000;

      if (!isConnected) {
        addSystemMessage("Offline - cannot rename threads until connection returns.");
        return;
      }

      setThreadTitleOptimistic(threadId, trimmedTitle);

      try {
        const updated = await updateThreadTitle(threadId, trimmedTitle);
        setActiveThread((prev) => (prev?.id === threadId ? updated : prev));
        syncThreadSummary(updated);
      } catch (error) {
        console.error("Title update failed", error);
        setThreadTitleOptimistic(threadId, beforeTitle, beforeUpdatedAt);
        addSystemMessage("Thread title update failed.");
      }
    },
    [activeThread, addSystemMessage, isConnected, setThreadTitleOptimistic, syncThreadSummary, threads]
  );

  const handleSendMessage = useCallback(
    async (text: string) => {
      const trimmedText = text.trim();
      if (sendingMessage || !trimmedText) return;
      let thread = activeThread;
      if (!thread) {
        thread = await handleNewThread();
      }
      if (!thread) {
        addSystemMessage("Offline - threads are unavailable until the backend is reachable.");
        return;
      }

      const shouldAutoTitle =
        (thread.title === THREAD_TITLE_DEFAULT || !thread.title) && thread.messages.length === 0;
      const autoTitle = shouldAutoTitle ? generateAutoTitle(trimmedText) : "";

      if (shouldAutoTitle && autoTitle) {
        const beforeTitle = thread.title;
        const beforeUpdatedAt = thread.updated_at;

        setThreadTitleOptimistic(thread.id, autoTitle);
        if (isConnected) {
          try {
            const updated = await updateThreadTitle(thread.id, autoTitle);
            setActiveThread(updated);
            syncThreadSummary(updated);
            thread = updated;
          } catch (error) {
            console.error("Failed to auto-title thread", error);
            setThreadTitleOptimistic(thread.id, beforeTitle, beforeUpdatedAt);
            addSystemMessage("Auto-titling failed.");
          }
        }
      }

      const localMessage = {
        id: generateLocalId(),
        role: "user" as const,
        content: trimmedText,
        ts: Date.now() / 1000,
      };
      setActiveThread((prev) => (prev ? { ...prev, messages: [...prev.messages, localMessage] } : prev));

      if (!isConnected) {
        addSystemMessage("Offline - messages cannot be persisted and assistant response is unavailable.");
        return;
      }

      setSendingMessage(true);
      try {
        const updatedThread = await appendThreadMessage(thread.id, { role: "user", content: trimmedText });
        setActiveThread(updatedThread);
        syncThreadSummary(updatedThread);

        const chatResponse = await sendChatMessage(trimmedText, updatedThread.id);
        setLastRetrieved(Array.isArray(chatResponse.retrieved) ? chatResponse.retrieved : []);
        setLastAuditTail(Array.isArray(chatResponse.audit_tail) ? chatResponse.audit_tail : []);
        setLastVerificationLevel(typeof chatResponse.verification_level === "string" ? chatResponse.verification_level : null);
        setLastVerification(chatResponse.verification ?? null);
        setLastWebMeta(chatResponse.web ?? null);
        const assistantThread = await appendThreadMessage(updatedThread.id, {
          role: "assistant",
          content: chatResponse.content,
        });
        setActiveThread(assistantThread);
        syncThreadSummary(assistantThread);
      } catch (error) {
        const message =
          error instanceof Error ? error.message : "Failed to persist message. Please try again later.";
        addSystemMessage(`Persistence error: ${message}`);
      } finally {
        setSendingMessage(false);
      }
    },
    [
      activeThread,
      addSystemMessage,
      handleNewThread,
      isConnected,
      sendingMessage,
      setThreadTitleOptimistic,
      syncThreadSummary,
    ]
  );

  useEffect(() => {
    const unsubSidebar = subscribeShowInspectorSidebar((value) => {
      setShowInspector(value);
    });
    const unsubWindow = subscribeInspectorWindow((value) => {
      setInspectorWindowEnabledState(value);
    });
    const unsubProvider = subscribeChatProvider((value) => {
      setChatProviderState(value);
    });
    const unsubModel = subscribeChatModel((value) => {
      setChatModelState(value);
    });
    return () => {
      unsubSidebar();
      unsubWindow();
      unsubProvider();
      unsubModel();
    };
  }, []);

  useEffect(() => {
    const controllerHolder = { current: null as AbortController | null };
    const refreshStatus = async () => {
      controllerHolder.current?.abort();
      const controller = new AbortController();
      controllerHolder.current = controller;
      try {
        const response = await getStatus(controller.signal);
        setStatus(response);
        setLastError(null);
      } catch (error) {
        if (controller.signal.aborted) {
          return;
        }
        setStatus(null);
        setLastError(error instanceof Error ? error.message : String(error));
      } finally {
        if (!controller.signal.aborted) {
          setLastCheck(Date.now());
        }
      }
    };
    refreshStatus();
    const intervalId = setInterval(refreshStatus, 3000);
    return () => {
      clearInterval(intervalId);
      controllerHolder.current?.abort();
    };
  }, []);

  const refreshModels = useCallback(async () => {
    try {
      const response = await getStatus(undefined, true);
      setStatus(response);
      setLastError(null);
      setLastCheck(Date.now());
    } catch (error) {
      setLastError(error instanceof Error ? error.message : String(error));
      setLastCheck(Date.now());
    }
  }, []);

  useEffect(() => {
    if (typeof window === "undefined") return;
    const inspectorWindowMode = window.location.hash === "#inspector";
    if (inspectorWindowMode) return;
    if (inspectorWindowEnabled) {
      openInspectorWindow().catch(() => {});
    } else {
      closeInspectorWindow().catch(() => {});
    }
  }, [inspectorWindowEnabled]);

  useEffect(() => {
    if (!isConnected) return;
    let cancelled = false;
    (async () => {
      try {
        const list = await listThreads();
        if (cancelled) return;
        setThreads(list);
        if (!defaultThreadLoaded.current && list.length > 0) {
          defaultThreadLoaded.current = true;
          await handleThreadSelect(list[0].id);
        }
      } catch (error) {
        console.error("Failed to load threads", error);
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [isConnected, handleThreadSelect]);

  const filteredRoutes = useMemo(() => {
    const term = navFilter.trim().toLowerCase();
    if (!term) return routeRegistry;
    return routeRegistry.filter((route) => route.label.toLowerCase().includes(term));
  }, [navFilter]);

  const modelOptions = useMemo(() => {
    const available = status?.available_chat_models ?? {};
    const openai = Array.isArray(available.openai) ? available.openai : [];
    const ollama = Array.isArray(available.ollama) ? available.ollama : [];
    const selectedKey = `${chatProvider}:${chatModel}`;
    const keys = new Set<string>();
    for (const id of openai) keys.add(`openai:${id}`);
    for (const id of ollama) keys.add(`ollama:${id}`);
    return {
      openai,
      ollama,
      selectedKey,
      hasSelected: keys.has(selectedKey),
      refreshing: Boolean(status?.models_refreshing),
      error: status?.models_error ?? null,
    };
  }, [chatModel, chatProvider, status]);

  const groupedRoutes = useMemo(() => {
    const map = new Map<string, RouteDefinition[]>();
    for (const route of filteredRoutes) {
      const section = map.get(route.section) ?? [];
      section.push(route);
      map.set(route.section, section);
    }
    return map;
  }, [filteredRoutes]);

  const page = useMemo(() => {
    if (activeRoute.id === "chat") {
      return (
        <ChatPage
          messages={activeThread?.messages ?? []}
          onSend={handleSendMessage}
          sending={sendingMessage}
          verification={lastVerification}
        />
      );
    }
    const Component = activeRoute.component;
    return <Component />;
  }, [activeRoute, activeThread, handleSendMessage, lastVerification, sendingMessage]);

  const isInspectorWindowMode =
    typeof window !== "undefined" && window.location.hash === "#inspector";
  const shouldRenderInspectorSidebar = showInspector && !inspectorWindowEnabled;
  const gridColumnsClass = shouldRenderInspectorSidebar
    ? "grid-cols-[260px_1fr_320px]"
    : "grid-cols-[260px_1fr]";

  if (isInspectorWindowMode) {
    return (
      <div className="h-full w-full bg-slate-50">
        <div className="min-h-screen min-w-0 p-4">
          <InspectorPanel
            status={status}
            lastCheck={lastCheck}
            lastError={lastError}
            apiBase={API_BASE}
            retrieved={lastRetrieved}
            auditTail={lastAuditTail}
            verificationLevel={lastVerificationLevel}
            verification={lastVerification}
            webMeta={lastWebMeta}
            activeThreadId={activeThread?.id ?? null}
          />
        </div>
      </div>
    );
  }

  const handleThreadClick = useCallback(
    (threadId: string) => {
      handleThreadSelect(threadId);
    },
    [handleThreadSelect]
  );

  return (
    <div className="h-full w-full bg-slate-50">
      <div className={["grid min-h-screen min-w-0 gap-3 p-4", gridColumnsClass].join(" ")}>
        <Panel className="flex min-h-0 flex-col gap-3 p-3">
          <div className="flex items-center justify-between rounded-xl border border-slate-200 p-2 text-sm font-semibold">
            <span>Sol</span>
            <StatusPill ok={isConnected} label={statusLabel} />
          </div>
          <Panel className="rounded-2xl border border-slate-200 p-3">
            <input
              value={navFilter}
              onChange={(event) => setNavFilter(event.target.value)}
              placeholder="Search routes..."
              className="w-full rounded-xl border border-neutral-200 bg-neutral-50 px-3 py-2 text-sm outline-none focus:border-slate-400"
            />
          </Panel>
          <ScrollArea className="min-h-0 flex-1 space-y-3">
            {filteredRoutes.length === 0 && (
              <div className="text-xs text-slate-500">No routes match that query.</div>
            )}
            {Array.from(groupedRoutes.entries()).map(([section, routes]) => (
              <section key={section} className="space-y-2">
                <div className="text-xs font-semibold uppercase tracking-wide text-slate-500">{section}</div>
                <div className="flex flex-col gap-2">
                  {routes.map((route) => (
                    <RouteButton
                      key={route.id}
                      active={route.id === activeRoute.id}
                      onClick={() => setActiveRouteId(route.id)}
                      label={route.label}
                      description={route.description}
                    />
                  ))}
                </div>
              </section>
            ))}
            <div className="rounded-2xl border border-slate-200 bg-white/60 p-3 text-sm shadow-sm">
              <div className="flex items-center justify-between gap-3">
                <div className="text-xs font-semibold uppercase tracking-wide text-slate-500">Threads</div>
                <button
                  className="rounded-full border border-slate-300 bg-slate-50 px-3 py-1 text-xs font-semibold text-slate-700 disabled:cursor-not-allowed disabled:opacity-50"
                  onClick={() => {
                    void handleNewThread();
                  }}
                  disabled={!isConnected || threadLoading}
                >
                  New Chat
                </button>
              </div>
              <div className="mt-3 max-h-72 overflow-y-auto pr-1">
                <ThreadList
                  threads={threads}
                  activeId={activeThread?.id}
                  onSelect={handleThreadClick}
                  onRename={handleThreadRename}
                  onDelete={handleThreadDelete}
                  offline={!isConnected}
                />
              </div>
            </div>
            <div className="text-xs text-slate-500">Backend status polling only.</div>
          </ScrollArea>
        </Panel>

        <div className="flex min-h-0 min-w-0 flex-col gap-3">
          <Panel className="flex items-center justify-between gap-3 p-3">
            <div>
              <div className="text-sm font-semibold">
                {activeRoute.label}
                {activeRoute.id === "chat" && activeThread ? ` - ${activeThread.title}` : ""}
              </div>
              <div className="text-xs text-slate-500">{activeRoute.description}</div>
            </div>
            {activeRoute.id === "chat" ? (
              <label className="flex items-center gap-2 text-xs text-slate-500">
                <span>Model:</span>
                <select
                  className="rounded-xl border border-neutral-200 bg-white px-3 py-2 text-xs outline-none focus:border-slate-400 disabled:opacity-50"
                  disabled={!isConnected}
                  value={modelOptions.selectedKey}
                  onChange={(event) => {
                    const [provider, ...rest] = event.target.value.split(":");
                    const model = rest.join(":");
                    setChatSelection(provider, model);
                  }}
                  title="Select chat model (OpenAI or Ollama)"
                >
                  {!modelOptions.hasSelected && (
                    <option value={modelOptions.selectedKey}>{modelOptions.selectedKey}</option>
                  )}
                  <optgroup label="OpenAI">
                    {modelOptions.openai.length === 0 ? (
                      <option value="openai:stub">
                        {modelOptions.refreshing ? "Loading..." : "No OpenAI models"}
                      </option>
                    ) : (
                      modelOptions.openai.map((m) => (
                        <option key={`openai:${m}`} value={`openai:${m}`}>
                          {m}
                        </option>
                      ))
                    )}
                  </optgroup>
                  <optgroup label="Ollama">
                    {modelOptions.ollama.length === 0 ? (
                      <option value="ollama:stub">
                        {modelOptions.refreshing ? "Loading..." : "No Ollama models"}
                      </option>
                    ) : (
                      modelOptions.ollama.map((m) => (
                        <option key={`ollama:${m}`} value={`ollama:${m}`}>
                          {m}
                        </option>
                      ))
                    )}
                  </optgroup>
                  <optgroup label="Stub">
                    <option value="stub:stub">stub</option>
                  </optgroup>
                </select>
                <button
                  type="button"
                  className="rounded-xl border border-neutral-200 bg-white px-3 py-2 text-xs outline-none hover:bg-slate-50 disabled:opacity-50"
                  disabled={!isConnected}
                  onClick={() => {
                    void refreshModels();
                  }}
                  title="Refresh model list"
                >
                  Refresh
                </button>
              </label>
            ) : (
              <div className="text-xs text-slate-500">Model: {status?.chat_model ?? "stub"}</div>
            )}
          </Panel>
          <Panel className="min-h-0 min-w-0 flex-1">
            <ScrollArea className="min-h-0">{page}</ScrollArea>
          </Panel>
        </div>

        {shouldRenderInspectorSidebar && (
        <InspectorPanel
          status={status}
          lastCheck={lastCheck}
          lastError={lastError}
          apiBase={API_BASE}
          retrieved={lastRetrieved}
          auditTail={lastAuditTail}
          verificationLevel={lastVerificationLevel}
          verification={lastVerification}
          webMeta={lastWebMeta}
          activeThreadId={activeThread?.id ?? null}
        />
      )}
      </div>
    </div>
  );
}

function RouteButton(props: RouteButtonProps) {
  return (
    <button
      onClick={props.onClick}
      className={`text-left rounded-xl border px-3 py-2 transition ${
        props.active
          ? "border-slate-900 bg-slate-900 text-white"
          : "border-slate-200 bg-white text-slate-900 hover:bg-slate-50"
      }`}
    >
      <div className="flex flex-col gap-0.5">
        <span className="text-sm font-medium">{props.label}</span>
        <span className="text-[10px] uppercase tracking-wide text-slate-500">
          {props.description}
        </span>
      </div>
    </button>
  );
}
