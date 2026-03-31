import React from "react";
import { borders, radii, shadows } from "../tokens";

export function Panel(props: React.PropsWithChildren<{ className?: string }>) {
  return (
    <div
      className={[
        "bg-white",
        borders.panel,
        radii.r16,
        shadows.soft,
        "min-w-0", // critical: prevents overflow layout bugs in flex/grid
        props.className ?? "",
      ].join(" ")}
    >
      {props.children}
    </div>
  );
}
