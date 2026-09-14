# Propuesta — `web-test-harness`

Estado: pendiente de aprobación
Fecha: 2026-09-13
Exploración: `explore.md`

## Problema

`apps/web` tiene 56 tests y ninguno toca un componente ni una página. No es
descuido de quien escribió los tests: **no hay con qué**. No está instalado
`jsdom`, ni `@testing-library/react`, y `vitest.config.ts:10` limita la
ejecución a `lib/**`, así que un test de componente escrito hoy ni siquiera
correría.

Eso bloquea los seis cambios que vienen después. Los cambios 3, 4 y 5 de la
hoja de ruta son correcciones de accesibilidad y de confirmación destructiva:
«el foco vuelve al botón que abrió el diálogo», «Escape cierra el modal», «las
flechas mueven la selección», «borrar la credencial pregunta primero». Ninguna
de esas afirmaciones se puede verificar leyendo el diff. O hay un test que
aprieta la tecla, o no hay verificación.

Arreglar accesibilidad sin tests es especialmente malo, porque el defecto es
invisible para quien lo arregla: se comprueba con el ratón, se ve bien, y se
rompe otra vez tres commits después sin que nadie se entere.

## Propuesta

Montar el arnés de tests de componente, y demostrar que funciona con tests
reales sobre tres componentes que ya existen.

Dos proyectos de Vitest en un solo `npm test`:

- `logic` — `environment: "node"`, `include: ["lib/**"]`. Idéntico a hoy.
- `components` — `environment: "jsdom"`, `include: ["components/**", "app/**"]`,
  con archivo de setup propio.

Dependencias nuevas, todas de desarrollo: `jsdom`,
`@testing-library/react`, `@testing-library/user-event`,
`@testing-library/jest-dom`.

Los primeros tests de componente cubren tres piezas puras, elegidas porque no
piden red y porque los cambios siguientes las van a tocar:

| Componente | Por qué esta |
|---|---|
| `components/rich-text.tsx` | Es la superficie que recibe texto de visitantes. Un test que demuestre que `<script>` sale como texto y que un enlace `javascript:` no se convierte en `<a>` documenta la propiedad de seguridad que hoy solo está implícita. |
| `components/ui.tsx` (`Modal`) | El cambio 3 le agrega Escape, foco inicial y trampa de foco. Sin un test de partida, esas mejoras no tienen contra qué compararse. |
| `components/ui.tsx` (`StatusBadge`) | El cambio 2 traduce su «Activo»/«Inactivo». El test fija el comportamiento actual para que el cambio siguiente lo rompa a propósito. |

Además, se elimina el paso «Install the test runner» de `ci.yml`, que su propio
comentario declara obsoleto y que este cambio vuelve contradictorio: no tiene
sentido instalar vitest a mano mientras se agregan cuatro dependencias de test
bien declaradas.

## Lo que NO hace este cambio

Delimitarlo importa, porque es la clase de cambio que se infla solo:

- **No arregla ningún defecto de la auditoría.** Ni accesibilidad, ni i18n, ni
  confirmaciones. Eso es de los cambios 2 a 7.
- **No agrega Playwright ni ningún e2e.** Es otra decisión, con otro coste de
  CI.
- **No agrega cobertura mínima ni la exige en CI.** Un umbral de cobertura
  sobre una base que arranca casi en cero solo genera tests de relleno.
- **No toca los 56 tests existentes.** Tienen que seguir corriendo en Node, con
  el mismo entorno y el mismo resultado.
- **No reactiva ninguna regla de ESLint.** Tentador, pero es un cambio aparte
  con su propio riesgo sobre el CI.

## Riesgos

| Riesgo | Severidad | Mitigación |
|---|---|---|
| El proyecto `components` queda mal configurado y no ejecuta nada, en verde | **Alta** | La verificación exige contar los tests ejecutados y comprobar que un test que debe fallar, falla. Detallado en `spec.md`. |
| `package.json` y `package-lock.json` quedan desincronizados y `npm ci` rompe la imagen Docker | Alta | Regenerar el lockfile con `npm install` y versionarlo en el mismo commit. Verificar con `npm ci` en limpio. |
| Los matchers de `jest-dom` rompen `tsc --noEmit` | Media | Declarar los tipos en `tsconfig.json` y correr `npx tsc --noEmit` como parte de la verificación, no al final. |
| El archivo de setup entra en el grafo de la aplicación y rompe `npm run build` | Media | El setup vive fuera de `app/` y `components/`; `npm run build` forma parte de la verificación. |
| Los 56 tests de `lib/` cambian de entorno sin que nadie lo note | Media | El proyecto `logic` fija `environment: "node"` explícitamente, y la verificación compara el total: tienen que seguir siendo 56 más los nuevos. |
| Cuatro dependencias nuevas en un proyecto que hoy tiene ocho | Baja | Todas son `devDependencies`: no entran en la imagen de producción, que instala con `--omit=dev`. |

## Presupuesto de revisión

Estimado: ~150 líneas de código y configuración, más el `package-lock.json`
regenerado.

El lockfile va a ser un diff grande y es ruido: no se revisa línea por línea, se
verifica corriendo `npm ci`. Queda **en su propio commit**, separado del resto,
para que el commit de código se lea limpio.

Dentro del presupuesto de 400 líneas. No hace falta encadenar PRs.

## Criterio de aceptación

Este cambio está listo cuando, sobre un clon limpio:

1. `npm ci` termina sin error.
2. `npm run lint` queda limpio.
3. `npx tsc --noEmit` queda limpio.
4. `npm test` corre los 56 tests de `lib/` **más** los nuevos de componente, y
   pasan todos.
5. `npm run build` termina sin error.
6. Un test de componente introducido a propósito para fallar, **falla** — y al
   quitarlo vuelve a verde.

El punto 6 es el que separa un arnés que funciona de uno que parece funcionar.

## Próxima fase

`spec.md` — requisitos y escenarios verificables.
