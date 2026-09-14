# Auditoría de `apps/web`

Fecha: 2026-09-13
Alcance: `apps/web` (Next.js 16 / React 19). Cuatro ejes: seguridad, calidad de
código, rendimiento, accesibilidad y UX.
Tipo: revisión de solo lectura. No se modificó ningún archivo de código.

Complementa a `AUDITORIA.md` (2026-09-05), que cubrió el repositorio completo y
se centró en el backend. Este documento no repite sus hallazgos.

## Estado verificado

Comprobado ejecutando los comandos, no por lectura:

| Comando | Resultado |
|---|---|
| `npx tsc --noEmit` | limpio |
| `npm run lint` | limpio |
| `npm test` | 56 tests, 9 archivos, todos pasan |

Los 56 tests viven todos en `lib/`. **Cero tests sobre los 21 componentes y las
21 páginas.** No hay `@testing-library/react`, no hay Playwright, no hay e2e.

Tamaño real: ~7.000 líneas de TS/TSX en 95 archivos versionados.

---

## 1. Seguridad

### 🟡 MEDIA — el logo de la agencia se sirve sin el endurecimiento que ya existe

`apps/api/app/services/attachments.py:109` define `logo_response()`, que sirve
un logo con `X-Content-Type-Options: nosniff` y
`Content-Security-Policy: default-src 'none'`. El comentario explica
exactamente por qué: los SVG se muestran en `<img>` (donde no ejecutan), pero
salen del mismo origen que la app, así que uno abierto por URL directa no puede
ejecutar.

`clients.py:115`, `portal.py:280`, `portal.py:288` y `portal.py:1340` usan esa
función. **`agency.py:69` no**: construye su propia respuesta con
`media_type=agency.logo_mime` y solo `Cache-Control: no-store`. Sin nosniff y
sin CSP.

`ALLOWED_LOGO_TYPES` acepta `image/svg+xml` (`agency.py:16`), y
`apps/web/app/settings/page.tsx:63` lo ofrece en el `accept` del input.

Camino de explotación: una persona del staff de la agencia sube un SVG con
`<script>`; otra persona de la misma agencia abre `/api/agency/logo`
directamente; el script corre en el origen de la aplicación. Las cookies son
httpOnly, así que no se leen, pero el script puede llamar a la API como la
víctima con las cookies puestas.

Es intra-agencia y requiere navegación directa al recurso, por eso es media y no
alta. La corrección es una línea: usar `logo_response()`, que ya está escrita,
probada y en uso en los otros cuatro sitios.

### 🟡 MEDIA — ocho acciones destructivas sin confirmación

Existe `ConfirmProvider` (`components/confirm-dialog.tsx`) con un campo
`consequence` pensado justamente para lo irreversible, y se usa en seis lugares.
No se usa en estos ocho:

| Archivo:línea | Qué borra sin preguntar |
|---|---|
| `app/settings/page.tsx:58` | **la credencial del proveedor de IA de toda la agencia** |
| `app/settings/page.tsx:43` | el logo de la agencia |
| `app/clients/[id]/page.tsx:39` | el logo del cliente |
| `app/clients/[id]/page.tsx:228` | **el acceso de una persona al portal** |
| `app/clients/[id]/page.tsx:276` | **el dominio propio del cliente** |
| `app/agents/[id]/page.tsx:138` | un par de preguntas y respuestas |
| `app/portal/[slug]/contacts.tsx:101` | un contacto |
| `app/portal/[slug]/profile.tsx:68` | la foto de perfil |

El primero es el peor: un clic deja sin responder a todos los agentes de la
agencia. Y la inconsistencia es visible dentro de un mismo archivo — en
`agents/[id]/page.tsx`, borrar un documento pregunta (línea 116) y borrar un par
de Q&A no (línea 138).

### 🟢 BAJA — `postMessage` con destino comodín en la página del widget

`app/widget/[publicId]/page.tsx:20` y `:82` mandan
`window.parent.postMessage(..., "*")`. El cargador del lado del anfitrión
(`public/widget.js:80`) sí fija el origen correctamente, y
`widget.js:95` valida `event.origin` al recibir. La página enmarcada no hace lo
propio al enviar.

Lo que se filtra es el saludo configurado del agente, que ya es público. El
riesgo real es bajo; lo que molesta es la asimetría: un archivo hace lo
correcto y el otro no, en el mismo canal.

### 🟢 BAJA — no hay CSP de contenido, solo `frame-ancestors`

`next.config.ts` manda `Content-Security-Policy: frame-ancestors 'self'`, que
resuelve el clickjacking, más `nosniff`, `Referrer-Policy`, `Permissions-Policy`
y HSTS opcional. Falta `default-src` / `script-src`. Con Next hace falta nonce o
hash para los scripts en línea, así que no es gratis — pero hoy no hay ninguna
defensa en profundidad contra XSS.

Vale decir qué está bien: no hay un solo `dangerouslySetInnerHTML` en todo el
frontend. `components/rich-text.tsx` construye nodos de React y su regex solo
acepta `https?://`, así que no hay forma de meter `javascript:`. El sandbox del
iframe del widget (`widget.js:34`) está bien elegido y su comentario documenta
con honestidad el límite de `allow-scripts` + `allow-same-origin`.
`lib/cache-policy.ts` es un acierto: la regla de `no-store` está separada del
runtime de Next precisamente para poder probarla, y tiene 9 tests.

---

## 2. Calidad de código

### 🔴 La aplicación entera es cliente

De las 42 páginas y componentes bajo `app/` y `components/`, solo **tres** no
llevan `"use client"`: `app/layout.tsx`, `components/discord-icon.tsx` y
`components/message-gestures.tsx`.

Next.js 16 con App Router y React 19, y no se usa un solo Server Component para
datos. Todas las pantallas siguen el mismo patrón: montar, mostrar un loader,
hacer `fetch` desde el navegador, pintar. No hay `loading.tsx`, no hay
`Suspense` salvo el obligatorio de `useSearchParams` en la página de invitación,
no hay streaming.

Esto no es un detalle de estilo: es el eje del que cuelgan casi todos los
hallazgos de rendimiento de la sección 3.

### 🔴 Las dos bandejas de entrada son el mismo código escrito dos veces

`app/inbox/page.tsx` (299 líneas) y `app/portal/[slug]/page.tsx` (359 líneas)
duplican, casi literalmente:

- `channelLabel()` y `channelIcon()` — idénticas (`inbox:43-57`, `portal:141-154`)
- `buildParams()` — misma forma
- el debounce de búsqueda a 300 ms
- los dos efectos de scroll al fondo con `wasNearBottomRef`
- `loadMore()` y `onScroll()` con el mismo umbral de 80 px
- el `useMemo` de `gallery`
- `reply()` y `sendAttachment()`

No hay un `useConversationInbox()` compartido. Cualquier arreglo en una bandeja
hay que acordarse de repetirlo en la otra, y hoy ya divergieron: el portal tiene
SSE en vivo (`lib/live.ts`), la bandeja de la agencia no; el portal marca sus
pestañas con `role="tab"` y `aria-selected`, la de la agencia no.

### 🟠 Densidad de estado y líneas de 2.700 caracteres

Medido archivo por archivo:

| Archivo | `useState` | `useEffect` | Líneas | Línea más larga |
|---|---|---|---|---|
| `app/portal/[slug]/page.tsx` | 24 | 12 | 359 | **2.770** |
| `app/channels/page.tsx` | 3 | 2 | 26 | **2.669** |
| `app/clients/[id]/page.tsx` | 18 | 7 | 312 | **2.235** |
| `components/chat-playground.tsx` | 11 | 4 | 135 | 1.905 |
| `app/settings/page.tsx` | 8 | 2 | 114 | 1.702 |
| `app/clients/page.tsx` | 4 | 2 | 25 | 1.549 |
| `app/agents/[id]/page.tsx` | 22 | 3 | 223 | 941 |

`app/portal/[slug]/page.tsx:66` es un `return` de un solo renglón con el
formulario de login completo. La línea 316 abre un `return` que no cierra hasta
la 358 y contiene la navegación, la cabecera, la lista, el hilo, el compositor y
tres modales.

No hay Prettier ni ninguna otra herramienta de formato en el repositorio —
ni en `apps/web` ni en la raíz. Nada impide que la próxima línea también tenga
2.700 caracteres.

Esto choca de frente con el patrón container/presentational: no hay separación
entre el componente que trae los datos y el que los pinta. Son el mismo.

### 🟠 Existe un `<Modal>` primitivo, y tres pantallas no lo usan

`components/ui.tsx:10` **sí** es un primitivo de modal, y hace bien lo básico:
`role="dialog"` y `aria-modal="true"`. Lo usan 8 sitios, entre ellos
`http-tool-modal.tsx:100`, `mcp-server-modal.tsx:80`, `templates.tsx:80,:124`
y `contacts.tsx:159,:166,:175`.

El problema no es que falte el primitivo, es que está incompleto y que tres
pantallas lo esquivaron reimplementando el backdrop a mano:

| Implementación | `role` | `aria-modal` | Escape | Foco inicial | Trampa de foco | Restaura foco |
|---|---|---|---|---|---|---|
| `components/ui.tsx:10` (8 usos) | `dialog` | sí | **no** | **no** | **no** | **no** |
| `components/confirm-dialog.tsx` | `alertdialog` | sí | sí | sí | **no** | **no** |
| `app/portal/[slug]/profile.tsx` | `dialog` | sí | **no** | **no** | **no** | **no** |
| `components/media-panel.tsx` | **no** | **no** | sí | **no** | **no** | **no** |

Ninguna de las cuatro atrapa el tabulador ni devuelve el foco al elemento que la
abrió. `Modal`, que es la que cubre 8 de los 11 casos, no responde a Escape.

`confirm-dialog.tsx` es la más completa y merece decirse: pone el foco en
Cancelar a propósito, con el comentario explicando que en algo que borra, Enter
no puede ser la tecla que borra.

El trabajo real es completar `ui.tsx:10` (Escape, foco inicial, trampa,
restauración) y migrar las tres reimplementaciones, no escribir un primitivo
nuevo.

### 🟠 Texto en español escrito a mano en componentes compartidos

`components/ui.tsx:7` — `StatusBadge` devuelve `"Activo"` o `"Inactivo"`
directamente, sin pasar por i18n. Se usa en 7 sitios: el panel de inicio
(`app/page.tsx:73`), el listado de agentes (`agents/page.tsx:24`), el de
clientes (`clients/page.tsx:23`) y la ficha de cliente
(`clients/[id]/page.tsx:161,:237`).

Consecuencia directa: con la interfaz en inglés, esas insignias siguen diciendo
«Activo» / «Inactivo».

`components/ui.tsx:17` — el botón de cerrar de **todos** los modales lleva
`aria-label="Cerrar"` escrito a mano. Mismo defecto, en la etiqueta que
justamente solo existe para los lectores de pantalla.

Contradice la convención del propio `AGENTS.md`: la copia visible va detrás de
una clave de i18n. El sistema de tipos no lo atrapa porque nadie llamó a `t()`.

### 🟡 Reglas de lint apagadas

`eslint.config.mjs` desactiva tres reglas. Medido qué aparece al reactivarlas:

| Regla | Avisos al activarla |
|---|---|
| `react-hooks/exhaustive-deps` | 6 |
| `react-hooks/set-state-in-effect` | 23 |
| `@next/next/no-img-element` | 18 |

Los 6 de `exhaustive-deps` son de bajo riesgo (`load` faltante en dependencias,
dos expresiones complejas en arrays de dependencias). Es decir: **la regla está
apagada y casi no costaría encenderla**. Lo que se pierde apagándola no es lo
que hay hoy, es la red para lo que venga. En un frontend construido
íntegramente sobre `useEffect` y `useCallback`, es la única regla que atrapa una
clausura vieja.

Uno de los 23 avisos de `set-state-in-effect` (`lib/i18n/index.tsx:84`) señala
exactamente el mismo defecto que la sección 4 describe como parpadeo de idioma.
El linter lo había visto.

### 🟢 Paso de CI que ya no hace falta

`.github/workflows/ci.yml` instala vitest con `npm install --no-save` y un
comentario que dice cómo eliminarlo: declararlo en `package.json` y refrescar el
lockfile. **Ya está hecho** — `package.json:23` lo declara y
`package-lock.json` lo tiene. El paso sobra.

### 🟢 Lo que está bien hecho

- **El sistema de i18n es de manual.** `lib/i18n/index.tsx:17-21` deriva todas
  las claves con puntos válidas del tipo del diccionario, así que un error de
  tipeo en `t("…")` es un error de TypeScript, no un fallback silencioso. La
  búsqueda lanza a propósito en vez de degradar. Hay tests de paridad entre `en`
  y `es`.
- `lib/api.ts` es un único envoltorio de fetch, sin copias.
- `lib/live.ts` está bien pensado: el comentario de las líneas 44-55 explica por
  qué cierra el `EventSource` en vez de dejarlo reintentar (no expone el código
  de respuesta, así que contra una sesión muerta serían 401 cada tres segundos
  para siempre). Eso es razonamiento real, no copiado.
- Las 9 suites de `lib/` prueban lo que hay que probar: la política de caché, la
  regla de refresco, el formato de fechas, el embed del widget.
- `strict: true` en TypeScript, y el typecheck pasa limpio.

---

## 3. Rendimiento

### 🔴 627 KB de logo para pintar 28 píxeles

`public/brand/openlivery-logo-original.png` pesa **627.860 bytes**. Se carga con
`<img>` crudo, sin `next/image`, sin `width`/`height`, en cuatro sitios:

- `components/app-shell.tsx:108` — el loader a pantalla completa, o sea lo
  primero que ve cualquiera al entrar
- `components/app-shell.tsx:116` — el logotipo de la barra lateral
- `app/login/page.tsx:52` y `:61` — **dos veces en la pantalla de login**

Se muestra a tamaño de icono. Son ~620 KB desperdiciados en la primera carga, y
sin `width`/`height` declarados también aporta desplazamiento de diseño.

El arreglo es de minutos: un PNG de 64 px (o un SVG) más `next/image`. La regla
que lo habría evitado, `@next/next/no-img-element`, está apagada.

### 🔴 El widget carga la aplicación entera en cada visita a la web del cliente

`public/widget.js:13-14` crea el iframe con el `src` ya puesto y lo añade al DOM
en la línea 106, con `display:none`. El navegador de quien visita el sitio del
cliente descarga la ruta `/widget/[publicId]` completa —Next, React, el bundle—
**aunque nunca abra el chat**.

Es un coste que le imponemos al sitio de la clientela, en cada página vista. La
corrección es diferir el `src` hasta el primer `setOpen(true)`.

### 🟠 Sondeo permanente, también en pestañas de fondo

`app/inbox/page.tsx:133-141` dispara un `setInterval` de 8 segundos fijos
(`POLL_MS = 8000`) que hace dos peticiones por vuelta. Sin SSE y, sobre todo,
**sin mirar `document.hidden`**: una pestaña minimizada toda la jornada sigue
pidiendo. Son ~900 peticiones por hora y por pestaña abierta.

El portal está mejor —tiene SSE y baja a 60 s cuando el stream conecta
(`lib/live.ts:8`)— pero tampoco comprueba visibilidad, y cada vuelta de su
`refresh()` (`portal/[slug]/page.tsx:200-216`) son **cuatro** peticiones:
resumen, asignaciones, lista y conversación abierta. Cuando el stream está
caído, eso es cada 8 segundos.

`announceAssignments()` (línea 85) pide hasta 100 conversaciones en cada vuelta
solo para comparar identificadores y detectar transferencias.

Añadir una comprobación de `document.visibilityState` es barato y corta la mayor
parte del gasto.

### 🟠 `no-store` en todo, y todo es cliente

`lib/cache-policy.ts:28` pone `no-store, must-revalidate` en todas las páginas
menos el widget. La justificación de seguridad es correcta y está bien
argumentada. Pero combinada con que todas las páginas son de cliente, cada
navegación es: documento sin caché, más el bundle, más el `fetch` de datos al
montar, más `/auth/me`, que `AppShell` revalida en **cada** cambio de ruta
(`app-shell.tsx:71-79`).

Con Server Components, la mayor parte de eso desaparecería sin tocar la política
de caché.

### 🟢 Menor

- `lib/i18n/index.tsx:57` construye un `new RegExp` por cada variable y por cada
  llamada a `format()`. En la bandeja se llama cientos de veces por render.
- `app/widget/[publicId]/page.tsx:150` usa `key={index}` en la lista de
  mensajes, con inserción optimista y reemplazo posterior por la respuesta del
  servidor. Es el caso exacto en que el índice como clave reconcilia mal.

---

## 4. Accesibilidad y UX

### 🔴 La navegación del portal no se puede usar con el teclado

`app/portal/[slug]/page.tsx:316`:

```tsx
<a className={view === "inbox" ? "active" : ""} onClick={() => setView("inbox")}>
```

Cinco enlaces de navegación —Bandeja, Tablero, Contactos, Plantillas, Agentes—
son `<a>` **sin `href`**. Un ancla sin `href` no entra en el orden de
tabulación, no expone rol de enlace y no responde a Enter. Quien no usa ratón no
puede cambiar de vista en el portal.

Es la pantalla que usa a diario el personal del cliente. El arreglo es cambiar
`<a>` por `<button type="button">`, que ya es lo que son.

### 🔴 El combobox declara ser un listbox y no se comporta como uno

`components/combobox.tsx` es el selector de zona horaria y de modelo. Problemas
acumulados:

- Línea 67: `role="listbox"` en un `<ul>` cuyos hijos son `<li>` con `<button>`
  dentro. Un listbox exige hijos con `role="option"`. El ARIA está roto, no
  incompleto.
- Línea 48: el disparador no tiene `aria-expanded`, ni `aria-haspopup`, ni
  `aria-controls`. Un lector de pantalla no anuncia que se abrió nada.
- **No hay navegación con flechas.** Solo Escape y Enter (línea 61-64). Para
  elegir una zona horaria hay que tabular por la lista completa.
- No devuelve el foco al disparador al cerrar.

### 🟠 El HTML se sirve declarando inglés con el contenido en español

`app/layout.tsx:23` fija `<html lang="en">`. El idioma por defecto es español
(`lib/i18n/index.tsx:11`) y solo se corrige al montar, desde un `useEffect`
(línea 85).

O sea: el HTML que llega del servidor dice inglés y el texto es español. Un
lector de pantalla lo pronuncia con fonemas ingleses hasta que hidrata, y los
buscadores leen la etiqueta equivocada.

Lo llamativo es que la preferencia **ya está en una cookie**
(`lib/i18n/index.tsx:91`, `openlivery.lang`). El layout puede leerla en el
servidor y emitir el `lang` correcto de entrada.

### 🟠 Se pide permiso de notificaciones sin que nadie lo haya pedido

`app/portal/[slug]/page.tsx:105-109` llama a `Notification.requestPermission()`
dentro de un `useEffect` al montar, sin ningún gesto de la persona.

Dos consecuencias. La de producto: lo primero que ve quien entra al portal es un
diálogo del navegador que no pidió, y el patrón conocido es que se deniegue por
reflejo — con lo cual se pierde el permiso para siempre, justo el que sí hacía
falta cuando llegara una transferencia. La técnica: Chrome y Firefox penalizan o
directamente bloquean las peticiones sin gesto previo.

Debe colgar de un botón explícito («avisarme de las conversaciones que me
asignen»).

### 🟠 No hay pantallas de error ni de carga

No existen `app/error.tsx`, `app/global-error.tsx`, `app/not-found.tsx` ni
ningún `loading.tsx`. Comprobado sobre los 95 archivos versionados.

`lib/i18n/index.tsx:38-51` lanza a propósito cuando falta una clave. Es una
decisión defendible —un fallo silencioso es peor—, pero sin un `error.tsx` que
lo recoja, una clave faltante en producción es una pantalla en blanco, sin
mensaje y sin forma de volver.

### 🟠 El foco y el movimiento, a medias

En las 1.522 líneas de `app/globals.css`:

- **Una sola** regla `:focus-visible` (línea 812), y es para una casilla.
- La línea 156 quita el contorno de todos los `input`, `textarea` y `select`, y
  lo reemplaza por `box-shadow` en `:focus` —no en `:focus-visible`—, así que
  también se dispara al hacer clic con el ratón. Cosmético, pero es el síntoma:
  no hay un sistema de foco pensado, hay parches.
- Botones y enlaces conservan el anillo del navegador, que no está diseñado ni
  comprobado contra la barra lateral oscura (`#17203a`).
- `prefers-reduced-motion` aparece **una vez** (línea 1206) y solo apaga la
  animación del esqueleto. La clase `.spin` de los cargadores, las transiciones
  y el `scrollIntoView({ behavior: "smooth" })` del widget
  (`app/widget/[publicId]/page.tsx:72`) la ignoran.
- 31 `!important` en una hoja global única, sin CSS Modules ni estilos por
  componente. Las clases son cadenas sueltas, sin comprobación de tipos.

### 🟡 Menor pero real

- `components/app-shell.tsx:113`: el fondo del menú móvil es un `<div>` con
  `onClick`. No hay Escape, no hay trampa de foco, y el contenido de atrás no
  queda `inert`. El botón de cerrar existe, así que no es un bloqueo, pero el
  panel deja escapar el tabulador.
- No hay enlace de «saltar al contenido». El `<main>` existe
  (`app-shell.tsx:151`), el atajo no.
- Los `<time>` se pintan sin atributo `dateTime` en toda la aplicación.
- La lista de mensajes del widget no tiene `aria-live`: una respuesta del agente
  es silenciosa para un lector de pantalla.
- `app/widget/[publicId]/page.tsx:131` (`"Chat unavailable"`) y `:145`
  (`aria-label="Close"`) son cadenas en inglés escritas a mano. `widget.js:41`
  y `:15` igual (`"Chat"`). Contradice la convención del propio `AGENTS.md`: la
  copia visible va detrás de una clave de i18n.
- La burbuja de saludo del widget (`widget.js:64-76`) es un `<div>` con
  `onClick` y un `<span>` como botón de cerrar. Ninguno de los dos es accesible
  por teclado, en una superficie pública.
- `app/inbox/page.tsx:163`: `throw err` dentro de un manejador `async` de clic.
  Nadie lo captura: es un rechazo de promesa sin gestionar y la persona no ve
  ningún mensaje.
- En un dominio propio, `proxy.ts:58` reescribe **cualquier** ruta a
  `/portal/{slug}`. No hay 404 posible en ese dominio: una URL mal escrita
  aterriza en la bandeja. Además, tras aceptar una invitación,
  `invite/page.tsx:52` hace `router.replace('/portal/{slug}')`, con lo que el
  slug interno queda a la vista en el dominio de marca del cliente.
- Los enlaces de invitación se construyen con un `frontend_url` global
  (`apps/api/app/routers/departments.py:111`), nunca con el dominio propio del
  cliente. Funciona, pero un portal de marca manda correos que apuntan al
  dominio de la agencia.

---

## 5. Plan de acción sugerido

Ordenado por relación entre impacto y esfuerzo, no por severidad.

### Esta semana — horas de trabajo, efecto inmediato

1. Sustituir el PNG de 627 KB por uno de 64 px o un SVG, y pasarlo por
   `next/image`. Es la mejora de rendimiento más grande por línea tocada.
2. Cambiar los cinco `<a>` de la navegación del portal por `<button>`
   (`portal/[slug]/page.tsx:316`). Devuelve el teclado a la pantalla que más se
   usa.
3. Usar `logo_response()` en `apps/api/app/routers/agency.py:69`. Una línea, y
   la función ya existe y está en uso en otros cuatro sitios.
4. Poner `useConfirm` en las ocho acciones destructivas de la sección 1,
   empezando por el borrado de la credencial del proveedor.
5. Colgar `Notification.requestPermission()` de un botón explícito.
6. Añadir `app/error.tsx` y `app/not-found.tsx`.
7. Eliminar el paso «Install the test runner» de `ci.yml`, que ya sobra.
8. Comprobar `document.visibilityState` antes de cada vuelta de sondeo, en las
   dos bandejas.
9. Diferir el `src` del iframe del widget hasta el primer `setOpen(true)`.

### Este mes — trabajo real, deuda que se paga sola

10. Leer la cookie `openlivery.lang` en el servidor y emitir el `lang` correcto
    en `app/layout.tsx`.
11. Completar el `<Modal>` de `ui.tsx:10` con Escape, foco inicial, trampa de
    foco y restauración, y migrar las tres pantallas que lo esquivaron.
    Traducir `StatusBadge` y el `aria-label` del botón de cerrar.
12. Reescribir `Combobox` siguiendo el patrón ARIA de combobox: `role="option"`,
    `aria-expanded`, `aria-controls`, navegación con flechas.
13. Extraer un `useConversationInbox()` compartido por las dos bandejas y borrar
    la duplicación.
14. Reactivar `react-hooks/exhaustive-deps` — son 6 avisos — y arreglarlos.
15. Añadir Prettier con `printWidth` y pasarlo una vez sobre todo el frontend.
    Las líneas de 2.700 caracteres no vuelven solas.
16. Un sistema de foco `:focus-visible` diseñado, comprobado sobre la barra
    lateral oscura. Extender `prefers-reduced-motion` a `.spin`, las
    transiciones y los desplazamientos suaves.

### Cuando haya margen — lo estructural

17. Mover a Server Components lo que solo lee datos: listados de clientes, de
    agentes, de canales, la configuración. El chat y las bandejas seguirán
    siendo de cliente, y está bien que lo sean.
18. Tests de componente con `@testing-library/react`. Hoy hay 56 tests y ninguno
    toca una página.
19. Un e2e mínimo con Playwright: login, crear cliente, crear agente, responder
    en la bandeja. Cuatro caminos que hoy nadie comprueba.
20. Separar `globals.css` en estilos por componente, o al menos por dominio.
21. Revisar el contraste de color de toda la interfaz contra WCAG AA. No se
    midió en esta auditoría.

---

## 6. Lectura general

El frontend está **bien pensado y mal terminado**.

Bien pensado se nota en los sitios que importan: el sistema de i18n con claves
verificadas por tipo es mejor que el de la mayoría de los productos comerciales;
`lib/cache-policy.ts` está separado del runtime de Next explícitamente para
poder probarse; los comentarios de `lib/live.ts` y del sandbox de `widget.js`
documentan el razonamiento y también el límite de la decisión. No hay un solo
`dangerouslySetInnerHTML`. El typecheck y el lint pasan limpios y hay CI de
verdad.

Mal terminado se nota en el borde: la aplicación no usa Server Components
aunque corra sobre Next 16; el teclado no llega a la navegación del portal; hay
un logo de 627 KB para pintar un icono; ocho acciones destructivas no preguntan
teniendo el diálogo ya escrito; y hay un primitivo de modal que tres pantallas
esquivaron en vez de completar.

Casi todo lo grave de esta lista es barato. Los nueve puntos de «esta semana»
son horas, no semanas, y cubren el hallazgo de seguridad, los dos de
rendimiento y los dos de accesibilidad más serios. La deuda real —los Server
Components, la duplicación de las bandejas, la hoja de estilos de 1.522
líneas— es estructural y puede esperar; lo que no debería esperar es que una
persona que usa el teclado no pueda cambiar de pestaña en el portal.
