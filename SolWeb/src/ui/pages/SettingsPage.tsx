import React, { useEffect, useMemo, useState } from "react";
import { DEFAULT_SOL_SETTINGS, saveSettings, type SolSettings, type StatusResponse } from "../../api/client";
import { config } from "../../config";
import { Panel } from "../components/Panel";
import { NexusDropdown, type NexusDropdownOption } from "../components/NexusDropdown";
import { ScrollArea } from "../components/ScrollArea";
import { tokens } from "../tokens";

type Props = {
  statusOk: boolean;
  status: Pick<StatusResponse, "chat_provider" | "chat_model" | "available_chat_models" | "models_error" | "models_refreshing" | "ollama_base_url">;
  settings: SolSettings | null;
  onSettingsSaved: (settings: SolSettings) => void;
  onSystemMessage: (msg: string) => void;
};

export function SettingsPage(props: Props) {
  const [loading, setLoading] = useState(false);
  const [settings, setSettings] = useState<SolSettings>(DEFAULT_SOL_SETTINGS);
  const [error, setError] = useState<string | null>(null);

  const provider = (settings?.chatProvider ?? props.status.chat_provider ?? "stub").toString();
  const model = (settings?.chatModel ?? props.status.chat_model ?? "stub").toString();
  const ollamaBaseUrl = (settings?.ollamaBaseUrl ?? props.status.ollama_base_url ?? "http://127.0.0.1:11434").toString();
  const ollamaRequestTimeoutS = Math.max(5, Number(settings?.ollamaRequestTimeoutS ?? DEFAULT_SOL_SETTINGS.ollamaRequestTimeoutS));

  const modelOptions = useMemo(() => {
    const openai = Array.isArray(props.status.available_chat_models?.openai) ? props.status.available_chat_models.openai : [];
    const ollama = Array.isArray(props.status.available_chat_models?.ollama) ? props.status.available_chat_models.ollama : [];
    return { openai, ollama };
  }, [props.status.available_chat_models]);

  const providerOptions = useMemo<NexusDropdownOption[]>(
    () => [
      { value: "openai", label: "openai" },
      { value: "ollama", label: "ollama" },
      { value: "stub", label: "stub" },
    ],
    []
  );

  const currentModelValue = provider === "ollama" && !model ? "__none__" : model;
  const currentModelOptions = useMemo<NexusDropdownOption[]>(() => {
    if (provider === "openai") {
      return modelOptions.openai.map((item) => ({ value: item, label: item }));
    }
    if (provider === "ollama") {
      if (modelOptions.ollama.length === 0) {
        return [{ value: "__none__", label: "No Ollama models discovered", disabled: true }];
      }
      return modelOptions.ollama.map((item) => ({ value: item, label: item }));
    }
    return [{ value: "stub", label: "stub" }];
  }, [modelOptions.ollama, modelOptions.openai, provider]);

  useEffect(() => {
    setSettings({ ...DEFAULT_SOL_SETTINGS, ...(props.settings ?? {}) });
  }, [props.settings]);

  const save = async (next: SolSettings) => {
    if (!props.statusOk) {
      props.onSystemMessage("Offline - cannot save settings.");
      return;
    }
    setLoading(true);
    setError(null);
    try {
      const saved = await saveSettings(next);
      setSettings({ ...DEFAULT_SOL_SETTINGS, ...saved });
      props.onSettingsSaved(saved);
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
              <NexusDropdown
                value={provider}
                options={providerOptions}
                disabled={loading}
                placeholder="Select provider"
                onChange={(nextProvider) => {
                  const nextModel =
                    nextProvider === "openai"
                      ? modelOptions.openai[0] ?? "stub"
                      : nextProvider === "ollama"
                        ? modelOptions.ollama[0] ?? ""
                        : "stub";
                  setSettings((prev) => ({ ...prev, chatProvider: nextProvider, chatModel: nextModel }));
                }}
              />

              <label className={tokens.fieldLabel}>Model</label>
              <NexusDropdown
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
                value={Number.isFinite(ollamaRequestTimeoutS) ? ollamaRequestTimeoutS : DEFAULT_SOL_SETTINGS.ollamaRequestTimeoutS}
                disabled={loading}
                type="number"
                min={5}
                max={600}
                onChange={(e) =>
                  setSettings((prev) => ({
                    ...prev,
                    ollamaRequestTimeoutS: Math.max(5, Number(e.target.value || DEFAULT_SOL_SETTINGS.ollamaRequestTimeoutS)),
                  }))
                }
              />
              <div className={tokens.helperText}>
                Applies to local Ollama generation requests. Increase this for slower local models to avoid premature timeouts.
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
