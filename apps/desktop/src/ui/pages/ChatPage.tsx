import React, { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { ScrollArea } from "../components/ScrollArea";
import { getToolsSchema, Message, ToolSchema } from "../../api/client";

type ChatPageProps = {
  messages: Message[];
  onSend: (text: string) => Promise<void>;
  sending: boolean;
  verification?: { verdict: string; confidence: number; contradictions: string[] } | null;
};

type ToolSuggestion = {
  display: string;
  canonical: string;
  tool: ToolSchema;
};

export function ChatPage({ messages, onSend, sending, verification }: ChatPageProps) {
  const [draft, setDraft] = useState("");
  const textareaRef = useRef<HTMLTextAreaElement | null>(null);
  const feedRef = useRef<HTMLDivElement | null>(null);
  const [isNearBottom, setIsNearBottom] = useState(true);
  const [tools, setTools] = useState<ToolSchema[] | null>(null);
  const [toolError, setToolError] = useState<string | null>(null);
  const [suggestions, setSuggestions] = useState<ToolSuggestion[]>([]);
  const [highlightIndex, setHighlightIndex] = useState(0);
  const [selectedTool, setSelectedTool] = useState<ToolSchema | null>(null);
  const schemaLoadedRef = useRef(false);

  const lastAssistantId = useMemo(() => {
    for (let i = messages.length - 1; i >= 0; i -= 1) {
      if (messages[i]?.role === "assistant") return messages[i].id;
    }
    return null;
  }, [messages]);

  const rendered = useMemo(
    () =>
      messages.map((m) => (
        <div key={m.id} className="space-y-1">
          <div
            className={[
              "text-xs font-semibold uppercase tracking-wide tracking-wider",
              m.role === "system" ? "text-rose-500" : "text-neutral-500",
            ].join(" ")}
          >
            <div className="flex items-center justify-between gap-2">
              <span>{m.role}</span>
              {m.id === lastAssistantId && m.role === "assistant" && verification ? (
                <span className="rounded-lg border border-slate-200 bg-slate-50 px-2 py-[1px] text-[10px] text-slate-700">
                  {verification.verdict} ({Math.round((verification.confidence ?? 0) * 100)}%)
                </span>
              ) : null}
            </div>
          </div>
          {m.id === lastAssistantId && m.role === "assistant" && verification?.contradictions?.length ? (
            <details className="rounded-lg border border-amber-200 bg-amber-50 px-2 py-1 text-[11px] text-amber-900">
              <summary className="cursor-pointer select-none">
                Contradictions ({verification.contradictions.length})
              </summary>
              <div className="mt-1 space-y-1">
                {verification.contradictions.map((c, idx) => (
                  <div key={`${idx}-${c}`}>{c}</div>
                ))}
              </div>
            </details>
          ) : null}
          <div
            className={[
              "text-sm leading-relaxed whitespace-pre-wrap",
              m.role === "system" ? "text-rose-600" : "text-neutral-900",
            ].join(" ")}
          >
            {m.content}
          </div>
        </div>
      )),
    [lastAssistantId, messages, verification]
  );

  const scrollToBottom = useCallback(() => {
    const container = feedRef.current;
    if (!container) return;
    container.scrollTo({ top: container.scrollHeight, behavior: "smooth" });
    setIsNearBottom(true);
  }, []);

  const handleSend = useCallback(async () => {
    const trimmed = draft.trim();
    if (!trimmed || sending) return;
    setDraft("");
    await onSend(trimmed);
    textareaRef.current?.focus({ preventScroll: true });
  }, [draft, onSend, sending]);

  const fetchToolsSchema = useCallback(async () => {
    if (schemaLoadedRef.current) return;
    schemaLoadedRef.current = true;
    try {
      const res = await getToolsSchema();
      setTools(res.tools ?? []);
      setToolError(null);
    } catch (e) {
      schemaLoadedRef.current = false;
      setTools(null);
      setToolError(e instanceof Error ? e.message : String(e));
    }
  }, []);

  const parseToolPartial = useCallback((value: string) => {
    const trimmed = value.trimStart();
    if (!trimmed.startsWith("/tool")) return null;
    const after = trimmed.slice(5); // "/tool".length
    const m = after.match(/^\s+([^\s{]*)/);
    const partial = (m?.[1] ?? "").trim();
    return { partial };
  }, []);

  const buildTemplate = useCallback((tool: ToolSchema) => {
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

  const applySuggestion = useCallback(
    (suggestion: ToolSuggestion) => {
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
      setSuggestions([]);
      setHighlightIndex(0);
      queueMicrotask(() => textareaRef.current?.focus({ preventScroll: true }));
    },
    [draft]
  );

  const insertTemplate = useCallback(() => {
    if (!selectedTool) return;
    const value = draft;
    const trimmedStart = value.trimStart();
    if (!trimmedStart.startsWith("/tool")) return;
    if (value.includes("{")) return;
    const template = buildTemplate(selectedTool);
    const next = `${value.trimEnd()} ${template}`;
    setDraft(next);
    queueMicrotask(() => textareaRef.current?.focus({ preventScroll: true }));
  }, [buildTemplate, draft, selectedTool]);

  const handleKeyDown = (event: React.KeyboardEvent<HTMLTextAreaElement>) => {
    if (suggestions.length > 0) {
      if (event.key === "ArrowDown") {
        event.preventDefault();
        setHighlightIndex((i) => Math.min(suggestions.length - 1, i + 1));
        return;
      }
      if (event.key === "ArrowUp") {
        event.preventDefault();
        setHighlightIndex((i) => Math.max(0, i - 1));
        return;
      }
      if (event.key === "Escape") {
        event.preventDefault();
        setSuggestions([]);
        setHighlightIndex(0);
        return;
      }
      if (event.key === "Enter" || event.key === "Tab") {
        const pick = suggestions[highlightIndex];
        if (pick) {
          event.preventDefault();
          applySuggestion(pick);
          return;
        }
      }
    }
    if (event.key === "Enter" && !event.shiftKey) {
      event.preventDefault();
      void handleSend();
    }
  };

  useEffect(() => {
    const container = feedRef.current;
    if (!container) return;

    const checkScroll = () => {
      const threshold = 120;
      const distanceToBottom =
        container.scrollHeight - container.scrollTop - container.clientHeight;
      setIsNearBottom(distanceToBottom <= threshold);
    };

    checkScroll();
    container.addEventListener("scroll", checkScroll);
    return () => container.removeEventListener("scroll", checkScroll);
  }, []);

  useEffect(() => {
    const container = feedRef.current;
    if (!container) return;
    const threshold = 120;
    const distanceToBottom = container.scrollHeight - container.scrollTop - container.clientHeight;
    if (distanceToBottom <= threshold) {
      container.scrollTop = container.scrollHeight;
      setIsNearBottom(true);
    }
  }, [messages]);

  useEffect(() => {
    const info = parseToolPartial(draft);
    if (!info) {
      setSuggestions([]);
      setSelectedTool(null);
      return;
    }
    if (!tools) {
      void fetchToolsSchema();
      return;
    }

    const q = info.partial.toLowerCase();
    const items: ToolSuggestion[] = [];
    for (const tool of tools) {
      items.push({ display: tool.name, canonical: tool.name, tool });
      for (const alias of tool.aliases ?? []) {
        if (alias && alias !== tool.name) {
          items.push({ display: alias, canonical: tool.name, tool });
        }
      }
    }
    const filtered = q
      ? items.filter((i) => i.display.toLowerCase().includes(q) || i.canonical.toLowerCase().includes(q))
      : items;
    const uniqueKey = new Set<string>();
    const deduped = filtered.filter((i) => {
      const key = `${i.display}=>${i.canonical}`;
      if (uniqueKey.has(key)) return false;
      uniqueKey.add(key);
      return true;
    });
    deduped.sort((a, b) => a.display.localeCompare(b.display));
    setSuggestions(deduped.slice(0, 30));
    setHighlightIndex(0);
  }, [draft, fetchToolsSchema, parseToolPartial, tools]);

  return (
    <div className="flex h-full min-h-0 flex-col">
      <div className="flex min-h-0 flex-1 flex-col">
        <ScrollArea
          ref={feedRef}
          className="flex min-h-0 flex-1 flex-col gap-4 px-4 py-4"
        >
          <div className="flex-grow space-y-4">{rendered}</div>
        </ScrollArea>
        {!isNearBottom && (
          <div className="flex justify-center py-2">
            <button
              onClick={scrollToBottom}
              className="rounded-full border border-slate-300 bg-white px-3 py-1 text-xs font-semibold shadow-sm"
            >
              Jump to latest
            </button>
          </div>
        )}
      </div>
      <div className="relative flex-none border-t border-neutral-200">
        <div className="p-3">
          <div className="flex gap-3 items-end">
            <div className="w-full">
              <textarea
                ref={textareaRef}
                className="w-full min-h-[80px] max-h-[200px] resize-y rounded-xl border border-neutral-200 p-3 text-sm outline-none focus:ring-2 focus:ring-neutral-200"
                placeholder="Type a message"
                value={draft}
                onChange={(e) => setDraft(e.target.value)}
                onKeyDown={handleKeyDown}
                onFocus={() => void fetchToolsSchema()}
                disabled={sending}
              />
              {draft.trimStart().startsWith("/tool") && toolError && (
                <div className="mt-2 text-xs text-rose-700">Tool schema unavailable: {toolError}</div>
              )}
              {draft.trimStart().startsWith("/tool") && suggestions.length > 0 && (
                <div className="mt-2 max-h-56 overflow-auto rounded-xl border border-slate-200 bg-white shadow-sm">
                  {suggestions.map((s, idx) => (
                    <button
                      key={`${s.display}=>${s.canonical}`}
                      type="button"
                      className={[
                        "w-full text-left px-3 py-2 text-sm",
                        idx === highlightIndex ? "bg-slate-50" : "bg-white hover:bg-slate-50",
                      ].join(" ")}
                      onMouseEnter={() => setHighlightIndex(idx)}
                      onClick={() => applySuggestion(s)}
                    >
                      <div className="flex items-center justify-between gap-2">
                        <span className="font-medium text-slate-900">{s.display}</span>
                        {s.display !== s.canonical && (
                          <span className="text-xs text-slate-500">→ {s.canonical}</span>
                        )}
                      </div>
                      {s.tool.description ? (
                        <div className="text-xs text-slate-500">{s.tool.description}</div>
                      ) : null}
                    </button>
                  ))}
                </div>
              )}
              {draft.trimStart().startsWith("/tool") && selectedTool && (
                <div className="mt-2 rounded-xl border border-slate-200 bg-slate-50/50 p-3 text-xs text-slate-700">
                  <div className="flex items-center justify-between gap-2">
                    <div className="font-semibold">{selectedTool.name}</div>
                    <button
                      type="button"
                      className="rounded-lg border border-slate-200 bg-white px-2 py-1 text-xs hover:bg-slate-50"
                      onClick={insertTemplate}
                    >
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
              )}
            </div>
            <button
              className="px-4 py-2 rounded-xl border border-neutral-200 bg-white hover:bg-neutral-50 active:bg-neutral-100 text-sm font-medium disabled:cursor-not-allowed disabled:opacity-60"
              onClick={() => {
                void handleSend();
              }}
              disabled={sending}
            >
              {sending ? "Sending…" : "Send"}
            </button>
          </div>
        </div>
      </div>
    </div>
  );
}
