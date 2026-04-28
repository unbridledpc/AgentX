import React, { useEffect, useMemo, useState } from "react";

import { config } from "../../config";

type CommitResponse = {
  sha?: string;
  html_url?: string;
  commit?: {
    message?: string;
    author?: { date?: string | null } | null;
  };
};

type UpdateState =
  | { status: "disabled" }
  | { status: "checking" }
  | { status: "error"; message: string }
  | { status: "current" | "update"; sha: string; message: string; date: string | null; url: string | null };

function shortSha(value: string | null | undefined): string {
  const clean = String(value ?? "").trim();
  return clean ? clean.slice(0, 7) : "unknown";
}

function formatCommitDate(value: string | null | undefined): string {
  if (!value) return "date unknown";
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return "date unknown";
  return new Intl.DateTimeFormat(undefined, {
    month: "short",
    day: "numeric",
    hour: "numeric",
    minute: "2-digit",
  }).format(date);
}

function trimCommitMessage(value: string | null | undefined): string {
  const firstLine = String(value ?? "").split("\n")[0]?.trim() ?? "";
  if (!firstLine) return "Latest GitHub commit";
  return firstLine.length > 92 ? `${firstLine.slice(0, 89)}...` : firstLine;
}

export function GitHubUpdateTicker() {
  const { enabled, repo, branch, currentSha, currentVersion } = config.updateFeed;
  const [state, setState] = useState<UpdateState>(() => (enabled ? { status: "checking" } : { status: "disabled" }));

  useEffect(() => {
    if (!enabled || !repo) {
      setState({ status: "disabled" });
      return;
    }

    const controller = new AbortController();
    const url = `https://api.github.com/repos/${repo}/commits/${encodeURIComponent(branch || "main")}`;

    async function checkForUpdates() {
      setState({ status: "checking" });
      try {
        const res = await fetch(url, {
          headers: { Accept: "application/vnd.github+json" },
          signal: controller.signal,
        });
        if (!res.ok) throw new Error(`GitHub returned ${res.status}`);
        const data = (await res.json()) as CommitResponse;
        const latestSha = String(data.sha ?? "").trim();
        const latestMessage = trimCommitMessage(data.commit?.message);
        const latestDate = data.commit?.author?.date ?? null;
        const latestUrl = data.html_url ?? null;
        const current = String(currentSha ?? "").trim().toLowerCase();
        const latest = latestSha.toLowerCase();
        const hasUpdate = Boolean(current && latest && !latest.startsWith(current) && !current.startsWith(latest));
        setState({
          status: hasUpdate ? "update" : "current",
          sha: latestSha,
          message: latestMessage,
          date: latestDate,
          url: latestUrl,
        });
      } catch (err) {
        if (controller.signal.aborted) return;
        setState({ status: "error", message: err instanceof Error ? err.message : "Unable to check GitHub" });
      }
    }

    void checkForUpdates();
    const timer = window.setInterval(() => void checkForUpdates(), 15 * 60 * 1000);
    return () => {
      controller.abort();
      window.clearInterval(timer);
    };
  }, [branch, currentSha, enabled, repo]);

  const label = useMemo(() => {
    if (state.status === "disabled") return null;
    if (state.status === "checking") return "Checking GitHub for updates...";
    if (state.status === "error") return `GitHub update check unavailable: ${state.message}`;
    const prefix = state.status === "update" ? "New GitHub update available" : "GitHub latest";
    return `${prefix} - ${shortSha(state.sha)} - ${state.message} - ${formatCommitDate(state.date)}`;
  }, [state]);

  if (!label) return null;

  const content = (
    <>
      <span className="agentx-update-ticker__badge">{state.status === "update" ? "Update" : state.status === "error" ? "Notice" : "GitHub"}</span>
      <span className="agentx-update-ticker__text">{label}</span>
      <span className="agentx-update-ticker__version">Local: {currentVersion || "local"}{currentSha ? ` @ ${shortSha(currentSha)}` : ""}</span>
    </>
  );

  const href = state.status === "current" || state.status === "update" ? state.url ?? `https://github.com/${repo}` : null;

  return (
    <div className={["agentx-update-ticker", `agentx-update-ticker--${state.status}`].join(" ")} role="status" aria-live="polite">
      <div className="agentx-update-ticker__track">
        {href ? (
          <a className="agentx-update-ticker__inner" href={href} target="_blank" rel="noreferrer">{content}</a>
        ) : (
          <div className="agentx-update-ticker__inner">{content}</div>
        )}
        <div className="agentx-update-ticker__inner agentx-update-ticker__inner--ghost" aria-hidden="true">{content}</div>
      </div>
    </div>
  );
}
