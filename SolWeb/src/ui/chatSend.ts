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
