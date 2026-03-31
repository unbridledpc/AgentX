import React from "react";

export const ScrollArea = React.forwardRef<HTMLDivElement, React.PropsWithChildren<{
  className?: string;
  style?: React.CSSProperties;
}>>((props, ref) => {
  return (
    <div
      ref={ref}
      className={["overflow-auto min-h-0 min-w-0", props.className ?? ""].join(" ")}
      style={props.style}
    >
      {props.children}
    </div>
  );
});

ScrollArea.displayName = "ScrollArea";
