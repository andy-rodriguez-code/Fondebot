# Diseño — OpenLivery como SaaS multi-empresa

Fecha: 2026-09-14
Estado: aprobado, pendiente de plan de implementación
Origen: sesión de diseño sobre el código en `main` (commit `cd1af12`)

Todo dato de este documento sobre el código actual fue verificado leyendo el
archivo, y se cita con archivo y línea. Lo que no pude verificar está marcado
como pregunta abierta, no como hecho.

---

## 1. La visión

Vender bots de atención a empresas, en una sola instalación que vos operás.

- Vos sos el **dueño del software**. Creás las empresas, las monitoreás, les
  cobrás el software y les cobrás la configuración cuando no la quieren hacer.
- Cada **empresa** configura su propia plataforma: sus bots, su información, sus
  dependencias, su clave de modelo. Prueban sus propios agentes en un sandbox.
- Las empresas **no** venden bots ni tienen marcas propias. Ese nivel es tuyo y
  solo tuyo.
- Cada empresa tiene su dashboard, acotado a su negocio.
- Vos también tenés un bot: el que vende la suscripción.

---

## 2. El modelo de datos, y cómo se mapea

El hallazgo central de la sesión de diseño: **la jerarquía que hace falta ya
existe**. No hay que agregar un nivel, hay que repartir permisos sobre el que
está.

```
AGENCIA = el SaaS. Una sola. Vos.
  │        allow_multi_agency se queda en FALSE (config.py:75)
  │
  ├── CLIENTE "Fondebot" ......... tu bot de ventas. Un cliente más, sin código especial
  │
  ├── CLIENTE "Panadería López" .. una empresa que te paga
  │      ├── is_active ........... el corte de servicio
  │      ├── max_agents = 5 ...... su cupo de bots
  │      ├── credencial de IA .... suya, obligatoria para que su bot use IA
  │      ├── dependencias ........ sus áreas de atención
  │      └── su gente ............ con rol: admin o agente
  │
  └── CLIENTE "Clínica Norte" .... otra empresa
```

**Empresa = `Client`.** **SaaS = `Agency`.**

Que tu propio bot de ventas sea un `Client` más no es una simplificación: si el
producto no alcanza para vender el producto, el producto tiene un problema que
conviene descubrir temprano.

### 2.1 Por qué `allow_multi_agency` se queda en `false`

`config.py:75` lo define en `false`, y `auth.py:31` hace que solo el primer
registro cree una agencia; después el alta pública se cierra.

Ese es exactamente el comportamiento que este diseño necesita: **una agencia,
que sos vos**. No hay que prender la bandera ni auditar el modo multi-agencia.

Consecuencia directa: la fuga entre agencias de `health.py:78` —donde las filas
de `error_events` con `agency_id` nulo son visibles para toda persona
autenticada— **no aplica a este diseño**, porque hay una sola agencia. Queda
anotada por si algún día se prende la bandera.

La frontera que sí importa acá es otra: **entre clientes**, dentro de la misma
agencia. Hoy esa frontera protege bandejas de entrada. Este diseño le va a pedir
que proteja configuración.

---

## 3. Qué ya está construido

Verificado archivo por archivo. Esta sección existe para que nadie reconstruya
lo que ya funciona.

| Requisito | Estado | Dónde |
|---|---|---|
| Vos el único con clientes/marcas | ✅ | Es el modelo actual tal cual |
| Empresas ilimitadas | ✅ | `Client`, sin límite |
| Login propio por empresa | ✅ | `POST /api/portal/{slug}/login` |
| Dependencias por empresa | ✅ | `Department` (`models.py:106`) |
| Dashboard con «clientes activos» | ✅ | `dashboard.py:22` |
| Métricas por día, semana o mes | ✅ | `dashboard.py:65` acepta `days=1..365` |
| Marca propia por empresa | ✅ | Logo, color, portal, dominio propio |
| Aislamiento entre inquilinos | ✅ | Toda consulta filtra por `agency_id` |
| Bandeja compartida y toma de control | ✅ | `Conversation.mode` ai ⇄ human |
| Ganchos para facturar | ✅ | `X-Redirect-To` (`lib/api.ts:27`), `EXTRA_NAV` (`app-shell.tsx:31`) |

### 3.1 El modo recepción ya existe

`services/departments.py` implementa, completo, el flujo que en la sesión se
describió como «saludar y preguntar con qué dependencia querés hablar»:

| Función | Qué hace |
|---|---|
| `send_menu()` (`:141`) | Ofrece el menú **una sola vez** por conversación, marcando `menu_sent_at`, y lo guarda en el hilo para que quien abra el portal vea lo mismo que vio el contacto |
| `_deliver_menu()` (`:115`) | Botones nativos en WhatsApp API si hay ≤3 dependencias, lista desplegable si hay más, texto numerado en Baileys |
| `menu_text()` (`:108`) | El menú como texto |
| `match_choice()` | Entiende el número, el nombre o el slug |
| `route()` (`:168`) | Rutea el caso a la dependencia y cambia el agente que lo contesta |

Y el disparador (`whatsapp_inbound.py:279`) **no depende de la clave de IA**:
depende de que la empresa tenga dependencias cargadas.

O sea: hoy, por WhatsApp, una empresa sin clave y con dependencias ya recibe al
contacto, le ofrece el menú, rutea el caso y lo deja en la bandeja de esa
dependencia esperando a una persona.

---

## 4. Qué falta

### 4.1 El toggle de servicio no corta nada — **bloquea el cobro**

`Client.is_active` existe (`models.py:69`). El único lugar del backend que lo
lee es `dashboard.py:22`, para contar el número del panel.

No corta el login del portal. No apaga el bot de WhatsApp. No apaga el widget.

Sus hermanos sí están enchufados, lo que confirma que es un olvido y no una
decisión:

| Campo | ¿Corta? | Dónde |
|---|---|---|
| `Agent.is_active` | ✅ | `conversations.py:184`, `widget.py:159` |
| `PortalUser.is_active` | ✅ | `portal.py:121`, `mobile.py:171` |
| **`Client.is_active`** | ❌ | en ningún lado |

Traducido al negocio: una empresa deja de pagar, apagás el toggle, el número del
panel baja, y su bot sigue atendiendo. **Sin corte no hay suscripción.**

### 4.2 El modo recepción no es un estado de primera clase

Tres huecos sobre la maquinaria del punto 3.1:

1. **El widget no participa.** `widget.py:159` devuelve `None` cuando no hay
   credenciales, y el archivo no tiene ninguna lógica de menú. En la web, sin
   clave, el visitante escribe y no pasa nada.
2. **El saludo es igual para todas las empresas.** `departments.py:33`:
   ```python
   MENU_INTRO = "¡Hola! ¿Con cuál dependencia deseas comunicarte?"
   ```
   Una constante de módulo. La panadería y la clínica saludan idéntico. En un
   producto cuyo argumento de venta es la marca propia, eso no cierra.
3. **Sin dependencias y sin clave, silencio.** Nadie saluda, en ningún canal.

### 4.3 La credencial de IA es por agencia, no por empresa

`models.py:158` declara `UniqueConstraint("agency_id", "provider")`: una clave
por agencia. Con este diseño, eso significa **tu** clave para todas las
empresas.

El requisito es que cada empresa traiga la suya.

La buena noticia: toda la resolución pasa por una sola función,
`services/providers.py:36`. El cambio es quirúrgico, no una refactorización.

### 4.4 No hay roles dentro de la empresa

`PortalUser` no tiene rol. Toda persona del portal puede lo mismo.

Hoy eso es tolerable porque el portal solo permite atender. En cuanto permita
configurar, deja de serlo: quien atiende el teléfono podría borrar el bot.

Nota de contexto: del lado de la agencia existe `User.role` (`models.py:54`) y
**nadie lo lee nunca**. `health.py:60` lo dice explícitamente: *«Sin gate por
rol: `User.role` queda sin leer a propósito»*. Es la misma trampa esperando del
otro lado, y conviene no repetirla: un campo de rol que nadie consulta es peor
que no tener campo, porque aparenta un control que no existe.

### 4.5 El portal es una bandeja, no una plataforma

Verificado endpoint por endpoint en `routers/portal.py`. Una persona del portal
puede: leer y contestar conversaciones, asignarlas, resolverlas, manejar
contactos y plantillas, y editar su perfil.

De los agentes solo tiene `GET /{slug}/agents`: **los ve, no los toca**.

No puede: crear o editar un bot, cargar conocimiento, conectar WhatsApp, crear
dependencias —`departments.py:31` monta el router bajo
`/clients/{client_id}/departments` y lo guarda `get_current_user`, que es el de
la agencia—, invitar gente, ni ver métricas.

### 4.6 No existe ningún concepto de cupo, plan ni suscripción

Buscado en `models.py` y `config.py`: nada. `agents.py:52` crea agentes sin
límite de ninguna clase.

### 4.7 «Posibles clientes» no existe

Hay `Contact`, que es quien ya escribió. Un lead —una oportunidad detectada— es
un dominio nuevo entero.

---

## 5. Cambios de esquema

Cuatro. Nada más.

| Cambio | Tabla | Detalle |
|---|---|---|
| Enchufar `is_active` | `clients` | El campo ya existe; falta que corte |
| `max_agents` | `clients` | `int`, default 5 |
| `role` | `portal_users` | `admin` \| `agent`, default `agent` |
| `client_id` | `provider_credentials` | Nulo permitido; la fila con `client_id` nulo sigue siendo la de la agencia |

La restricción de unicidad de `provider_credentials` cambia, y hay que decirlo
explícito porque admite dos lecturas. Hoy es
`UniqueConstraint("agency_id", "provider")` (`models.py:158`): **una** clave de
OpenAI por agencia. Pasa a ser `("agency_id", "client_id", "provider")`, de modo
que cada cliente pueda tener la suya y la agencia siga teniendo la propia en la
fila con `client_id` nulo.

En PostgreSQL, `NULL` no colisiona con `NULL` en un índice único, así que esa
restricción **no** impide dos filas de agencia para el mismo proveedor. Hace
falta además un índice único parcial sobre `(agency_id, provider)` donde
`client_id IS NULL`. Omitirlo deja entrar dos claves de agencia para OpenAI, y
cuál gana depende del orden de la consulta.

### 5.1 Una columna, no una tabla de planes

`max_agents` va como columna en `clients`, no como una tabla `plans` con una
clave foránea.

Todavía no se sabe qué se va a cobrar. Una columna permite venderle 5 a uno y 20
a otro desde el primer día. La tabla de planes se construye cuando existan tres
planes reales, no tres imaginados.

Pasar de columna a tabla después es una migración de media hora. Haber
construido la tabla de más es código que hay que mantener mientras se descubre
que el modelo de precios era otro.

### 5.2 El cupo se valida en el backend

En `create_agent` (`agents.py:52`). Un botón deshabilitado en la pantalla no es
un límite: es una sugerencia.

### 5.3 La credencial: cadena de resolución

`resolve_agent_credentials` (`services/providers.py:36`) pasa a resolver así:

1. Credencial del cliente del agente, si existe.
2. Si no, la de la agencia.

Esa cadena deja elegir **por empresa**, sin casarse con un modelo de negocio:
se le puede vender con IA incluida a una y BYOK a otra. Hoy el requisito es que
todas traigan la suya; el respaldo existe para tu propio bot de ventas y para no
tener que migrar el día que quieras vender un plan con IA incluida.

---

## 6. Modo recepción como estado de primera clase

El cambio de diseño más importante de la sesión, y vino del lado del producto,
no del técnico.

**Sin clave de IA no es un estado roto: es el modo recepción.** Un canal de
atención humana, con saludo propio, menú de dependencias, ruteo y bandeja
compartida. Sin una línea de IA.

Lo que eso resuelve, y no es técnico: **se puede vender y entregar valor antes
de que la empresa toque OpenAI.** Se instala, se cargan sus dependencias,
funciona como mesa de entrada, y la IA es la mejora que se prende después.

Eso desarma la fricción de exigir la clave propia, que era el mayor riesgo
comercial de este diseño.

Requisitos concretos:

- **R-REC-1.** El saludo y el pie del menú son configurables por empresa.
  `MENU_INTRO` y `MENU_FOOTER` dejan de ser constantes de módulo.
- **R-REC-2.** El widget ofrece el mismo menú de dependencias que WhatsApp
  cuando el agente no puede responder con IA.
- **R-REC-3.** No hay silencio en ningún canal. Si no hay clave y no hay
  dependencias, el contacto igual recibe una respuesta —configurable— que le
  dice que alguien lo va a atender.
- **R-REC-4.** El estado del bot es visible para la empresa y para vos: «listo»,
  «modo recepción», «falta la clave».

---

## 7. Los proyectos, en orden

| | Proyecto | Por qué ahí |
|---|---|---|
| **S0** | **El toggle corta de verdad** | Es lo único que hoy impide cobrar. Chico |
| **S1** | **Modo recepción de primera clase** | Saludo por empresa, menú en el widget, sin silencio, estado visible |
| **S2** | **Credencial por empresa** | Esquema, cadena de resolución, y pantalla del lado de la agencia para cargarla vos |
| **S3** | **Auditoría de la frontera entre clientes** | **Antes** de abrir el portal a configuración |
| **S4** | **Roles: admin vs agente** | Base de permisos del portal |
| **S5** | **Su bot, su sandbox, su info, el cupo de 5** | El grande |
| **S6** | **Su dashboard** | Las mismas métricas, acotadas |
| **S7** | **Posibles clientes / leads** | Lo único nuevo de cero |

Dos decisiones de orden que no son negociables:

**S0 primero.** Sin corte de servicio no hay suscripción. Es de un día.

**S3 antes de S5, no después.** S5 le da a un tercero el poder de editar el
prompt de un bot que atiende clientes reales y de subir documentos al servidor.
Esa frontera se revisa antes de abrirla. Auditar un plano cuesta mucho menos que
auditar un edificio con gente adentro.

**Y todo esto va después del arnés de tests de componente** (PR #88). S5 no se
suelta sin tests.

---

## 8. Riesgos

| Riesgo | Severidad | Mitigación |
|---|---|---|
| El portal recibe permisos de configuración sin que la frontera entre clientes haya sido revisada para eso | **Alta** | S3 antes de S5, sin excepción |
| Un rol que nadie lee, repitiendo lo de `User.role` | Alta | En S4, el rol se lee en el backend o el proyecto no está terminado |
| Cupo validado solo en la interfaz | Media | 5.2: se valida en `create_agent` |
| Exigir clave propia frena la venta | Media | Resuelto por el modo recepción (sección 6) |
| El corte de servicio deja conversaciones a medias | Media | Definir en S0 qué pasa con los hilos abiertos de una empresa apagada — ver preguntas abiertas |
| Una empresa que se fue ocupa disco para siempre (PDFs, adjuntos) | Baja | Fuera de alcance; anotado para retención |

---

## 9. Preguntas abiertas

Ninguna bloquea el arranque. Se resuelven en la especificación del proyecto que
las toca.

1. **S0** — Cuando se apaga una empresa, ¿qué pasa con las conversaciones
   abiertas? ¿Se congelan y siguen visibles, o el portal queda cerrado del todo?
   Afecta la pantalla que ve su gente al intentar entrar.
2. **S2** — Si una empresa carga una clave inválida, ¿el bot cae en modo
   recepción o responde un error? El modo recepción parece mejor, pero hay que
   distinguir «clave mal escrita» de «sin saldo».
3. **S5** — ¿El cupo de 5 cuenta agentes inactivos, o solo activos?
4. **S7** — ¿Qué es un lead, exactamente? ¿Lo marca una persona, lo detecta el
   bot, o las dos cosas?

---

## 10. Fuera de alcance

Declarado para que no se cuele:

- **Facturación y cobro.** Los ganchos existen (`X-Redirect-To`). La decisión se
  toma cuando se sepa qué se cobra.
- **Infraestructura separada por empresa.** Descartado en la sesión de diseño: el
  aislamiento por filas ya está auditado, y separar infraestructura convierte
  esto en una empresa de infraestructura antes del décimo cliente.
- **Modo multi-agencia.** `allow_multi_agency` se queda en `false`.
- **Automatizaciones** más allá del ruteo por dependencia que ya existe.
- **Retención y borrado** de datos de empresas dadas de baja.
