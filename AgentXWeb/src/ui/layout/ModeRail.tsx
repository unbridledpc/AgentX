import React from "react";

export type DeckModeId = "command" | "drafts" | "memory" | "scripts" | "coding" | "models" | "health" | "validation" | "workspaces" | "github" | "settings";

export type DeckMode = {
  id: DeckModeId;
  label: string;
  icon: string;
  disabled?: boolean;
  title?: string;
};

type Props = {
  modes: DeckMode[];
  activeId: DeckModeId;
  onSelect: (id: DeckModeId) => void;
};

export function ModeRail({ modes, activeId, onSelect }: Props) {
  return (
    <nav className="agentx-mode-rail" aria-label="AgentX modes">
      {modes.map((mode) => {
        const active = mode.id === activeId;

        return (
          <button
            key={mode.id}
            type="button"
            className={["agentx-mode-rail-button", active ? "agentx-mode-rail-button--active" : ""].join(" ")}
            disabled={mode.disabled}
            title={mode.title || mode.label}
            aria-pressed={active}
            onClick={() => onSelect(mode.id)}
          >
            <span className="agentx-mode-rail-icon" aria-hidden="true">{mode.icon}</span>
            <span className="agentx-mode-rail-label">{mode.label}</span>
          </button>
        );
      })}
    </nav>
  );
}
