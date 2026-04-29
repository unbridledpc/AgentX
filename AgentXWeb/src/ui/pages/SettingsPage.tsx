import React, { useEffect, useMemo, useState } from "react";
import { DEFAULT_AGENTX_SETTINGS, DEFAULT_MODEL_BEHAVIOR_SETTINGS, getGitHubStatus, getOllamaModelUpdates, normalizeModelBehaviorSettings, saveSettings, updateFromGitHub, type AgentXSettings, type GitHubStatusResponse, type OllamaModelUpdatesResponse, type StatusResponse } from "../../api/client";
import { config } from "../../config";
import { Panel } from "../components/Panel";
import { AgentXDropdown, type AgentXDropdownOption } from "../components/AgentXDropdown";
import { ScrollArea } from "../components/ScrollArea";
import { tokens } from "../tokens";


const apiBaseUrl = () => config.apiBase;

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
  const [githubStatus, setGithubStatus] = useState<GitHubStatusResponse | null>(null);
  const [githubBusy, setGithubBusy] = useState(false);
  const [githubMessage, setGithubMessage] = useState<string | null>(null);
  const [ollamaUpdates, setOllamaUpdates] = useState<OllamaModelUpdatesResponse | null>(null);
  const [ollamaUpdatesBusy, setOllamaUpdatesBusy] = useState(false);

  const rawProvider = (settings?.chatProvider ?? props.status.chat_provider ?? "ollama").toString().toLowerCase();
  const provider = rawProvider === "openai" || rawProvider === "ollama" ? rawProvider : "ollama";
  const model = (settings?.chatModel ?? props.status.chat_model ?? "").toString();
  const ollamaBaseUrl = (settings?.ollamaBaseUrl ?? props.status.ollama_base_url ?? "http://127.0.0.1:11434").toString();
  const ollamaEndpoints = props.status.ollama_endpoints ?? {};
  const modelsLastRefresh = props.status.models_last_refresh ?? null;
  const ollamaMultiEndpointEnabled = Boolean(settings?.ollamaMultiEndpointEnabled ?? DEFAULT_AGENTX_SETTINGS.ollamaMultiEndpointEnabled);
  const ollamaFastBaseUrl = (settings?.ollamaFastBaseUrl ?? DEFAULT_AGENTX_SETTINGS.ollamaFastBaseUrl).toString();
  const ollamaHeavyBaseUrl = (settings?.ollamaHeavyBaseUrl ?? DEFAULT_AGENTX_SETTINGS.ollamaHeavyBaseUrl).toString();
  const ollamaFastModel = (settings?.ollamaFastModel ?? DEFAULT_AGENTX_SETTINGS.ollamaFastModel).toString();
  const ollamaHeavyModel = (settings?.ollamaHeavyModel ?? DEFAULT_AGENTX_SETTINGS.ollamaHeavyModel).toString();
  const ollamaDraftEndpoint = (settings?.ollamaDraftEndpoint ?? DEFAULT_AGENTX_SETTINGS.ollamaDraftEndpoint).toString();
  const ollamaReviewEndpoint = (settings?.ollamaReviewEndpoint ?? DEFAULT_AGENTX_SETTINGS.ollamaReviewEndpoint).toString();
  const ollamaRepairEndpoint = (settings?.ollamaRepairEndpoint ?? DEFAULT_AGENTX_SETTINGS.ollamaRepairEndpoint).toString();
  const ollamaFastGpuPin = (settings?.ollamaFastGpuPin ?? DEFAULT_AGENTX_SETTINGS.ollamaFastGpuPin).toString();
  const ollamaHeavyGpuPin = (settings?.ollamaHeavyGpuPin ?? DEFAULT_AGENTX_SETTINGS.ollamaHeavyGpuPin).toString();
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

  const endpointOptions = useMemo<AgentXDropdownOption[]>(
    () => [
      { value: "default", label: "Default endpoint" },
      { value: "fast", label: "Fast endpoint / small GPU" },
      { value: "heavy", label: "Heavy endpoint / big GPU" },
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
  const refreshGithubStatus = async () => {
    if (!props.statusOk) return;
    setGithubBusy(true);
    setGithubMessage(null);
    try {
      const status = await getGitHubStatus(true);
      setGithubStatus(status);
    } catch (e) {
      setGithubMessage(e instanceof Error ? e.message : String(e));
    } finally {
      setGithubBusy(false);
    }
  };

  const runGithubUpdate = async () => {
    if (!props.statusOk) {
      props.onSystemMessage("Offline - cannot update from GitHub.");
      return;
    }
    setGithubBusy(true);
    setGithubMessage(null);
    try {
      const result = await updateFromGitHub({ branch: githubStatus?.branch ?? undefined });
      setGithubStatus(result.after ?? result.before);
      setGithubMessage(result.message + (result.backup_path ? ` Backup: ${result.backup_path}` : ""));
      props.onSystemMessage(result.ok ? "GitHub update completed. Restarting services may be needed." : result.message);
    } catch (e) {
      setGithubMessage(e instanceof Error ? e.message : String(e));
      props.onSystemMessage("GitHub update failed.");
    } finally {
      setGithubBusy(false);
    }
  };

  const refreshOllamaUpdates = async (refresh = false) => {
    if (!props.statusOk) return;
    setOllamaUpdatesBusy(true);
    try {
      setOllamaUpdates(await getOllamaModelUpdates(refresh));
    } catch (e) {
      setOllamaUpdates({ ok: false, source: "https://ollama.com/search", fetched_at: Date.now() / 1000, cached: false, models: [], error: e instanceof Error ? e.message : String(e) });
    } finally {
      setOllamaUpdatesBusy(false);
    }
  };

  useEffect(() => {
    if (!props.statusOk) return;
    void refreshGithubStatus();
    void refreshOllamaUpdates(false);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [props.statusOk]);

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
            <div className="flex items-start justify-between gap-3">
              <div>
                <div className={tokens.smallLabel}>GitHub Status</div>
                <div className="mt-2 flex items-center gap-2 text-sm text-slate-200">
                  <span className={githubStatus?.is_up_to_date ? "agentx-status-dot agentx-status-dot--ok" : "agentx-status-dot agentx-status-dot--bad"} aria-hidden="true" />
                  <span>{githubBusy ? "Checking..." : githubStatus?.message || "Not checked yet"}</span>
                </div>
                <div className={tokens.helperText}>
                  {githubStatus?.branch ? `Branch: ${githubStatus.branch}` : "Checks the local checkout against GitHub."}
                  {githubStatus?.local_commit ? ` • Local: ${githubStatus.local_commit.slice(0, 7)}` : ""}
                  {githubStatus?.remote_commit ? ` • Remote: ${githubStatus.remote_commit.slice(0, 7)}` : ""}
                </div>
                {githubMessage ? <div className={tokens.helperText}>{githubMessage}</div> : null}
              </div>
              <div className="flex shrink-0 gap-2">
                <button type="button" className={tokens.buttonSecondary} disabled={githubBusy || !props.statusOk} onClick={() => void refreshGithubStatus()}>Refresh</button>
                {!githubStatus?.is_up_to_date ? (
                  <button type="button" className={tokens.button} disabled={githubBusy || !props.statusOk} onClick={() => void runGithubUpdate()}>Update</button>
                ) : null}
              </div>
            </div>
          </Panel>

          <Panel className="p-3">
            <div className="flex items-start justify-between gap-3">
              <div>
                <div className={tokens.smallLabel}>Ollama Model Updates</div>
                <div className={tokens.helperText}>Recent model links from Ollama. Cached locally so AgentX does not hammer Ollama.</div>
              </div>
              <button type="button" className={tokens.buttonSecondary} disabled={ollamaUpdatesBusy || !props.statusOk} onClick={() => void refreshOllamaUpdates(true)}>{ollamaUpdatesBusy ? "Refreshing..." : "Refresh"}</button>
            </div>
            {ollamaUpdates?.error ? <div className="mt-2 rounded-xl border border-amber-400/20 bg-amber-500/10 px-3 py-2 text-xs text-amber-100">{ollamaUpdates.error}</div> : null}
            <div className="mt-3 grid gap-2 sm:grid-cols-2">
              {(ollamaUpdates?.models ?? []).slice(0, 8).map((model) => (
                <a key={model.name} href={model.url} target="_blank" rel="noreferrer" className="agentx-model-update-card">
                  <span>{model.name}</span>
                  <small>Open on Ollama</small>
                </a>
              ))}
              {ollamaUpdates && ollamaUpdates.models.length === 0 ? <div className={tokens.helperText}>No model updates available yet.</div> : null}
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

              <div className="mt-3 rounded-2xl border border-cyan-400/20 bg-cyan-400/5 p-3">
                <label className="flex items-center gap-2 text-sm font-semibold text-slate-100">
                  <input
                    type="checkbox"
                    checked={ollamaMultiEndpointEnabled}
                    disabled={loading}
                    onChange={(e) => setSettings((prev) => ({ ...prev, ollamaMultiEndpointEnabled: e.target.checked }))}
                  />
                  <span>Enable multi-Ollama endpoint routing</span>
                </label>
                <div className={`${tokens.helperText} mt-1`}>
                  Route Draft + Review across separate Ollama servers. GPU pins are labels for your startup scripts; AgentX cannot force remote Windows GPU assignment by itself.
                </div>

                <div className="mt-3 grid gap-3 md:grid-cols-2">
                  <div className="grid gap-2">
                    <div className={tokens.smallLabel}>Fast endpoint / small GPU</div>
                    <input className={tokens.input} value={ollamaFastBaseUrl} disabled={loading || !ollamaMultiEndpointEnabled} onChange={(e) => setSettings((prev) => ({ ...prev, ollamaFastBaseUrl: e.target.value }))} placeholder="http://192.168.68.50:11434" />
                    <input className={tokens.input} value={ollamaFastModel} disabled={loading || !ollamaMultiEndpointEnabled} onChange={(e) => setSettings((prev) => ({ ...prev, ollamaFastModel: e.target.value }))} placeholder="qwen2.5-coder:7b-4k-gpu" />
                    <input className={tokens.input} value={ollamaFastGpuPin} disabled={loading || !ollamaMultiEndpointEnabled} onChange={(e) => setSettings((prev) => ({ ...prev, ollamaFastGpuPin: e.target.value }))} placeholder="CUDA_VISIBLE_DEVICES, e.g. 1" />
                  </div>
                  <div className="grid gap-2">
                    <div className={tokens.smallLabel}>Heavy endpoint / big GPU</div>
                    <input className={tokens.input} value={ollamaHeavyBaseUrl} disabled={loading || !ollamaMultiEndpointEnabled} onChange={(e) => setSettings((prev) => ({ ...prev, ollamaHeavyBaseUrl: e.target.value }))} placeholder="http://192.168.68.50:11435" />
                    <input className={tokens.input} value={ollamaHeavyModel} disabled={loading || !ollamaMultiEndpointEnabled} onChange={(e) => setSettings((prev) => ({ ...prev, ollamaHeavyModel: e.target.value }))} placeholder="devstral-small-2:24b-4k-gpu" />
                    <input className={tokens.input} value={ollamaHeavyGpuPin} disabled={loading || !ollamaMultiEndpointEnabled} onChange={(e) => setSettings((prev) => ({ ...prev, ollamaHeavyGpuPin: e.target.value }))} placeholder="CUDA_VISIBLE_DEVICES, e.g. 0" />
                  </div>
                </div>

                <div className="mt-3 grid gap-2 md:grid-cols-3">
                  <div className="grid gap-1">
                    <label className={tokens.fieldLabel}>Draft route</label>
                    <AgentXDropdown value={ollamaDraftEndpoint} options={endpointOptions} disabled={loading || !ollamaMultiEndpointEnabled} onChange={(value) => setSettings((prev) => ({ ...prev, ollamaDraftEndpoint: value as AgentXSettings["ollamaDraftEndpoint"] }))} />
                  </div>
                  <div className="grid gap-1">
                    <label className={tokens.fieldLabel}>Review route</label>
                    <AgentXDropdown value={ollamaReviewEndpoint} options={endpointOptions} disabled={loading || !ollamaMultiEndpointEnabled} onChange={(value) => setSettings((prev) => ({ ...prev, ollamaReviewEndpoint: value as AgentXSettings["ollamaReviewEndpoint"] }))} />
                  </div>
                  <div className="grid gap-1">
                    <label className={tokens.fieldLabel}>Repair route</label>
                    <AgentXDropdown value={ollamaRepairEndpoint} options={endpointOptions} disabled={loading || !ollamaMultiEndpointEnabled} onChange={(value) => setSettings((prev) => ({ ...prev, ollamaRepairEndpoint: value as AgentXSettings["ollamaRepairEndpoint"] }))} />
                  </div>
                </div>
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
                    ollamaMultiEndpointEnabled,
                    ollamaFastBaseUrl,
                    ollamaHeavyBaseUrl,
                    ollamaFastModel,
                    ollamaHeavyModel,
                    ollamaDraftEndpoint: ollamaDraftEndpoint as AgentXSettings["ollamaDraftEndpoint"],
                    ollamaReviewEndpoint: ollamaReviewEndpoint as AgentXSettings["ollamaReviewEndpoint"],
                    ollamaRepairEndpoint: ollamaRepairEndpoint as AgentXSettings["ollamaRepairEndpoint"],
                    ollamaFastGpuPin,
                    ollamaHeavyGpuPin,
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

              <label className="flex items-center gap-2">
                <input
                  type="checkbox"
                  checked={modelBehavior.collaborativeReviewerContractEnabled}
                  disabled={loading || !modelBehavior.enabled}
                  onChange={(e) => updateModelBehavior({ collaborativeReviewerContractEnabled: e.target.checked })}
                />
                <span>Enable collaborative reviewer contract for Draft + Review</span>
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
                <label className="flex items-center gap-2" title="Runs deterministic checks after Draft + Review and sends one repair pass when checks fail.">
                  <input
                    type="checkbox"
                    checked={modelBehavior.autoRepairEnabled}
                    disabled={loading || !modelBehavior.enabled}
                    onChange={(e) => updateModelBehavior({ autoRepairEnabled: e.target.checked })}
                  />
                  <span>Quality gate auto-repair</span>
                </label>
                <label className="flex items-center gap-2" title="Shows pass/repaired/warning details under collaborative coding responses.">
                  <input
                    type="checkbox"
                    checked={modelBehavior.showQualityGateReport}
                    disabled={loading || !modelBehavior.enabled}
                    onChange={(e) => updateModelBehavior({ showQualityGateReport: e.target.checked })}
                  />
                  <span>Show quality gate report</span>
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

              <label className={tokens.fieldLabel}>Collaborative Reviewer Contract</label>
              <div className={tokens.helperText}>
                Used only for Draft + Review. This controls how Devstral reviews Qwen's draft before the final answer.
              </div>
              <textarea
                className={`${tokens.input} min-h-[260px] font-mono text-xs`}
                value={modelBehavior.collaborativeReviewerContract}
                disabled={loading || !modelBehavior.enabled || !modelBehavior.collaborativeReviewerContractEnabled}
                onChange={(e) => updateModelBehavior({ collaborativeReviewerContract: e.target.value })}
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
