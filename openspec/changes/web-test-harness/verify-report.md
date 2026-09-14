# Verificación — `web-test-harness`

Fecha: 2026-09-13
Rama: `web-test-harness` (3 commits sobre `main`)
Especificación: `spec.md` · Tareas: `tasks.md`

Todo lo que sigue se ejecutó. Ningún punto se da por supuesto.

---

## Evidencia del control negativo (R4 / D7)

El riesgo alto de este cambio era entregar un arnés que reportara verde sin
ejecutar nada. Se descartó de forma activa.

Con el test escrito para fallar en `components/ui.test.tsx`:

```
❯ components/ui.test.tsx:8:19
    expect(screen.getByText("Inactivo")).toBeVisible();

 Test Files  1 failed | 9 passed (10)
      Tests  1 failed | 56 passed (57)
 EXIT: 1
```

Cuatro cosas quedan probadas de una sola vez:

1. **El proyecto `components` ejecuta.** El recuento pasó de 56 a 57.
2. **La salida nombra el test.** No es un fallo genérico.
3. **jsdom renderiza de verdad.** El volcado del error mostró el DOM real:
   `<span class="status status-active"><i />Activo</span>`.
4. **Los matchers de `jest-dom` están cargados.** La cadena llegó hasta
   `toBeVisible()`; el fallo fue de `getByText`, no de un matcher inexistente.

Test eliminado a continuación (T8). No queda en el repositorio.

---

## Los cinco pasos del CI, desde instalación limpia

Se borró `node_modules` y se corrió `npm ci`, replicando lo que hacen el runner
del job `web` y `apps/web/Dockerfile:5`.

| # | Paso | Resultado |
|---|---|---|
| 1 | `npm ci` | **código 0** |
| 2 | `npm run lint` | **limpio** |
| 3 | `npx tsc --noEmit` | **limpio** |
| 4 | `npm test` | **11 archivos, 63 tests, todos en verde** |
| 5 | `npm run build` | **código 0** |

## El CI real, sobre el PR #88

Lo de arriba es local, en Windows. Esto es el runner de GitHub, en Ubuntu, que
es lo que decide. Corrida `34792352566`, **los 7 jobs en verde**:

| Job | Resultado |
|---|---|
| `web (lint + types + tests + build)` | pass · 57s |
| `api (pytest + migrations)` | pass · 2m52s |
| `whatsapp (tests + build)` | pass · 13s |
| `mobile (types)` | pass · 25s |
| `stack (compose boots and stays hardened)` | pass · 1m26s |
| `dependency scan` | pass · 23s |
| `guard (no internal content)` | pass · 5s |

Dos cosas que solo se podían comprobar acá:

1. **Los globs funcionan en Linux.** El log del job `web` muestra los dos
   proyectos y el recuento completo:
   ```
   ✓  components  components/ui.test.tsx (4 tests)
   ✓  components  components/rich-text.test.tsx (3 tests)
    Test Files  11 passed (11)
         Tests  63 passed (63)
   ```
   No son solo los 56 de `lib/`: el proyecto `components` también corre en el
   runner.

2. **Eliminar el paso «Install the test runner» no rompió nada** (R7/E7.2).
   `npm ci` instaló 451 paquetes, vitest entre ellos, y `npm test` lo encontró.

El job `dependency scan` —que no estaba en el análisis inicial— pasó. Confirma
lo que dice la sección de fuera de alcance: las vulnerabilidades de vitest son
de desarrollo y no bloquean la entrega.

---

## Requisitos

| Req. | Qué exige | Estado | Evidencia |
|---|---|---|---|
| R1 | Los 56 de `lib/` siguen en Node, sin tocarse | ✅ | Salida etiquetada `logic`; `git diff main --stat` no muestra ningún archivo de `lib/` |
| R2 | Proyecto de componentes con DOM | ✅ | 7 tests etiquetados `components` |
| R3 | Los tests se descubren donde se escriben | ✅ | `components/ui.test.tsx` y `components/rich-text.test.tsx` aparecen en la corrida |
| R4 | Arnés probado en vivo | ✅ | Sección de arriba |
| R5 | Dependencias declaradas, lockfile coincidente | ✅ | `npm ci` en 0 sobre un árbol sin `node_modules` |
| R6 | Los cinco pasos del CI en verde | ✅ | Tabla de arriba |
| R7 | Paso redundante eliminado | ✅ | `ci.yml`, −9 líneas |
| R8 | Primeros tests cubren algo real | ✅ | 7 tests, detalle abajo |
| R9 | Ni una línea de producción | ✅ | `git diff main --stat` |

### Detalle de R5

```
"@testing-library/dom": "^10.4.2"
"@testing-library/jest-dom": "^7.0.1"
"@testing-library/react": "^16.3.3"
"@testing-library/user-event": "^14.6.7"
"jsdom": "^29.1.1"
```

Las cinco en `devDependencies`. `dependencies` quedó intacto: `lucide-react`,
`next`, `react`, `react-dom`. `@testing-library/react` resolvió a **16.3.3**,
que cumple el mínimo de v16 exigido por React 19 (D4).

### Detalle de R8 — los 7 tests

`components/rich-text.test.tsx` (3):
- El marcado sale como texto y no existe ningún elemento `script`.
- Un destino `javascript:` no genera ningún `<a>`.
- Una URL `https` normal sí se convierte en enlace, con su `href` correcto.

Los dos primeros ponen por escrito propiedades de seguridad que hoy solo
estaban implícitas en la regex de `rich-text.tsx:9`. El tercero existe para que
los otros dos no puedan aprobarse con la función rota del todo.

`components/ui.test.tsx` (4):
- `Modal` cerrado no renderiza ningún rol `dialog`.
- `Modal` abierto expone rol `dialog`, `aria-modal="true"` y nombre accesible
  igual al título.
- `StatusBadge` activo dice «Activo»; inactivo dice «Inactivo».

### Detalle de R9

```
 .github/workflows/ci.yml               |   9 -
 apps/web/components/rich-text.test.tsx |  34 ++
 apps/web/components/ui.test.tsx        |  40 ++
 apps/web/package-lock.json             | 785 +++++++++++++++++++++
 apps/web/package.json                  |   5 +
 apps/web/test/setup.ts                 |  13 +
 apps/web/vitest.config.ts              |  44 +-
```

Ningún archivo bajo `app/`, `lib/`, `public/`, ni `proxy.ts`, ni
`next.config.ts`. En `components/` solo los dos archivos de test nuevos.

**145 líneas** sin contar el `package-lock.json`. Presupuesto: 400. Sin
encadenar PRs.

---

## Hallazgo fuera de alcance

`npm audit` reporta 2 vulnerabilidades, **1 moderada y 1 crítica**. Las dos
están en **vitest**, que ya era dependencia antes de este cambio
(`^3.2.4`, commit `1cab8bc`). **No las introduce este trabajo.**

- `@vitest/mocker` — *Path Traversal / Arbitrary File Read* (moderada).
- `vitest` — *arbitrary file read and execution when the Vitest UI server is
  listening* (crítica).

Alcance real acotado, por tres motivos:

1. `npm audit --omit=dev` devuelve **0 vulnerabilidades**. Nada de esto llega a
   la imagen de producción, que instala con `--omit=dev`.
2. La crítica exige que el servidor de la interfaz de Vitest esté escuchando.
   Este proyecto nunca corre `vitest --ui`: `package.json` define `vitest run`
   y `vitest`.
3. El rango afectado es `2.1.0 - 4.1.10`. La última 3.x es la **3.2.7**, que
   está dentro de ese rango: **no alcanza con actualizar el parche**. Arreglarlo
   exige subir a vitest 4.x, que es un salto mayor.

Por eso **no se toca acá**: un salto mayor del corredor de tests, metido dentro
del cambio que estrena el arnés, mezcla dos fallos posibles en un solo diff.
Queda propuesto como cambio aparte.

---

## Estado

**Aprobado.** Las 19 tareas cerradas y los 6 puntos del criterio de aceptación
de `proposal.md` con evidencia.

Próxima fase: `archive`, o pasar al cambio 2 de
`openspec/changes/README.md` (`web-i18n-hardcoded-strings`), que es el primero
que ya puede apoyarse en este arnés.
