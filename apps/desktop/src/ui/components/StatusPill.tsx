import React from "react";

export function StatusPill(props: { ok: boolean; label: string }) {
  return (
    <span
      className={[
        "inline-flex items-center gap-2 px-3 py-1 text-xs font-medium rounded-full border",
        props.ok ? "bg-emerald-50 border-emerald-200 text-emerald-700" : "bg-rose-50 border-rose-200 text-rose-700",
      ].join(" ")}
      title={props.ok ? "Backend reachable" : "Backend not reachable"}
    >
      <span
        className={[
          "h-2 w-2 rounded-full",
          props.ok ? "bg-emerald-500" : "bg-rose-500",
        ].join(" ")}
      />
      {props.label}
    </span>
  );
}
