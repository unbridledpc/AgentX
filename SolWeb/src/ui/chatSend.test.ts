import { describe, expect, it } from "vitest";

import type { Thread } from "../api/client";
import { buildSendFailureMessage, restoreDraftAfterSendFailure, rollbackOptimisticThread } from "./chatSend";

function sampleThread(): Thread {
  return {
    id: "thread-1",
    title: "Thread",
    created_at: 1,
    updated_at: 3,
    messages: [
      { id: "persisted", role: "assistant", content: "ready", ts: 2 },
      { id: "optimistic", role: "user", content: "draft", ts: 3 },
    ],
  };
}

describe("chatSend", () => {
  it("rolls back the optimistic user message when user persistence failed", () => {
    const next = rollbackOptimisticThread(sampleThread(), "optimistic", false);
    expect(next?.messages.map((message) => message.id)).toEqual(["persisted"]);
  });

  it("keeps the thread intact when the user message already persisted", () => {
    const thread = sampleThread();
    expect(rollbackOptimisticThread(thread, "optimistic", true)).toBe(thread);
  });

  it("restores the original draft only when the user message did not persist", () => {
    expect(restoreDraftAfterSendFailure("hello", false)).toBe("hello");
    expect(restoreDraftAfterSendFailure("hello", true)).toBe("");
  });

  it("builds truthful failure messages for each failure stage", () => {
    expect(buildSendFailureMessage({ errorMessage: "append failed", userMessagePersisted: false, assistantReplyReceived: false })).toContain("not sent or saved");
    expect(buildSendFailureMessage({ errorMessage: "model failed", userMessagePersisted: true, assistantReplyReceived: false })).toContain("Error sending message");
    expect(buildSendFailureMessage({ errorMessage: "persist reply failed", userMessagePersisted: true, assistantReplyReceived: true })).toContain("could not be saved");
  });
});
