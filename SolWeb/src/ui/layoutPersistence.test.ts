// @vitest-environment jsdom

import { beforeEach, describe, expect, it } from "vitest";

import { applyPendingLayoutToSettings, clearPendingLayoutSave, loadPendingLayoutSave, savePendingLayoutSave } from "./layoutPersistence";

describe("layoutPersistence", () => {
  beforeEach(() => {
    localStorage.clear();
  });

  it("persists and loads pending layout changes", () => {
    savePendingLayoutSave({ showSidebar: false, showInspector: true, showHeader: true, showCodeCanvas: false });
    const pending = loadPendingLayoutSave();
    expect(pending?.layout.showSidebar).toBe(false);
    expect(pending?.layout.showCodeCanvas).toBe(false);
  });

  it("applies a pending layout over loaded settings", () => {
    const pending = savePendingLayoutSave({ showSidebar: false, showInspector: false, showHeader: true, showCodeCanvas: true });
    const merged = applyPendingLayoutToSettings(
      {
        assistantDisplayName: "Nexus",
        userDisplayName: "You",
        layout: { showSidebar: true, showInspector: true, showHeader: true, showCodeCanvas: true },
      },
      pending
    );
    expect(merged.layout?.showSidebar).toBe(false);
    expect(merged.layout?.showInspector).toBe(false);
  });

  it("clears pending layout state", () => {
    savePendingLayoutSave({ showSidebar: false });
    clearPendingLayoutSave();
    expect(loadPendingLayoutSave()).toBeNull();
  });
});
