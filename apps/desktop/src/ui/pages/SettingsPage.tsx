import React, { useEffect, useState } from "react";
import { Panel } from "../components/Panel";
import { ScrollArea } from "../components/ScrollArea";
import {
  getChatModel,
  getChatProvider,
  getInspectorWindowEnabled,
  getShowInspectorSidebar,
  getTheme,
  setChatModel,
  setChatProvider,
  setInspectorWindowEnabled,
  setShowInspectorSidebar,
  setTheme,
  subscribeChatModel,
  subscribeChatProvider,
  subscribeInspectorWindow,
  subscribeShowInspectorSidebar,
  subscribeTheme,
} from "../prefs";

export function SettingsPage() {
  const [showInspector, setShowInspectorState] = useState(getShowInspectorSidebar());
  const [inspectorWindowEnabled, setInspectorWindowEnabledState] = useState(getInspectorWindowEnabled());
  const [theme, setThemeState] = useState(getTheme());
  const [chatProvider, setChatProviderState] = useState(getChatProvider());
  const [chatModel, setChatModelState] = useState(getChatModel());

  useEffect(() => {
    const unsubSidebar = subscribeShowInspectorSidebar(setShowInspectorState);
    const unsubWindow = subscribeInspectorWindow(setInspectorWindowEnabledState);
    const unsubTheme = subscribeTheme(setThemeState);
    const unsubProvider = subscribeChatProvider(setChatProviderState);
    const unsubModel = subscribeChatModel(setChatModelState);
    return () => {
      unsubSidebar();
      unsubWindow();
      unsubTheme();
      unsubProvider();
      unsubModel();
    };
  }, []);

  const toggleInspector = (next: boolean) => {
    setShowInspectorState(next);
    setShowInspectorSidebar(next);
  };

  const toggleInspectorWindow = (next: boolean) => {
    setInspectorWindowEnabledState(next);
    setInspectorWindowEnabled(next);
  };

  return (
    <Panel className="p-4 h-full min-h-0">
      <ScrollArea className="h-full">
        <div className="space-y-3">
          <h2 className="text-base font-semibold">Settings (stub)</h2>
          <p className="text-sm text-neutral-600">
            This page is intentionally filled to validate scrolling and spacing.
          </p>
          <Panel className="rounded-2xl border border-neutral-200 p-3">
            <div className="text-sm font-semibold">Chat</div>
            <div className="text-xs text-neutral-500">Chat provider and model selection (also available in Chat header).</div>
            <label className="mt-3 flex flex-col gap-1 text-sm font-medium">
              <span>Provider</span>
              <select
                className="rounded-xl border border-neutral-200 bg-white px-3 py-2 text-sm outline-none focus:border-slate-400"
                value={chatProvider}
                onChange={(event) => {
                  const next = event.target.value;
                  setChatProviderState(next);
                  setChatProvider(next);
                }}
              >
                <option value="openai">OpenAI</option>
                <option value="ollama">Ollama</option>
                <option value="stub">Stub</option>
              </select>
            </label>
            <label className="mt-3 flex flex-col gap-1 text-sm font-medium">
              <span>Model</span>
              <input
                className="rounded-xl border border-neutral-200 bg-white px-3 py-2 text-sm outline-none focus:border-slate-400"
                value={chatModel}
                onChange={(event) => {
                  const next = event.target.value;
                  setChatModelState(next);
                  setChatModel(next);
                }}
                placeholder="e.g. gpt-4.1-mini or llama3.2:latest"
              />
            </label>
          </Panel>
          <Panel className="rounded-2xl border border-neutral-200 p-3">
            <div className="text-sm font-semibold">View</div>
            <div className="text-xs text-neutral-500">
              Control which UI helpers are visible.
            </div>
            <label className="mt-3 flex items-center gap-3 text-sm font-medium">
              <input
                type="checkbox"
                className="h-4 w-4 rounded border border-neutral-300 text-slate-900 focus:ring-0"
                checked={showInspector}
                onChange={(event) => toggleInspector(event.target.checked)}
                disabled={inspectorWindowEnabled}
              />
              <span>Show Inspector sidebar</span>
            </label>
            {inspectorWindowEnabled && (
              <div className="text-xs text-slate-500">
                Sidebar is disabled while inspector window is open.
              </div>
            )}
            <label className="mt-3 flex flex-col gap-1 text-sm font-medium">
              <span>Theme</span>
              <select
                className="rounded-xl border border-neutral-200 bg-white px-3 py-2 text-sm outline-none focus:border-slate-400"
                value={theme}
                onChange={(event) => setTheme(event.target.value as "win11-light")}
              >
                <option value="win11-light">Win11 Light</option>
              </select>
            </label>
            <label className="mt-3 flex items-center gap-3 text-sm font-medium">
              <input
                type="checkbox"
                className="h-4 w-4 rounded border border-neutral-300 text-slate-900 focus:ring-0"
                checked={inspectorWindowEnabled}
                onChange={(event) => toggleInspectorWindow(event.target.checked)}
              />
              <span>Open Inspector in new window</span>
            </label>
          </Panel>
          {Array.from({ length: 40 }).map((_, i) => (
            <div key={i} className="p-3 rounded-xl border border-neutral-200 bg-white">
              Option row {i + 1}
            </div>
          ))}
        </div>
      </ScrollArea>
    </Panel>
  );
}
