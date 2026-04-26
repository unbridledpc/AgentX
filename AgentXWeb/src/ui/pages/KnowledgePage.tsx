import React, { useCallback, useEffect, useMemo, useState } from "react";
import {
  deleteRagSource,
  getRagStatus,
  ingestRagFolder,
  ingestRagUrl,
  listRagSources,
  queryRag,
  type RagQueryHit,
  type RagSource,
  type RagStatusResponse,
} from "../../api/client";
import { Panel } from "../components/Panel";
import { ScrollArea } from "../components/ScrollArea";
import { tokens } from "../tokens";

type KnowledgePageProps = {
  onSystemMessage: (message: string) => void;
};

function parseTags(raw: string): string[] {
  return raw.split(",").map((item) => item.trim()).filter(Boolean);
}

function formatDate(value: number | null | undefined): string {
  if (!value) return "Unknown";
  const date = new Date(value < 1000000000000 ? value * 1000 : value);
  if (Number.isNaN(date.getTime())) return "Unknown";
  return new Intl.DateTimeFormat(undefined, { month: "short", day: "numeric", hour: "numeric", minute: "2-digit" }).format(date);
}

function sourceKind(source: RagSource): string {
  const kind = source.meta?.kind;
  if (typeof kind === "string" && kind) return kind;
  if (source.source.startsWith("url:")) return "url";
  if (source.source.startsWith("file:")) return "file";
  return "manual";
}

export function KnowledgePage({ onSystemMessage }: KnowledgePageProps) {
  const [status, setStatus] = useState<RagStatusResponse | null>(null);
  const [sources, setSources] = useState<RagSource[]>([]);
  const [sourceQuery, setSourceQuery] = useState("");
  const [busy, setBusy] = useState(false);
  const [url, setUrl] = useState("");
  const [urlTitle, setUrlTitle] = useState("");
  const [collection, setCollection] = useState("General");
  const [tags, setTags] = useState("");
  const [folderPath, setFolderPath] = useState("");
  const [folderCollection, setFolderCollection] = useState("Project Files");
  const [folderTags, setFolderTags] = useState("game, project");
  const [extensions, setExtensions] = useState(".py,.ps1,.lua,.xml,.json,.md,.txt,.ts,.tsx,.js,.yaml,.yml,.toml");
  const [search, setSearch] = useState("");
  const [hits, setHits] = useState<RagQueryHit[]>([]);
  const [error, setError] = useState<string | null>(null);

  const refresh = useCallback(async () => {
    setError(null);
    try {
      const [nextStatus, nextSources] = await Promise.all([
        getRagStatus(),
        listRagSources({ query: sourceQuery || undefined, limit: 200 }),
      ]);
      setStatus(nextStatus);
      setSources(nextSources.sources);
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    }
  }, [sourceQuery]);

  useEffect(() => {
    void refresh();
  }, [refresh]);

  const collections = useMemo(() => {
    const found = new Set<string>();
    for (const source of sources) {
      const value = source.meta?.collection;
      if (typeof value === "string" && value.trim()) found.add(value.trim());
    }
    return Array.from(found).sort();
  }, [sources]);

  const ingestUrl = async () => {
    setBusy(true);
    setError(null);
    try {
      const result = await ingestRagUrl({ url, title: urlTitle || undefined, collection, tags: parseTags(tags) });
      setUrl("");
      setUrlTitle("");
      onSystemMessage(`Ingested URL: ${result.title} (${result.chunks} chunks).`);
      await refresh();
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setBusy(false);
    }
  };

  const ingestFolder = async () => {
    setBusy(true);
    setError(null);
    try {
      const extList = extensions.split(",").map((item) => item.trim()).filter(Boolean);
      await ingestRagFolder({ path: folderPath, collection: folderCollection, tags: parseTags(folderTags), extensions: extList, max_files: 500, max_bytes: 8_000_000 });
      onSystemMessage("Folder ingest finished.");
      await refresh();
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setBusy(false);
    }
  };

  const runSearch = async () => {
    if (!search.trim()) return;
    setBusy(true);
    setError(null);
    try {
      const result = await queryRag({ query: search, k: 8 });
      setHits(result.hits);
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setBusy(false);
    }
  };

  const removeSource = async (docId: string) => {
    setBusy(true);
    setError(null);
    try {
      await deleteRagSource(docId);
      onSystemMessage("Knowledge source removed.");
      await refresh();
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="mt-3 grid min-h-0 flex-1 gap-3 overflow-hidden xl:grid-cols-[380px_1fr]">
      <div className="grid min-h-0 gap-3 overflow-hidden">
        <Panel className="p-4">
          <div className={tokens.smallLabel}>Knowledge Ingest</div>
          <div className="mt-1 text-sm text-slate-400">
            Ingest URLs and local project folders into AgentX RAG. This does not retrain the model; it creates searchable local knowledge used as chat context.
          </div>
          {status ? (
            <div className="mt-3 grid grid-cols-3 gap-2 text-xs">
              <div className="agentx-pill px-2 py-2">RAG: {status.enabled ? "On" : "Off"}</div>
              <div className="agentx-pill px-2 py-2">Docs: {status.doc_count}</div>
              <div className="agentx-pill px-2 py-2">Chunks: {status.chunk_count}</div>
            </div>
          ) : null}
          {error ? <div className="mt-3 rounded-xl border border-rose-400/25 bg-rose-500/10 p-3 text-sm text-rose-100">{error}</div> : null}
        </Panel>

        <Panel className="grid gap-3 p-4">
          <div>
            <div className={tokens.smallLabel}>Ingest URL</div>
            <div className="mt-1 text-xs text-slate-500">Example: https://en.wikipedia.org/wiki/Lua</div>
          </div>
          <input className={tokens.input} value={url} onChange={(e) => setUrl(e.target.value)} placeholder="https://..." />
          <input className={tokens.input} value={urlTitle} onChange={(e) => setUrlTitle(e.target.value)} placeholder="Optional title" />
          <div className="grid grid-cols-2 gap-2">
            <input className={tokens.input} value={collection} onChange={(e) => setCollection(e.target.value)} placeholder="Collection" />
            <input className={tokens.input} value={tags} onChange={(e) => setTags(e.target.value)} placeholder="tags, comma, separated" />
          </div>
          <button className={tokens.button} disabled={busy || !url.trim()} onClick={() => void ingestUrl()}>Ingest URL</button>
          <div className="text-xs text-slate-500">URL ingest follows web policy. Enable web access/allow domains if needed.</div>
        </Panel>

        <Panel className="grid gap-3 p-4">
          <div>
            <div className={tokens.smallLabel}>Ingest Local Folder</div>
            <div className="mt-1 text-xs text-slate-500">Use this for game files, AgentX source, Lua/XML scripts, docs, and configs.</div>
          </div>
          <input className={tokens.input} value={folderPath} onChange={(e) => setFolderPath(e.target.value)} placeholder="F:\\YourGameFolder or /home/user/project" />
          <div className="grid grid-cols-2 gap-2">
            <input className={tokens.input} value={folderCollection} onChange={(e) => setFolderCollection(e.target.value)} placeholder="Collection" />
            <input className={tokens.input} value={folderTags} onChange={(e) => setFolderTags(e.target.value)} placeholder="tags" />
          </div>
          <textarea className={tokens.textarea} rows={2} value={extensions} onChange={(e) => setExtensions(e.target.value)} />
          <button className={tokens.button} disabled={busy || !folderPath.trim()} onClick={() => void ingestFolder()}>Ingest Folder</button>
          <div className="text-xs text-slate-500">Folder ingest is restricted by AGENTX_RAG_ALLOWED_ROOTS.</div>
        </Panel>
      </div>

      <div className="grid min-h-0 gap-3 overflow-hidden">
        <Panel className="grid gap-3 p-4">
          <div className="flex flex-wrap items-center justify-between gap-2">
            <div>
              <div className={tokens.smallLabel}>Search Knowledge</div>
              <div className="mt-1 text-sm text-slate-400">Search the same local RAG store AgentX uses during chat.</div>
            </div>
            <button className={tokens.buttonUtility} onClick={() => void refresh()}>Refresh</button>
          </div>
          <div className="flex gap-2">
            <input className={tokens.input} value={search} onChange={(e) => setSearch(e.target.value)} placeholder="Search Lua, game files, AgentX code..." onKeyDown={(e) => { if (e.key === "Enter") void runSearch(); }} />
            <button className={tokens.button} disabled={busy || !search.trim()} onClick={() => void runSearch()}>Search</button>
          </div>
          {hits.length ? (
            <div className="space-y-2">
              {hits.map((hit) => (
                <div key={`${hit.doc_id}:${hit.chunk_id}`} className="rounded-2xl border border-slate-800 bg-slate-950/70 p-3 text-sm">
                  <div className="font-semibold text-slate-100">{hit.title}</div>
                  <div className="mt-1 truncate text-xs text-slate-500">{hit.source}</div>
                  <div className="mt-2 whitespace-pre-wrap text-slate-300">{hit.snippet || hit.content.slice(0, 500)}</div>
                </div>
              ))}
            </div>
          ) : null}
        </Panel>

        <Panel className="flex min-h-0 flex-col gap-3 p-4">
          <div className="flex flex-wrap items-center justify-between gap-2">
            <div>
              <div className={tokens.smallLabel}>Sources</div>
              <div className="mt-1 text-sm text-slate-400">{sources.length} indexed sources{collections.length ? ` · ${collections.length} collections` : ""}</div>
            </div>
            <input className={[tokens.input, "max-w-xs"].join(" ")} value={sourceQuery} onChange={(e) => setSourceQuery(e.target.value)} placeholder="Filter sources..." />
          </div>
          <ScrollArea className="min-h-0 flex-1 pr-1">
            <div className="space-y-2">
              {sources.length === 0 ? (
                <div className="rounded-2xl border border-slate-800 bg-slate-950/70 p-4 text-sm text-slate-400">No knowledge sources yet.</div>
              ) : sources.map((source) => (
                <div key={source.doc_id} className="rounded-2xl border border-slate-800 bg-slate-950/75 p-3 text-sm">
                  <div className="flex items-start justify-between gap-3">
                    <div className="min-w-0">
                      <div className="truncate font-semibold text-slate-100">{source.title}</div>
                      <div className="mt-1 truncate text-xs text-slate-500">{source.source}</div>
                    </div>
                    <button className={tokens.buttonUtility} disabled={busy} onClick={() => void removeSource(source.doc_id)}>Delete</button>
                  </div>
                  <div className="mt-2 flex flex-wrap gap-2 text-xs text-slate-500">
                    <span className="agentx-pill px-2 py-1">{sourceKind(source)}</span>
                    <span className="agentx-pill px-2 py-1">{source.chunk_count} chunks</span>
                    <span className="agentx-pill px-2 py-1">{formatDate(source.updated_at)}</span>
                    {typeof source.meta?.collection === "string" ? <span className="agentx-pill px-2 py-1">{source.meta.collection}</span> : null}
                  </div>
                </div>
              ))}
            </div>
          </ScrollArea>
        </Panel>
      </div>
    </div>
  );
}
