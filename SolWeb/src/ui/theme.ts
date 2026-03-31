export const theme = {
  radius: {
    panel: "rounded-[1.35rem]",
    control: "rounded-xl",
    pill: "rounded-full",
  },
  shell: {
    app: "nexus-shell relative h-full w-full",
    mainPanel: "nexus-main-panel flex min-h-0 min-w-0 flex-col p-4",
    topBar: "nexus-topbar flex items-center justify-between gap-3 border-b pb-4",
    feed: "nexus-feed min-h-0 flex-1 overflow-auto rounded-[1.45rem] border p-4",
    composer: "nexus-composer mt-4 flex flex-none flex-col gap-3 rounded-[1.45rem] border p-4",
  },
  controls: {
    button: "nexus-button nexus-button--primary",
    secondaryButton: "nexus-button nexus-button--secondary",
    utilityButton: "nexus-button nexus-button--utility",
    dangerButton: "nexus-button nexus-button--danger",
    toggle: "nexus-toggle",
    input: "nexus-input",
    inputCompact: "nexus-input nexus-input--compact",
    inputNumber: "nexus-input nexus-input--compact nexus-input--number",
    select: "nexus-input nexus-input--compact",
    textarea: "nexus-textarea",
  },
  copy: {
    eyebrow: "text-[11px] font-semibold uppercase tracking-[0.18em] text-cyan-100/55",
    title: "text-sm font-semibold text-slate-50",
    muted: "text-xs text-slate-500",
    fieldLabel: "nexus-field-label",
    helper: "nexus-helper-text",
    warning: "nexus-helper-text nexus-helper-text--warning",
  },
} as const;
