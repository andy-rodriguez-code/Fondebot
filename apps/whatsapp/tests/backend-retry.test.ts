import assert from "node:assert/strict";
import { afterEach, test } from "node:test";

import { ATTEMPTS, backend } from "../src/api.js";

// El bug que esto fija: la API se redesplegó, el contenedor nuevo tiene otra
// IP, y las conexiones que este proceso tenía guardadas apuntan a un socket
// muerto. La primera reutilización lanza "fetch failed" y una conexión nueva
// anda perfecto. Sin reintento el puente queda MUDO hasta que alguien lo
// reinicia a mano, y nadie se entera: los mensajes dejan de llegar.

const realFetch = globalThis.fetch;
afterEach(() => { globalThis.fetch = realFetch; });

function respondWith(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), { status, headers: { "Content-Type": "application/json" } });
}

test("a dead connection is retried and the call succeeds", async () => {
  let calls = 0;
  globalThis.fetch = (async () => {
    calls += 1;
    if (calls === 1) throw new TypeError("fetch failed");
    return respondWith({ ok: true });
  }) as typeof fetch;

  assert.deepEqual(await backend("/channels/x/status"), { ok: true });
  assert.equal(calls, 2, "tuvo que reintentar exactamente una vez");
});

test("it gives up instead of retrying forever", async () => {
  let calls = 0;
  globalThis.fetch = (async () => { calls += 1; throw new TypeError("fetch failed"); }) as typeof fetch;

  await assert.rejects(backend("/channels/x/status"), /fetch failed/);
  assert.equal(calls, ATTEMPTS, "el reintento tiene que estar acotado");
});

test("an HTTP error is NOT retried", async () => {
  // Un 4xx no mejora por insistir, y reintentar un POST duplicaría mensajes.
  let calls = 0;
  globalThis.fetch = (async () => {
    calls += 1;
    return respondWith({ detail: "That channel does not exist" }, 404);
  }) as typeof fetch;

  await assert.rejects(backend("/channels/x/status"), /does not exist/);
  assert.equal(calls, 1, "una respuesta HTTP se entrega tal cual, sin reintentar");
});
