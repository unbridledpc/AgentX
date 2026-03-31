import React, { useEffect, useState } from "react";
import { tokens } from "../tokens";

type Props = {
  content: string;
  onQuote: (content: string) => void;
};

export function MessageActions({ content, onQuote }: Props) {
  const [copied, setCopied] = useState(false);

  useEffect(() => {
    if (!copied) return;
    const id = window.setTimeout(() => setCopied(false), 1400);
    return () => window.clearTimeout(id);
  }, [copied]);

  const copy = async () => {
    try {
      await navigator.clipboard.writeText(content);
      setCopied(true);
    } catch {
      setCopied(false);
    }
  };

  return (
    <div className="nexus-message-actions">
      <button
        type="button"
        className={[tokens.buttonUtility, "nexus-message-actions__button"].join(" ")}
        onClick={() => void copy()}
      >
        {copied ? "Copied" : "Copy"}
      </button>
      <button
        type="button"
        className={[tokens.buttonUtility, "nexus-message-actions__button"].join(" ")}
        onClick={() => onQuote(content)}
      >
        Quote
      </button>
    </div>
  );
}
