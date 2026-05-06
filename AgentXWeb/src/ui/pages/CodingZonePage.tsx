import React, { useEffect, useMemo, useState } from "react";
import {
  createCodingZoneSession,
  deleteCodingZoneFile,
  deleteCodingZoneSession,
  getCodingZoneFile,
  getCodingZoneSession,
  listCodingZoneLanguages,
  listCodingZoneRuns,
  listCodingZoneSessions,
  runCodingZoneFile,
  writeCodingZoneFile,
  type CodingZoneFileSummary,
  type CodingZoneLanguage,
  type CodingZoneLanguageId,
  type CodingZoneRunResult,
  type CodingZoneSession,
} from "../../api/client";
import { tokens } from "../tokens";

type Props = {
  statusOk: boolean;
  onSystemMessage: (message: string) => void;
  onAskAgentX?: (prompt: string) => void;
};

const DEFAULT_LANGUAGES: CodingZoneLanguage[] = [
  { id: "python", label: "Python", runnable: true },
  { id: "javascript", label: "JavaScript / Node", runnable: true },
  { id: "typescript", label: "TypeScript", runnable: true },
  { id: "shell", label: "Shell", runnable: true },
  { id: "html", label: "HTML", runnable: false, note: "Preview-only for now" },
  { id: "text", label: "Text", runnable: false },
];

const EXT_BY_LANGUAGE: Record<CodingZoneLanguageId, string> = {
  python: "py",
  javascript: "js",
  typescript: "ts",
  shell: "sh",
  lua: "lua",
  cpp: "cpp",
  c: "c",
  go: "go",
  rust: "rs",
  java: "java",
  html: "html",
  text: "txt",
};

function languageLabel(languages: CodingZoneLanguage[], id: string): string {
  return languages.find((item) => item.id === id)?.label ?? id;
}

function bytes(value: number): string {
  if (value < 1024) return `${value} B`;
  if (value < 1024 * 1024) return `${(value / 1024).toFixed(1)} KB`;
  return `${(value / 1024 / 1024).toFixed(1)} MB`;
}

function nextPath(language: CodingZoneLanguageId, files: CodingZoneFileSummary[]): string {
  const ext = EXT_BY_LANGUAGE[language] ?? "txt";
  for (let i = 1; i < 1000; i += 1) {
    const path = i === 1 ? `scratch.${ext}` : `scratch-${i}.${ext}`;
    if (!files.some((file) => file.path === path)) return path;
  }
  return `scratch-${Date.now()}.${ext}`;
}

export function CodingZonePage({ statusOk, onSystemMessage, onAskAgentX }: Props) {
  const [languages, setLanguages] = useState<CodingZoneLanguage[]>(DEFAULT_LANGUAGES);
  const [sessions, setSessions] = useState<CodingZoneSession[]>([]);
  const [session, setSession] = useState<CodingZoneSession | null>(null);
  const [files, setFiles] = useState<CodingZoneFileSummary[]>([]);
  const [activePath, setActivePath] = useState("");
  const [newPath, setNewPath] = useState("");
  const [content, setContent] = useState("");
  const [savedContent, setSavedContent] = useState("");
  const [language, setLanguage] = useState<CodingZoneLanguageId>("python");
  const [title, setTitle] = useState("Scratch");
  const [stdin, setStdin] = useState("");
  const [timeoutS, setTimeoutS] = useState(10);
  const [runs, setRuns] = useState<CodingZoneRunResult[]>([]);
  const [lastRun, setLastRun] = useState<CodingZoneRunResult | null>(null);
  const [busy, setBusy] = useState(false);
  const [running, setRunning] = useState(false);

  const dirty = content !== savedContent;
  const activeLanguage = useMemo(() => languages.find((item) => item.id === language), [language, languages]);
  const runnable = Boolean(session && activePath && activeLanguage?.runnable);

  const openFile = async (sessionId: string, path: string) => {
    const file = await getCodingZoneFile(sessionId, path);
    setActivePath(file.path);
    setNewPath(file.path);
    setContent(file.content);
    setSavedContent(file.content);
  };

  const loadRuns = async (sessionId: string) => {
    try {
      const payload = await listCodingZoneRuns(sessionId);
      setRuns(payload.runs);
      setLastRun(payload.runs[0] ?? null);
    } catch {
      setRuns([]);
      setLastRun(null);
    }
  };

  const openSession = async (sessionId: string) => {
    setBusy(true);
    try {
      const payload = await getCodingZoneSession(sessionId);
      setSession(payload.session);
      setFiles(payload.files);
      setLanguage(payload.session.language);
      setTitle(payload.session.title);
      const path = payload.session.default_file || payload.files[0]?.path || "";
      if (path) await openFile(sessionId, path);
      await loadRuns(sessionId);
      onSystemMessage("");
    } catch (error) {
      onSystemMessage(error instanceof Error ? error.message : "Failed to open Coding Zone session.");
    } finally {
      setBusy(false);
    }
  };

  const refreshSessions = async () => {
    const payload = await listCodingZoneSessions();
    setSessions(payload.sessions);
    return payload.sessions;
  };

  const createSession = async () => {
    setBusy(true);
    try {
      const payload = await createCodingZoneSession({ title: title.trim() || "Scratch", language });
      setSessions((items) => [payload.session, ...items.filter((item) => item.id !== payload.session.id)]);
      setSession(payload.session);
      setFiles(payload.files);
      const path = payload.session.default_file || payload.files[0]?.path || "";
      if (path) await openFile(payload.session.id, path);
      setRuns([]);
      setLastRun(null);
      onSystemMessage("Coding Zone session created.");
    } catch (error) {
      onSystemMessage(error instanceof Error ? error.message : "Failed to create Coding Zone session.");
    } finally {
      setBusy(false);
    }
  };

  const saveFile = async () => {
    if (!session || !activePath) return;
    setBusy(true);
    try {
      const payload = await writeCodingZoneFile(session.id, { path: activePath, content, language });
      setFiles(payload.files);
      setSavedContent(content);
      await refreshSessions();
      onSystemMessage("Coding Zone file saved.");
    } catch (error) {
      onSystemMessage(error instanceof Error ? error.message : "Failed to save file.");
    } finally {
      setBusy(false);
    }
  };

  const createFile = async () => {
    if (!session) return;
    const path = newPath.trim() && newPath.trim() !== activePath ? newPath.trim() : nextPath(language, files);
    setBusy(true);
    try {
      const payload = await writeCodingZoneFile(session.id, { path, content: "", language });
      setFiles(payload.files);
      await openFile(session.id, path);
      onSystemMessage(`Created ${path}.`);
    } catch (error) {
      onSystemMessage(error instanceof Error ? error.message : "Failed to create file.");
    } finally {
      setBusy(false);
    }
  };

  const removeFile = async () => {
    if (!session || !activePath || !window.confirm(`Delete ${activePath}?`)) return;
    setBusy(true);
    try {
      const payload = await deleteCodingZoneFile(session.id, activePath);
      setFiles(payload.files);
      const next = payload.files[0]?.path || "";
      if (next) await openFile(session.id, next);
      else {
        setActivePath("");
        setContent("");
        setSavedContent("");
      }
      onSystemMessage("Coding Zone file deleted.");
    } catch (error) {
      onSystemMessage(error instanceof Error ? error.message : "Failed to delete file.");
    } finally {
      setBusy(false);
    }
  };

  const removeSession = async () => {
    if (!session || !window.confirm(`Delete coding session "${session.title}"?`)) return;
    setBusy(true);
    try {
      await deleteCodingZoneSession(session.id);
      const remaining = sessions.filter((item) => item.id !== session.id);
      setSessions(remaining);
      if (remaining[0]) await openSession(remaining[0].id);
      else {
        setSession(null);
        setFiles([]);
        setActivePath("");
        setContent("");
        setSavedContent("");
        setRuns([]);
        setLastRun(null);
      }
      onSystemMessage("Coding Zone session deleted.");
    } catch (error) {
      onSystemMessage(error instanceof Error ? error.message : "Failed to delete session.");
    } finally {
      setBusy(false);
    }
  };

  const runFile = async () => {
    if (!session || !activePath || !runnable) return;
    setRunning(true);
    try {
      if (dirty) await saveFile();
      const result = await runCodingZoneFile(session.id, { path: activePath, language, stdin, timeout_s: timeoutS });
      setLastRun(result);
      setRuns((items) => [result, ...items.filter((item) => item.id !== result.id)]);
      onSystemMessage(result.ok ? "Coding Zone run passed." : "Coding Zone run failed.");
    } catch (error) {
      onSystemMessage(error instanceof Error ? error.message : "Failed to run file.");
    } finally {
      setRunning(false);
    }
  };

  const askAgentX = (mode: "explain" | "fix" | "review") => {
    if (!onAskAgentX || !activePath) return;
    const output = lastRun ? [
      `Exit code: ${lastRun.exit_code}`,
      lastRun.stdout ? `STDOUT:\n${lastRun.stdout}` : "",
      lastRun.stderr ? `STDERR:\n${lastRun.stderr}` : "",
    ].filter(Boolean).join("\n\n") : "No run output yet.";
    const prompt = mode === "fix"
      ? `Fix this ${languageLabel(languages, language)} Coding Zone file. Return the corrected complete file.\n\nFile: ${activePath}\n\nCode:\n\`\`\`${language}\n${content}\n\`\`\`\n\nLatest output:\n${output}`
      : mode === "review"
        ? `Review this ${languageLabel(languages, language)} Coding Zone file for bugs, safety issues, and improvements.\n\nFile: ${activePath}\n\nCode:\n\`\`\`${language}\n${content}\n\`\`\``
        : `Explain this Coding Zone error and suggest the smallest fix.\n\nFile: ${activePath}\nLanguage: ${languageLabel(languages, language)}\n\nCode:\n\`\`\`${language}\n${content}\n\`\`\`\n\nLatest output:\n${output}`;
    onAskAgentX(prompt);
  };

  useEffect(() => {
    let cancelled = false;
    void (async () => {
      try {
        const [languagePayload, sessionPayload] = await Promise.all([
          listCodingZoneLanguages().catch(() => ({ languages: DEFAULT_LANGUAGES })),
          listCodingZoneSessions(),
        ]);
        if (cancelled) return;
        setLanguages(languagePayload.languages.length ? languagePayload.languages : DEFAULT_LANGUAGES);
        setSessions(sessionPayload.sessions);
        if (sessionPayload.sessions[0]) await openSession(sessionPayload.sessions[0].id);
      } catch (error) {
        if (!cancelled) onSystemMessage(error instanceof Error ? error.message : "Failed to load Coding Zone.");
      }
    })();
    return () => { cancelled = true; };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  return (
    <div className="mt-3 grid min-h-0 flex-1 grid-cols-[300px_minmax(0,1fr)_360px] gap-3">
      <section className="flex min-h-0 flex-col rounded-3xl border border-slate-800 bg-slate-950/70 p-3">
        <div className="mb-3 flex items-center justify-between gap-2">
          <div>
            <div className="text-sm font-bold text-slate-100">Coding Zone</div>
            <div className="text-xs text-slate-500">Scratch sessions and files</div>
          </div>
          <button className={tokens.buttonSecondary} disabled={!statusOk || busy} onClick={() => void refreshSessions()}>Refresh</button>
        </div>
        <div className="space-y-2 rounded-2xl border border-slate-800 bg-slate-900/40 p-2">
          <input className={tokens.input} value={title} onChange={(event) => setTitle(event.target.value)} placeholder="Session title" />
          <select className={tokens.input} value={language} onChange={(event) => setLanguage(event.target.value as CodingZoneLanguageId)}>
            {languages.map((item) => <option key={item.id} value={item.id}>{item.label}</option>)}
          </select>
          <button className={tokens.button} disabled={!statusOk || busy} onClick={() => void createSession()}>New Session</button>
        </div>
        <div className="mt-3 min-h-0 flex-1 space-y-2 overflow-auto">
          {sessions.length ? sessions.map((item) => (
            <button key={item.id} className={["w-full rounded-2xl border px-3 py-2 text-left text-sm", item.id === session?.id ? "border-cyan-400/40 bg-cyan-400/10 text-cyan-50" : "border-slate-800 bg-slate-900/50 text-slate-300 hover:bg-slate-900"].join(" ")} onClick={() => void openSession(item.id)}>
              <div className="font-semibold">{item.title}</div>
              <div className="text-xs text-slate-500">{languageLabel(languages, item.language)} · {item.file_count ?? 0} file(s)</div>
            </button>
          )) : <div className="rounded-2xl border border-dashed border-slate-800 p-3 text-sm text-slate-500">No coding sessions yet.</div>}
        </div>
        {session ? <button className={[tokens.buttonSecondary, "mt-3"].join(" ")} disabled={busy} onClick={() => void removeSession()}>Delete Session</button> : null}
      </section>

      <section className="flex min-h-0 flex-col rounded-3xl border border-slate-800 bg-slate-950/70 p-3">
        <div className="mb-3 flex flex-wrap items-center justify-between gap-2">
          <div className="min-w-0">
            <div className="truncate text-sm font-bold text-slate-100">{activePath || "No file selected"}</div>
            <div className="text-xs text-slate-500">{dirty ? "Unsaved changes" : "Saved"} · {languageLabel(languages, language)}</div>
          </div>
          <div className="flex flex-wrap gap-2">
            <button className={tokens.buttonSecondary} disabled={!session || busy} onClick={() => void createFile()}>New File</button>
            <button className={tokens.buttonSecondary} disabled={!activePath || busy} onClick={() => void removeFile()}>Delete File</button>
            <button className={tokens.button} disabled={!activePath || busy || !dirty} onClick={() => void saveFile()}>Save</button>
            <button className={running ? tokens.buttonDanger : tokens.button} disabled={!statusOk || !runnable || running} onClick={() => void runFile()}>{running ? "Running..." : "Run"}</button>
          </div>
        </div>
        <div className="mb-3 grid grid-cols-[1fr_180px_130px] gap-2">
          <input className={tokens.input} value={newPath} onChange={(event) => setNewPath(event.target.value)} placeholder="new-file.py or folder/file.py" />
          <select className={tokens.input} value={language} onChange={(event) => setLanguage(event.target.value as CodingZoneLanguageId)}>
            {languages.map((item) => <option key={item.id} value={item.id}>{item.label}{item.runnable ? "" : " (preview)"}</option>)}
          </select>
          <input className={tokens.input} type="number" min={1} max={30} value={timeoutS} onChange={(event) => setTimeoutS(Number(event.target.value || 10))} title="Timeout seconds" />
        </div>
        <textarea className={[tokens.textarea, "min-h-0 flex-1 font-mono text-sm leading-5"].join(" ")} value={content} onChange={(event) => setContent(event.target.value)} spellCheck={false} placeholder="Create a session to start coding..." />
      </section>

      <section className="flex min-h-0 flex-col gap-3 rounded-3xl border border-slate-800 bg-slate-950/70 p-3">
        <div>
          <div className="mb-2 text-sm font-bold text-slate-100">Files</div>
          <div className="max-h-44 space-y-1 overflow-auto">
            {files.length ? files.map((file) => (
              <button key={file.path} className={["w-full rounded-xl border px-2 py-1.5 text-left text-xs", file.path === activePath ? "border-cyan-400/40 bg-cyan-400/10 text-cyan-50" : "border-slate-800 bg-slate-900/50 text-slate-300 hover:bg-slate-900"].join(" ")} onClick={() => session ? void openFile(session.id, file.path) : undefined}>
                <div className="truncate font-semibold">{file.path}</div>
                <div className="text-slate-500">{bytes(file.size)}</div>
              </button>
            )) : <div className="text-xs text-slate-500">No files.</div>}
          </div>
        </div>
        <div>
          <div className="mb-2 flex items-center justify-between">
            <div className="text-sm font-bold text-slate-100">Run Output</div>
            {lastRun ? <span className={lastRun.ok ? "text-xs font-bold text-emerald-300" : "text-xs font-bold text-rose-300"}>{lastRun.ok ? "PASS" : `FAIL ${lastRun.exit_code}`}</span> : null}
          </div>
          <textarea className={[tokens.textarea, "h-20 font-mono text-xs"].join(" ")} value={stdin} onChange={(event) => setStdin(event.target.value)} placeholder="Optional stdin..." />
          <pre className="mt-2 max-h-72 min-h-44 overflow-auto rounded-2xl border border-slate-800 bg-black/40 p-3 text-xs text-slate-200">
            {lastRun ? [`$ ${lastRun.command.join(" ")}`, `exit=${lastRun.exit_code} duration=${lastRun.duration_ms}ms`, lastRun.stdout ? `\nSTDOUT:\n${lastRun.stdout}` : "", lastRun.stderr ? `\nSTDERR:\n${lastRun.stderr}` : ""].join("\n") : "Run a file to see stdout/stderr here."}
          </pre>
        </div>
        <div className="space-y-2">
          <div className="text-sm font-bold text-slate-100">Ask AgentX</div>
          <button className={tokens.buttonSecondary} disabled={!activePath || !onAskAgentX} onClick={() => askAgentX("explain")}>Explain Error</button>
          <button className={tokens.buttonSecondary} disabled={!activePath || !onAskAgentX} onClick={() => askAgentX("fix")}>Fix Code</button>
          <button className={tokens.buttonSecondary} disabled={!activePath || !onAskAgentX} onClick={() => askAgentX("review")}>Review Code</button>
        </div>
        <div>
          <div className="mb-2 text-sm font-bold text-slate-100">Run History</div>
          <div className="max-h-40 space-y-1 overflow-auto">
            {runs.length ? runs.map((run) => (
              <button key={run.id} className="w-full rounded-xl border border-slate-800 bg-slate-900/50 px-2 py-1.5 text-left text-xs text-slate-300" onClick={() => setLastRun(run)}>
                <div className={run.ok ? "font-semibold text-emerald-300" : "font-semibold text-rose-300"}>{run.ok ? "PASS" : `FAIL ${run.exit_code}`}</div>
                <div className="truncate text-slate-500">{run.path} · {run.duration_ms}ms</div>
              </button>
            )) : <div className="text-xs text-slate-500">No runs yet.</div>}
          </div>
        </div>
      </section>
    </div>
  );
}
