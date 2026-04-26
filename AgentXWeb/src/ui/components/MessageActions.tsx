import React, { useEffect, useMemo, useState } from "react";
import { tokens } from "../tokens";

export type MessageFeedback = "like" | "dislike" | null;

type Props = {
  role: "user" | "assistant" | "system";
  content: string;
  feedback?: MessageFeedback;
  canOpenCanvas?: boolean;
  canSaveScript?: boolean;
  canAddToProject?: boolean;
  onQuote: (content: string) => void;
  onEdit?: (content: string) => void;
  onRetry?: () => void;
  onContinue?: () => void;
  onFeedback?: (feedback: Exclude<MessageFeedback, null>) => void;
  onSaveScript?: () => void;
  onOpenCanvas?: () => void;
  onAddToProject?: () => void;
};

type ActionButtonProps = {
  children: React.ReactNode;
  onClick: () => void;
  title?: string;
  active?: boolean;
  disabled?: boolean;
};

function ActionButton({ children, onClick, title, active = false, disabled = false }: ActionButtonProps) {
  return (
    <button
      type="button"
      className={[
        tokens.buttonUtility,
        "agentx-message-actions__button",
        active ? "agentx-message-actions__button--active" : "",
      ].join(" ")}
      onClick={onClick}
      title={title}
      aria-pressed={active || undefined}
      disabled={disabled}
    >
      {children}
    </button>
  );
}

export function MessageActions({
  role,
  content,
  feedback = null,
  canOpenCanvas = false,
  canSaveScript = false,
  canAddToProject = false,
  onQuote,
  onEdit,
  onRetry,
  onContinue,
  onFeedback,
  onSaveScript,
  onOpenCanvas,
  onAddToProject,
}: Props) {
  const [copied, setCopied] = useState(false);
  const [saved, setSaved] = useState(false);

  useEffect(() => {
    if (!copied) return;
    const id = window.setTimeout(() => setCopied(false), 1400);
    return () => window.clearTimeout(id);
  }, [copied]);

  useEffect(() => {
    if (!saved) return;
    const id = window.setTimeout(() => setSaved(false), 1400);
    return () => window.clearTimeout(id);
  }, [saved]);

  const shortContent = useMemo(() => content.trim(), [content]);

  const copy = async () => {
    try {
      await navigator.clipboard.writeText(content);
      setCopied(true);
    } catch {
      setCopied(false);
    }
  };

  const saveScript = () => {
    onSaveScript?.();
    setSaved(true);
  };

  if (role === "system") return null;

  return (
    <div className="agentx-message-actions" aria-label="Message actions">
      <ActionButton onClick={() => void copy()} title="Copy this message">
        {copied ? "Copied" : "Copy"}
      </ActionButton>

      {role === "user" ? (
        <>
          <ActionButton onClick={() => onEdit?.(content)} title="Edit this prompt" disabled={!onEdit}>
            Edit
          </ActionButton>
          <ActionButton onClick={() => onRetry?.()} title="Retry from this prompt" disabled={!onRetry || !shortContent}>
            Retry
          </ActionButton>
        </>
      ) : (
        <>
          <ActionButton onClick={() => onRetry?.()} title="Retry the previous user prompt" disabled={!onRetry}>
            Retry
          </ActionButton>
          <ActionButton onClick={() => onContinue?.()} title="Ask the model to continue" disabled={!onContinue}>
            Continue
          </ActionButton>
          <ActionButton onClick={() => onFeedback?.("like")} title="Mark this answer as helpful" active={feedback === "like"} disabled={!onFeedback}>
            Like
          </ActionButton>
          <ActionButton onClick={() => onFeedback?.("dislike")} title="Mark this answer as not helpful" active={feedback === "dislike"} disabled={!onFeedback}>
            Dislike
          </ActionButton>
          {canSaveScript ? (
            <ActionButton onClick={saveScript} title="Save code from this response to Scripts" disabled={!onSaveScript}>
              {saved ? "Saved" : "Save Script"}
            </ActionButton>
          ) : null}
          {canOpenCanvas ? (
            <ActionButton onClick={() => onOpenCanvas?.()} title="Open this code in Code Canvas" disabled={!onOpenCanvas}>
              Canvas
            </ActionButton>
          ) : null}
          {canAddToProject ? (
            <ActionButton onClick={() => onAddToProject?.()} title="Add this chat to a project" disabled={!onAddToProject}>
              Project
            </ActionButton>
          ) : null}
          <ActionButton onClick={() => onQuote(content)} title="Quote this answer in the composer">
            Quote
          </ActionButton>
        </>
      )}
    </div>
  );
}
