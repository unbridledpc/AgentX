type CryptoLike = {
  randomUUID?: () => string;
  getRandomValues?: <T extends ArrayBufferView>(array: T) => T;
};

function fallbackId(prefix: string): string {
  return `${prefix}-${Date.now().toString(36)}-${Math.random().toString(36).slice(2, 12)}`;
}

export function createClientIdWithCrypto(cryptoSource: CryptoLike | undefined, prefix = "id"): string {
  if (cryptoSource && typeof cryptoSource.randomUUID === "function") {
    try {
      return cryptoSource.randomUUID.call(cryptoSource);
    } catch {
      // Fall through to getRandomValues/Math fallback.
    }
  }

  if (cryptoSource && typeof cryptoSource.getRandomValues === "function") {
    try {
      const bytes = new Uint8Array(16);
      cryptoSource.getRandomValues.call(cryptoSource, bytes);

      // Format as UUID v4.
      bytes[6] = (bytes[6] & 0x0f) | 0x40;
      bytes[8] = (bytes[8] & 0x3f) | 0x80;

      const hex = Array.from(bytes, (byte) => byte.toString(16).padStart(2, "0"));
      return `${hex.slice(0, 4).join("")}-${hex.slice(4, 6).join("")}-${hex.slice(6, 8).join("")}-${hex.slice(8, 10).join("")}-${hex.slice(10, 16).join("")}`;
    } catch {
      // Fall through to non-crypto fallback.
    }
  }

  return fallbackId(prefix);
}

export function createClientId(prefix = "id"): string {
  return createClientIdWithCrypto(globalThis.crypto, prefix);
}
