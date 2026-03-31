import React, { useEffect, useMemo, useState } from "react";
import { DEFAULT_LAYOUT_SETTINGS, DEFAULT_SOL_SETTINGS, normalizeLayoutSettings, saveSettings, type LayoutSettings, type SolSettings } from "../../api/client";
import { NexusToggle } from "../components/NexusToggle";
import { Panel } from "../components/Panel";
import { NexusDropdown, type NexusDropdownOption } from "../components/NexusDropdown";
import { ScrollArea } from "../components/ScrollArea";
import { clearPendingLayoutSave, loadPendingLayoutSave, savePendingLayoutSave, type PendingLayoutSave } from "../layoutPersistence";
import { tokens } from "../tokens";

type Props = {
  statusOk: boolean;
  settings: SolSettings | null;
  layoutGuards: {
    headerForcedVisible: boolean;
    inspectorUnavailableReason: string | null;
    codeCanvasInactive: boolean;
  };
  onSettingsChange: (settings: SolSettings) => void;
  onSettingsSaved: (settings: SolSettings) => void;
  onSystemMessage: (msg: string) => void;
};

function normalizeCustomizationSettings(settings: SolSettings | null | undefined): SolSettings {
  return {
    ...DEFAULT_SOL_SETTINGS,
    ...(settings ?? {}),
    layout: normalizeLayoutSettings(settings?.layout),
  };
}

export function CustomizationPage({ statusOk, settings, layoutGuards, onSettingsChange, onSettingsSaved, onSystemMessage }: Props) {
  const [loading, setLoading] = useState(false);
  const [layoutSaving, setLayoutSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [draft, setDraft] = useState<SolSettings>(DEFAULT_SOL_SETTINGS);
  const [pendingLayout, setPendingLayout] = useState<PendingLayoutSave | null>(() => loadPendingLayoutSave());

  useEffect(() => {
    setDraft(normalizeCustomizationSettings(settings));
    setPendingLayout(loadPendingLayoutSave());
  }, [settings]);

  const effectiveLayout = normalizeLayoutSettings(draft.layout);

  const appearancePresetOptions = useMemo<NexusDropdownOption[]>(
    () => [
      { value: "nexus", label: "Nexus" },
      { value: "midnight", label: "Midnight" },
      { value: "ice", label: "Ice" },
    ],
    []
  );

  const accentIntensityOptions = useMemo<NexusDropdownOption[]>(
    () => [
      { value: "soft", label: "Soft" },
      { value: "balanced", label: "Balanced" },
      { value: "vivid", label: "Vivid" },
    ],
    []
  );

  const densityModeOptions = useMemo<NexusDropdownOption[]>(
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
                value={draft.assistantDisplayName ?? DEFAULT_SOL_SETTINGS.assistantDisplayName}
                disabled={loading}
                onChange={(e) => setDraft((prev) => ({ ...prev, assistantDisplayName: e.target.value }))}
                placeholder="Nexus"
              />
              <div className={tokens.helperText}>
                Used for the assistant identity in chat, composer copy, and user-facing labels.
              </div>

              <label className={tokens.fieldLabel}>User Display Name</label>
              <input
                className={tokens.input}
                value={draft.userDisplayName ?? DEFAULT_SOL_SETTINGS.userDisplayName}
                disabled={loading}
                onChange={(e) => setDraft((prev) => ({ ...prev, userDisplayName: e.target.value }))}
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
              <NexusDropdown
                value={draft.appearancePreset ?? DEFAULT_SOL_SETTINGS.appearancePreset}
                options={appearancePresetOptions}
                disabled={loading}
                onChange={(value) => setDraft((prev) => ({ ...prev, appearancePreset: value as SolSettings["appearancePreset"] }))}
              />

              <label className={tokens.fieldLabel}>Accent Intensity</label>
              <NexusDropdown
                value={draft.accentIntensity ?? DEFAULT_SOL_SETTINGS.accentIntensity}
                options={accentIntensityOptions}
                disabled={loading}
                onChange={(value) => setDraft((prev) => ({ ...prev, accentIntensity: value as SolSettings["accentIntensity"] }))}
              />

              <label className={tokens.fieldLabel}>Density</label>
              <NexusDropdown
                value={draft.densityMode ?? DEFAULT_SOL_SETTINGS.densityMode}
                options={densityModeOptions}
                disabled={loading}
                onChange={(value) => setDraft((prev) => ({ ...prev, densityMode: value as SolSettings["densityMode"] }))}
              />

              <div className={tokens.helperText}>
                Appearance settings are stored independently from provider and model configuration, and act as the foundation for future visual presets.
              </div>
            </div>
          </Panel>

          <Panel className="p-3">
            <div className="flex items-center justify-between gap-3">
              <div>
                <div className={tokens.smallLabel}>Layout</div>
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
              <NexusToggle
                checked={effectiveLayout.showSidebar}
                disabled={layoutSaving}
                label="Show Sidebar"
                helper="Thread navigation, projects, and page switching."
                onChange={(checked) => updateLayoutToggle("showSidebar", checked)}
              />
              <NexusToggle
                checked={effectiveLayout.showInspector}
                disabled={layoutSaving}
                label="Show Inspector"
                helper={inspectorHelper}
                onChange={(checked) => updateLayoutToggle("showInspector", checked)}
              />
              <NexusToggle
                checked={effectiveLayout.showHeader}
                disabled={layoutSaving}
                label="Show Header"
                helper={headerHelper}
                onChange={(checked) => updateLayoutToggle("showHeader", checked)}
              />
              <NexusToggle
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
                  <div className="text-sm font-semibold text-slate-100">{draft.assistantDisplayName || DEFAULT_SOL_SETTINGS.assistantDisplayName}</div>
                  <div className={tokens.helperText}>Assistant identity</div>
                </div>
                <div className="text-right">
                  <div className="text-sm font-semibold text-slate-200">{draft.userDisplayName || DEFAULT_SOL_SETTINGS.userDisplayName}</div>
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
