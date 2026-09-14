# Especificación — `web-test-harness`

Propuesta: `proposal.md`
Ámbito: `apps/web` (más un paso en `.github/workflows/ci.yml`)

Cada requisito trae los escenarios que lo verifican. Un escenario que no se
puede ejecutar no es un escenario: es una intención.

---

## R1 — Los 56 tests actuales siguen corriendo en Node, sin cambios

El entorno `node` de los tests de `lib/` no es un detalle heredado. Su
configuración lo declara a propósito (`vitest.config.ts:3-6`): esos módulos
corren a ambos lados del cable, y correrlos sin DOM es lo que verifica que de
verdad no dependan de uno. Darles jsdom no los rompería — les quitaría la
propiedad que hoy demuestran.

**E1.1 — El entorno se mantiene**
- **Dado** el proyecto `logic` configurado con `environment: "node"`
- **Cuando** se corre `npm test`
- **Entonces** los tests de `lib/` se ejecutan sin `window` ni `document`
  definidos.

**E1.2 — Ningún test existente se modifica**
- **Dado** el conjunto de 9 archivos de test bajo `lib/`
- **Cuando** termina el cambio
- **Entonces** `git diff` no muestra ninguna modificación en esos 9 archivos.

**E1.3 — El recuento no baja**
- **Cuando** se corre `npm test`
- **Entonces** la suma de tests ejecutados es **56 más los nuevos**, nunca
  menos de 56.

---

## R2 — Existe un proyecto de tests de componente con DOM

**E2.1 — Un componente se puede renderizar**
- **Dado** un test bajo `components/`
- **Cuando** llama a `render()` de `@testing-library/react`
- **Entonces** el componente se monta y se puede consultar por rol accesible.

**E2.2 — La interacción de teclado funciona**
- **Dado** un test que usa `@testing-library/user-event`
- **Cuando** simula `Tab` y `Enter`
- **Entonces** el foco y los manejadores responden como en un navegador.

Este escenario no es decorativo: es el que habilita los cambios 3 y 4, que son
enteramente de teclado.

---

## R3 — Los tests de componente se descubren donde se escriben

Hoy `vitest.config.ts:10` acota la ejecución a `lib/**`. Un test en
`components/` no correría, y su ausencia no se notaría: la suite seguiría en
verde.

**E3.1 — Un test en `components/` se ejecuta**
- **Dado** un archivo `components/ui.test.tsx`
- **Cuando** se corre `npm test`
- **Entonces** aparece en la salida del corredor.

**E3.2 — Un test en `app/` se ejecuta**
- **Dado** un archivo de test bajo `app/`
- **Cuando** se corre `npm test`
- **Entonces** aparece en la salida del corredor.

**E3.3 — La convención de ubicación se mantiene**
- El repositorio ya coloca el test al lado del módulo (`lib/api.ts` +
  `lib/api.test.ts`). Los tests de componente siguen esa misma convención.
  No se crea un árbol `__tests__/` aparte.

---

## R4 — El arnés está probado en vivo, no supuesto

El riesgo dominante de este cambio es un arnés que no ejecuta nada y reporta
verde. Este requisito existe para descartarlo con evidencia, no con confianza.

**E4.1 — Control negativo**
- **Dado** un test de componente escrito para fallar (por ejemplo, afirmar que
  `StatusBadge` con `active` verdadero dice «Inactivo»)
- **Cuando** se corre `npm test`
- **Entonces** `npm test` **falla**, y la salida nombra ese test.

**E4.2 — Vuelta a verde**
- **Cuando** se corrige o se elimina ese test
- **Entonces** `npm test` vuelve a pasar.

Los dos pasos se ejecutan durante la implementación y su salida se registra en
el informe de verificación. El test del control negativo **no** queda en el
repositorio.

---

## R5 — Las dependencias están declaradas y el lockfile coincide

`apps/web/Dockerfile:5` corre `npm ci`, que falla si `package.json` y
`package-lock.json` discrepan. Declarar sin regenerar rompe la imagen.

**E5.1 — Instalación limpia**
- **Dado** un clon sin `node_modules`
- **Cuando** se corre `npm ci`
- **Entonces** termina con código 0.

**E5.2 — Solo dependencias de desarrollo**
- **Entonces** `jsdom`, `@testing-library/react`,
  `@testing-library/user-event` y `@testing-library/jest-dom` figuran en
  `devDependencies`, nunca en `dependencies`.

**E5.3 — La imagen de producción no engorda**
- **Dado** que la imagen instala con `--omit=dev`
- **Entonces** ninguna de las cuatro llega al bundle ni a la imagen final.

---

## R6 — Los cinco pasos del CI quedan en verde

No es un chequeo al final: es el requisito. El job `web` de
`.github/workflows/ci.yml` corre `npm ci`, `npm run lint`, `npx tsc --noEmit`,
`npm test` y `npm run build`.

**E6.1 — Lint**
- **Cuando** se corre `npm run lint`
- **Entonces** termina sin errores ni avisos nuevos.
- Los archivos de test importan de `"vitest"` explícitamente, siguiendo la
  convención vigente (`lib/api.test.ts:1`). **No** se activa `globals: true`,
  así que no hacen falta globales declarados en la configuración de ESLint.

**E6.2 — Tipos**
- **Cuando** se corre `npx tsc --noEmit`
- **Entonces** termina limpio, con los matchers de `jest-dom` reconocidos.
- `tsconfig.json` incluye `**/*.ts` y `**/*.tsx`, así que los archivos de test
  **sí** se comprueban. Un matcher sin tipos rompe el CI.

**E6.3 — Build**
- **Cuando** se corre `npm run build`
- **Entonces** termina sin error.
- El archivo de setup no puede quedar dentro del grafo de la aplicación: ni en
  `app/`, ni importado por código de producción.

---

## R7 — El paso redundante del CI se elimina

`ci.yml` instala vitest con `npm install --no-save` y su comentario declara la
condición para borrarlo: declararlo en `package.json` y refrescar el lockfile.
Ambas cosas ya están hechas (`package.json:23`, y el paquete está en el
lockfile).

**E7.1 — El paso ya no está**
- **Entonces** el paso «Install the test runner» no existe en `ci.yml`.

**E7.2 — El CI sigue pasando sin él**
- **Cuando** corre el job `web` en un runner limpio
- **Entonces** `npm test` encuentra vitest desde `node_modules`, instalado por
  `npm ci`.

---

## R8 — Los primeros tests de componente cubren algo real

Un arnés con un test de humo («el componente no explota») no demuestra nada y
envejece mal. Los tres primeros fijan comportamiento que los cambios siguientes
van a tocar a propósito.

**E8.1 — `RichText` no ejecuta lo que recibe**
- **Dado** `<RichText text="<script>alert(1)</script>" />`
- **Entonces** el marcado aparece como texto visible, y no existe ningún
  elemento `script` en el resultado.

**E8.2 — `RichText` no crea enlaces peligrosos**
- **Dado** un texto con `[x](javascript:alert(1))`
- **Entonces** no se genera ningún `<a>` hacia ese destino.
- Esto documenta una propiedad que hoy solo está implícita en la regex de
  `rich-text.tsx:9`.

**E8.3 — `Modal` cerrado no renderiza**
- **Dado** `<Modal open={false} …>`
- **Entonces** no hay ningún elemento con rol `dialog` en el documento.

**E8.4 — `Modal` abierto expone su rol y su nombre accesible**
- **Dado** `<Modal open title="Editar contacto" …>`
- **Entonces** existe un elemento con rol `dialog`, con `aria-modal`, cuyo
  nombre accesible es «Editar contacto».
- Este es el punto de partida contra el que el cambio 3 va a comparar el
  Escape, el foco inicial y la trampa de foco.

**E8.5 — `StatusBadge` fija su comportamiento actual**
- **Dado** `<StatusBadge active />`
- **Entonces** muestra «Activo».
- Queda escrito a propósito **como está hoy**, en español y sin i18n, para que
  el cambio 2 lo rompa de forma visible al traducirlo. Un test que no se rompe
  cuando el comportamiento cambia no estaba probando nada.

---

## R9 — No cambia el comportamiento de la aplicación

**E9.1 — Ni una línea de producción**
- **Entonces** `git diff` no toca ningún archivo bajo `app/`, `components/`,
  `lib/`, `proxy.ts`, `next.config.ts` ni `public/`, salvo los archivos de test
  nuevos.

Este cambio agrega la capacidad de probar. No arregla nada. Lo que arregla es
de los cambios 2 a 7.

---

## Fuera de alcance

Declarado explícitamente para que nadie lo agregue «de paso»:

- Playwright o cualquier e2e.
- Umbrales de cobertura, en CI o fuera.
- Reactivar reglas de ESLint apagadas.
- Tests sobre páginas de `app/` que hacen red (necesitan decidir cómo se simula
  `fetch`; eso es del cambio que las toque).
- Cualquier corrección de la auditoría.

## Próxima fase

`design.md` — cómo se implementa.
