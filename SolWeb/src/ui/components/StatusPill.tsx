import React from "react";

export function StatusPill(props: { ok: boolean; label: string; compact?: boolean }) {
  return (
    <div
      className={[
        "nexus-status-pill inline-flex items-center gap-2 rounded-full border px-3 py-1.5 text-[11px] font-semibold uppercase tracking-[0.16em]",
        props.ok ? "nexus-status-pill--ok" : "nexus-status-pill--warn",
        props.compact ? "nexus-status-pill--compact" : "",
      ].join(" ")}
    >
      <span className="nexus-status-pill__signal" aria-hidden="true">
        <span className={["nexus-status-pill__dot h-2 w-2 rounded-full", props.ok ? "bg-emerald-300" : "bg-rose-300"].join(" ")} />
      </span>
      <span>{props.label}</span>
    </div>
  );
}
