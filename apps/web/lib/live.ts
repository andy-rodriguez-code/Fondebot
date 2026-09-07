import { useEffect, useRef, useState } from "react";
import { apiUrl } from "./api";

// Cada cuánto se refresca por las suyas. El intervalo no desaparece cuando el
// stream conecta: se hace lento. Un aviso perdido —cola llena, un proxy que
// corta, dos workers detrás de un balanceador— deja la pantalla vieja para
// siempre si el refresco es lo único que la puede corregir y ya no corre.
export const POLL_WHILE_LIVE_MS = 60000;
export const POLL_WHILE_OFFLINE_MS = 8000;
// Cuánto se espera antes de volver a abrir el stream después de un error.
// EventSource reintenta solo cada ~3 segundos, y contra una sesión que ya
// terminó eso es un 401 cada tres segundos para siempre.
export const REOPEN_AFTER_ERROR_MS = 30000;

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
  // Se incrementa para volver a abrir el stream después de un error. Sin esto
  // no hay forma de reabrirlo, porque el efecto solo depende del slug.
  const [attempt, setAttempt] = useState(0);
  // `onChange` se rearma en cada render de la página. Guardarlo en una ref
  // mantiene el efecto atado sólo al slug: sin esto, cada render cerraría y
  // reabriría el stream, que es justo lo que se quería dejar de hacer.
  const handler = useRef(onChange);
  useEffect(() => { handler.current = onChange; }, [onChange]);

  useEffect(() => {
    if (typeof window === "undefined" || typeof EventSource === "undefined") return;
    const source = new EventSource(apiUrl(`/portal/${slug}/events`), { withCredentials: true });
    let reopen: ReturnType<typeof setTimeout> | undefined;
    source.onopen = () => setLive(true);
    source.addEventListener("conversation", () => handler.current());
    source.onerror = () => {
      setLive(false);
      // Se cierra en vez de dejar que reintente solo. EventSource no expone el
      // código de la respuesta, así que no puede distinguir un corte de red de
      // una sesión terminada: contra la segunda, su reintento automático es un
      // 401 cada tres segundos, para siempre, y nadie se entera de nada.
      //
      // Quien sí puede darse cuenta es el refresco por intervalo, que usa
      // fetch y ve el 401. Se le deja el trabajo a él, y mientras tanto se
      // vuelve a intentar mucho más lento.
      source.close();
      reopen = setTimeout(() => setAttempt((value) => value + 1), REOPEN_AFTER_ERROR_MS);
    };
    return () => { clearTimeout(reopen); source.close(); setLive(false); };
  }, [slug, attempt]);

  return live;
}
