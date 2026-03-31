import { WebviewWindow } from "@tauri-apps/api/webviewWindow";

const LABEL = "inspector";
const URL = "tauri://localhost/#inspector";

function isTauriEnvironment() {
  if (typeof window === "undefined") return false;
  return typeof (window as any).__TAURI__ !== "undefined";
}

export async function openInspectorWindow() {
  if (!isTauriEnvironment()) return;

  try {
    const existing = await WebviewWindow.getByLabel(LABEL);
    if (existing) {
      await existing.show();
      await existing.setFocus();
      return;
    }
  } catch {
    // ignored; create new window
  }

  new WebviewWindow(LABEL, {
    url: URL,
    title: "Sol Inspector",
    width: 420,
    height: 800,
    resizable: true,
  });
}

export async function closeInspectorWindow() {
  if (!isTauriEnvironment()) return;
  try {
    const existing = await WebviewWindow.getByLabel(LABEL);
    if (existing) {
      await existing.close();
    }
  } catch {
    // window not open
  }
}
