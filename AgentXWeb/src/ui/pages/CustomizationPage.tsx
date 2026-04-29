import React, { useEffect, useMemo, useState } from "react";
import { DEFAULT_LAYOUT_SETTINGS, DEFAULT_AGENTX_SETTINGS, normalizeLayoutSettings, saveSettings, type LayoutSettings, type AgentXSettings } from "../../api/client";
import { AgentXToggle } from "../components/AgentXToggle";
import { Panel } from "../components/Panel";
import { AgentXDropdown, type AgentXDropdownOption } from "../components/AgentXDropdown";
import { ScrollArea } from "../components/ScrollArea";
import { clearPendingLayoutSave, loadPendingLayoutSave, savePendingLayoutSave, type PendingLayoutSave } from "../layoutPersistence";
import { tokens } from "../tokens";

type Props = {
  statusOk: boolean;
  settings: AgentXSettings | null;
  layoutGuards: {
    headerForcedVisible: boolean;
    inspectorUnavailableReason: string | null;
    codeCanvasInactive: boolean;
  };
  onSettingsChange: (settings: AgentXSettings) => void;
  onSettingsSaved: (settings: AgentXSettings) => void;
  onSystemMessage: (msg: string) => void;
};

function normalizeCustomizationSettings(settings: AgentXSettings | null | undefined): AgentXSettings {
  return {
    ...DEFAULT_AGENTX_SETTINGS,
    ...(settings ?? {}),
    layout: normalizeLayoutSettings(settings?.layout),
  };
}

export function CustomizationPage({ statusOk, settings, layoutGuards, onSettingsChange, onSettingsSaved, onSystemMessage }: Props) {
  const [loading, setLoading] = useState(false);
  const [layoutSaving, setLayoutSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [draft, setDraft] = useState<AgentXSettings>(DEFAULT_AGENTX_SETTINGS);
  const [pendingLayout, setPendingLayout] = useState<PendingLayoutSave | null>(() => loadPendingLayoutSave());

  useEffect(() => {
    setDraft(normalizeCustomizationSettings(settings));
    setPendingLayout(loadPendingLayoutSave());
  }, [settings]);

  const effectiveLayout = normalizeLayoutSettings(draft.layout);
  const [deckLayoutPrefs, setDeckLayoutPrefs] = useState(() => ({
    showModeRail: window.localStorage.getItem("agentx.deck.showModeRail") !== "false",
    showContextStack: window.localStorage.getItem("agentx.deck.showContextStack") !== "false",
  }));

  const updateDeckLayoutPref = (key: "showModeRail" | "showContextStack", value: boolean) => {
    const next = { ...deckLayoutPrefs, [key]: value };
    setDeckLayoutPrefs(next);
    window.localStorage.setItem("agentx.deck.showModeRail", String(next.showModeRail));
    window.localStorage.setItem("agentx.deck.showContextStack", String(next.showContextStack));
    window.dispatchEvent(new Event("agentx-deck-layout-changed"));
  };

  const updateDraft = (updater: (previous: AgentXSettings) => AgentXSettings) => {
    setDraft((previous) => {
      const next = normalizeCustomizationSettings(updater(previous));
      onSettingsChange(next);
      return next;
    });
  };

  const appearancePresetOptions = useMemo<AgentXDropdownOption[]>(
    () => [
      { value: "agentx", label: "AgentX Cyan" },
      { value: "midnight", label: "Midnight Blue" },
      { value: "ice", label: "Ice" },
      { value: "emerald", label: "Emerald" },
      { value: "violet", label: "Violet" },
      { value: "amber", label: "Amber" },
    ],
    []
  );

  const accentIntensityOptions = useMemo<AgentXDropdownOption[]>(
    () => [
      { value: "soft", label: "Soft" },
      { value: "balanced", label: "Balanced" },
      { value: "vivid", label: "Vivid" },
    ],
    []
  );

  const densityModeOptions = useMemo<AgentXDropdownOption[]>(
    () => [
      { value: "compact", label: "Compact" },
      { value: "comfortable", label: "Comfortable" },
      { value: "airy", label: "Airy" },
    ],
    []
  );

  const save = async () => {
    if (!statusOk) {
      onSystemMessage("Offline - cannot save customization settings.");
      return;
    }
    setLoading(true);
    setError(null);
    const nextSettings = normalizeCustomizationSettings(draft);
    const previousSettings = normalizeCustomizationSettings(settings);
    onSettingsChange(nextSettings);
    try {
      const saved = await saveSettings(nextSettings);
      onSettingsSaved(saved);
    } catch (e) {
      console.error("save customization failed", e);
      const message = e instanceof Error ? e.message : String(e);
      setError(message);
      setDraft(previousSettings);
      onSettingsChange(previousSettings);
      onSystemMessage("Customization save failed.");
    } finally {
      setLoading(false);
    }
  };

  const saveLayout = async (layout: LayoutSettings) => {
    const nextDraft = normalizeCustomizationSettings({ ...draft, layout });
    setDraft(nextDraft);
    onSettingsChange(nextDraft);
    const pending = savePendingLayoutSave(layout);
    setPendingLayout(pending);
    if (!statusOk) {
      setError("Layout updated locally and is queued to sync when the API is available again.");
      onSystemMessage("Layout updated locally and is pending sync.");
      return;
    }
    setLayoutSaving(true);
    setError(null);
    try {
      const saved = await saveSettings(nextDraft);
      clearPendingLayoutSave();
      setPendingLayout(null);
      onSettingsSaved(saved);
    } catch (e) {
      console.error("save layout failed", e);
      setError(`Layout updated locally but could not be saved yet. ${e instanceof Error ? e.message : String(e)}`);
      onSystemMessage("Layout save failed and is pending retry.");
    } finally {
      setLayoutSaving(false);
    }
  };

  const updateLayoutToggle = (key: keyof Required<LayoutSettings>, value: boolean) => {
    const nextLayout = { ...effectiveLayout, [key]: value };
    void saveLayout(nextLayout);
  };

  const resetLayout = () => {
    void saveLayout(DEFAULT_LAYOUT_SETTINGS);
  };

  const headerHelper = layoutGuards.headerForcedVisible
    ? "Top bar with title, model selector, and quick canvas access. Currently forced visible on mobile while the sidebar is enabled."
    : "Top bar with title, model selector, and quick canvas access.";

  const inspectorHelper = layoutGuards.inspectorUnavailableReason
    ? `Diagnostics and advanced local controls when available. ${layoutGuards.inspectorUnavailableReason}`
    : "Diagnostics and advanced local controls when available.";

  const codeCanvasHelper = layoutGuards.codeCanvasInactive
    ? "Auto-opening code workspace for assistant-generated code output. No canvas is currently open, so this will not change the shell until one opens."
    : "Auto-opening code workspace for assistant-generated code output.";

  return (
    <Panel className="flex min-h-0 flex-col gap-3 p-3">
      <div className="flex items-center justify-between">
        <div className="text-sm font-semibold">Customization</div>
        <div className={tokens.helperText}>{loading ? "Saving..." : layoutSaving ? "Updating layout..." : ""}</div>
      </div>

      <ScrollArea className="min-h-0 flex-1 pr-1">
        <div className="space-y-3">
          <Panel className="p-3">
            <div className={tokens.smallLabel}>Identity</div>
            <div className="mt-2 grid gap-2">
              <label className={tokens.fieldLabel}>Assistant Name</label>
              <input
                className={tokens.input}
                value={draft.assistantDisplayName ?? DEFAULT_AGENTX_SETTINGS.assistantDisplayName}
                disabled={loading}
                onChange={(e) => updateDraft((prev) => ({ ...prev, assistantDisplayName: e.target.value }))}
                placeholder="AgentX"
              />
              <div className={tokens.helperText}>
                Used for the assistant identity in chat, composer copy, and user-facing labels.
              </div>

              <label className={tokens.fieldLabel}>User Display Name</label>
              <input
                className={tokens.input}
                value={draft.userDisplayName ?? DEFAULT_AGENTX_SETTINGS.userDisplayName}
                disabled={loading}
                onChange={(e) => updateDraft((prev) => ({ ...prev, userDisplayName: e.target.value }))}
                placeholder="You"
              />
              <div className={tokens.helperText}>
                Used anywhere the local user identity is shown in chat and conversation context.
              </div>
            </div>
          </Panel>

          <Panel className="p-3">
            <div className={tokens.smallLabel}>Appearance</div>
            <div className="mt-2 grid gap-2">
              <label className={tokens.fieldLabel}>Preset</label>
              <AgentXDropdown
                value={draft.appearancePreset ?? DEFAULT_AGENTX_SETTINGS.appearancePreset}
                options={appearancePresetOptions}
                disabled={loading}
                onChange={(value) => updateDraft((prev) => ({ ...prev, appearancePreset: value as AgentXSettings["appearancePreset"] }))}
              />

              <label className={tokens.fieldLabel}>Accent Intensity</label>
              <AgentXDropdown
                value={draft.accentIntensity ?? DEFAULT_AGENTX_SETTINGS.accentIntensity}
                options={accentIntensityOptions}
                disabled={loading}
                onChange={(value) => updateDraft((prev) => ({ ...prev, accentIntensity: value as AgentXSettings["accentIntensity"] }))}
              />

              <label className={tokens.fieldLabel}>Density</label>
              <AgentXDropdown
                value={draft.densityMode ?? DEFAULT_AGENTX_SETTINGS.densityMode}
                options={densityModeOptions}
                disabled={loading}
                onChange={(value) => updateDraft((prev) => ({ ...prev, densityMode: value as AgentXSettings["densityMode"] }))}
              />

              <div className={tokens.helperText}>
                Preset changes the active color palette immediately. Accent Intensity controls how strong the selected palette glows, while Density controls spacing.
              </div>
            </div>
          </Panel>

          <Panel className="p-3">
            <div className="flex items-center justify-between gap-3">
              <div>
                <div className={tokens.smallLabel}>Layout</div>
                <div className="mt-3 grid gap-3 rounded-2xl border border-slate-800 bg-slate-950/70 p-3">
                  <div className={tokens.smallLabel}>Command Deck</div>

                  <label className="flex items-center justify-between gap-3 rounded-xl border border-slate-800 bg-slate-950/80 px-3 py-2 text-sm text-slate-100">
                    <span>
                      <span className="block font-semibold">Show mode rail</span>
                      <span className="block text-xs text-slate-500">Left Command / Drafts / Memory / Models rail.</span>
                    </span>
                    <input
                      type="checkbox"
                      checked={deckLayoutPrefs.showModeRail}
                      onChange={(event) => updateDeckLayoutPref("showModeRail", event.target.checked)}
                    />
                  </label>

                  <label className="flex items-center justify-between gap-3 rounded-xl border border-slate-800 bg-slate-950/80 px-3 py-2 text-sm text-slate-100">
                    <span>
                      <span className="block font-semibold">Show inspector / context stack</span>
                      <span className="block text-xs text-slate-500">Right-side active thread, memory, model, and context panel.</span>
                    </span>
                    <input
                      type="checkbox"
                      checked={deckLayoutPrefs.showContextStack}
                      onChange={(event) => updateDeckLayoutPref("showContextStack", event.target.checked)}
                    />
                  </label>
                </div>
                <div className={tokens.helperText}>Choose which major app regions stay visible.</div>
              </div>
              <button className={tokens.buttonSecondary} disabled={layoutSaving} onClick={resetLayout}>
                Reset Layout
              </button>
            </div>

            {layoutGuards.headerForcedVisible || layoutGuards.inspectorUnavailableReason || layoutGuards.codeCanvasInactive ? (
              <div className="mt-3 rounded-xl border border-amber-400/20 bg-amber-500/10 px-3 py-2 text-xs text-amber-100">
                {layoutGuards.headerForcedVisible ? <div>Header is temporarily forced on while mobile navigation is active.</div> : null}
                {layoutGuards.inspectorUnavailableReason ? <div>{layoutGuards.inspectorUnavailableReason}</div> : null}
                {layoutGuards.codeCanvasInactive ? <div>Code Canvas visibility only affects an active canvas.</div> : null}
              </div>
            ) : null}

            {pendingLayout ? (
              <div className="mt-3 rounded-xl border border-cyan-400/20 bg-cyan-500/10 px-3 py-2 text-xs text-cyan-100">
                Layout changes are applied locally and pending sync.
              </div>
            ) : null}

            <div className="mt-3 grid gap-2">
              <AgentXToggle
                checked={effectiveLayout.showSidebar}
                disabled={layoutSaving}
                label="Show Sidebar"
                helper="Thread navigation, projects, and page switching."
                onChange={(checked) => updateLayoutToggle("showSidebar", checked)}
              />
              <AgentXToggle
                checked={effectiveLayout.showInspector}
                disabled={layoutSaving}
                label="Show Inspector"
                helper={inspectorHelper}
                onChange={(checked) => updateLayoutToggle("showInspector", checked)}
              />
              <AgentXToggle
                checked={effectiveLayout.showHeader}
                disabled={layoutSaving}
                label="Show Header"
                helper={headerHelper}
                onChange={(checked) => updateLayoutToggle("showHeader", checked)}
              />
              <AgentXToggle
                checked={effectiveLayout.showCodeCanvas}
                disabled={layoutSaving}
                label="Show Code Canvas"
                helper={codeCanvasHelper}
                onChange={(checked) => updateLayoutToggle("showCodeCanvas", checked)}
              />
            </div>
          </Panel>

          <Panel className="p-3">
            <div className={tokens.smallLabel}>Preview</div>
            <div className="mt-3 rounded-[1.1rem] border border-slate-800/90 bg-slate-950/72 p-3">
              <div className="flex items-center justify-between gap-3">
                <div>
                  <div className="text-sm font-semibold text-slate-100">{draft.assistantDisplayName || DEFAULT_AGENTX_SETTINGS.assistantDisplayName}</div>
                  <div className={tokens.helperText}>Assistant identity</div>
                </div>
                <div className="text-right">
                  <div className="text-sm font-semibold text-slate-200">{draft.userDisplayName || DEFAULT_AGENTX_SETTINGS.userDisplayName}</div>
                  <div className={tokens.helperText}>User identity</div>
                </div>
              </div>
            </div>
          </Panel>

          <button className={tokens.button} disabled={loading} onClick={() => void save()}>
            Save Customization
          </button>

          {error ? (
            <Panel className="border-rose-200 bg-rose-50 p-3">
              <div className="text-sm font-semibold text-rose-800">Customization Error</div>
              <div className="mt-1 text-xs text-rose-800">{error}</div>
            </Panel>
          ) : null}
        </div>
      </ScrollArea>
    </Panel>
  );
}
