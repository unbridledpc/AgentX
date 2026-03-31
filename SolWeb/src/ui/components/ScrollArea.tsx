import React from "react";

export function ScrollArea(props: React.PropsWithChildren<{ className?: string }>) {
  return (
    <div className={["min-h-0 min-w-0 overflow-auto", props.className].filter(Boolean).join(" ")}>
      {props.children}
    </div>
  );
}

