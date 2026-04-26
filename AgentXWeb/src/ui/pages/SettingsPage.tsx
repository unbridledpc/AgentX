import React, { useEffect, useMemo, useState } from "react";
import { DEFAULT_AGENTX_SETTINGS, DEFAULT_MODEL_BEHAVIOR_SETTINGS, normalizeModelBehaviorSettings, saveSettings, type AgentXSettings, type StatusResponse } from "../../api/client";
import { config } from "../../config";
import { Panel } from "../components/Panel";
import { AgentXDropdown, type AgentXDropdownOption } from "../components/AgentXDropdown";
import { ScrollArea } from "../components/ScrollArea";
import { tokens } from "../tokens";

type Props = {
  statusOk: boolean;
  status: Pick<StatusResponse, "chat_provider" | "chat_model" | "available_chat_models" | "models_error" | "models_refreshing" | "ollama_base_url">;
  settings: AgentXSettings | null;
  onSettingsSaved: (settings: AgentXSettings) => void;
  onSystemMessage: (msg: string) => void;
};

export function SettingsPage(props: Props) {
  const [loading, setLoading] = useState(false);
  const [settings, setSettings] = useState<AgentXSettings>(DEFAULT_AGENTX_SETTINGS);
  const [error, setError] = useState<string | null>(null);

  const rawProvider = (settings?.chatProvider ?? props.status.chat_provider ?? "ollama").toString().toLowerCase();
  const provider = rawProvider === "openai" || rawProvider === "ollama" ? rawProvider : "ollama";
  const model = (settings?.chatModel ?? props.status.chat_model ?? "").toString();
  const ollamaBaseUrl = (settings?.ollamaBaseUrl ?? props.status.ollama_base_url ?? "http://127.0.0.1:11434").toString();
  const ollamaRequestTimeoutS = Math.max(1, Number(settings?.ollamaRequestTimeoutS ?? DEFAULT_AGENTX_SETTINGS.ollamaRequestTimeoutS));
  const modelBehavior = normalizeModelBehaviorSettings(settings.modelBehavior ?? DEFAULT_MODEL_BEHAVIOR_SETTINGS);

  const modelOptions = useMemo(() => {
    const openai = Array.isArray(props.status.available_chat_models?.openai) ? props.status.available_chat_models.openai : [];
    const ollama = Array.isArray(props.status.available_chat_models?.ollama) ? props.status.available_chat_models.ollama : [];
    return { openai, ollama };
  }, [props.status.available_chat_models]);

  const providerOptions = useMemo<AgentXDropdownOption[]>(
    () => [
      { value: "ollama", label: "ollama" },
      { value: "openai", label: "openai" },
    ],
    []
  );

  const currentModelValue = provider === "ollama" && !model ? "__none__" : model;
  const currentModelOptions = useMemo<AgentXDropdownOption[]>(() => {
    if (provider === "openai") {
      return modelOptions.openai.map((item) => ({ value: item, label: item }));
    }
    if (provider === "ollama") {
      if (modelOptions.ollama.length === 0) {
        return [{ value: "__none__", label: "No Ollama models discovered", disabled: true }];
      }
      return modelOptions.ollama.map((item) => ({ value: item, label: item }));
    }
    return [{ value: "__none__", label: "Select a provider first", disabled: true }];
  }, [modelOptions.ollama, modelOptions.openai, provider]);

  useEffect(() => {
    const incoming = { ...DEFAULT_AGENTX_SETTINGS, ...(props.settings ?? {}) };
    setSettings({ ...incoming, modelBehavior: normalizeModelBehaviorSettings(incoming.modelBehavior) });
  }, [props.settings]);

  const updateModelBehavior = (patch: Partial<typeof DEFAULT_MODEL_BEHAVIOR_SETTINGS>) => {
    setSettings((prev) => ({
      ...prev,
      modelBehavior: {
        ...normalizeModelBehaviorSettings(prev.modelBehavior),
        ...patch,
      },
    }));
  };

  const save = async (next: AgentXSettings) => {
    if (!props.statusOk) {
      props.onSystemMessage("Offline - cannot save settings.");
      return;
    }
    setLoading(true);
    setError(null);
    try {
      const saved = await saveSettings({ ...next, modelBehavior: normalizeModelBehaviorSettings(next.modelBehavior) });
      const normalizedSaved = { ...DEFAULT_AGENTX_SETTINGS, ...saved, modelBehavior: normalizeModelBehaviorSettings(saved.modelBehavior) };
      setSettings(normalizedSaved);
      props.onSettingsSaved(normalizedSaved);
    } catch (e) {
      console.error("save settings failed", e);
      setError(e instanceof Error ? e.message : String(e));
      props.onSystemMessage("Settings save failed.");
    } finally {
      setLoading(false);
    }
  };

  return (
    <Panel className="flex min-h-0 flex-col gap-3 p-3">
      <div className="flex items-center justify-between">
        <div className="text-sm font-semibold">Settings</div>
        <div className={tokens.helperText}>{loading ? "Loading..." : ""}</div>
      </div>

      <ScrollArea className="min-h-0 flex-1 pr-1">
        <div className="space-y-3">
          <Panel className="p-3">
            <div className={tokens.smallLabel}>Connection</div>
            <div className="mt-2 text-sm text-slate-300">
              <div>
                <span className="font-semibold">API:</span> {config.apiBase}
              </div>
              <div>
                <span className="font-semibold">Status:</span> {props.statusOk ? "Connected" : "Offline"}
              </div>
            </div>
          </Panel>

          <Panel className="p-3">
            <div className={tokens.smallLabel}>Chat Model</div>
            <div className="mt-2 grid gap-2">
              <label className={tokens.fieldLabel}>Provider</label>
              <AgentXDropdown
                value={provider}
                options={providerOptions}
                disabled={loading}
                placeholder="Select provider"
                onChange={(nextProvider) => {
                  const nextModel =
                    nextProvider === "openai"
                      ? modelOptions.openai[0] ?? ""
                      : nextProvider === "ollama"
                        ? modelOptions.ollama[0] ?? ""
                        : "";
                  setSettings((prev) => ({ ...prev, chatProvider: nextProvider, chatModel: nextModel }));
                }}
              />

              <label className={tokens.fieldLabel}>Model</label>
              <AgentXDropdown
                value={currentModelValue}
                options={currentModelOptions}
                disabled={loading}
                placeholder="Select model"
                onChange={(nextModel) => setSettings((prev) => ({ ...prev, chatModel: nextModel }))}
              />

              <label className={tokens.fieldLabel}>Ollama Endpoint</label>
              <input
                className={tokens.input}
                value={ollamaBaseUrl}
                disabled={loading}
                onChange={(e) => setSettings((prev) => ({ ...prev, ollamaBaseUrl: e.target.value }))}
                placeholder="http://127.0.0.1:11434"
              />
              <div className={tokens.helperText}>
                Used when provider is <span className="font-semibold">ollama</span>. In WSL, Windows-hosted Ollama may need a reachable Windows host IP instead of <code>127.0.0.1</code>.
              </div>

              <label className={tokens.fieldLabel}>Ollama Request Timeout (seconds)</label>
              <input
                className={tokens.inputNumber}
                value={Number.isFinite(ollamaRequestTimeoutS) ? ollamaRequestTimeoutS : DEFAULT_AGENTX_SETTINGS.ollamaRequestTimeoutS}
                disabled={loading}
                type="number"
                min={1}
                step={1}
                onChange={(e) =>
                  setSettings((prev) => ({
                    ...prev,
                    ollamaRequestTimeoutS: Math.max(1, Number(e.target.value || DEFAULT_AGENTX_SETTINGS.ollamaRequestTimeoutS)),
                  }))
                }
              />
              <div className={tokens.helperText}>
                Applies to local Ollama generation requests. Use larger values for big local models; there is no UI cap.
              </div>

              <button
                className={tokens.button}
                disabled={loading}
                onClick={() =>
                  void save({
                    ...settings,
                    chatProvider: provider,
                    chatModel: provider === "ollama" && model === "__none__" ? "" : model,
                    ollamaBaseUrl,
                    ollamaRequestTimeoutS,
                  })
                }
              >
                Save
              </button>

              {props.status.models_error ? (
                <div className={tokens.warningText}>
                  <span className="font-semibold">Model discovery:</span> {props.status.models_error}
                </div>
              ) : null}
            </div>
          </Panel>

          <Panel className="p-3">
            <div className={tokens.smallLabel}>Model Behavior</div>
            <div className="mt-2 grid gap-3 text-sm text-slate-300">
              <div className={tokens.helperText}>
                These instructions are prepended to model requests so local models keep code, exports, and formatting consistent.
              </div>

              <label className="flex items-center gap-2">
                <input
                  type="checkbox"
                  checked={modelBehavior.enabled}
                  disabled={loading}
                  onChange={(e) => updateModelBehavior({ enabled: e.target.checked })}
                />
                <span>Enable global model contract</span>
              </label>

              <label className="flex items-center gap-2">
                <input
                  type="checkbox"
                  checked={modelBehavior.codingContractEnabled}
                  disabled={loading || !modelBehavior.enabled}
                  onChange={(e) => updateModelBehavior({ codingContractEnabled: e.target.checked })}
                />
                <span>Enable coding contract when coding intent is detected</span>
              </label>

              <div className="grid gap-2 sm:grid-cols-2">
                <label className="flex items-center gap-2">
                  <input
                    type="checkbox"
                    checked={modelBehavior.requireFencedCode}
                    disabled={loading || !modelBehavior.enabled}
                    onChange={(e) => updateModelBehavior({ requireFencedCode: e.target.checked })}
                  />
                  <span>Require fenced code blocks</span>
                </label>
                <label className="flex items-center gap-2">
                  <input
                    type="checkbox"
                    checked={modelBehavior.preferStandardLibrary}
                    disabled={loading || !modelBehavior.enabled}
                    onChange={(e) => updateModelBehavior({ preferStandardLibrary: e.target.checked })}
                  />
                  <span>Prefer standard library</span>
                </label>
                <label className="flex items-center gap-2">
                  <input
                    type="checkbox"
                    checked={modelBehavior.windowsAwareExamples}
                    disabled={loading || !modelBehavior.enabled}
                    onChange={(e) => updateModelBehavior({ windowsAwareExamples: e.target.checked })}
                  />
                  <span>Windows-aware examples</span>
                </label>
                <label className="flex items-center gap-2" title="Reserved for the next quality-gate pass.">
                  <input
                    type="checkbox"
                    checked={modelBehavior.autoRepairEnabled}
                    disabled={loading || !modelBehavior.enabled}
                    onChange={(e) => updateModelBehavior({ autoRepairEnabled: e.target.checked })}
                  />
                  <span>Auto-repair missed requirements</span>
                </label>
              </div>

              <label className={tokens.fieldLabel}>Global Instructions</label>
              <textarea
                className={`${tokens.input} min-h-[120px] font-mono text-xs`}
                value={modelBehavior.globalInstructions}
                disabled={loading || !modelBehavior.enabled}
                onChange={(e) => updateModelBehavior({ globalInstructions: e.target.value })}
              />

              <label className={tokens.fieldLabel}>Default Coding Contract</label>
              <textarea
                className={`${tokens.input} min-h-[220px] font-mono text-xs`}
                value={modelBehavior.codingContract}
                disabled={loading || !modelBehavior.enabled || !modelBehavior.codingContractEnabled}
                onChange={(e) => updateModelBehavior({ codingContract: e.target.value })}
              />

              <div className="flex flex-wrap gap-2">
                <button
                  className={tokens.buttonSecondary}
                  disabled={loading}
                  onClick={() => updateModelBehavior(DEFAULT_MODEL_BEHAVIOR_SETTINGS)}
                >
                  Restore Defaults
                </button>
                <button
                  className={tokens.button}
                  disabled={loading}
                  onClick={() => void save({ ...settings, modelBehavior })}
                >
                  Save Model Behavior
                </button>
              </div>
            </div>
          </Panel>

          <Panel className="p-3">
            <div className={tokens.smallLabel}>View</div>
            <div className="mt-2 text-sm text-slate-300">
              Inspector is auto-hidden on non-localhost deployments.
            </div>
          </Panel>

          {error ? (
            <Panel className="border-rose-200 bg-rose-50 p-3">
              <div className="text-sm font-semibold text-rose-800">Settings Error</div>
              <div className="mt-1 text-xs text-rose-800">{error}</div>
            </Panel>
          ) : null}
        </div>
      </ScrollArea>
    </Panel>
  );
}
