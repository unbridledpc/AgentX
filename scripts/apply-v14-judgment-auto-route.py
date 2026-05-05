#!/usr/bin/env python3
from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
AUTO_ROUTE_KEY = "agentx.judgment.autoRoute.v1"


def patch_app() -> None:
    path = ROOT / "AgentXWeb/src/ui/App.tsx"
    text = path.read_text()

    state_marker = '''  const [judgmentPreview, setJudgmentPreview] = useState<JudgmentClassifyResponse | null>(null);
  const [judgmentPreviewError, setJudgmentPreviewError] = useState<string | null>(null);
  const [judgmentPreviewLoading, setJudgmentPreviewLoading] = useState(false);
'''
    state_add = state_marker + f'''  const [judgmentAutoRouteEnabled, setJudgmentAutoRouteEnabled] = useState(() => {{
    try {{
      return window.localStorage.getItem("{AUTO_ROUTE_KEY}") === "true";
    }} catch {{
      return false;
    }}
  }});
'''
    if "judgmentAutoRouteEnabled" not in text:
        if state_marker not in text:
            raise SystemExit("Could not find judgment preview state block in App.tsx")
        text = text.replace(state_marker, state_add, 1)

    effect_marker = '''  useEffect(() => {
    const value = draft.trim();
'''
    auto_route_effect = f'''  useEffect(() => {{
    try {{
      window.localStorage.setItem("{AUTO_ROUTE_KEY}", judgmentAutoRouteEnabled ? "true" : "false");
    }} catch {{
      // Ignore localStorage failures; auto-route still works for this session.
    }}
  }}, [judgmentAutoRouteEnabled]);

'''
    if AUTO_ROUTE_KEY not in text.split(effect_marker)[0]:
        if effect_marker not in text:
            raise SystemExit("Could not find judgment preview effect in App.tsx")
        text = text.replace(effect_marker, auto_route_effect + effect_marker, 1)

    send_marker = '''    if (!statusOk) {
      setSystemMessage("Offline - cannot send messages until the API is reachable.");
      return;
    }

    // Prevent obvious model/provider mismatches (most common source of 502s).
    const provider = (overrideSelection?.provider || chatProvider || "stub").toLowerCase();
    const effectiveModel = (overrideSelection?.model || chatModel || "stub").trim();
'''
    send_add = '''    if (!statusOk) {
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
      };
    })();

    const effectiveSelection = overrideSelection || judgmentRouteSelection;

    // Prevent obvious model/provider mismatches (most common source of 502s).
    const provider = (effectiveSelection?.provider || chatProvider || "stub").toLowerCase();
    const effectiveModel = (effectiveSelection?.model || chatModel || "stub").trim();
'''
    if "const judgmentRouteSelection = (() =>" not in text:
        if send_marker not in text:
            raise SystemExit("Could not find send provider selection block in App.tsx")
        text = text.replace(send_marker, send_add, 1)

    replacements = {
        "Boolean(overrideSelection && !overrideSelection.preserveCurrentSelection)": "Boolean(effectiveSelection && !effectiveSelection.preserveCurrentSelection)",
        "overrideSelection?.assistantLabel": "effectiveSelection?.assistantLabel",
        "overrideSelection?.codingPipeline": "effectiveSelection?.codingPipeline",
        "overrideSelection?.suppressHandoff": "effectiveSelection?.suppressHandoff",
    }
    for old, new in replacements.items():
        text = text.replace(old, new)

    ui_marker = '''                          <span className="min-w-0 flex-1 truncate text-slate-400" title={judgmentPreview.reason}>{judgmentPreview.reason}</span>
'''
    ui_add = ui_marker + '''                          <button
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
'''
    if "Auto Route:" not in text:
        if ui_marker not in text:
            raise SystemExit("Could not find judgment preview reason span in App.tsx")
        text = text.replace(ui_marker, ui_add, 1)

    deps_marker = '''    composerAttachments,
    composerRagMode,
    draft,
'''
    deps_add = '''    appSettings.ollamaFastModel,
    appSettings.ollamaHeavyModel,
    appSettings.ollamaMultiEndpointEnabled,
    composerAttachments,
    composerRagMode,
    draft,
    judgmentAutoRouteEnabled,
    judgmentPreview,
'''
    if "judgmentAutoRouteEnabled," not in text[text.find("composerAttachments,")-200:text.find("composerAttachments,")+500]:
        if deps_marker in text:
            text = text.replace(deps_marker, deps_add, 1)

    path.write_text(text)


def patch_readme() -> None:
    path = ROOT / "readme/README_V14_JUDGMENT_CONTROLLER.md"
    text = path.read_text()
    addition = '''
## Local Auto Route Toggle

V14 can keep auto-routing as a browser-local toggle:

```text
Auto Route: off/on
```

When enabled, the current judgment preview can choose a send-only route:

- `FAST` -> Ollama fast model
- `DEEP` -> Ollama heavy model
- `RECOVER` -> Ollama heavy model
- `HOLD` -> no automatic route change
- `BLOCK` -> send is blocked with a local warning

The toggle is stored in browser localStorage under `agentx.judgment.autoRoute.v1`.

Auto Route is intentionally send-only for V14. It does not permanently change the selected model dropdown.
'''
    if "## Local Auto Route Toggle" not in text:
        text = text.rstrip() + "\n" + addition
    path.write_text(text)


def main() -> None:
    patch_app()
    patch_readme()
    print("Applied AgentX V14 local judgment auto-route toggle.")


if __name__ == "__main__":
    main()
