import React, { useId } from "react";
import { tokens } from "../tokens";

type Props = {
  checked: boolean;
  onChange: (checked: boolean) => void;
  disabled?: boolean;
  label: string;
  helper?: string;
};

export function NexusToggle({ checked, onChange, disabled = false, label, helper }: Props) {
  const helperId = useId();

  return (
    <label className={["nexus-toggle-row", disabled ? "nexus-toggle-row--disabled" : ""].join(" ").trim()}>
      <div className="min-w-0">
        <div className="nexus-toggle-row__label">{label}</div>
        {helper ? <div id={helperId} className="nexus-toggle-row__helper">{helper}</div> : null}
      </div>
      <span className="nexus-toggle-control">
        <input
          type="checkbox"
          role="switch"
          aria-checked={checked}
          aria-label={label}
          aria-describedby={helper ? helperId : undefined}
          checked={checked}
          className="nexus-toggle__input"
          disabled={disabled}
          onChange={(event) => onChange(event.target.checked)}
        />
        <span
          aria-hidden="true"
          className={[tokens.toggle, checked ? "nexus-toggle--on" : "", disabled ? "nexus-toggle--disabled" : ""].join(" ").trim()}
        >
          <span className="nexus-toggle__thumb" />
        </span>
      </span>
    </label>
  );
}
