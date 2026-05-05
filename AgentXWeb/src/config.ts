type RuntimeAgentXWebConfig = {
  apiBase?: string;
  showInspector?: boolean;
  updateFeed?: {
    enabled?: boolean;
    repo?: string;
    branch?: string;
    currentSha?: string;
    currentVersion?: string;
  };
};

function runtimeConfig(): RuntimeAgentXWebConfig {
  const g = globalThis as typeof globalThis & {
    AGENTX_WEB_CONFIG?: RuntimeAgentXWebConfig;
    __AGENTXWEB_CONFIG__?: RuntimeAgentXWebConfig;
    AGENTX_CONFIG?: { apiBaseUrl?: string };
    location?: Location;
  };

  return g.AGENTX_WEB_CONFIG ?? g.__AGENTXWEB_CONFIG__ ?? {};
}

function defaultApiBase(): string {
  const g = globalThis as typeof globalThis & { location?: Location };
  const origin = g.location?.origin ?? "";

  if (origin) {
    return origin.replace(":5173", ":8000").replace(":5174", ":8000");
  }

  return "http://127.0.0.1:8000";
}

export const config = {
  updateFeed: (() => {
    const runtime = runtimeConfig().updateFeed;
    const repo = String(runtime?.repo ?? (import.meta as any).env?.VITE_AGENTX_UPDATE_REPO ?? "unbridledpc/AgentX").trim();
    const branch = String(runtime?.branch ?? (import.meta as any).env?.VITE_AGENTX_UPDATE_BRANCH ?? "main").trim();
    const currentSha = String(runtime?.currentSha ?? (import.meta as any).env?.VITE_AGENTX_BUILD_SHA ?? "").trim();
    const currentVersion = String(runtime?.currentVersion ?? (import.meta as any).env?.VITE_AGENTX_APP_VERSION ?? "0.3.0-v12").trim();
    const enabledRaw = runtime?.enabled ?? (import.meta as any).env?.VITE_AGENTX_UPDATE_CHECK_ENABLED ?? "true";
    const enabled = typeof enabledRaw === "boolean" ? enabledRaw : String(enabledRaw).toLowerCase() !== "false";
    return { enabled, repo, branch, currentSha, currentVersion };
  })(),

  apiBase: (() => {
    const runtime = runtimeConfig();
    const runtimeTrimmed = String(runtime.apiBase ?? "").trim();
    if (runtimeTrimmed.length > 0) return runtimeTrimmed;

    const legacy = (globalThis as any).AGENTX_CONFIG?.apiBaseUrl as string | undefined;
    const legacyTrimmed = String(legacy ?? "").trim();
    if (legacyTrimmed.length > 0) return legacyTrimmed;

    const raw = (import.meta as any).env?.VITE_AGENTX_API_BASE as string | undefined;
    const trimmed = String(raw ?? "").trim();
    if (trimmed.length > 0) return trimmed;

    return defaultApiBase();
  })(),

  showInspector: (() => {
    const runtime = runtimeConfig();
    if (typeof runtime.showInspector === "boolean") return runtime.showInspector;

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
