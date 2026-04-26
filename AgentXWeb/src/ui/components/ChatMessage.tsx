import React from "react";

import type { Message } from "../../api/client";
import { MessageActions, type MessageFeedback } from "./MessageActions";
import { MessageBubble } from "./MessageBubble";
import { MessageContent } from "./MessageContent";
import { languageAccentClass } from "../codeCanvas";

type Props = {
  message: Message;
  isLastAssistant: boolean;
  verification?: { verdict: string; confidence: number; contradictions: string[] } | null;
  onQuote: (content: string) => void;
  onEdit?: (content: string) => void;
  onRetry?: (() => void) | null;
  onContinue?: (() => void) | null;
  onFeedback?: ((feedback: Exclude<MessageFeedback, null>) => void) | null;
  onSaveScript?: (() => void) | null;
  onAddToProject?: (() => void) | null;
  feedback?: MessageFeedback;
  startsGroup?: boolean;
  endsGroup?: boolean;
  assistantLabel?: string;
  userLabel?: string;
  displayContent?: string;
  codeCanvasMeta?: { language: string; lineCount: number; title: string } | null;
  onOpenCodeCanvas?: (() => void) | null;
};

function glyphForLabel(label: string, fallback: string): string {
  const candidate = label.trim().charAt(0).toUpperCase();
  return candidate || fallback;
}

function roleLabel(role: Message["role"], assistantLabel: string, userLabel: string): string {
  if (role === "assistant") return assistantLabel;
  if (role === "user") return userLabel;
  return "System";
}

function roleGlyph(role: Message["role"], assistantLabel: string, userLabel: string): string {
  if (role === "assistant") return glyphForLabel(assistantLabel, "N");
  if (role === "user") return glyphForLabel(userLabel, "Y");
  return "S";
}

export function ChatMessage({
  message,
  isLastAssistant,
  verification,
  onQuote,
  onEdit,
  onRetry = null,
  onContinue = null,
  onFeedback = null,
  onSaveScript = null,
  onAddToProject = null,
  feedback = null,
  startsGroup = true,
  endsGroup = true,
  assistantLabel = "AgentX",
  userLabel = "You",
  displayContent,
  codeCanvasMeta = null,
  onOpenCodeCanvas = null,
}: Props) {
  const showIdentity = startsGroup || message.role === "system";
  const rowClass =
    message.role === "user"
      ? "agentx-message-row agentx-message-row--user"
      : message.role === "assistant"
        ? "agentx-message-row agentx-message-row--assistant"
        : "agentx-message-row agentx-message-row--system";
  const showActions = message.role !== "system" && (showIdentity || endsGroup);
  const authorLabel = roleLabel(message.role, assistantLabel, userLabel);

  return (
    <article className={[rowClass, startsGroup ? "agentx-message-row--start" : "agentx-message-row--continued", endsGroup ? "agentx-message-row--end" : ""].join(" ")}>
      <div className="agentx-message-row__rail" aria-hidden="true">
        {showIdentity ? (
          <div className={["agentx-message-avatar", `agentx-message-avatar--${message.role}`].join(" ")}>
            {roleGlyph(message.role, assistantLabel, userLabel)}
          </div>
        ) : (
          <div className="agentx-message-avatar agentx-message-avatar--ghost" />
        )}
      </div>

      <div className="agentx-message-row__body">
        {showIdentity ? (
          <div className="agentx-message-row__meta">
            <div className="agentx-message-row__identity">
              <span className="agentx-message-row__author">{authorLabel}</span>
              <span className="agentx-message-row__time">{new Date(message.ts * 1000).toLocaleTimeString()}</span>
            </div>
            {showActions ? (
              <MessageActions
                role={message.role}
                content={message.content}
                feedback={feedback}
                canOpenCanvas={Boolean(codeCanvasMeta && onOpenCodeCanvas)}
                canSaveScript={message.role === "assistant" && Boolean(codeCanvasMeta || onSaveScript)}
                canAddToProject={message.role === "assistant" && Boolean(onAddToProject)}
                onQuote={onQuote}
                onEdit={onEdit}
                onRetry={onRetry ?? undefined}
                onContinue={onContinue ?? undefined}
                onFeedback={onFeedback ?? undefined}
                onSaveScript={onSaveScript ?? undefined}
                onOpenCanvas={onOpenCodeCanvas ?? undefined}
                onAddToProject={onAddToProject ?? undefined}
              />
            ) : null}
          </div>
        ) : (
          <div className="agentx-message-row__meta agentx-message-row__meta--continued">
            <span className="agentx-message-row__time">{new Date(message.ts * 1000).toLocaleTimeString()}</span>
            {showActions ? (
              <MessageActions
                role={message.role}
                content={message.content}
                feedback={feedback}
                canOpenCanvas={Boolean(codeCanvasMeta && onOpenCodeCanvas)}
                canSaveScript={message.role === "assistant" && Boolean(codeCanvasMeta || onSaveScript)}
                canAddToProject={message.role === "assistant" && Boolean(onAddToProject)}
                onQuote={onQuote}
                onEdit={onEdit}
                onRetry={onRetry ?? undefined}
                onContinue={onContinue ?? undefined}
                onFeedback={onFeedback ?? undefined}
                onSaveScript={onSaveScript ?? undefined}
                onOpenCanvas={onOpenCodeCanvas ?? undefined}
                onAddToProject={onAddToProject ?? undefined}
              />
            ) : null}
          </div>
        )}

        <MessageBubble role={message.role} compactTop={!startsGroup} compactBottom={!endsGroup}>
          {isLastAssistant && verification ? (
            <div className="agentx-message-bubble__badges">
              <span className="agentx-pill rounded-full px-2.5 py-1 text-[11px]">
                {verification.verdict} ({Math.round((verification.confidence ?? 0) * 100)}%)
              </span>
              {verification.contradictions?.length ? (
                <span className="agentx-message-badge agentx-message-badge--warn">
                  Contradictions: {verification.contradictions.length}
                </span>
              ) : null}
            </div>
          ) : null}

          {isLastAssistant && verification?.contradictions?.length ? (
            <details className="agentx-message-bubble__details">
              <summary className="agentx-message-bubble__details-summary">Show contradictions</summary>
              <div className="agentx-message-bubble__details-body">
                {verification.contradictions.map((item, index) => (
                  <div key={`${index}-${item}`}>{item}</div>
                ))}
              </div>
            </details>
          ) : null}

          {codeCanvasMeta ? (
            <div className={["agentx-message-canvas-note", languageAccentClass(codeCanvasMeta.language)].join(" ")}>
              <div className="agentx-message-canvas-note__meta">
                <span className="agentx-message-canvas-note__title">{codeCanvasMeta.title}</span>
                <span className="agentx-message-canvas-note__details">
                  {codeCanvasMeta.language} · {codeCanvasMeta.lineCount} lines
                </span>
              </div>
              {onOpenCodeCanvas ? (
                <button className="agentx-message-canvas-note__button" type="button" onClick={onOpenCodeCanvas}>
                  Open canvas
                </button>
              ) : null}
            </div>
          ) : null}

          <MessageContent content={displayContent ?? message.content} />
        </MessageBubble>
      </div>
    </article>
  );
}
