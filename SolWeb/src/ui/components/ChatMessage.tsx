import React from "react";

import type { Message } from "../../api/client";
import { MessageActions } from "./MessageActions";
import { MessageBubble } from "./MessageBubble";
import { MessageContent } from "./MessageContent";

type Props = {
  message: Message;
  isLastAssistant: boolean;
  verification?: { verdict: string; confidence: number; contradictions: string[] } | null;
  onQuote: (content: string) => void;
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
  startsGroup = true,
  endsGroup = true,
  assistantLabel = "Nexus",
  userLabel = "You",
  displayContent,
  codeCanvasMeta = null,
  onOpenCodeCanvas = null,
}: Props) {
  const showIdentity = startsGroup || message.role === "system";
  const rowClass =
    message.role === "user"
      ? "nexus-message-row nexus-message-row--user"
      : message.role === "assistant"
        ? "nexus-message-row nexus-message-row--assistant"
        : "nexus-message-row nexus-message-row--system";
  const showAssistantActions = message.role === "assistant" && (showIdentity || endsGroup);
  const authorLabel = roleLabel(message.role, assistantLabel, userLabel);

  return (
    <article className={[rowClass, startsGroup ? "nexus-message-row--start" : "nexus-message-row--continued", endsGroup ? "nexus-message-row--end" : ""].join(" ")}>
      <div className="nexus-message-row__rail" aria-hidden="true">
        {showIdentity ? (
          <div className={["nexus-message-avatar", `nexus-message-avatar--${message.role}`].join(" ")}>
            {roleGlyph(message.role, assistantLabel, userLabel)}
          </div>
        ) : (
          <div className="nexus-message-avatar nexus-message-avatar--ghost" />
        )}
      </div>

      <div className="nexus-message-row__body">
        {showIdentity ? (
          <div className="nexus-message-row__meta">
            <div className="nexus-message-row__identity">
              <span className="nexus-message-row__author">{authorLabel}</span>
              <span className="nexus-message-row__time">{new Date(message.ts * 1000).toLocaleTimeString()}</span>
            </div>
            {showAssistantActions ? <MessageActions content={message.content} onQuote={onQuote} /> : null}
          </div>
        ) : (
          <div className="nexus-message-row__meta nexus-message-row__meta--continued">
            <span className="nexus-message-row__time">{new Date(message.ts * 1000).toLocaleTimeString()}</span>
            {showAssistantActions ? <MessageActions content={message.content} onQuote={onQuote} /> : null}
          </div>
        )}

        <MessageBubble role={message.role} compactTop={!startsGroup} compactBottom={!endsGroup}>
          {isLastAssistant && verification ? (
            <div className="nexus-message-bubble__badges">
              <span className="nexus-pill rounded-full px-2.5 py-1 text-[11px]">
                {verification.verdict} ({Math.round((verification.confidence ?? 0) * 100)}%)
              </span>
              {verification.contradictions?.length ? (
                <span className="nexus-message-badge nexus-message-badge--warn">
                  Contradictions: {verification.contradictions.length}
                </span>
              ) : null}
            </div>
          ) : null}

          {isLastAssistant && verification?.contradictions?.length ? (
            <details className="nexus-message-bubble__details">
              <summary className="nexus-message-bubble__details-summary">Show contradictions</summary>
              <div className="nexus-message-bubble__details-body">
                {verification.contradictions.map((item, index) => (
                  <div key={`${index}-${item}`}>{item}</div>
                ))}
              </div>
            </details>
          ) : null}

          {codeCanvasMeta ? (
            <div className="nexus-message-canvas-note">
              <div className="nexus-message-canvas-note__meta">
                <span className="nexus-message-canvas-note__title">{codeCanvasMeta.title}</span>
                <span className="nexus-message-canvas-note__details">
                  {codeCanvasMeta.language} · {codeCanvasMeta.lineCount} lines
                </span>
              </div>
              {onOpenCodeCanvas ? (
                <button className="nexus-message-canvas-note__button" type="button" onClick={onOpenCodeCanvas}>
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
