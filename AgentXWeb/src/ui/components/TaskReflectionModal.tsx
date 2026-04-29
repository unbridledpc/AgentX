import React, { useEffect, useMemo, useState } from "react";
import { draftTaskReflection, promoteTaskReflection, type ReflectionMessage, type TaskReflectionDraft } from "../../api/client";
import { tokens } from "../tokens";

type Props = {
  open: boolean;
  statusOk: boolean;
  threadTitle?: string | null;
  projectName?: string | null;
  model?: string | null;
  messages: ReflectionMessage[];
  onClose: () => void;
  onSaved: (message: string) => void;
};

function ListEditor({ label, values, onChange }: { label: string; values: string[]; onChange: (values: string[]) => void }) {
  return (
    <label className="agentx-reflection-field">
      <span>{label}</span>
      <textarea
        className={tokens.textarea}
        rows={4}
        value={values.join("\n")}
        onChange={(event) => onChange(event.target.value.split("\n").map((x) => x.trim()).filter(Boolean))}
      />
    </label>
  );
}

export function TaskReflectionModal({ open, statusOk, threadTitle, projectName, model, messages, onClose, onSaved }: Props) {
  const [loading, setLoading] = useState(false);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [draft, setDraft] = useState<TaskReflectionDraft | null>(null);
  const latestMessages = useMemo(() => messages.slice(-18), [messages]);

  useEffect(() => {
    if (!open) return;
    const onKey = (event: KeyboardEvent) => {
      if (event.key === "Escape") onClose();
    };
    window.addEventListener("keydown", onKey, true);
    return () => window.removeEventListener("keydown", onKey, true);
  }, [open, onClose]);

  useEffect(() => {
    if (!open || !statusOk) return;
    let cancelled = false;
    setLoading(true);
    setError(null);
    draftTaskReflection({
      task_title: threadTitle || "Current AgentX task",
      project_name: projectName || "AgentX",
      thread_title: threadTitle || null,
      messages: latestMessages,
      model: model || null,
    })
      .then((next) => {
        if (!cancelled) setDraft(next);
      })
      .catch((err) => {
        if (!cancelled) setError(err instanceof Error ? err.message : String(err));
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, [open, statusOk, threadTitle, projectName, model, latestMessages]);

  if (!open) return null;

  const update = (patch: Partial<TaskReflectionDraft>) => setDraft((prev) => (prev ? { ...prev, ...patch } : prev));

  const save = async () => {
    if (!draft) return;
    setSaving(true);
    setError(null);
    try {
      const result = await promoteTaskReflection({
        title: draft.title,
        summary: draft.summary,
        scope: "task",
        kind: "task_note",
        durability: "high",
        tags: ["phase3", "task-reflection", "agentx"],
        affected_files: draft.affected_files,
        decisions: draft.decisions,
        assumptions_corrected: draft.assumptions_corrected,
        evidence: draft.changed,
        confidence: draft.confidence,
      });
      onSaved(`Task reflection saved to project memory: ${result.entry_id}`);
      onClose();
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setSaving(false);
    }
  };

  return (
    <div className="agentx-reflection-modal-layer" onClick={onClose}>
      <section className="agentx-reflection-modal" onClick={(event) => event.stopPropagation()}>
        <header className="agentx-reflection-header">
          <div>
            <div className="agentx-reflection-eyebrow">Phase 3</div>
            <h2>Task Reflection Gate</h2>
            <p>Review what changed before this task becomes durable AgentX project memory.</p>
          </div>
          <button type="button" className={tokens.buttonSecondary} onClick={onClose}>Close</button>
        </header>

        {loading ? <div className="agentx-reflection-loading">Drafting task reflection...</div> : null}
        {error ? <div className="agentx-reflection-error">{error}</div> : null}

        {draft ? (
          <div className="agentx-reflection-grid">
            <label className="agentx-reflection-field agentx-reflection-field--wide">
              <span>Title</span>
              <input className={tokens.input} value={draft.title} onChange={(event) => update({ title: event.target.value })} />
            </label>
            <label className="agentx-reflection-field agentx-reflection-field--wide">
              <span>Summary</span>
              <textarea className={tokens.textarea} rows={4} value={draft.summary} onChange={(event) => update({ summary: event.target.value })} />
            </label>
            <ListEditor label="What changed" values={draft.changed} onChange={(changed) => update({ changed })} />
            <ListEditor label="Affected files" values={draft.affected_files} onChange={(affected_files) => update({ affected_files })} />
            <ListEditor label="Decisions" values={draft.decisions} onChange={(decisions) => update({ decisions })} />
            <ListEditor label="Assumptions corrected" values={draft.assumptions_corrected} onChange={(assumptions_corrected) => update({ assumptions_corrected })} />
            <ListEditor label="Durable memory candidates" values={draft.durable_memory} onChange={(durable_memory) => update({ durable_memory })} />
            <ListEditor label="Discard as task noise" values={draft.discard_noise} onChange={(discard_noise) => update({ discard_noise })} />
            <ListEditor label="Done checklist" values={draft.checklist} onChange={(checklist) => update({ checklist })} />
          </div>
        ) : null}

        <footer className="agentx-reflection-actions">
          <button type="button" className={tokens.buttonSecondary} onClick={onClose}>Discard</button>
          <button type="button" className={tokens.button} disabled={!draft || saving || !statusOk} onClick={() => void save()}>
            {saving ? "Saving..." : "Save to Project Memory"}
          </button>
        </footer>
      </section>
    </div>
  );
}
