import { describe, expect, it } from "vitest";

import { createClientIdWithCrypto } from "./clientId";

describe("createClientIdWithCrypto", () => {
  it("uses randomUUID when available", () => {
    expect(createClientIdWithCrypto({ randomUUID: () => "fixed-uuid" })).toBe("fixed-uuid");
  });

  it("falls back to getRandomValues when randomUUID is unavailable", () => {
    const id = createClientIdWithCrypto({
      getRandomValues: (array) => {
        const bytes = array as Uint8Array;
        bytes.fill(1);
        return array;
      },
    });

    expect(id).toMatch(/^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/);
  });

  it("falls back without browser crypto support", () => {
    expect(createClientIdWithCrypto(undefined, "message")).toMatch(/^message-/);
  });
});
