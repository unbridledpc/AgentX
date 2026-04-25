import type { Thread } from "../api/client";

export function rollbackOptimisticThread(thread: Thread | null, optimisticMessageId: string, userMessagePersisted: boolean): Thread | null {
  if (!thread || userMessagePersisted) return thread;
  const nextMessages = thread.messages.filter((message) => message.id !== optimisticMessageId);
  if (nextMessages.length === thread.messages.length) return thread;
  return {
    ...thread,
    messages: nextMessages,
    updated_at: nextMessages.length ? nextMessages[nextMessages.length - 1].ts : thread.updated_at,
  };
}

export function buildSendFailureMessage(args: {
  errorMessage: string;
  userMessagePersisted: boolean;
  assistantReplyReceived: boolean;
}): string {
  if (!args.userMessagePersisted) {
    return `Message was not sent or saved: ${args.errorMessage}`;
  }
  if (args.assistantReplyReceived) {
    return `Assistant replied, but the response could not be saved to the thread: ${args.errorMessage}`;
  }
  return `Error sending message: ${args.errorMessage}`;
}

export function restoreDraftAfterSendFailure(originalDraft: string, userMessagePersisted: boolean): string {
  return userMessagePersisted ? "" : originalDraft;
}

export function isAbortError(error: unknown): boolean {
  if (!error || typeof error !== "object") return false;
  const candidate = error as { name?: unknown; message?: unknown };
  if (candidate.name === "AbortError") return true;
  if (typeof candidate.message === "string" && candidate.message.toLowerCase().includes("abort")) return true;
  return false;
}

export function restoreDraftAfterStop(originalDraft: string, currentDraft: string): string {
  return currentDraft.trim().length > 0 ? currentDraft : originalDraft;
}
