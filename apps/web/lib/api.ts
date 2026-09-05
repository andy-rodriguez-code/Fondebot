import { translate } from "./i18n";

// Vacío significa mismo origen: la app y la API se sirven desde un solo dominio
// a través del gateway, así que los pedidos usan una ruta relativa "/api/...".
// Definí NEXT_PUBLIC_API_URL solo cuando la API vive en otro origen (por
// ejemplo, corriendo el frontend por su cuenta en desarrollo local).
const API_URL = process.env.NEXT_PUBLIC_API_URL || "";

export class ApiError extends Error {
  status: number;
  constructor(message: string, status: number) {
    super(message);
    this.status = status;
  }
}

export async function api<T>(path: string, options: RequestInit = {}): Promise<T> {
  const isForm = options.body instanceof FormData;
  const response = await fetch(`${API_URL}/api${path}`, {
    ...options,
    credentials: "include",
    headers: {
      ...(isForm ? {} : { "Content-Type": "application/json" }),
      ...options.headers,
    },
  });
  // Un deployment puede bloquear un pedido devolviendo esta cabecera (por
  // ejemplo, una suscripción vencida); la seguimos en vez de mostrarle el error
  // a quien llamó.
  const redirectTo = response.headers.get("X-Redirect-To");
  if (redirectTo && typeof window !== "undefined" && window.location.pathname !== redirectTo) {
    window.location.assign(redirectTo);
    return new Promise<T>(() => {}); // nunca se resuelve; la página está navegando
  }
  if (!response.ok) {
    let message = translate("errors.unexpected");
    try {
      const data = await response.json();
      if (typeof data.detail === "string") {
        message = data.detail;
      } else if (Array.isArray(data.detail) && typeof data.detail[0]?.msg === "string") {
        message = translate("errors.formFields", { detail: data.detail[0].msg });
      }
    } catch {}
    throw new ApiError(message, response.status);
  }
  if (response.status === 204) return undefined as T;
  return response.json();
}

export function messageFrom(error: unknown): string {
  return error instanceof Error ? error.message : translate("errors.unexpected");
}

// URL absoluta para recursos de la API referenciados fuera de fetch() (por
// ejemplo, el src de un <img>/<audio> de un adjunto); las cookies viajan porque
// los adjuntos son del mismo origen.
export function apiUrl(path: string): string {
  return `${API_URL}/api${path}`;
}
