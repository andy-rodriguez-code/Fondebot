# Diseño — `web-test-harness`

Propuesta: `proposal.md` · Especificación: `spec.md`

---

## D1 — Dos proyectos de Vitest, no un entorno global

`vitest.config.ts` pasa de un único bloque `test` a `test.projects`:

```ts
import { defineConfig } from "vitest/config";

export default defineConfig({
  test: {
    projects: [
      {
        test: {
          name: "logic",
          environment: "node",
          include: ["lib/**/*.test.ts", "lib/**/*.test.tsx"],
        },
      },
      {
        test: {
          name: "components",
          environment: "jsdom",
          globals: true,
          setupFiles: ["./test/setup.ts"],
          include: ["components/**/*.test.tsx", "app/**/*.test.tsx"],
        },
      },
    ],
  },
});
```

El proyecto `logic` conserva palabra por palabra el `environment` y el `include`
de hoy. El comentario que explica por qué es `node` se mantiene sobre él: sigue
siendo cierto y sigue siendo el motivo.

`projects` está en los tipos de la versión instalada, `vitest@3.2.4`
(`node_modules/vitest/dist/chunks/reporters.d.BFLkQcL6.d.ts:1767`).
`environmentMatchGlob`, que sería la alternativa, **no existe** en esa versión.

Alias `@/*`: los tests de `lib/` ya lo usan (`lib/board.test.ts:3` importa
`@/types`), así que hoy resuelve. Si al pasar a `projects` deja de resolver en
alguno de los dos, se agrega `resolve.alias` a nivel raíz del archivo, no por
proyecto.

---

## D2 — `globals: true`, pero solo en el proyecto de componentes

Esta es la decisión menos obvia del cambio, y la que más fácil sale mal.

React Testing Library registra su limpieza automática así
(`src/index.js` de la librería):

```js
if (typeof afterEach === 'function') {
  afterEach(() => { cleanup() })
}
if (typeof beforeAll === 'function' && typeof afterAll === 'function') {
  // fija IS_REACT_ACT_ENVIRONMENT durante la suite
}
```

Comprueba los hooks como **globales**. Vitest, por defecto, no los expone:
`globals` es `false`, y los tests de este repositorio importan explícitamente
(`lib/api.test.ts:1`).

Con `globals: false`, entonces:

1. **La limpieza no se registra.** Cada `render()` deja su árbol montado en el
   `document`. Dos tests que rendericen el mismo componente encuentran dos
   coincidencias, y `getByRole` falla con un error que habla de elementos
   duplicados y no dice nada del verdadero motivo.
2. **El entorno de `act` no se configura.** `IS_REACT_ACT_ENVIRONMENT` queda sin
   fijar y React 19 emite avisos en cada actualización de estado.

Ninguna de las dos cosas aparece al escribir el primer test. Aparecen al
escribir el tercero, y se diagnostican mal.

**Decisión:** `globals: true` en el proyecto `components`, y solo ahí. El
proyecto `logic` no se toca.

Esto no cambia la convención del repositorio: los tests **siguen importando**
`describe`, `it` y `expect` desde `"vitest"`, igual que los de `lib/`.
`globals: true` solo hace que además existan como globales, que es lo que RTL
necesita encontrar para armarse sola.

La alternativa —dejar `globals: false` y replicar a mano la limpieza y el
entorno de `act` en el archivo de setup— es reimplementar lo que la librería ya
hace, y quedarse desincronizado con ella en la próxima versión.

---

## D3 — Archivo de setup

`apps/web/test/setup.ts`. Fuera de `app/` y de `components/` a propósito: no
puede entrar en el grafo que compila `next build` (R6/E6.3).

```ts
import "@testing-library/jest-dom/vitest";
```

El punto de entrada `/vitest` registra los matchers en el `expect` de Vitest y
trae sus tipos. Como `tsconfig.json` incluye `**/*.ts`, ese import basta para
que `tsc --noEmit` reconozca `toBeVisible`, `toHaveAccessibleName` y el resto.
No hace falta tocar `compilerOptions.types`.

La limpieza no se escribe acá: con D2, RTL la registra sola.

---

## D4 — Dependencias

Las cinco, en `devDependencies`:

| Paquete | Por qué |
|---|---|
| `jsdom` | El DOM del proyecto `components`. |
| `@testing-library/react` | `render`, consultas por rol. |
| `@testing-library/dom` | **Peer dependency explícita** de RTL desde la v16. No se instala sola. Omitirla es el fallo de instalación más común de esta librería. |
| `@testing-library/user-event` | Teclado y puntero reales. Es lo que hace verificables los cambios 3 y 4. |
| `@testing-library/jest-dom` | Matchers accesibles y legibles. |

`@testing-library/react` tiene que ser **v16 o superior**: es la primera línea
que declara compatibilidad con React 19, y este proyecto usa
`react@^19.2.4` (`package.json:15`).

Se instalan con `npm install -D`, no a mano en el archivo, y el
`package-lock.json` regenerado se versiona en el mismo cambio (R5).

---

## D5 — Ubicación y forma de los tests

Al lado del módulo, como ya hace el repositorio:

```
components/rich-text.tsx      →  components/rich-text.test.tsx
components/ui.tsx             →  components/ui.test.tsx
```

Consultas **por rol accesible**, no por clase CSS ni por `data-testid`:
`getByRole("dialog")`, `getByRole("button", { name: … })`. No es preferencia de
estilo. Los cambios 3 y 4 son correcciones de accesibilidad; un test que busca
por clase pasaría en verde con el árbol accesible roto, que es exactamente el
defecto que hay que atrapar.

---

## D6 — Orden de los commits

Tres, en este orden. Cada uno deja el árbol coherente:

1. **`chore(web): declare component testing dependencies`** — solo
   `package.json` y `package-lock.json`. Es el diff grande y ruidoso; queda
   solo, y se verifica corriendo `npm ci`, no leyéndolo.
2. **`test(web): run component tests in a jsdom project`** —
   `vitest.config.ts`, `test/setup.ts`, y los tests de `rich-text` y `ui`.
3. **`ci: drop the redundant test runner install step`** — `ci.yml`.

El 1 solo no deja el CI en rojo: agrega dependencias que nadie usa todavía.
El 3 es independiente y podría ir primero; va último para no quedar
momentáneamente sin vitest si algo del 1 sale mal.

Total estimado sin el lockfile: ~150 líneas. Dentro del presupuesto de 400.

---

## D7 — Cómo se prueba que el arnés corre de verdad (R4)

Durante la implementación, y **antes** de dar el cambio por hecho:

1. Se agrega un test que debe fallar:
   ```tsx
   it("control negativo — tiene que fallar", () => {
     render(<StatusBadge active />);
     expect(screen.getByText("Inactivo")).toBeVisible();
   });
   ```
2. Se corre `npm test`. **Tiene que fallar**, y la salida tiene que nombrar
   ese test. Si pasa, o si no aparece, el proyecto `components` no está
   ejecutando nada: el `include` no coincide, o el proyecto no está registrado.
3. Se registra la salida en el informe de verificación.
4. Se elimina el test y se comprueba que vuelve a verde.

Sin este paso, el modo de fallo de este cambio es entregar un arnés vacío en
verde. Es el único riesgo alto de la propuesta, y esto es lo que lo cierra.

---

## D8 — Qué puede romper el CI, y dónde se comprueba

| Paso | Cómo lo rompe este cambio | Dónde se atrapa |
|---|---|---|
| `npm ci` | Lockfile desincronizado | Tarea de verificación con `node_modules` borrado |
| `npm run lint` | Reglas de Next sobre archivos `.test.tsx` | Se corre lint antes de cerrar, no al final |
| `npx tsc --noEmit` | Matchers de `jest-dom` sin tipos | D3; se corre `tsc` explícitamente |
| `npm test` | `include` mal escrito, proyecto vacío en verde | D7, control negativo |
| `npm run build` | `test/setup.ts` dentro del grafo de la app | D3, vive fuera de `app/` |

## Próxima fase

`tasks.md` — desglose accionable.
