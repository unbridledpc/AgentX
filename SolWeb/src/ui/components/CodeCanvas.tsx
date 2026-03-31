import React, { useEffect, useMemo, useRef, useState } from "react";
import { tokens } from "../tokens";
import type { CodeCanvasLanguage, CodeCanvasState } from "../codeCanvas";
import { languageAccentClass } from "../codeCanvas";

type Props = {
  canvas: CodeCanvasState;
  onUpdate: (update: Partial<CodeCanvasState>) => void;
  onClose: () => void;
  onSendSelection: (payload: { scope: "selection" | "document"; content: string; language: CodeCanvasLanguage }) => void;
};

function languageLabel(language: CodeCanvasLanguage): string {
  if (language === "typescript") return "TypeScript";
  if (language === "javascript") return "JavaScript";
  if (language === "python") return "Python";
  if (language === "html") return "HTML";
  if (language === "css") return "CSS";
  if (language === "json") return "JSON";
  if (language === "shell") return "Shell";
  if (language === "csharp") return "C#";
  if (language === "rust") return "Rust";
  return "Code";
}

export function CodeCanvas({ canvas, onUpdate, onClose, onSendSelection }: Props) {
  const editorRef = useRef<HTMLTextAreaElement | null>(null);
  const [selection, setSelection] = useState({ start: 0, end: 0 });
  const [copied, setCopied] = useState(false);
  const selectedText = useMemo(() => {
    if (selection.end <= selection.start) return "";
    return canvas.content.slice(selection.start, selection.end);
  }, [canvas.content, selection.end, selection.start]);

  useEffect(() => {
    if (!copied) return;
    const id = window.setTimeout(() => setCopied(false), 1400);
    return () => window.clearTimeout(id);
  }, [copied]);

  const syncSelection = () => {
    const node = editorRef.current;
    if (!node) return;
    setSelection({ start: node.selectionStart, end: node.selectionEnd });
  };

  const copyCode = async () => {
    try {
      await navigator.clipboard.writeText(selectedText || canvas.content);
      setCopied(true);
    } catch {
      setCopied(false);
    }
  };

  return (
    <aside
      className={[
        "nexus-code-canvas",
        languageAccentClass(canvas.language),
        canvas.viewMode === "fullscreen" ? "nexus-code-canvas--fullscreen" : "nexus-code-canvas--docked",
      ].join(" ")}
    >
      <div className="nexus-code-canvas__header">
        <div className="nexus-code-canvas__identity">
          <div>
            <div className="nexus-code-canvas__eyebrow">Code Canvas</div>
            <div className="nexus-code-canvas__title">{canvas.title}</div>
          </div>
          <span className="nexus-code-canvas__language">{languageLabel(canvas.language)}</span>
        </div>
        <div className="nexus-code-canvas__header-actions">
          <button className={tokens.buttonUtility} onClick={() => void copyCode()}>
            {copied ? "Copied" : "Copy"}
          </button>
          <button
            className={tokens.buttonUtility}
            onClick={() => onSendSelection({ scope: selectedText ? "selection" : "document", content: selectedText || canvas.content, language: canvas.language })}
            disabled={!canvas.content.trim()}
          >
            Send to chat
          </button>
          <button
            className={tokens.buttonUtility}
            onClick={() => onUpdate({ viewMode: canvas.viewMode === "fullscreen" ? "docked" : "fullscreen" })}
          >
            {canvas.viewMode === "fullscreen" ? "Dock" : "Expand"}
          </button>
          <button className={tokens.buttonUtility} onClick={onClose}>
            Close
          </button>
        </div>
      </div>

      <div className="nexus-code-canvas__meta">
        <span>{canvas.isDirty ? "Edited locally" : "Synced from assistant output"}</span>
        <span>{selectedText ? `${selectedText.split("\n").length} lines selected` : `${canvas.content.split("\n").length} lines`}</span>
      </div>

      <div className="nexus-code-canvas__editor-wrap">
        <textarea
          ref={editorRef}
          className={[tokens.textarea, "nexus-code-canvas__editor"].join(" ")}
          value={canvas.content}
          onChange={(event) => onUpdate({ content: event.target.value, isDirty: true })}
          onSelect={syncSelection}
          onKeyUp={syncSelection}
          onMouseUp={syncSelection}
          spellCheck={false}
          placeholder="Code output will appear here"
        />
      </div>
    </aside>
  );
}
