# Exploración — `web-test-harness`

Fecha: 2026-09-13
Fuente: `AUDITORIA-WEB.md`, sección «Estado verificado» y sección 2.

## Qué hay hoy, verificado

Comprobado ejecutando los comandos, no por lectura:

```
npx tsc --noEmit   → limpio
npm run lint       → limpio
npm test           → 56 tests, 9 archivos, todos pasan
```

Los 9 archivos de test viven **todos** bajo `lib/`:

| Archivo | Tests |
|---|---|
| `lib/widget-embed.test.ts` | 9 |
| `lib/cache-policy.test.ts` | 9 |
| `lib/board.test.ts` | 13 |
| `lib/api.test.ts` | 10 |
| `lib/i18n/i18n.test.ts` | 5 |
| `lib/datetime.test.ts` | 4 |
| `lib/invitations.test.ts` | 2 |
| `lib/i18n/dicts/portal.test.ts` | 2 |
| `lib/live.test.ts` | 2 |

Cero tests sobre los 21 componentes de `components/` y las 21 páginas de
`app/`. No está instalado `@testing-library/react`, ni `jsdom`, ni
`@testing-library/user-event`. No hay Playwright ni ningún e2e.

## La decisión ya estaba anotada

`apps/web/vitest.config.ts:3-6` dice, literalmente:

```
// Node environment on purpose: these tests cover the logic modules under lib/,
// which run on both sides of the wire and render nothing. Component tests would
// need jsdom and a DOM testing library; that is a separate decision, not a
// prerequisite for having a test suite at all.
```

Quien escribió esa configuración dejó la puerta señalizada. Este cambio es
cruzarla. No hay que discutir si conviene: hay que decidir cómo, sin romper lo
que ya funciona.

Consecuencia concreta de esa configuración: `include` está acotado a
`["lib/**/*.test.ts", "lib/**/*.test.tsx"]`. Un test escrito en
`components/` o en `app/` **no se ejecuta**. Pasaría inadvertido, en verde,
sin correr nunca.

## Restricciones que condicionan la solución

### 1. El CI tiene que quedar en verde

`.github/workflows/ci.yml`, job `web`, en este orden:

```
npm ci
npm run lint
npx tsc --noEmit
npm test
npm run build
```

Los cinco. Un entorno de test mal configurado rompe `tsc` (tipos de los
matchers), o `lint` (globales de test sin declarar), o `build` (si el archivo
de setup entra en el grafo de la aplicación).

### 2. El lockfile y `npm ci`

`apps/web/Dockerfile:5` corre `npm ci`, que **falla** si `package.json` y
`package-lock.json` no coinciden. No alcanza con declarar las dependencias:
hay que regenerar el lockfile y versionarlo en el mismo commit.

Esto no es teórico. `ci.yml` tiene hoy un paso llamado «Install the test
runner» que instala vitest con `npm install --no-save`, con este comentario:

> Installed here rather than declared in package.json on purpose. The image
> build runs `npm ci` (apps/web/Dockerfile:5), which fails when package.json
> and package-lock.json disagree, and the lockfile cannot be regenerated from a
> machine with no node_modules. TO FIX PROPERLY: run `npm install -D vitest`
> once locally, commit the refreshed lockfile, and delete this step.

**Eso ya se hizo.** `package.json:23` declara `vitest` y el lockfile lo tiene.
El paso sobra y se elimina en este cambio.

### 3. El guard de pre-commit

`.githooks/pre-commit` bloquea rutas local-only y palabras de una lista
privada. El mismo hook corre en CI como job `guard`. Nada de lo que agrega
este cambio cae en esas rutas, pero conviene tenerlo presente.

## Opciones consideradas

### A. Un solo proyecto vitest con `environment: "jsdom"` global

Simple, un archivo de configuración. Pero le pone un DOM a los 56 tests de
`lib/` que hoy corren en Node y no lo necesitan: más lento y, peor, deja de
verificar que esos módulos funcionen **sin** DOM, que es justo lo que su
comentario dice que garantizan («run on both sides of the wire»).

Se descarta: rompe una propiedad que el código afirma tener.

### B. `environmentMatchGlob`

Permitiría node para `lib/` y jsdom para componentes en una sola corrida.

Se descarta porque **ya no existe**. Comprobado contra la versión instalada
(`vitest@3.2.4`): el identificador no aparece en ninguna de las definiciones de
tipos de `node_modules/vitest/dist/`. No está deprecado, está eliminado.

### C. Dos proyectos de Vitest (`test.projects`)

Un proyecto `logic` con `environment: "node"` e `include: ["lib/**"]`,
idéntico al de hoy. Un proyecto `components` con `environment: "jsdom"`,
`include: ["components/**", "app/**"]` y su archivo de setup.

`npm test` corre los dos. Los 56 tests actuales conservan exactamente su
entorno, y los nuevos tienen DOM.

Es la forma soportada en la versión instalada: `projects?: TestProjectConfiguration[]`
está en los tipos de `vitest@3.2.4`
(`node_modules/vitest/dist/chunks/reporters.d.BFLkQcL6.d.ts:1767`).

**Elegida.**

## Preguntas abiertas

Ninguna bloqueante. Dos decisiones menores se resuelven en el diseño:

1. Dónde viven los tests de componente: junto al componente
   (`components/ui.test.tsx`) o en un árbol aparte. El repositorio ya usa la
   convención de al lado (`lib/api.ts` + `lib/api.test.ts`); conviene seguirla.
2. Si se agrega `@testing-library/jest-dom`. Aporta matchers legibles
   (`toBeVisible`, `toHaveAccessibleName`) que los cambios 3 y 4 van a usar
   mucho, a cambio de una dependencia más y un `tsconfig` que la conozca.

## Qué prueba que el cambio funcionó

No alcanza con «pasan los tests». El riesgo real de este cambio es montar un
arnés que **parezca** funcionar y no ejecute nada. La verificación tiene que
demostrar lo contrario de forma activa; se detalla en `spec.md`.
