/**
 * Qué páginas puede guardar el navegador.
 *
 * La regla vive acá, sola y sin depender de Next, porque decide si una pantalla
 * con sesión puede volver con la flecha atrás después de cerrar sesión. Está
 * separada de `proxy.ts` para poder probarla: ese archivo necesita el runtime
 * de Next para correr, y una regla de seguridad que no se puede probar es una
 * regla que nadie revisa.
 */

/** Rutas públicas: no tienen sesión que proteger y conviene que se cacheen. */
const PUBLIC_PREFIXES = ["/widget/"];

export function isPublicPage(pathname: string): boolean {
  return PUBLIC_PREFIXES.some((prefix) => pathname.startsWith(prefix));
}

/**
 * `no-store` para todo lo demás.
 *
 * Sin esto el panel salía con `s-maxage` de un año: el navegador quedaba libre
 * de devolverlo con la flecha atrás DESPUÉS de cerrar sesión, restaurándolo
 * desde su caché de atrás/adelante con el estado revivido y sin correr ningún
 * control. `no-store` además apaga esa caché para el documento en los
 * navegadores actuales, así que corta la causa y no el síntoma.
 */
export function cacheControlFor(pathname: string): string | null {
  return isPublicPage(pathname) ? null : "no-store, must-revalidate";
}
