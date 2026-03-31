import React from "react";
import { Panel } from "../components/Panel";
import { ScrollArea } from "../components/ScrollArea";

export function PlaceholderPage(props: { title: string; description?: string }) {
  return (
    <div className="h-full min-h-0 flex flex-col gap-3">
      <Panel className="p-4 min-h-0 flex-1">
        <ScrollArea className="h-full">
          <div className="space-y-3">
            <div className="text-lg font-semibold text-slate-900">{props.title}</div>
            <div className="text-sm text-slate-600">{props.description ?? "Content coming soon."}</div>
            <div className="rounded-xl border border-dashed border-slate-200 p-4 text-xs text-slate-500">
              This is a placeholder page rendered from the shared route registry.
            </div>
          </div>
        </ScrollArea>
      </Panel>
    </div>
  );
}
