# Tareas — `web-test-harness`

Especificación: `spec.md` · Diseño: `design.md`

Presupuesto de revisión: 400 líneas. Estimado sin el `package-lock.json`: ~150.
**No hace falta encadenar PRs.**

Todo lo que sigue ocurre dentro de `apps/web`, salvo T9 (`.github/`).

---

## Bloque A — Preparación

- [x] **T1.** Crear la rama `web-test-harness` desde `main`.
      No se commitea en `main`.

- [x] **T2.** Instalar las cinco dependencias de desarrollo, con `npm install -D`
      para que el lockfile se regenere solo:
      ```
      npm install -D jsdom @testing-library/react @testing-library/dom \
                     @testing-library/user-event @testing-library/jest-dom
      ```
      Verificar antes de seguir:
      - Las cinco quedaron en `devDependencies`, ninguna en `dependencies` (E5.2).
      - `@testing-library/react` resolvió a v16 o superior (D4). Si resolvió a
        v15 o menos, **parar**: no soporta React 19.

- [x] **T3.** Commit 1 — `chore(web): declare component testing dependencies`.
      Solo `package.json` y `package-lock.json`. Nada más entra en este commit.

---

## Bloque B — El arnés

- [x] **T4.** Reescribir `vitest.config.ts` con los dos proyectos de D1.
      - El proyecto `logic` conserva `environment: "node"` y el `include` actual,
        palabra por palabra (R1).
      - Mantener sobre él el comentario que explica por qué es `node`: sigue
        siendo cierto.
      - El proyecto `components` lleva `environment: "jsdom"`, `globals: true`,
        `setupFiles` e `include` para `components/**/*.test.tsx` y
        `app/**/*.test.tsx`.

- [x] **T5.** Crear `test/setup.ts` con una sola línea:
      ```ts
      import "@testing-library/jest-dom/vitest";
      ```
      Fuera de `app/` y de `components/`, o entra en el grafo de `next build`
      (D3, E6.3).

- [x] **T6.** Comprobar que el proyecto `logic` no se movió:
      ```
      npm test
      ```
      Tienen que seguir corriendo **56** tests en 9 archivos, todos en verde
      (E1.3). Todavía no hay tests de componente; el proyecto `components`
      puede reportar cero y está bien en este punto.

---

## Bloque C — Control negativo (el paso que no se saltea)

Este bloque existe porque el riesgo alto de este cambio es un arnés que reporta
verde sin ejecutar nada (D7, R4).

- [x] **T7.** Escribir en `components/ui.test.tsx` un test que **tiene que
      fallar**:
      ```tsx
      it("control negativo — tiene que fallar", () => {
        render(<StatusBadge active />);
        expect(screen.getByText("Inactivo")).toBeVisible();
      });
      ```
      Correr `npm test` y comprobar las dos cosas:
      1. La corrida **falla**.
      2. La salida **nombra** ese test.

      Si pasa, o si el test no aparece por ningún lado, el proyecto
      `components` no está ejecutando: revisar `include` y el registro del
      proyecto. **No avanzar hasta que falle.**

      Guardar la línea decisiva de la salida: va al informe de verificación.

- [x] **T8.** Eliminar el test del control negativo. No queda en el
      repositorio (R4).

---

## Bloque D — Los primeros tests de verdad

- [x] **T9.** `components/rich-text.test.tsx`:
      - `<script>alert(1)</script>` sale como texto visible y no existe ningún
        elemento `script` en el resultado (E8.1).
      - `[x](javascript:alert(1))` no genera ningún `<a>` hacia ese destino
        (E8.2).

- [x] **T10.** `components/ui.test.tsx`:
      - `Modal` con `open={false}` no renderiza ningún rol `dialog` (E8.3).
      - `Modal` con `open` expone rol `dialog`, `aria-modal`, y su nombre
        accesible es el título (E8.4).
      - `StatusBadge` con `active` dice **«Activo»** — el comportamiento actual,
        en español y sin i18n, escrito así a propósito para que el cambio 2 lo
        rompa de forma visible (E8.5). Dejar el comentario que lo explica, o el
        próximo que lo lea va a creer que es un descuido.

      Consultar siempre por rol accesible, nunca por clase CSS ni
      `data-testid` (D5).

- [x] **T11.** Commit 2 — `test(web): run component tests in a jsdom project`.
      `vitest.config.ts`, `test/setup.ts`, `components/rich-text.test.tsx`,
      `components/ui.test.tsx`.

---

## Bloque E — Limpieza del CI

- [x] **T12.** Eliminar el paso «Install the test runner» de
      `.github/workflows/ci.yml`, junto con su comentario, que describe una
      condición ya cumplida (R7).

- [x] **T13.** Commit 3 — `ci: drop the redundant test runner install step`.

---

## Bloque F — Verificación (los cinco pasos del CI)

En este orden, y con la salida registrada. Ninguno se da por supuesto.

- [x] **T14.** Instalación limpia:
      ```
      rm -rf node_modules && npm ci
      ```
      Tiene que terminar en 0 (E5.1). Es lo que corre `apps/web/Dockerfile:5`;
      si falla acá, la imagen no se construye.

- [x] **T15.** `npm run lint` — limpio, sin avisos nuevos (E6.1).

- [x] **T16.** `npx tsc --noEmit` — limpio, con los matchers de `jest-dom`
      reconocidos (E6.2).

- [x] **T17.** `npm test` — **56 + los nuevos**, todos en verde. Anotar el
      recuento exacto (E1.3, E3.1).

- [x] **T18.** `npm run build` — sin error (E6.3).

- [x] **T19.** Comprobar R9: `git diff main --stat` no toca ningún archivo de
      producción. Solo `package.json`, `package-lock.json`, `vitest.config.ts`,
      `test/setup.ts`, los dos archivos de test nuevos y `ci.yml`.

---

## Definición de terminado

Las 19 tareas cerradas, y los seis puntos del criterio de aceptación de
`proposal.md` con evidencia registrada — incluido el control negativo, que es
el que distingue un arnés que funciona de uno que lo aparenta.

## Fuera de estas tareas

No se agrega Playwright, ni umbrales de cobertura, ni se reactiva ninguna regla
de ESLint, ni se corrige ningún hallazgo de la auditoría. Si algo de eso aparece
en el diff, se sacó de alcance.
