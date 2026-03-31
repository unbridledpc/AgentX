import { DEFAULT_SETTINGS, loadSettings, saveSettings, SolSettings } from "../config";

const inspectorListeners = new Set<(value: boolean) => void>();
const themeListeners = new Set<(value: SolSettings["theme"]) => void>();
const inspectorWindowListeners = new Set<(value: boolean) => void>();
const chatProviderListeners = new Set<(value: string) => void>();
const chatModelListeners = new Set<(value: string) => void>();

let currentSettings: SolSettings = DEFAULT_SETTINGS;

function emit() {
  for (const listener of inspectorListeners) {
    listener(currentSettings.showInspector);
  }
  for (const listener of themeListeners) {
    listener(currentSettings.theme);
  }
  for (const listener of inspectorWindowListeners) {
    listener(currentSettings.inspectorWindow);
  }
  for (const listener of chatProviderListeners) {
    listener(currentSettings.chatProvider);
  }
  for (const listener of chatModelListeners) {
    listener(currentSettings.chatModel);
  }
}

loadSettings().then((loaded) => {
  currentSettings = loaded;
  emit();
});

function updateSettings(next: SolSettings) {
  currentSettings = next;
  emit();
  void saveSettings(next);
}

export function getShowInspectorSidebar(): boolean {
  return currentSettings.showInspector;
}

export function setShowInspectorSidebar(value: boolean) {
  updateSettings({ ...currentSettings, showInspector: value });
}

export function subscribeShowInspectorSidebar(listener: (value: boolean) => void) {
  inspectorListeners.add(listener);
  listener(currentSettings.showInspector);
  return () => {
    inspectorListeners.delete(listener);
  };
}

export function getTheme(): string {
  return currentSettings.theme;
}

export function setTheme(theme: SolSettings["theme"]) {
  updateSettings({ ...currentSettings, theme });
}

export function subscribeTheme(listener: (value: SolSettings["theme"]) => void) {
  themeListeners.add(listener);
  listener(currentSettings.theme);
  return () => {
    themeListeners.delete(listener);
  };
}

export function getInspectorWindowEnabled(): boolean {
  return currentSettings.inspectorWindow;
}

export function setInspectorWindowEnabled(value: boolean) {
  updateSettings({ ...currentSettings, inspectorWindow: value });
}

export function subscribeInspectorWindow(listener: (value: boolean) => void) {
  inspectorWindowListeners.add(listener);
  listener(currentSettings.inspectorWindow);
  return () => {
    inspectorWindowListeners.delete(listener);
  };
}

export function getChatProvider(): string {
  return currentSettings.chatProvider;
}

export function setChatProvider(value: string) {
  updateSettings({ ...currentSettings, chatProvider: value as any });
}

export function subscribeChatProvider(listener: (value: string) => void) {
  chatProviderListeners.add(listener);
  listener(currentSettings.chatProvider);
  return () => {
    chatProviderListeners.delete(listener);
  };
}

export function getChatModel(): string {
  return currentSettings.chatModel;
}

export function setChatModel(value: string) {
  updateSettings({ ...currentSettings, chatModel: value });
}

export function setChatSelection(provider: string, model: string) {
  updateSettings({ ...currentSettings, chatProvider: provider as any, chatModel: model });
}

export function subscribeChatModel(listener: (value: string) => void) {
  chatModelListeners.add(listener);
  listener(currentSettings.chatModel);
  return () => {
    chatModelListeners.delete(listener);
  };
}
