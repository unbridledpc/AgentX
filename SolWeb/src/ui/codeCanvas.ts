import { config } from "../config";

export type CodeCanvasLanguage =
  | "typescript"
  | "javascript"
  | "python"
  | "html"
  | "css"
  | "json"
  | "shell"
  | "csharp"
  | "rust"
  | "text";

export type CodeCanvasViewMode = "docked" | "fullscreen";

export type CodeCanvasCompanion = {
  sourceMessageId: string;
  language: CodeCanvasLanguage;
  summary: string;
  lineCount: number;
  title: string;
};

export type CodeCanvasState = {
  isOpen: boolean;
  content: string;
  language: CodeCanvasLanguage;
  sourceMessageId: string | null;
  title: string;
  isDirty: boolean;
  viewMode: CodeCanvasViewMode;
  companions: Record<string, CodeCanvasCompanion>;
  sources: Record<string, { content: string; language: CodeCanvasLanguage; title: string }>;
};

export type CodeCanvasDetectionInput = {
  prompt: string;
  content: string;
  messageId: string;
  threadTitle?: string | null;
};

export type CodeCanvasDetectionResult = {
  shouldOpen: boolean;
  code: string;
  language: CodeCanvasLanguage;
  title: string;
  companion: CodeCanvasCompanion;
};

type PersistedCodeCanvasState = {
  savedAt: number;
  expiresAt: number;
  state: CodeCanvasState;
};

const DEFAULT_STATE: CodeCanvasState = {
  isOpen: false,
  content: "",
  language: "text",
  sourceMessageId: null,
  title: "Code Canvas",
  isDirty: false,
  viewMode: "docked",
  companions: {},
  sources: {},
};

const CODE_CANVAS_TTL_MS = 7 * 24 * 60 * 60 * 1000;
const MAX_CANVAS_CONTENT_CHARS = 120_000;
const MAX_CANVAS_STORED_BYTES = 200_000;

const languagePatterns: Array<{ language: CodeCanvasLanguage; patterns: RegExp[] }> = [
  { language: "typescript", patterns: [/\btypescript\b/i, /\binterface\s+\w+/, /\btype\s+\w+\s*=/, /:\s*(string|number|boolean|React\.)/, /import\s+type\s+/] },
  { language: "javascript", patterns: [/\bjavascript\b/i, /\bconst\s+\w+\s*=/, /\bexport\s+default\b/, /=>\s*{/, /function\s+\w+\s*\(/] },
  { language: "python", patterns: [/\bpython\b/i, /^\s*def\s+\w+\(/m, /^\s*class\s+\w+/m, /^\s*import\s+\w+/m, /if __name__ == ["']__main__["']:/] },
  { language: "html", patterns: [/\bhtml\b/i, /<!DOCTYPE html>/i, /<html[\s>]/i, /<div[\s>]/i, /<script[\s>]/i] },
  { language: "css", patterns: [/\bcss\b/i, /[.#][\w-]+\s*\{/, /:\s*[\w#().,% -]+;/, /@media\s*\(/] },
  { language: "json", patterns: [/\bjson\b/i, /^\s*\{[\s\S]*\}\s*$/m, /"\w+"\s*:\s*["{\[]/] },
  { language: "shell", patterns: [/\bbash\b/i, /\bshell\b/i, /^\s*#!/m, /^\s*(sudo|npm|pnpm|yarn|git|cd|ls)\b/m] },
  { language: "csharp", patterns: [/\bc#\b/i, /\bcsharp\b/i, /\bnamespace\s+\w+/, /\busing\s+System\b/, /\bpublic\s+class\s+\w+/] },
  { language: "rust", patterns: [/\brust\b/i, /\bfn\s+\w+\s*\(/, /\blet\s+mut\s+\w+/, /\bimpl\s+\w+/, /\bpub\s+struct\s+\w+/] },
];

function detectLanguageFromText(text: string): CodeCanvasLanguage {
  const trimmed = text.trim();
  for (const { language, patterns } of languagePatterns) {
    if (patterns.some((pattern) => pattern.test(trimmed))) return language;
  }
  return "text";
}

function normalizeFenceLanguage(value: string): CodeCanvasLanguage {
  const normalized = value.trim().toLowerCase();
  if (normalized === "ts" || normalized === "tsx" || normalized === "typescript") return "typescript";
  if (normalized === "js" || normalized === "jsx" || normalized === "javascript") return "javascript";
  if (normalized === "py" || normalized === "python") return "python";
  if (normalized === "html" || normalized === "xml") return "html";
  if (normalized === "css" || normalized === "scss") return "css";
  if (normalized === "json") return "json";
  if (normalized === "sh" || normalized === "bash" || normalized === "shell" || normalized === "zsh") return "shell";
  if (normalized === "cs" || normalized === "csharp") return "csharp";
  if (normalized === "rs" || normalized === "rust") return "rust";
  return detectLanguageFromText(normalized);
}

function extractLargestFence(content: string): { language: CodeCanvasLanguage; code: string } | null {
  const regex = /```([\w+-]*)\n([\s\S]*?)```/g;
  let best: { language: CodeCanvasLanguage; code: string } | null = null;
  for (const match of content.matchAll(regex)) {
    const code = (match[2] || "").trim();
    if (!code) continue;
    if (!best || code.length > best.code.length) {
      best = {
        language: normalizeFenceLanguage(match[1] || ""),
        code,
      };
    }
  }
  return best;
}

function looksLikePromptForCode(prompt: string): boolean {
  return /\b(write|build|create|implement|generate|make|fix|refactor|component|script|function|class|endpoint|query|regex|snippet|code)\b/i.test(prompt);
}

function isCodeLikeLine(line: string): boolean {
  const trimmed = line.trim();
  if (!trimmed) return false;
  return /[{}();=\[\]<>]/.test(trimmed) ||
    /^\s*(import|export|const|let|var|function|class|def|return|if|for|while|try|catch|#!\/).*/.test(trimmed) ||
    /^\s*[.#][\w-]+\s*\{/.test(trimmed) ||
    /^\s*<[\w-]+/.test(trimmed) ||
    /^\s*"\w+"\s*:/.test(trimmed);
}

function extractCodeBody(content: string): { code: string; language: CodeCanvasLanguage; summary: string } | null {
  const fenced = extractLargestFence(content);
  if (fenced) {
    const intro = content.slice(0, content.indexOf("```")).trim();
    const summary = intro ? intro.split(/\n+/).slice(0, 2).join(" ").trim() : "";
    return { code: fenced.code, language: fenced.language, summary };
  }

  const lines = content.split("\n");
  const codeLines = lines.filter(isCodeLikeLine);
  const ratio = lines.length > 0 ? codeLines.length / lines.length : 0;
  const denseCode = codeLines.length >= 8 && ratio >= 0.55;
  if (!denseCode) return null;
  return {
    code: content.trim(),
    language: detectLanguageFromText(content),
    summary: "",
  };
}

function languageLabel(language: CodeCanvasLanguage): string {
  if (language === "typescript") return "TypeScript";
  if (language === "javascript") return "JavaScript";
  if (language === "python") return "Python";
  if (language === "html") return "HTML";
  if (language === "css") return "CSS";
  if (language === "json") return "JSON";
  if (language === "shell") return "Shell";
  if (language === "csharp") return "C#";
  if (language === "rust") return "Rust";
  return "Code";
}

function compactSummary(value: string): string {
  const normalized = value.replace(/\s+/g, " ").trim();
  if (!normalized) return "";
  return normalized.length > 180 ? `${normalized.slice(0, 177).trimEnd()}...` : normalized;
}

export function detectCodeCanvas(input: CodeCanvasDetectionInput): CodeCanvasDetectionResult | null {
  const extracted = extractCodeBody(input.content);
  const promptSuggestsCode = looksLikePromptForCode(input.prompt);
  const contentLooksLikeCode = Boolean(extracted);
  const lineCount = extracted?.code.split("\n").length ?? 0;
  const shouldOpen = Boolean(extracted && (promptSuggestsCode || lineCount >= 8 || extracted.code.length >= 180));
  if (!shouldOpen || !extracted) return null;

  const language = extracted.language === "text" ? detectLanguageFromText(`${input.prompt}\n${extracted.code}`) : extracted.language;
  const titleBase = input.threadTitle?.trim() || `${languageLabel(language)} draft`;
  const summaryLead = extracted.summary || `Generated ${languageLabel(language)} has been opened in the code canvas.`;
  return {
    shouldOpen: true,
    code: extracted.code,
    language,
    title: `${titleBase} · ${languageLabel(language)}`,
    companion: {
      sourceMessageId: input.messageId,
      language,
      lineCount,
      title: `${languageLabel(language)} canvas`,
      summary: compactSummary(summaryLead),
    },
  };
}

export function defaultCodeCanvasState(): CodeCanvasState {
  return { ...DEFAULT_STATE };
}

function sanitizeCanvasStateForStorage(state: CodeCanvasState): CodeCanvasState {
  const content = state.content.length > MAX_CANVAS_CONTENT_CHARS ? state.content.slice(-MAX_CANVAS_CONTENT_CHARS) : state.content;
  const currentSource = state.sourceMessageId ? state.sources[state.sourceMessageId] : null;
  const nextSources =
    currentSource && state.sourceMessageId
      ? {
          [state.sourceMessageId]: {
            content: currentSource.content.length > MAX_CANVAS_CONTENT_CHARS ? currentSource.content.slice(-MAX_CANVAS_CONTENT_CHARS) : currentSource.content,
            language: currentSource.language,
            title: currentSource.title,
          },
        }
      : {};
  const nextCompanions =
    state.sourceMessageId && state.companions[state.sourceMessageId]
      ? { [state.sourceMessageId]: state.companions[state.sourceMessageId] }
      : {};
  return {
    ...state,
    content,
    companions: nextCompanions,
    sources: nextSources,
  };
}

export function serializeCodeCanvasState(state: CodeCanvasState, now = Date.now()): string | null {
  const persisted: PersistedCodeCanvasState = {
    savedAt: now,
    expiresAt: now + CODE_CANVAS_TTL_MS,
    state: sanitizeCanvasStateForStorage(state),
  };
  let json = JSON.stringify(persisted);
  if (json.length <= MAX_CANVAS_STORED_BYTES) return json;
  const minimal: PersistedCodeCanvasState = {
    savedAt: now,
    expiresAt: now + CODE_CANVAS_TTL_MS,
    state: {
      ...DEFAULT_STATE,
      isOpen: persisted.state.isOpen,
      language: persisted.state.language,
      title: persisted.state.title,
      viewMode: persisted.state.viewMode,
      sourceMessageId: persisted.state.sourceMessageId,
      content: persisted.state.content.slice(-Math.min(24_000, persisted.state.content.length)),
      isDirty: persisted.state.isDirty,
      companions: persisted.state.companions,
      sources: persisted.state.sources,
    },
  };
  json = JSON.stringify(minimal);
  return json.length <= MAX_CANVAS_STORED_BYTES ? json : null;
}

export function deserializeCodeCanvasState(raw: string | null, now = Date.now()): CodeCanvasState {
  if (!raw) return defaultCodeCanvasState();
  try {
    const parsed = JSON.parse(raw) as Partial<PersistedCodeCanvasState> | Partial<CodeCanvasState> | null;
    if (!parsed || typeof parsed !== "object") return defaultCodeCanvasState();
    const persisted = "state" in parsed ? parsed as Partial<PersistedCodeCanvasState> : null;
    if (persisted?.expiresAt && typeof persisted.expiresAt === "number" && persisted.expiresAt <= now) {
      return defaultCodeCanvasState();
    }
    const state = (persisted?.state && typeof persisted.state === "object" ? persisted.state : parsed) as Partial<CodeCanvasState>;
    return {
      ...DEFAULT_STATE,
      ...state,
      language: typeof state.language === "string" ? normalizeFenceLanguage(state.language) : "text",
      viewMode: state.viewMode === "fullscreen" ? "fullscreen" : "docked",
      companions: state.companions && typeof state.companions === "object" ? state.companions as Record<string, CodeCanvasCompanion> : {},
      sources: state.sources && typeof state.sources === "object" ? state.sources as Record<string, { content: string; language: CodeCanvasLanguage; title: string }> : {},
    };
  } catch {
    return defaultCodeCanvasState();
  }
}

export function loadCodeCanvasState(): CodeCanvasState {
  try {
    return deserializeCodeCanvasState(localStorage.getItem(config.codeCanvasStateKey));
  } catch {
    return defaultCodeCanvasState();
  }
}

export function saveCodeCanvasState(state: CodeCanvasState) {
  const serialized = serializeCodeCanvasState(state);
  if (!serialized) {
    try {
      localStorage.removeItem(config.codeCanvasStateKey);
    } catch {
      // ignore
    }
    return;
  }
  try {
    localStorage.setItem(config.codeCanvasStateKey, serialized);
  } catch {
    try {
      localStorage.removeItem(config.codeCanvasStateKey);
    } catch {
      // ignore
    }
  }
}

export function languageAccentClass(language: CodeCanvasLanguage): string {
  return `nexus-code-canvas--${language}`;
}
