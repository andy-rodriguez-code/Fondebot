import { timingSafeEqual } from "node:crypto";
const backendUrl = (process.env.BACKEND_URL || "http://localhost:8000").replace(/\/$/, "");
export const bridgeToken = process.env.WHATSAPP_BRIDGE_TOKEN || "dev-local-change-this-bridge-token";

export async function backend<T>(path: string, options: RequestInit = {}): Promise<T> {
  const response = await fetch(`${backendUrl}/api/internal/whatsapp${path}`, {
    ...options,
    headers: {
      "Content-Type": "application/json",
      "X-Bridge-Token": bridgeToken,
      ...options.headers,
    },
  });
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
