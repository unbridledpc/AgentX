import React from "react";

import type { Message, QualityGateReport } from "../../api/client";
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
  showQualityGateReport?: boolean;
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

function formatDuration(ms?: number | null): string | null {
  if (typeof ms !== "number" || !Number.isFinite(ms) || ms < 0) return null;
  if (ms < 1000) return `${Math.round(ms)}ms`;
  const seconds = ms / 1000;
  if (seconds < 60) return `${seconds.toFixed(seconds < 10 ? 1 : 0)}s`;
  const minutes = Math.floor(seconds / 60);
  const rest = Math.round(seconds % 60);
  return `${minutes}m ${rest}s`;
}


function qualityGateLabel(report?: QualityGateReport | null): { label: string; tone: "good" | "warn" | "info" } | null {
  if (!report) return null;
  const status = String(report.status || (report.passed ? "passed" : "warning")).toLowerCase();
  const failed = Number(report.checks_failed ?? report.failures?.length ?? 0);
  const fixed = Number(report.checks_fixed ?? report.fixed_failures?.length ?? 0);
  const warned = Number(report.checks_warned ?? report.warnings?.length ?? 0);

  if (status === "repaired") {
    return { label: `Quality Gate: repaired${fixed ? ` · fixed ${fixed}` : ""}${failed ? ` · ${failed} open` : ""}`, tone: failed ? "warn" : "good" };
  }
  if (status === "passed") {
    return { label: `Quality Gate: passed${warned ? ` · ${warned} warning${warned === 1 ? "" : "s"}` : ""}`, tone: warned ? "info" : "good" };
  }
  if (status === "failed") {
    return { label: `Quality Gate: failed${failed ? ` · ${failed} issue${failed === 1 ? "" : "s"}` : ""}`, tone: "warn" };
  }
  return { label: `Quality Gate: warning${failed ? ` · ${failed} issue${failed === 1 ? "" : "s"}` : ""}`, tone: "warn" };
}

function QualityGateReportCard({ report }: { report: QualityGateReport }) {
  const label = qualityGateLabel(report);
  if (!label) return null;
  const failures = report.failures ?? [];
  const fixed = report.fixed_failures ?? [];
  const warnings = report.warnings ?? [];
  const pipeline = [report.draft_model, report.review_model].filter(Boolean).join(" → ");
  const hasDetails = Boolean(pipeline || failures.length || fixed.length || warnings.length);

  return (
    <div className={["agentx-quality-gate", `agentx-quality-gate--${label.tone}`].join(" ")}>
      <div className="agentx-quality-gate__header">
        <span className="agentx-quality-gate__title">{label.label}</span>
        {report.language ? <span className="agentx-quality-gate__meta">{report.language}</span> : null}
      </div>
      <div className="agentx-quality-gate__summary">
        <span>{Number(report.checks_passed ?? 0)} passed</span>
        <span>{Number(report.checks_fixed ?? fixed.length)} fixed</span>
        <span>{Number(report.checks_failed ?? failures.length)} open</span>
        <span>{Number(report.checks_warned ?? warnings.length)} warnings</span>
      </div>
      {hasDetails ? (
        <details className="agentx-quality-gate__details">
          <summary>Show quality gate details</summary>
          <div className="agentx-quality-gate__details-body">
            {pipeline ? <div><strong>Pipeline:</strong> {pipeline}</div> : null}
            {fixed.length ? (
              <div>
                <strong>Fixed:</strong>
                <ul>{fixed.map((item, index) => <li key={`fixed-${index}`}>{item}</li>)}</ul>
              </div>
            ) : null}
            {failures.length ? (
              <div>
                <strong>Still open:</strong>
                <ul>{failures.map((item, index) => <li key={`failure-${index}`}>{item}</li>)}</ul>
              </div>
            ) : null}
            {warnings.length ? (
              <div>
                <strong>Warnings:</strong>
                <ul>{warnings.map((item, index) => <li key={`warning-${index}`}>{item}</li>)}</ul>
              </div>
            ) : null}
          </div>
        </details>
      ) : null}
    </div>
  );
}

function responseMetricsLabel(message: Message): string | null {
  const metrics = message.response_metrics;
  if (!metrics || message.role !== "assistant") return null;
  const total = formatDuration(metrics.duration_ms);
  if (!total) return null;
  const kind = metrics.response_kind === "code" ? "Code" : "Reply";
  const firstToken = formatDuration(metrics.first_token_ms ?? null);
  return firstToken ? `${kind} ${total} · first token ${firstToken}` : `${kind} ${total}`;
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
  showQualityGateReport = true,
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
  const metricsLabel = responseMetricsLabel(message);
  const qualityGate = showQualityGateReport && message.role === "assistant" ? message.quality_gate ?? null : null;

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
              {metricsLabel ? <span className="agentx-message-row__timer">{metricsLabel}</span> : null}
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
            {metricsLabel ? <span className="agentx-message-row__timer">{metricsLabel}</span> : null}
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

          {qualityGate ? <QualityGateReportCard report={qualityGate} /> : null}

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
