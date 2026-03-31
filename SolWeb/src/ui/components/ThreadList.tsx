import React, { useEffect, useMemo, useRef, useState } from "react";
import { createPortal } from "react-dom";
import type { ThreadSummary } from "../../api/client";
import { config } from "../../config";
import { tokens } from "../tokens";

type Props = {
  threads: ThreadSummary[];
  activeId: string | null;
  onSelect: (id: string) => void;
  onRename: (id: string, title: string) => void;
  onDelete: (id: string) => void;
  disabled?: boolean;
};

export function ThreadList(props: Props) {
  const [filter, setFilter] = useState("");
  const [editingId, setEditingId] = useState<string | null>(null);
  const [value, setValue] = useState("");
  const [menu, setMenu] = useState<{ id: string; x: number; y: number } | null>(null);
  const menuRef = useRef<HTMLDivElement | null>(null);

  const filtered = useMemo(() => {
    const term = filter.trim().toLowerCase();
    if (!term) return props.threads;
    return props.threads.filter((t) => (t.title || config.threadTitleDefault).toLowerCase().includes(term));
  }, [filter, props.threads]);

  const startEdit = (thread: ThreadSummary) => {
    if (props.disabled) return;
    setEditingId(thread.id);
    setValue(thread.title || config.threadTitleDefault);
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
    await props.onRename(editingId, value.trim());
    cancelEdit();
  };

  useEffect(() => {
    if (!menu) return;

    const onPointerDown = (event: MouseEvent) => {
      if (!menuRef.current?.contains(event.target as Node)) {
        setMenu(null);
      }
    };
    const onKeyDown = (event: KeyboardEvent) => {
      if (event.key === "Escape") {
        setMenu(null);
      }
    };

    document.addEventListener("mousedown", onPointerDown);
    window.addEventListener("keydown", onKeyDown);
    return () => {
      document.removeEventListener("mousedown", onPointerDown);
      window.removeEventListener("keydown", onKeyDown);
    };
  }, [menu]);

  return (
    <div
      className="space-y-2"
      onClick={() => {
        setMenu(null);
      }}
    >
      <input
        value={filter}
        onChange={(e) => setFilter(e.target.value)}
        disabled={props.disabled}
        placeholder="Search chats..."
        className={tokens.input}
      />

      {filtered.length === 0 ? (
        <div className="text-xs text-slate-500">No chats.</div>
      ) : (
        <div className="space-y-2">
          {filtered.map((t) => {
            const active = t.id === props.activeId;
            const title = t.title || config.threadTitleDefault;
            return (
              <button
                key={t.id}
                disabled={props.disabled}
                onClick={() => props.onSelect(t.id)}
                onContextMenu={(event) => {
                  event.preventDefault();
                  if (props.disabled) return;
                  setMenu({ id: t.id, x: event.clientX, y: event.clientY });
                }}
                className={[
                  "w-full rounded-[1rem] border px-3 py-2.5 text-left text-sm font-medium transition disabled:cursor-not-allowed disabled:opacity-50",
                  active ? "border-cyan-400/30 bg-slate-900 text-cyan-50 shadow-[0_10px_24px_rgba(8,145,178,0.12)]" : "border-slate-800 bg-slate-950/70 text-slate-200 hover:bg-slate-900/80",
                ].join(" ")}
              >
                <div className="flex items-center justify-between gap-2">
                  {editingId === t.id ? (
                    <input
                      className={`flex-1 ${tokens.inputCompact}`}
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
                        startEdit(t);
                      }}
                    >
                      {title}
                    </span>
                  )}

                  <span className="text-[10px] uppercase tracking-[0.18em] text-slate-500">
                    {new Date(t.updated_at * 1000).toLocaleTimeString()}
                  </span>
                </div>
              </button>
            );
          })}
        </div>
      )}

      {menu
        ? createPortal(
            <div
              ref={menuRef}
              className="nexus-context-menu"
              style={{ left: menu.x, top: menu.y }}
              onClick={(e) => e.stopPropagation()}
              onContextMenu={(e) => e.preventDefault()}
            >
              <button
                className={`${tokens.buttonSecondary} w-full justify-start`}
                onClick={() => {
                  const thread = props.threads.find((x) => x.id === menu.id);
                  if (thread) startEdit(thread);
                  setMenu(null);
                }}
              >
                Rename
              </button>
              <button
                className={`${tokens.buttonDanger} w-full justify-start`}
                onClick={() => {
                  setMenu(null);
                  if (window.confirm("Delete this chat thread? This cannot be undone.")) {
                    props.onDelete(menu.id);
                  }
                }}
              >
                Delete
              </button>
            </div>,
            document.body
          )
        : null}
    </div>
  );
}
