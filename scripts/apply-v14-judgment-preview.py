#!/usr/bin/env python3
from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def patch_client() -> None:
    path = ROOT / "AgentXWeb/src/api/client.ts"
    text = path.read_text()

    type_marker = 'export type ResponseMode = "chat" | "research" | "rag";\n'
    type_add = type_marker + '''export type JudgmentRoute = "FAST" | "HOLD" | "BLOCK" | "DEEP" | "RECOVER";

export type JudgmentClassifyResponse = {
  ok: boolean;
  route: JudgmentRoute;
  endpoint: "default" | "fast" | "heavy" | null;
  reason: string;
  confidence: number;
  signals: Record<string, unknown>;
};
'''
    if "export type JudgmentRoute" not in text:
        text = text.replace(type_marker, type_add)

    function_marker = "export async function streamChatMessage(\n"
    function_add = '''export async function classifyJudgment(
  text: string,
  contextTurns = 0,
  previousError = false,
  signal?: AbortSignal
): Promise<JudgmentClassifyResponse> {
  const res = await fetch(`${config.apiBase}/v1/judgment/classify`, {
    method: "POST",
    headers: jsonHeaders(),
    body: JSON.stringify({ text, context_turns: contextTurns, previous_error: previousError }),
    signal,
  });
  return handle(res);
}

''' + function_marker
    if "export async function classifyJudgment" not in text:
        text = text.replace(function_marker, function_add)

    path.write_text(text)


def patch_app() -> None:
    path = ROOT / "AgentXWeb/src/ui/App.tsx"
    text = path.read_text()

    import_marker = "  CodingPipelineRequest,\n  type DraftGenerateResponse,\n"
    import_add = "  CodingPipelineRequest,\n  classifyJudgment,\n  type JudgmentClassifyResponse,\n  type DraftGenerateResponse,\n"
    if "classifyJudgment," not in text:
        text = text.replace(import_marker, import_add)

    state_marker = '  const [draft, setDraft] = useState("");\n'
    state_add = state_marker + '''  const [judgmentPreview, setJudgmentPreview] = useState<JudgmentClassifyResponse | null>(null);
  const [judgmentPreviewError, setJudgmentPreviewError] = useState<string | null>(null);
  const [judgmentPreviewLoading, setJudgmentPreviewLoading] = useState(false);
'''
    if "judgmentPreview" not in text:
        text = text.replace(state_marker, state_add)

    effect_marker = '''  const textareaRef = useRef<HTMLTextAreaElement | null>(null);
'''
    effect_add = effect_marker + '''
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
        .then((result) => {
          setJudgmentPreview(result);
          setJudgmentPreviewError(null);
        })
        .catch((error) => {
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

'''
    if "classifyJudgment(" not in text:
        text = text.replace(effect_marker, effect_add)

    toolbar_marker = '''                  <div className="agentx-composer-toolbar">
'''
    preview_block = '''                  {draft.trim() ? (
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
                        </>
                      ) : judgmentPreviewError ? (
                        <span className="text-amber-200">{judgmentPreviewError}</span>
                      ) : (
                        <span className="text-slate-500">ready</span>
                      )}
                    </div>
                  ) : null}
''' + toolbar_marker
    if "Judgment:" not in text:
        text = text.replace(toolbar_marker, preview_block)

    path.write_text(text)


def patch_readme() -> None:
    path = ROOT / "readme/README_V14_JUDGMENT_CONTROLLER.md"
    text = path.read_text()
    addition = '''
## Frontend Preview

The chat composer can call `/v1/judgment/classify` while the user types and show a non-blocking preview:

```text
Judgment: FAST -> fast
Judgment: DEEP -> heavy
Judgment: RECOVER -> heavy
Judgment: BLOCK -> none
```

This preview does not automatically change routing yet. It is visibility-only for V14.
'''
    if "## Frontend Preview" not in text:
        text = text.rstrip() + "\n" + addition
    path.write_text(text)


def main() -> None:
    patch_client()
    patch_app()
    patch_readme()
    print("Applied AgentX V14 judgment preview frontend slice.")


if __name__ == "__main__":
    main()
