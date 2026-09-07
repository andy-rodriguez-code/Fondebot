import { timingSafeEqual } from "node:crypto";
const backendUrl = (process.env.BACKEND_URL || "http://localhost:8000").replace(/\/$/, "");
export const bridgeToken = process.env.WHATSAPP_BRIDGE_TOKEN || "dev-local-change-this-bridge-token";

/** Cuantas veces se intenta antes de rendirse, y cuanto se espera entre una y
 * otra. Acotado a proposito: esto no es para aguantar una caida larga, es para
 * cruzar un redespliegue de unos segundos. */
export const ATTEMPTS = 3;
const BACKOFF_MS = [250, 1000];

const wait = (ms: number) => new Promise((resolve) => setTimeout(resolve, ms));

export async function backend<T>(path: string, options: RequestInit = {}): Promise<T> {
  const send = () =>
    fetch(`${backendUrl}/api/internal/whatsapp${path}`, {
      ...options,
      headers: {
        "Content-Type": "application/json",
        "X-Bridge-Token": bridgeToken,
        ...options.headers,
      },
    });

  // Se reintenta solo un fallo de RED, nunca una respuesta HTTP: un 4xx no
  // mejora por insistir, y reintentarlo duplicaria mensajes.
  //
  // El caso real que esto arregla: la API se redespliega, el contenedor nuevo
  // tiene otra IP, y las conexiones que este proceso tenia guardadas apuntan a
  // un socket muerto. La primera reutilizacion lanza "fetch failed" y una
  // conexion nueva anda perfecto.
  //
  // Sin esto el puente queda MUDO hasta que alguien lo reinicia a mano, y nadie
  // se entera: los mensajes de WhatsApp simplemente dejan de llegar. Se
  // encontro asi, con el puente vivo y la API sana, fallando cada pocos
  // segundos por conexiones que ya no existian.
  let response: Response | undefined;
  let lastError: unknown;
  for (let attempt = 0; attempt < ATTEMPTS; attempt += 1) {
    try {
      response = await send();
      break;
    } catch (error) {
      lastError = error;
      if (attempt < ATTEMPTS - 1) await wait(BACKOFF_MS[attempt] ?? 1000);
    }
  }
  if (!response) throw lastError instanceof Error ? lastError : new Error("The backend could not be reached");
  if (!response.ok) {
    let detail = `FastAPI responded with ${response.status}`;
    try {
      const data = await response.json() as { detail?: string };
      if (data.detail) detail = data.detail;
    } catch {}
    throw new Error(detail);
  }
  if (response.status === 204) return undefined as T;
  return response.json() as Promise<T>;
}

export async function setStatus(
  channelId: string,
  status: "disconnected" | "connecting" | "qr" | "connected" | "reconnecting" | "error",
  extra: Record<string, unknown> = {},
): Promise<void> {
  await backend(`/channels/${channelId}/status`, {
    method: "PUT",
    body: JSON.stringify({ status, ...extra }),
  });
}

/** Compara el token en tiempo constante.
 *
 * `!==` corta en el primer byte distinto, así que el tiempo de respuesta va
 * revelando el prefijo correcto. El lado FastAPI ya usaba `hmac.compare_digest`
 * para este mismo secreto (`routers/whatsapp.py`); este lado no. El puente
 * escucha en 127.0.0.1 por defecto, lo que acota mucho el riesgo, pero
 * `WHATSAPP_BRIDGE_HOST` es configurable y un puerto expuesto por error no
 * debería ser la única defensa.
 *
 * `timingSafeEqual` exige buffers del mismo largo, así que el largo se compara
 * antes — eso sí filtra el largo del token, que no es secreto.
 */
export function tokenMatches(received: unknown): boolean {
  // Un puente configurado sin token no acepta a nadie. Sin este guard, con
  // WHATSAPP_BRIDGE_TOKEN="" un header vacío coincidiría y quedaría abierto:
  // un secreto compartido vacío no es autenticación, es su ausencia.
  if (!bridgeToken) return false;
  if (typeof received !== "string") return false;
  const a = Buffer.from(received, "utf8");
  const b = Buffer.from(bridgeToken, "utf8");
  return a.length === b.length && timingSafeEqual(a, b);
}
