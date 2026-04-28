export const config = {
  updateFeed: (() => {
    const runtime = (globalThis as any).__AGENTXWEB_CONFIG__?.updateFeed as Record<string, unknown> | undefined;
    const repo = String(runtime?.repo ?? (import.meta as any).env?.VITE_AGENTX_UPDATE_REPO ?? "unbridledpc/AgentX").trim();
    const branch = String(runtime?.branch ?? (import.meta as any).env?.VITE_AGENTX_UPDATE_BRANCH ?? "main").trim();
    const currentSha = String(runtime?.currentSha ?? (import.meta as any).env?.VITE_AGENTX_BUILD_SHA ?? "").trim();
    const currentVersion = String(runtime?.currentVersion ?? (import.meta as any).env?.VITE_AGENTX_APP_VERSION ?? "local").trim();
    const enabledRaw = runtime?.enabled ?? (import.meta as any).env?.VITE_AGENTX_UPDATE_CHECK_ENABLED ?? "true";
    const enabled = typeof enabledRaw === "boolean" ? enabledRaw : String(enabledRaw).toLowerCase() !== "false";
    return { enabled, repo, branch, currentSha, currentVersion };
  })(),
  apiBase: (() => {
    const runtime = (globalThis as any).__AGENTXWEB_CONFIG__?.apiBase as string | undefined;
    const runtimeTrimmed = (runtime ?? "").trim();
    if (runtimeTrimmed.length > 0) return runtimeTrimmed;

    const legacy = (globalThis as any).AGENTX_CONFIG?.apiBaseUrl as string | undefined;
    const legacyTrimmed = (legacy ?? "").trim();
    if (legacyTrimmed.length > 0) return legacyTrimmed;

    const raw = (import.meta as any).env?.VITE_AGENTX_API_BASE as string | undefined;
    const trimmed = (raw ?? "").trim();
    if (trimmed.length > 0) return trimmed;

    return "http://127.0.0.1:8420";
  })(),
  showInspector: (() => {
    const runtime = (globalThis as any).__AGENTXWEB_CONFIG__?.showInspector as boolean | undefined;
    if (typeof runtime === "boolean") return runtime;

    const hostname = (globalThis as any)?.location?.hostname as string | undefined;
    const host = (hostname ?? "").trim().toLowerCase();
    return host === "localhost" || host === "127.0.0.1";
  })(),
  threadTitleDefault: "New thread",
  threadTitleMax: 64,
  threadTitleWordLimit: 8,
  projectStorageKey: "agentxweb.projects.v1",
  threadProjectMapKey: "agentxweb.threadProjects.v1",
  codeCanvasStateKey: "agentxweb.codeCanvas.v1",
} as const;
