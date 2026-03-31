import { theme } from "./theme";

export const tokens = {
  gutter: "p-4",
  gap: "gap-3",
  panel: `${theme.radius.panel} border border-slate-800/80 bg-slate-950/78 text-slate-100 shadow-[0_18px_50px_rgba(2,8,23,0.38)] backdrop-blur-xl`,
  panelMuted: `${theme.radius.panel} border border-slate-800/70 bg-slate-900/72 text-slate-100 shadow-[0_14px_40px_rgba(2,8,23,0.28)] backdrop-blur-xl`,
  button: theme.controls.button,
  buttonSecondary: theme.controls.secondaryButton,
  buttonUtility: theme.controls.utilityButton,
  buttonDanger: theme.controls.dangerButton,
  toggle: theme.controls.toggle,
  input: theme.controls.input,
  inputCompact: theme.controls.inputCompact,
  inputNumber: theme.controls.inputNumber,
  select: theme.controls.select,
  textarea: theme.controls.textarea,
  smallLabel: "text-[11px] font-semibold uppercase tracking-[0.16em] text-cyan-100/55",
  fieldLabel: theme.copy.fieldLabel,
  helperText: theme.copy.helper,
  warningText: theme.copy.warning,
} as const;
