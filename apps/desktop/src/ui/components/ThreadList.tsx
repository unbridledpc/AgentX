import React, { useState } from "react";
import { ThreadSummary } from "../../api/client";
import { THREAD_TITLE_DEFAULT } from "../../config";

type Props = {
  threads: ThreadSummary[];
  activeId?: string;
  onSelect: (id: string) => void;
  onRename: (id: string, title: string) => void;
  onDelete: (id: string) => void;
  offline: boolean;
};

export function ThreadList({ threads, activeId, onSelect, onRename, onDelete, offline }: Props) {
  const [editingId, setEditingId] = useState<string | null>(null);
  const [value, setValue] = useState("");
  const [menu, setMenu] = useState<{ id: string; x: number; y: number } | null>(null);

  const startEdit = (thread: ThreadSummary) => {
    if (offline) return;
    setEditingId(thread.id);
    setValue(thread.title || THREAD_TITLE_DEFAULT);
  };

  const cancelEdit = () => {
    setEditingId(null);
    setValue("");
  };

  const handleSave = async () => {
    if (!editingId || !value.trim()) {
      cancelEdit();
      return;
    }
    await onRename(editingId, value.trim());
    cancelEdit();
  };

  return (
    <div
      className="space-y-2"
      onClick={() => {
        setMenu(null);
      }}
    >
      {threads.length === 0 && (
        <div className="text-xs text-slate-500">No threads yet.</div>
      )}
      {threads.map((thread) => {
        const isActive = thread.id === activeId;
        const title = thread.title || THREAD_TITLE_DEFAULT;
        return (
          <button
            key={thread.id}
            onClick={() => onSelect(thread.id)}
            onContextMenu={(event) => {
              event.preventDefault();
              setMenu({ id: thread.id, x: event.clientX, y: event.clientY });
            }}
            className={`w-full rounded-xl border px-3 py-2 text-left text-sm font-medium transition ${
              isActive
                ? "border-slate-900 bg-slate-900 text-white"
                : "border-slate-200 bg-white text-slate-900 hover:bg-slate-50"
            }`}
          >
            <div className="flex items-center justify-between gap-2">
              {editingId === thread.id ? (
                <input
                  className="flex-1 rounded border border-slate-300 px-2 py-1 text-xs text-slate-900"
                  value={value}
                  onChange={(event) => setValue(event.target.value)}
                  onKeyDown={(event) => {
                    if (event.key === "Enter") {
                      event.preventDefault();
                      void handleSave();
                    } else if (event.key === "Escape") {
                      event.preventDefault();
                      cancelEdit();
                    }
                  }}
                  onClick={(event) => event.stopPropagation()}
                  autoFocus
                />
              ) : (
                <span
                  className="flex-1 truncate"
                  onClick={(event) => {
                    event.stopPropagation();
                    startEdit(thread);
                  }}
                >
                  {title}
                </span>
              )}
              <span className="text-[10px] uppercase tracking-wide text-slate-400">
                {new Date(thread.updated_at * 1000).toLocaleTimeString()}
              </span>
            </div>
          </button>
        );
      })}

      {menu && (
        <div
          className="fixed z-50 min-w-[180px] rounded-xl border border-slate-200 bg-white p-1 text-sm shadow-sm"
          style={{ left: menu.x, top: menu.y }}
          onClick={(e) => e.stopPropagation()}
          onContextMenu={(e) => e.preventDefault()}
        >
          <button
            className="w-full rounded-lg px-3 py-2 text-left hover:bg-slate-50 disabled:opacity-50"
            disabled={offline}
            onClick={() => {
              const thread = threads.find((t) => t.id === menu.id);
              if (thread) startEdit(thread);
              setMenu(null);
            }}
          >
            Rename
          </button>
          <button
            className="w-full rounded-lg px-3 py-2 text-left text-rose-700 hover:bg-rose-50 disabled:opacity-50"
            disabled={offline}
            onClick={() => {
              setMenu(null);
              if (window.confirm("Delete this chat thread? This cannot be undone.")) {
                onDelete(menu.id);
              }
            }}
          >
            Delete
          </button>
        </div>
      )}
    </div>
  );
}
