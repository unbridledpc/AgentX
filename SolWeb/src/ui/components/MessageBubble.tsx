import React from "react";

type Props = React.PropsWithChildren<{
  role: "user" | "assistant" | "system";
  compactTop?: boolean;
  compactBottom?: boolean;
}>;

export function MessageBubble({ role, compactTop = false, compactBottom = false, children }: Props) {
  return (
    <div
      className={[
        "nexus-message-bubble",
        role === "assistant"
          ? "nexus-message-bubble--assistant"
          : role === "user"
            ? "nexus-message-bubble--user"
            : "nexus-message-bubble--system",
        compactTop ? "nexus-message-bubble--compact" : "",
        compactBottom ? "nexus-message-bubble--compact-bottom" : "",
      ].join(" ")}
    >
      {children}
    </div>
  );
}
