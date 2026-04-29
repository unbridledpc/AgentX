import React, { useCallback, useEffect, useMemo, useState } from "react";
import {
  createProjectMemory,
  listProjectMemory,
  searchProjectMemory,
  updateProjectMemoryStatus,
  type ProjectMemoryEntry,
  type ProjectMemoryHit,
  type ProjectMemoryStats,
} from "../../api/client";
import { Panel } from "../components/Panel";
import { ScrollArea } from "../components/ScrollArea";
import { AgentXDropdown, type AgentXDropdownOption } from "../components/AgentXDropdown";
import { tokens } from "../tokens";
import { KnowledgePage } from "./KnowledgePage";

type Props = {
  onSystemMessage: (message: string) => void;
};

type Tab = "project" | "rag";

const scopeOptions: AgentXDropdownOption[] = [
  { value: "", label: "All scopes" },
  { value: "global", label: "Global" },
  { value: "module", label: "Module" },
  { value: "file", label: "File" },
  { value: "task", label: "Task" },
  { value: "decision", label: "Decision" },
  { value: "error", label: "Error" },
];

const kindOptions: AgentXDropdownOption[] = [
  { value: "task_note", label: "Task note" },
  { value: "architecture", label: "Architecture" },
  { value: "convention", label: "Convention" },
  { value: "dependency", label: "Dependency" },
  { value: "module_note", label: "Module note" },
  { value: "decision", label: "Decision" },
  { value: "error", label: "Error" },
  { value: "test_result", label: "Test result" },
  { value: "setup", label: "Setup" },
  { value: "user_preference", label: "User preference" },
  { value: "change_summary", label: "Change summary" },
];

const durabilityOptions: AgentXDropdownOption[] = [
  { value: "ephemeral", label: "Ephemeral" },
  { value: "low", label: "Low" },
  { value: "medium", label: "Medium" },
  { value: "high", label: "High" },
];

function formatDate(value: number | null | undefined): string {
  if (!value) return "Unknown";
  const date = new Date(value < 1000000000000 ? value * 1000 : value);
  if (Number.isNaN(date.getTime())) return "Unknown";
  return new Intl.DateTimeFormat(undefined, { month: "short", day: "numeric", hour: "numeric", minute: "2-digit" }).format(date);
}

function chipClass(value: string): string {
  if (value === "high" || value === "active") return "agentx-memory-chip agentx-memory-chip--ok";
  if (value === "discarded" || value === "error") return "agentx-memory-chip agentx-memory-chip--bad";
  if (value === "superseded" || value === "decision") return "agentx-memory-chip agentx-memory-chip--warn";
  return "agentx-memory-chip";
}

function EntryCard({ entry, snippet, onDiscard, onRestore }: { entry: ProjectMemoryEntry; snippet?: string; onDiscard: () => void; onRestore: () => void }) {
  return (
    <article className="agentx-memory-card">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div className="min-w-0">
          <div className="agentx-memory-card__title">{entry.title}</div>
          <div className="mt-1 flex flex-wrap gap-2">
            <span className={chipClass(entry.scope)}>{entry.scope}</span>
            <span className={chipClass(entry.kind)}>{entry.kind}</span>
            <span className={chipClass(entry.durability)}>{entry.durability}</span>
            <span className={chipClass(entry.status)}>{entry.status}</span>
          </div>
        </div>
        <div className="flex shrink-0 gap-2">
          {entry.status === "discarded" ? (
            <button className={tokens.buttonUtility} type="button" onClick={onRestore}>Restore</button>
          ) : (
            <button className={tokens.buttonSecondary} type="button" onClick={onDiscard}>Discard</button>
          )}
        </div>
      </div>
      <div className="agentx-memory-card__summary">{snippet || entry.summary}</div>
      <div className="agentx-memory-card__meta">
        <span>Updated {formatDate(entry.updated_at)}</span>
        {entry.module ? <span>Module: {entry.module}</span> : null}
        {entry.file_path ? <span>File: {entry.file_path}</span> : null}
        <span>Confidence: {Math.round((entry.confidence ?? 0) * 100)}%</span>
      </div>
      {entry.tags?.length ? <div className="agentx-memory-card__tags">{entry.tags.map((tag) => <span key={tag}>{tag}</span>)}</div> : null}
      {entry.decisions?.length ? <div className="agentx-memory-card__section"><strong>Decisions:</strong> {entry.decisions.join(" • ")}</div> : null}
      {entry.assumptions_corrected?.length ? <div className="agentx-memory-card__section"><strong>Corrected assumptions:</strong> {entry.assumptions_corrected.join(" • ")}</div> : null}
      {entry.affected_files?.length ? <div className="agentx-memory-card__section"><strong>Affected files:</strong> {entry.affected_files.join(" • ")}</div> : null}
    </article>
  );
}

export function MemoryPage({ onSystemMessage }: Props) {
  const [tab, setTab] = useState<Tab>("project");
  const [entries, setEntries] = useState<ProjectMemoryEntry[]>([]);
  const [hits, setHits] = useState<ProjectMemoryHit[]>([]);
  const [stats, setStats] = useState<ProjectMemoryStats | null>(null);
  const [query, setQuery] = useState("");
  const [scope, setScope] = useState("");
  const [status, setStatus] = useState("active");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [newEntry, setNewEntry] = useState({ title: "", summary: "", scope: "global", kind: "task_note", durability: "medium", tags: "" });

  const refresh = useCallback(async () => {
    setBusy(true);
    setError(null);
    try {
      const result = await listProjectMemory({ scope: scope || undefined, status: status || undefined, limit: 200 });
      setEntries(result.entries);
      setStats(result.stats);
      if (!query.trim()) setHits([]);
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setBusy(false);
    }
  }, [query, scope, status]);

  useEffect(() => {
    if (tab === "project") void refresh();
  }, [refresh, tab]);

  const runSearch = async () => {
    if (!query.trim()) {
      setHits([]);
      await refresh();
      return;
    }
    setBusy(true);
    setError(null);
    try {
      const result = await searchProjectMemory({ query, scope: scope || undefined, limit: 24 });
      setHits(result.hits);
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setBusy(false);
    }
  };

  const saveNewEntry = async () => {
    if (!newEntry.title.trim() || !newEntry.summary.trim()) return;
    setBusy(true);
    setError(null);
    try {
      await createProjectMemory({
        title: newEntry.title.trim(),
        summary: newEntry.summary.trim(),
        scope: newEntry.scope,
        kind: newEntry.kind,
        durability: newEntry.durability,
        tags: newEntry.tags.split(",").map((item) => item.trim()).filter(Boolean),
        source: "ui",
      });
      setNewEntry({ title: "", summary: "", scope: "global", kind: "task_note", durability: "medium", tags: "" });
      onSystemMessage("Project memory entry saved.");
      await refresh();
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setBusy(false);
    }
  };

  const setEntryStatus = async (entry: ProjectMemoryEntry, nextStatus: "active" | "discarded" | "superseded") => {
    setBusy(true);
    setError(null);
    try {
      await updateProjectMemoryStatus(entry.entry_id, { status: nextStatus, reason: `Changed from Memory page to ${nextStatus}` });
      onSystemMessage(`Memory entry marked ${nextStatus}.`);
      await refresh();
      if (query.trim()) await runSearch();
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setBusy(false);
    }
  };

  const displayed = useMemo(() => {
    if (query.trim() && hits.length) {
      return hits.map((hit) => ({ entry: hit.entry, snippet: hit.snippet || hit.content.slice(0, 500) }));
    }
    return entries.map((entry) => ({ entry, snippet: "" }));
  }, [entries, hits, query]);

  if (tab === "rag") {
    return (
      <div className="mt-3 flex min-h-0 flex-1 flex-col gap-3">
        <div className="agentx-memory-tabs">
          <button type="button" onClick={() => setTab("project")}>Project Memory</button>
          <button type="button" className="agentx-memory-tab--active">RAG Knowledge</button>
        </div>
        <KnowledgePage onSystemMessage={onSystemMessage} />
      </div>
    );
  }

  return (
    <div className="mt-3 grid min-h-0 flex-1 gap-3 overflow-hidden xl:grid-cols-[360px_minmax(0,1fr)]">
      <div className="grid min-h-0 gap-3 overflow-hidden">
        <Panel className="p-4">
          <div className={tokens.smallLabel}>Project Memory</div>
          <div className="mt-1 text-sm text-slate-400">Durable project knowledge with scope, kind, confidence, and lifecycle status.</div>
          <div className="mt-3 grid grid-cols-3 gap-2 text-xs">
            <div className="agentx-pill px-2 py-2">Entries: {stats?.entry_count ?? entries.length}</div>
            <div className="agentx-pill px-2 py-2">Active: {stats?.by_status?.active ?? 0}</div>
            <div className="agentx-pill px-2 py-2">Discarded: {stats?.by_status?.discarded ?? 0}</div>
          </div>
          {error ? <div className="mt-3 rounded-xl border border-rose-400/25 bg-rose-500/10 p-3 text-sm text-rose-100">{error}</div> : null}
        </Panel>

        <Panel className="grid gap-3 p-4">
          <div>
            <div className={tokens.smallLabel}>Search + Filters</div>
            <div className="mt-1 text-xs text-slate-500">Search project memory or filter the ledger by scope/status.</div>
          </div>
          <input className={tokens.input} value={query} onChange={(e) => setQuery(e.target.value)} placeholder="Search architecture, decisions, errors..." onKeyDown={(e) => { if (e.key === "Enter") void runSearch(); }} />
          <div className="grid grid-cols-2 gap-2">
            <AgentXDropdown value={scope} options={scopeOptions} onChange={setScope} />
            <AgentXDropdown value={status} options={[{ value: "active", label: "Active" }, { value: "discarded", label: "Discarded" }, { value: "superseded", label: "Superseded" }, { value: "", label: "All statuses" }]} onChange={setStatus} />
          </div>
          <div className="flex gap-2">
            <button className={tokens.button} disabled={busy} onClick={() => void runSearch()}>{busy ? "Working..." : "Search"}</button>
            <button className={tokens.buttonSecondary} disabled={busy} onClick={() => { setQuery(""); setHits([]); void refresh(); }}>Refresh</button>
          </div>
          <div className="agentx-memory-tabs">
            <button type="button" className="agentx-memory-tab--active">Project Memory</button>
            <button type="button" onClick={() => setTab("rag")}>RAG Knowledge</button>
          </div>
        </Panel>

        <Panel className="grid gap-3 p-4">
          <div>
            <div className={tokens.smallLabel}>Add Memory</div>
            <div className="mt-1 text-xs text-slate-500">Manual durable knowledge. Reflection Gate will automate this in Phase 3.</div>
          </div>
          <input className={tokens.input} value={newEntry.title} onChange={(e) => setNewEntry((prev) => ({ ...prev, title: e.target.value }))} placeholder="Title" />
          <textarea className={tokens.textarea} rows={4} value={newEntry.summary} onChange={(e) => setNewEntry((prev) => ({ ...prev, summary: e.target.value }))} placeholder="Reusable project knowledge..." />
          <div className="grid grid-cols-2 gap-2">
            <AgentXDropdown value={newEntry.scope} options={scopeOptions.filter((item) => item.value)} onChange={(value) => setNewEntry((prev) => ({ ...prev, scope: value }))} />
            <AgentXDropdown value={newEntry.kind} options={kindOptions} onChange={(value) => setNewEntry((prev) => ({ ...prev, kind: value }))} />
          </div>
          <AgentXDropdown value={newEntry.durability} options={durabilityOptions} onChange={(value) => setNewEntry((prev) => ({ ...prev, durability: value }))} />
          <input className={tokens.input} value={newEntry.tags} onChange={(e) => setNewEntry((prev) => ({ ...prev, tags: e.target.value }))} placeholder="tags, comma, separated" />
          <button className={tokens.button} disabled={busy || !newEntry.title.trim() || !newEntry.summary.trim()} onClick={() => void saveNewEntry()}>Save Memory</button>
        </Panel>
      </div>

      <Panel className="flex min-h-0 flex-col gap-3 p-4">
        <div className="flex flex-wrap items-center justify-between gap-2">
          <div>
            <div className={tokens.smallLabel}>{query.trim() ? "Search Results" : "Memory Ledger"}</div>
            <div className="mt-1 text-sm text-slate-400">Visible project memory entries. Discard removes them from active context without deleting history.</div>
          </div>
          <button className={tokens.buttonUtility} disabled={busy} onClick={() => void refresh()}>Refresh</button>
        </div>
        <ScrollArea className="min-h-0 flex-1 pr-1">
          <div className="space-y-3">
            {displayed.length === 0 ? (
              <div className="rounded-2xl border border-dashed border-slate-800 bg-slate-950/60 p-8 text-center text-sm text-slate-400">
                No project memory found yet. Add one manually or wait for Phase 3 reflection to promote task knowledge.
              </div>
            ) : (
              displayed.map(({ entry, snippet }) => (
                <EntryCard
                  key={entry.entry_id}
                  entry={entry}
                  snippet={snippet}
                  onDiscard={() => void setEntryStatus(entry, "discarded")}
                  onRestore={() => void setEntryStatus(entry, "active")}
                />
              ))
            )}
          </div>
        </ScrollArea>
      </Panel>
    </div>
  );
}
