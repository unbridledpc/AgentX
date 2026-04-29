import React, { useMemo, useState } from "react";
import type { AgentXSettings, StatusResponse } from "../../api/client";
import { Panel } from "../components/Panel";
import { ScrollArea } from "../components/ScrollArea";
import { tokens } from "../tokens";

type Props = {
  statusOk: boolean;
  status: Pick<StatusResponse, "chat_provider" | "chat_model" | "available_chat_models" | "ollama_base_url" | "ollama_endpoints" | "models_error" | "models_refreshing" | "models_last_refresh">;
  settings: AgentXSettings | null;
  onUseModel: (provider: string, model: string) => void;
  onRefreshModels: () => void;
  onSystemMessage: (message: string) => void;
};

type ModelCard = {
  id: string;
  provider: string;
  model: string;
  endpoint: string;
  baseUrl: string;
  reachable: boolean | null;
  gpuPin: string | null;
  role: string;
  installed: boolean;
};

function baseModelName(model: string): string {
  return model.split(":")[0]?.trim() || model;
}

function ollamaLibraryUrl(model: string): string {
  const base = baseModelName(model).replace(/^x\//, "");
  return `https://ollama.com/library/${encodeURIComponent(base)}`;
}

function modelRole(model: string, settings: AgentXSettings | null | undefined, endpoint: string): string {
  const lower = model.toLowerCase();
  if (settings?.ollamaFastModel === model) return "Fast / Draft";
  if (settings?.ollamaHeavyModel === model) return "Heavy / Review";
  if (/devstral|coder|code|deepseek-coder|qwen.*coder/.test(lower)) return "Coding";
  if (/vision|llava|moondream/.test(lower)) return "Vision";
  if (/llama|mistral|mixtral|qwen|glm|kimi/.test(lower)) return endpoint === "heavy" ? "Reasoning" : "Chat";
  return endpoint === "fast" ? "Fast chat" : endpoint === "heavy" ? "Heavy task" : "General";
}

function endpointLabel(endpoint: string): string {
  if (endpoint === "default") return "Default";
  if (endpoint === "fast") return "Fast";
  if (endpoint === "heavy") return "Heavy";
  if (endpoint === "cloud") return "Cloud";
  return endpoint;
}

function uniqueCards(cards: ModelCard[]): ModelCard[] {
  const seen = new Set<string>();
  const result: ModelCard[] = [];
  for (const card of cards) {
    const key = `${card.provider}:${card.endpoint}:${card.model}`;
    if (seen.has(key)) continue;
    seen.add(key);
    result.push(card);
  }
  const order: Record<string, number> = { default: 0, fast: 1, heavy: 2, cloud: 3 };
  return result.sort((a, b) => (order[a.endpoint] ?? 9) - (order[b.endpoint] ?? 9) || a.model.localeCompare(b.model));
}

export function ModelsPage(props: Props) {
  const [filter, setFilter] = useState("");
  const [endpointFilter, setEndpointFilter] = useState("all");

  const cards = useMemo(() => {
    const output: ModelCard[] = [];
    const endpoints = props.status.ollama_endpoints ?? {};

    for (const [endpoint, info] of Object.entries(endpoints)) {
      for (const model of info.models ?? []) {
        output.push({
          id: `ollama:${endpoint}:${model}`,
          provider: "ollama",
          model,
          endpoint,
          baseUrl: info.base_url || props.status.ollama_base_url || "",
          reachable: typeof info.reachable === "boolean" ? info.reachable : null,
          gpuPin: info.gpu_pin ?? null,
          role: modelRole(model, props.settings, endpoint),
          installed: true,
        });
      }
    }

    for (const [provider, models] of Object.entries(props.status.available_chat_models ?? {})) {
      for (const model of models ?? []) {
        output.push({
          id: `${provider}:available:${model}`,
          provider,
          model,
          endpoint: provider === "ollama" ? "default" : "cloud",
          baseUrl: provider === "ollama" ? props.status.ollama_base_url || "" : "cloud provider",
          reachable: null,
          gpuPin: null,
          role: modelRole(model, props.settings, provider === "ollama" ? "default" : "cloud"),
          installed: provider === "ollama",
        });
      }
    }

    return uniqueCards(output);
  }, [props.status.available_chat_models, props.status.ollama_base_url, props.status.ollama_endpoints, props.settings]);

  const filteredCards = useMemo(() => {
    const term = filter.trim().toLowerCase();
    return cards.filter((card) => {
      if (endpointFilter !== "all" && card.endpoint !== endpointFilter) return false;
      if (!term) return true;
      return [card.model, card.provider, card.endpoint, card.role, card.baseUrl].some((value) => value.toLowerCase().includes(term));
    });
  }, [cards, endpointFilter, filter]);

  const currentProvider = props.status.chat_provider || props.settings?.chatProvider || "ollama";
  const currentModel = props.status.chat_model || props.settings?.chatModel || "";
  const endpointNames = Array.from(new Set(cards.map((card) => card.endpoint))).sort();

  return (
    <div className="agentx-model-deck flex min-h-0 flex-1 flex-col gap-3">
      <div className="agentx-model-deck-hero">
        <div>
          <div className={tokens.smallLabel}>Model Deck</div>
          <h2>Local model command center</h2>
          <p>See every model AgentX can route to, which endpoint owns it, and what role it should play.</p>
        </div>
        <div className="agentx-model-deck-hero__actions">
          <button className={tokens.buttonSecondary} type="button" onClick={props.onRefreshModels} disabled={!props.statusOk || Boolean(props.status.models_refreshing)}>
            {props.status.models_refreshing ? "Refreshing..." : "Refresh Models"}
          </button>
          <span className="agentx-model-deck-pill">Current: {currentProvider}:{currentModel || "none"}</span>
        </div>
      </div>

      {props.status.models_error ? (
        <div className="rounded-2xl border border-amber-400/25 bg-amber-500/10 px-3 py-2 text-sm text-amber-100">{props.status.models_error}</div>
      ) : null}

      <div className="grid min-h-0 gap-3 lg:grid-cols-[minmax(0,1fr)_320px]">
        <Panel className="min-h-0 p-3">
          <div className="flex flex-wrap items-center justify-between gap-3">
            <div>
              <div className={tokens.smallLabel}>Installed / Available Models</div>
              <div className={tokens.helperText}>{filteredCards.length} shown of {cards.length} discovered models.</div>
            </div>
            <div className="flex flex-wrap gap-2">
              <input className={tokens.inputCompact} value={filter} onChange={(event) => setFilter(event.target.value)} placeholder="Search models..." />
              <select className={tokens.inputCompact} value={endpointFilter} onChange={(event) => setEndpointFilter(event.target.value)}>
                <option value="all">All endpoints</option>
                {endpointNames.map((endpoint) => <option key={endpoint} value={endpoint}>{endpointLabel(endpoint)}</option>)}
              </select>
            </div>
          </div>

          <ScrollArea className="mt-3 max-h-[68vh] pr-1">
            <div className="agentx-model-card-grid">
              {filteredCards.map((card) => {
                const selected = card.provider === currentProvider && card.model === currentModel;
                return (
                  <article key={card.id} className={["agentx-model-card", selected ? "agentx-model-card--selected" : ""].join(" ")}>
                    <div className="agentx-model-card__top">
                      <div className="min-w-0">
                        <h3 title={card.model}>{card.model}</h3>
                        <p>{card.provider} · {endpointLabel(card.endpoint)}{card.gpuPin ? ` · GPU ${card.gpuPin}` : ""}</p>
                      </div>
                      <span className={card.reachable === false ? "agentx-model-status agentx-model-status--bad" : "agentx-model-status agentx-model-status--ok"}>
                        {card.reachable === false ? "offline" : card.installed ? "available" : "listed"}
                      </span>
                    </div>
                    <div className="agentx-model-card__meta">
                      <span>Role: <strong>{card.role}</strong></span>
                      <span>Endpoint: <strong>{endpointLabel(card.endpoint)}</strong></span>
                      <span>Base: <strong>{card.baseUrl || "unknown"}</strong></span>
                    </div>
                    <div className="agentx-model-card__actions">
                      <button className={tokens.button} type="button" disabled={!props.statusOk || selected} onClick={() => props.onUseModel(card.provider, card.model)}>
                        {selected ? "Using for Chat" : "Use for Chat"}
                      </button>
                      {card.provider === "ollama" ? <a className={tokens.buttonSecondary} href={ollamaLibraryUrl(card.model)} target="_blank" rel="noreferrer">Open Ollama</a> : null}
                    </div>
                  </article>
                );
              })}
              {filteredCards.length === 0 ? <div className={tokens.helperText}>No models match your current filter.</div> : null}
            </div>
          </ScrollArea>
        </Panel>

        <div className="grid content-start gap-3">
          <Panel className="p-3">
            <div className={tokens.smallLabel}>Routing</div>
            <div className="mt-2 grid gap-2 text-sm text-slate-200">
              <div>Default: <strong>{props.settings?.ollamaBaseUrl || props.status.ollama_base_url || "not set"}</strong></div>
              <div>Fast model: <strong>{props.settings?.ollamaFastModel || "not set"}</strong></div>
              <div>Heavy model: <strong>{props.settings?.ollamaHeavyModel || "not set"}</strong></div>
              <div>Draft route: <strong>{props.settings?.ollamaDraftEndpoint || "default"}</strong></div>
              <div>Review route: <strong>{props.settings?.ollamaReviewEndpoint || "default"}</strong></div>
              <div>Repair route: <strong>{props.settings?.ollamaRepairEndpoint || "default"}</strong></div>
            </div>
          </Panel>

          <Panel className="p-3">
            <div className={tokens.smallLabel}>Recommendations</div>
            <div className="mt-2 grid gap-2 text-sm text-slate-300">
              <div><strong>Coding:</strong> devstral, qwen-coder, deepseek-coder, dolphincoder.</div>
              <div><strong>Drafts:</strong> smaller fast models with low latency.</div>
              <div><strong>Review:</strong> heavier models with stronger reasoning.</div>
              <div><strong>Vision:</strong> models with llava/vision tags when available.</div>
            </div>
          </Panel>
        </div>
      </div>
    </div>
  );
}
