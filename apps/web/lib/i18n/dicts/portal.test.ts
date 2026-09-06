import { describe, expect, it } from "vitest";
import { portal } from "./portal";

// The generic parity test in lib/i18n/i18n.test.ts already covers the whole
// dictionary tree, so this is a focused, human-readable guard for the keys
// this slice adds (Spec: Invitation Acceptance UI copy) rather than a
// duplicate of that mechanism.
describe("portal.invite dictionary", () => {
  it("mirrors the same invite.* keys in en and es", () => {
    const enKeys = Object.keys(portal.en.invite).sort();
    const esKeys = Object.keys(portal.es.invite).sort();
    expect(esKeys).toEqual(enKeys);
  });

  it("does not leave any invite string empty", () => {
    const empties = Object.entries(portal.en.invite).filter(
      ([, value]) => typeof value === "string" && value.trim() === "",
    );
    expect(empties).toEqual([]);
  });
});
