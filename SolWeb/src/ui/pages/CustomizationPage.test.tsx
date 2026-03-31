// @vitest-environment jsdom

import React from "react";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { DEFAULT_SOL_SETTINGS } from "../../api/client";
import { CustomizationPage } from "./CustomizationPage";

const saveSettingsMock = vi.fn();

vi.mock("../../api/client", async () => {
  const actual = await vi.importActual<typeof import("../../api/client")>("../../api/client");
  return {
    ...actual,
    saveSettings: (...args: Parameters<typeof actual.saveSettings>) => saveSettingsMock(...args),
  };
});

describe("CustomizationPage", () => {
  beforeEach(() => {
    saveSettingsMock.mockReset();
    localStorage.clear();
  });

  it("rolls the visible draft back when customization save fails", async () => {
    saveSettingsMock.mockRejectedValueOnce(new Error("save failed"));
    const onSettingsChange = vi.fn();

    render(
      <CustomizationPage
        statusOk
        settings={DEFAULT_SOL_SETTINGS}
        layoutGuards={{ headerForcedVisible: false, inspectorUnavailableReason: null, codeCanvasInactive: false }}
        onSettingsChange={onSettingsChange}
        onSettingsSaved={vi.fn()}
        onSystemMessage={vi.fn()}
      />
    );

    const assistantInput = screen.getByDisplayValue("Nexus");
    await userEvent.clear(assistantInput);
    await userEvent.type(assistantInput, "Orion");
    await userEvent.click(screen.getByRole("button", { name: "Save Customization" }));

    await waitFor(() => expect(saveSettingsMock).toHaveBeenCalled());
    await waitFor(() => expect(screen.getByDisplayValue("Nexus")).toBeTruthy());
    expect(onSettingsChange).toHaveBeenLastCalledWith(expect.objectContaining({ assistantDisplayName: "Nexus" }));
  });

  it("applies layout toggles immediately and marks offline changes as pending sync", async () => {
    const onSettingsChange = vi.fn();

    render(
      <CustomizationPage
        statusOk={false}
        settings={DEFAULT_SOL_SETTINGS}
        layoutGuards={{ headerForcedVisible: false, inspectorUnavailableReason: null, codeCanvasInactive: false }}
        onSettingsChange={onSettingsChange}
        onSettingsSaved={vi.fn()}
        onSystemMessage={vi.fn()}
      />
    );

    const sidebarToggle = screen.getAllByRole("switch", { name: "Show Sidebar" }).at(-1) as HTMLInputElement;
    expect(sidebarToggle.checked).toBe(true);

    await userEvent.click(sidebarToggle);

    expect(sidebarToggle.checked).toBe(false);
    expect(onSettingsChange).toHaveBeenCalledWith(
      expect.objectContaining({
        layout: expect.objectContaining({ showSidebar: false }),
      })
    );
    expect(saveSettingsMock).not.toHaveBeenCalled();
    expect(screen.getByText(/pending sync/i)).toBeTruthy();
  });
});
