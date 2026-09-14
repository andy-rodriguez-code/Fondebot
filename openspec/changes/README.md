# Cambios SDD — frontend `apps/web`

Hoja de ruta derivada de `AUDITORIA-WEB.md` (2026-09-13).

Los hallazgos de la auditoría no entran en un solo cambio. Se parten en siete,
ordenados por dependencia real, no por severidad: el primero existe porque sin
él ninguno de los otros se puede probar.

Cada cambio tiene que dejar el CI en verde por sí solo. El job `web` de
`.github/workflows/ci.yml` corre, en este orden: `npm ci`, `npm run lint`,
`npx tsc --noEmit`, `npm test`, `npm run build`. Un cambio que rompa cualquiera
de los cinco no se sube.

## Secuencia

| # | Cambio | Qué resuelve | Depende de | Líneas estimadas |
|---|---|---|---|---|
| 1 | `web-test-harness` | No hay forma de probar un componente | — | ~150 |
| 2 | `web-i18n-hardcoded-strings` | Texto en español escrito a mano en 9 sitios | 1 | ~80 |
| 3 | `web-keyboard-access` | Navegación del portal y modales sin teclado | 1, 2 | ~250 |
| 4 | `web-combobox-aria` | `role="listbox"` roto, sin flechas | 1, 3 | ~180 |
| 5 | `web-destructive-confirm` | 8 borrados sin confirmación | 1, 2 | ~200 |
| 6 | `web-asset-weight` | Logo de 627 KB, widget que carga la app entera | 1 | ~60 |
| 7 | `api-agency-logo-hardening` | `agency.py:69` sirve SVG sin `nosniff` ni CSP | — | ~20 |

El 7 no depende de nada y es el único que toca `apps/api`. Se puede adelantar
en cualquier momento; se deja al final solo porque su riesgo es el más acotado
de los siete (intra-agencia, requiere navegación directa al recurso).

## Lo que queda fuera, y por qué

Tres hallazgos de la auditoría **no** se convierten en cambios ahora:

- **Migrar a Server Components** (39 de 42 archivos llevan `"use client"`). Es
  la deuda más grande y la de mayor rendimiento, pero toca todas las pantallas
  a la vez. Merece su propio ciclo, después de que exista la red de tests que
  construye el cambio 1.
- **Deduplicar las dos bandejas de entrada** en un `useConversationInbox()`.
  Mismo motivo: un refactor de ~650 líneas sin tests de componente es
  exactamente lo que no hay que hacer.
- **Partir `globals.css`** (1.522 líneas). No bloquea nada y no tiene forma
  barata de verificarse.

El orden no es casual: los tres son refactors grandes, y los siete cambios de
arriba son los que dejan el terreno en condiciones de encararlos.

## Estado

| # | Cambio | Fase actual |
|---|---|---|
| 1 | `web-test-harness` | verificado — listo para archivar |
| 2–7 | — | sin empezar |
