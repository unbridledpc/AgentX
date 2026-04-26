// @vitest-environment jsdom

import React from "react";
import { cleanup, render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";

import { MessageActions } from "./MessageActions";

afterEach(() => cleanup());

describe("MessageActions", () => {
  it("shows assistant QoL controls", () => {
    render(
      <MessageActions
        role="assistant"
        content="hello"
        canOpenCanvas
        canSaveScript
        canAddToProject
        onQuote={vi.fn()}
        onRetry={vi.fn()}
        onContinue={vi.fn()}
        onFeedback={vi.fn()}
        onSaveScript={vi.fn()}
        onOpenCanvas={vi.fn()}
        onAddToProject={vi.fn()}
      />,
    );

    expect(screen.getByRole("button", { name: "Copy" })).toBeTruthy();
    expect(screen.getByRole("button", { name: "Retry" })).toBeTruthy();
    expect(screen.getByRole("button", { name: "Continue" })).toBeTruthy();
    expect(screen.getByRole("button", { name: "Like" })).toBeTruthy();
    expect(screen.getByRole("button", { name: "Dislike" })).toBeTruthy();
    expect(screen.getByRole("button", { name: "Save Script" })).toBeTruthy();
    expect(screen.getByRole("button", { name: "Canvas" })).toBeTruthy();
    expect(screen.getByRole("button", { name: "Project" })).toBeTruthy();
  });

  it("supports user edit and retry actions", async () => {
    const user = userEvent.setup();
    const onEdit = vi.fn();
    const onRetry = vi.fn();

    render(
      <MessageActions
        role="user"
        content="prompt"
        onQuote={vi.fn()}
        onEdit={onEdit}
        onRetry={onRetry}
      />,
    );

    await user.click(screen.getByRole("button", { name: "Edit" }));
    await user.click(screen.getByRole("button", { name: "Retry" }));

    expect(onEdit).toHaveBeenCalledWith("prompt");
    expect(onRetry).toHaveBeenCalledTimes(1);
  });

  it("toggles feedback callbacks", async () => {
    const user = userEvent.setup();
    const onFeedback = vi.fn();

    render(
      <MessageActions
        role="assistant"
        content="answer"
        feedback="like"
        onQuote={vi.fn()}
        onFeedback={onFeedback}
      />,
    );

    expect(screen.getByRole("button", { name: "Like" }).getAttribute("aria-pressed")).toBe("true");
    await user.click(screen.getByRole("button", { name: "Dislike" }));
    expect(onFeedback).toHaveBeenCalledWith("dislike");
  });
});
