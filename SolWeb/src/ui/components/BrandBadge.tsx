import React from "react";

type Props = {
  compact?: boolean;
};

export function BrandBadge({ compact = false }: Props) {
  return (
    <div className={["nexus-badge", compact ? "nexus-badge--compact" : ""].join(" ").trim()}>
      <span className="nexus-badge__dot" />
      <div className="min-w-0">
        <div className="nexus-badge__title">Nexus</div>
        {!compact ? <div className="nexus-badge__subtitle">Local AI control surface</div> : null}
      </div>
    </div>
  );
}
