import React, { useEffect, useState } from "react";

import { tokens } from "../tokens";

type Props = {
  code: string;
  language?: string;
};

export function CodeBlock({ code, language }: Props) {
  const [copied, setCopied] = useState(false);

  useEffect(() => {
    if (!copied) return;
    const id = window.setTimeout(() => setCopied(false), 1400);
    return () => window.clearTimeout(id);
  }, [copied]);

  const onCopy = async () => {
    try {
      await navigator.clipboard.writeText(code);
      setCopied(true);
    } catch {
      setCopied(false);
    }
  };

  return (
    <div className="nexus-codeblock">
      <div className="nexus-codeblock__header">
        <div className="nexus-codeblock__meta">
          <span className="nexus-codeblock__traffic" aria-hidden="true">
            <span />
            <span />
            <span />
          </span>
          <span className="nexus-codeblock__language">{language || "text"}</span>
        </div>
        <button type="button" className={[tokens.buttonUtility, "nexus-codeblock__copy"].join(" ")} onClick={() => void onCopy()}>
          {copied ? "Copied" : "Copy code"}
        </button>
      </div>
      <pre className="nexus-codeblock__pre">
        <code>{code}</code>
      </pre>
    </div>
  );
}
