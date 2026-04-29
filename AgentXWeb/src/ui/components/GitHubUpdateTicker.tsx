import { useEffect, useState } from "react";
import { config } from "../../config";

type GitHubStatus = {
  ok?: boolean;
  status?: string;
  up_to_date?: boolean;
  current_commit?: string;
  local_commit?: string;
  remote_commit?: string;
  latest_commit?: string;
  current_message?: string;
  latest_message?: string;
  branch?: string;
  checked_at?: string;
  local_version?: string;
  version?: string;
  error?: string | null;
};

function shortSha(value?: string | null): string {
  if (!value) return "unknown";
  return value.length > 8 ? value.slice(0, 8) : value;
}

function statusText(state: GitHubStatus | null): string {
  if (!state) return "Checking GitHub status...";
  if (state.error) return `GitHub status unavailable - ${state.error}`;

  const local = state.local_commit || state.current_commit;
  const remote = state.remote_commit || state.latest_commit;
  const msg = state.latest_message || state.current_message || "";
  const version = state.local_version || state.version || "";

  const upToDate =
    state.up_to_date === true ||
    state.status === "up_to_date" ||
    state.status === "current" ||
    state.status === "clean";

  const prefix = upToDate ? "GitHub latest" : "GitHub update available";
  const sha = shortSha(remote || local);
  const branch = state.branch ? ` on ${state.branch}` : "";
  const versionText = version ? `    Local: ${version}` : "";

  return `${prefix}${branch} - ${sha}${msg ? ` - ${msg}` : ""}${versionText}`;
}

export function GitHubUpdateTicker() {
  const [state, setState] = useState<GitHubStatus | null>(null);

  useEffect(() => {
    let cancelled = false;

    async function load() {
      try {
        const res = await fetch(`${config.apiBase}/v1/github/status`, { cache: "no-store" });
        if (!res.ok) throw new Error(`HTTP ${res.status}`);
        const json = (await res.json()) as GitHubStatus;
        if (!cancelled) setState(json);
      } catch (err) {
        if (!cancelled) {
          setState({
            ok: false,
            error: err instanceof Error ? err.message : "request failed",
          });
        }
      }
    }

    load();
    const timer = window.setInterval(load, 60_000);

    return () => {
      cancelled = true;
      window.clearInterval(timer);
    };
  }, []);

  const isUpdate =
    state?.up_to_date === false ||
    state?.status === "behind" ||
    state?.status === "update" ||
    state?.status === "update_available";

  return (
    <div className="github-update-strip" role="status" aria-live="polite">
      <span className={isUpdate ? "github-pill github-pill-warn" : "github-pill"}>
        GITHUB
      </span>
      <span className="github-update-text">{statusText(state)}</span>
    </div>
  );
}
