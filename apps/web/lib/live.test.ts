import { describe, expect, it } from "vitest";
import { POLL_WHILE_LIVE_MS, POLL_WHILE_OFFLINE_MS, pollIntervalFor } from "./live";

describe("pollIntervalFor", () => {
  it("keeps refreshing while the stream is live", () => {
    // Lo importante no es el número, es que no sea cero: si el refresco se
    // apagara al conectar, un aviso perdido dejaría la pantalla vieja hasta que
    // alguien recargue a mano.
    expect(pollIntervalFor(true)).toBeGreaterThan(0);
    expect(pollIntervalFor(true)).toBe(POLL_WHILE_LIVE_MS);
  });

  it("refreshes faster while there is no stream", () => {
    expect(pollIntervalFor(false)).toBe(POLL_WHILE_OFFLINE_MS);
    expect(POLL_WHILE_OFFLINE_MS).toBeLessThan(POLL_WHILE_LIVE_MS);
  });
});
