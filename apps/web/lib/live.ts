import { useEffect, useRef, useState } from "react";
import { apiUrl } from "./api";

// Cada cuánto se refresca por las suyas. El intervalo no desaparece cuando el
// stream conecta: se hace lento. Un aviso perdido —cola llena, un proxy que
// corta, dos workers detrás de un balanceador— deja la pantalla vieja para
// siempre si el refresco es lo único que la puede corregir y ya no corre.
export const POLL_WHILE_LIVE_MS = 60000;
export const POLL_WHILE_OFFLINE_MS = 8000;

export function pollIntervalFor(live: boolean): number {
  return live ? POLL_WHILE_LIVE_MS : POLL_WHILE_OFFLINE_MS;
}

/**
 * Escucha los avisos en vivo del portal y llama a `onChange` en cada uno.
 *
 * Lo que llega es una señal, no la conversación: quien la recibe vuelve a pedir
 * por los endpoints de siempre, que son los que aplican el permiso por
 * dependencia. Devuelve si el stream está conectado, para que el refresco por
 * intervalo sepa a qué ritmo correr.
 */
export function useLiveChanges(slug: string, onChange: () => void): boolean {
  const [live, setLive] = useState(false);
  // `onChange` se rearma en cada render de la página. Guardarlo en una ref
  // mantiene el efecto atado sólo al slug: sin esto, cada render cerraría y
  // reabriría el stream, que es justo lo que se quería dejar de hacer.
  const handler = useRef(onChange);
  useEffect(() => { handler.current = onChange; }, [onChange]);

  useEffect(() => {
    if (typeof window === "undefined" || typeof EventSource === "undefined") return;
    const source = new EventSource(apiUrl(`/portal/${slug}/events`), { withCredentials: true });
    source.onopen = () => setLive(true);
    source.addEventListener("conversation", () => handler.current());
    // EventSource reconecta solo; acá sólo se anota que por ahora no hay
    // stream, para que el refresco vuelva al ritmo rápido mientras tanto.
    source.onerror = () => setLive(false);
    return () => { source.close(); setLive(false); };
  }, [slug]);

  return live;
}
