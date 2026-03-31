// @vitest-environment jsdom

import { beforeEach, describe, expect, it, vi } from "vitest";

import { defaultCodeCanvasState, deserializeCodeCanvasState, saveCodeCanvasState, serializeCodeCanvasState } from "./codeCanvas";
import { config } from "../config";

describe("codeCanvas storage", () => {
  beforeEach(() => {
    localStorage.clear();
  });

  it("expires stale persisted canvas state", () => {
    const raw = JSON.stringify({
      savedAt: 1,
      expiresAt: 2,
      state: {
        ...defaultCodeCanvasState(),
        isOpen: true,
        content: "stale",
      },
    });
    expect(deserializeCodeCanvasState(raw, 3)).toEqual(defaultCodeCanvasState());
  });

  it("bounds oversized persisted code content", () => {
    const serialized = serializeCodeCanvasState({
      ...defaultCodeCanvasState(),
      isOpen: true,
      sourceMessageId: "m1",
      content: "x".repeat(400_000),
      sources: {
        m1: {
          content: "x".repeat(400_000),
          language: "typescript",
          title: "huge",
        },
      },
    });
    expect(serialized).not.toBeNull();
    expect((serialized ?? "").length).toBeLessThanOrEqual(200_000);
  });

  it("fails safely when browser storage rejects the write", () => {
    const setItem = vi.spyOn(Storage.prototype, "setItem").mockImplementation(() => {
      throw new Error("quota exceeded");
    });
    const removeItem = vi.spyOn(Storage.prototype, "removeItem").mockImplementation(() => undefined);

    saveCodeCanvasState({
      ...defaultCodeCanvasState(),
      isOpen: true,
      content: "hello",
    });

    expect(setItem).toHaveBeenCalled();
    expect(removeItem).toHaveBeenCalledWith(config.codeCanvasStateKey);
    setItem.mockRestore();
    removeItem.mockRestore();
  });
});
