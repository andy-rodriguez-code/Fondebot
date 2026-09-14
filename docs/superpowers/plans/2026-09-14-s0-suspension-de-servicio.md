# S0 — Suspensión de servicio Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Que apagar `Client.is_active` corte el servicio de esa empresa de verdad — portal, widget, WhatsApp y mobile — sin tocar sus datos y sin que el dueño pierda acceso.

**Architecture:** No hay modelo nuevo ni migración. El campo ya existe (`models.py:69`) y hoy solo lo lee `dashboard.py:22` para contar. El trabajo es agregar la condición en los **cinco puntos donde una petición externa resuelve a un `Client`**, que ya están identificados. Cada canal falla a su manera: el portal responde 403 para que el frontend pueda mostrar una pantalla propia; el widget y WhatsApp responden como si el servicio no existiera.

**Tech Stack:** FastAPI, SQLAlchemy, pytest (`apps/api`), Next.js 16 + Vitest + Testing Library (`apps/web`).

**Prerequisito:** el arnés de tests de componente (PR #88) mergeado, para la Tarea 7.

---

## Contexto que el implementador necesita

Lee esto antes de la Tarea 1. Ahorra media hora de exploración.

### Los cinco puntos de corte

Todos verificados leyendo el archivo:

| # | Archivo:línea | Qué resuelve | ¿Tiene el `Client` a mano? |
|---|---|---|---|
| 1 | `app/routers/portal.py:65` `_public_client` | Rutas públicas del portal: login, datos públicos, logo | Sí, es el `Client` |
| 2 | `app/routers/portal.py:72` `_portal_client` | **Dependencia que guarda toda ruta autenticada del portal** | Sí |
| 3 | `app/routers/widget.py:48` `_agent` | El agente detrás de un widget público | Sí, vía `joinedload(Agent.client)` en la línea 51 |
| 4 | `app/routers/whatsapp.py:215` `inbound_message` | Mensaje entrante de Baileys | Sí, `_internal_channel` hace `joinedload(...).joinedload(Agent.client)` (línea 74) |
| 5 | `app/routers/mobile.py:133` y `:157` | Login y sesión de la app mobile | Sí |

Los puntos 1 y 2 son el par que cierra el portal entero: no hace falta tocar
ninguna ruta individual, porque todas pasan por uno de los dos.

### Lo que NO hay que romper

- **Los datos no se tocan.** Suspender no borra ni archiva nada. Volver a
  prender el toggle devuelve todo como estaba.
- **El dueño sigue viendo la empresa.** El corte es para la empresa, no para la
  agencia. Toda ruta bajo `get_current_user` sigue funcionando igual. La
  Tarea 6 existe solo para probar esto.
- **`portal_enabled` es otra cosa.** Ya existe y significa «esta empresa no
  usa portal». `is_active` significa «esta empresa está suspendida». No se
  fusionan: una empresa al día puede no querer portal.

### Convenciones de test de este repo

- Base de datos `openlivery_test`, creada y destruida por test
  (`tests/conftest.py:42`).
- La fixture `authenticated_client` ya registra agencia y devuelve un
  `TestClient` logueado (`conftest.py:59`).
- Los tests se agrupan en clases `class TestAlgo:` con docstring en español
  explicando **qué se protege**, no qué se llama. Mirá
  `tests/test_portal_profile.py` como modelo.
- Correr: `cd apps/api && pytest -q`

---

### Task 1: Helpers de test compartidos

**Files:**
- Create: `apps/api/tests/test_suspension.py`

- [ ] **Step 1: Crear el archivo con los helpers y el docstring**

```python
"""Suspender una empresa le corta el servicio, sin tocarle un dato.

`Client.is_active` existía desde el principio y no cortaba nada: el único
lugar que lo leía era el contador del panel. Una empresa que dejaba de pagar
seguía atendiendo por WhatsApp toda la noche.

Lo que se prueba acá es que el corte alcance los cuatro caminos por los que
entra una petición de afuera —portal, widget, WhatsApp y mobile—, que no se
borre nada, y que el corte sea para la empresa y no para quien la administra.
"""

from fastapi.testclient import TestClient

PASSWORD = "una-clave-de-prueba-larga"


def _empresa_con_portal(admin: TestClient) -> dict:
    """Una empresa activa, con portal abierto y una persona que lo usa."""
    customer = admin.post(
        "/api/clients",
        json={"name": "Panaderia Lopez", "industry": "", "description": "", "general_context": "", "is_active": True},
    ).json()
    admin.post(
        f"/api/clients/{customer['id']}/portal-users",
        json={"email": "ada@panaderia.com", "password": PASSWORD, "name": "Ada"},
    )
    return admin.patch(f"/api/clients/{customer['id']}/portal", json={"portal_enabled": True}).json()


def _suspender(admin: TestClient, client_id: str) -> None:
    response = admin.patch(f"/api/clients/{client_id}", json={"is_active": False})
    assert response.status_code == 200, response.text


def _reactivar(admin: TestClient, client_id: str) -> None:
    response = admin.patch(f"/api/clients/{client_id}", json={"is_active": True})
    assert response.status_code == 200, response.text
```

- [ ] **Step 2: Verificar que el archivo importa y no rompe la suite**

Run: `cd apps/api && pytest tests/test_suspension.py -q`
Expected: `no tests ran` — sin errores de importación.

- [ ] **Step 3: Commit**

```bash
git add apps/api/tests/test_suspension.py
git commit -m "test(api): add fixtures for company suspension"
```

---

### Task 2: El portal se cierra

**Files:**
- Modify: `apps/api/app/routers/portal.py:65-69` (`_public_client`)
- Modify: `apps/api/app/routers/portal.py:93-95` (la consulta de `_portal_client`)
- Test: `apps/api/tests/test_suspension.py`

- [ ] **Step 1: Escribir los tests que fallan**

Agregar al final de `apps/api/tests/test_suspension.py`:

```python
class TestElPortalSeCierra:
    """Suspendida, su gente no entra: ni con credenciales correctas, ni con la
    sesión que ya tenía abierta."""

    def test_el_login_se_rechaza(self, authenticated_client: TestClient):
        customer = _empresa_con_portal(authenticated_client)
        _suspender(authenticated_client, customer["id"])

        portal = TestClient(authenticated_client.app)
        response = portal.post(
            f"/api/portal/{customer['portal_slug']}/login",
            json={"email": "ada@panaderia.com", "password": PASSWORD},
        )

        assert response.status_code == 403
        assert "suspend" in response.json()["detail"].lower()

    def test_una_sesion_ya_abierta_deja_de_servir(self, authenticated_client: TestClient):
        # La sesión se abre ANTES de suspender: es el caso real, alguien
        # trabajando cuando se corta el servicio.
        customer = _empresa_con_portal(authenticated_client)
        portal = TestClient(authenticated_client.app)
        assert portal.post(
            f"/api/portal/{customer['portal_slug']}/login",
            json={"email": "ada@panaderia.com", "password": PASSWORD},
        ).status_code == 200

        _suspender(authenticated_client, customer["id"])

        response = portal.get(f"/api/portal/{customer['portal_slug']}/conversations")
        assert response.status_code == 403

    def test_reactivar_devuelve_el_acceso(self, authenticated_client: TestClient):
        # Suspender no borra: es lo que separa "te cortamos" de "te perdimos".
        customer = _empresa_con_portal(authenticated_client)
        _suspender(authenticated_client, customer["id"])
        _reactivar(authenticated_client, customer["id"])

        portal = TestClient(authenticated_client.app)
        response = portal.post(
            f"/api/portal/{customer['portal_slug']}/login",
            json={"email": "ada@panaderia.com", "password": PASSWORD},
        )

        assert response.status_code == 200
```

- [ ] **Step 2: Correr y verificar que fallan**

Run: `cd apps/api && pytest tests/test_suspension.py::TestElPortalSeCierra -v`
Expected: FAIL. Los dos primeros dan `200` donde se espera `403`.

- [ ] **Step 3: Implementar el corte en `_public_client`**

En `apps/api/app/routers/portal.py`, reemplazar la función de la línea 65:

```python
def _public_client(db: Session, slug: str) -> Client:
    client = db.scalar(select(Client).where(Client.portal_slug == slug, Client.portal_enabled.is_(True)))
    if not client:
        raise HTTPException(status_code=404, detail="Portal not found or disabled")
    # 403 y no 404: el portal existe y su gente lo conoce. Decirle "no existe"
    # a quien lo viene usando hace diez meses manda a revisar la URL en vez de
    # llamar a quien factura. El 404 queda para el slug que de verdad no está.
    if not client.is_active:
        raise HTTPException(status_code=403, detail="This portal is suspended")
    return client
```

- [ ] **Step 4: Implementar el corte en `_portal_client`**

En la misma función `_portal_client`, reemplazar el bloque de las líneas 93-95:

```python
    client = db.scalar(select(Client).where(Client.id == client_id, Client.portal_slug == slug, Client.portal_enabled.is_(True)))
    if not client:
        raise HTTPException(status_code=401, detail="The portal is no longer available")
    if not client.is_active:
        raise HTTPException(status_code=403, detail="This portal is suspended")
    return client
```

- [ ] **Step 5: Correr y verificar que pasan**

Run: `cd apps/api && pytest tests/test_suspension.py::TestElPortalSeCierra -v`
Expected: PASS, 3 tests.

- [ ] **Step 6: Correr la suite entera, que es donde aparecen las sorpresas**

Run: `cd apps/api && pytest -q`
Expected: PASS. Si algún test de portal se rompe, es porque creaba clientes sin
`is_active`; el default del modelo es `True`, así que revisá si ese test lo pone
en `False` a propósito.

- [ ] **Step 7: Commit**

```bash
git add apps/api/app/routers/portal.py apps/api/tests/test_suspension.py
git commit -m "feat(api): close the portal for a suspended company"
```

---

### Task 3: El widget deja de atender

**Files:**
- Modify: `apps/api/app/routers/widget.py:48-56` (`_agent`)
- Test: `apps/api/tests/test_suspension.py`

- [ ] **Step 1: Escribir el test que falla**

```python
class TestElWidgetDejaDeAtender:
    """El chat embebido en el sitio de la empresa deja de cargar. Un widget que
    responde es un servicio que se está prestando."""

    def test_la_configuracion_del_widget_no_se_entrega(self, authenticated_client: TestClient):
        customer = _empresa_con_portal(authenticated_client)
        agent = authenticated_client.post(
            "/api/agents",
            json={
                "client_id": customer["id"],
                "name": "Bot Panaderia",
                "instructions": "Atende pedidos.",
                "provider": "openai",
                "model": "gpt-4o-mini",
            },
        ).json()
        authenticated_client.patch(f"/api/agents/{agent['id']}", json={"widget_enabled": True})
        public_id = authenticated_client.get(f"/api/agents/{agent['id']}").json()["widget_public_id"]

        visitante = TestClient(authenticated_client.app)
        assert visitante.get(f"/api/widget/{public_id}").status_code == 200

        _suspender(authenticated_client, customer["id"])

        assert visitante.get(f"/api/widget/{public_id}").status_code == 404
```

- [ ] **Step 2: Correr y verificar que falla**

Run: `cd apps/api && pytest tests/test_suspension.py::TestElWidgetDejaDeAtender -v`
Expected: FAIL — devuelve `200` donde se espera `404`.

Si falla antes, en el `POST /api/agents` o en el `PATCH`, ajustá el payload a
lo que pida `AgentCreate` en `apps/api/app/schemas.py`. El resto del test no
cambia.

- [ ] **Step 3: Implementar**

En `apps/api/app/routers/widget.py`, reemplazar la función de la línea 48:

```python
def _agent(db: Session, public_id: str) -> Agent:
    agent = db.scalar(
        select(Agent)
        .options(joinedload(Agent.client))
        .where(Agent.widget_public_id == public_id, Agent.widget_enabled.is_(True))
    )
    # 404 y no 403, al revés que en el portal: acá quien pregunta es un
    # visitante del sitio de la empresa, no la empresa. No tiene por qué
    # enterarse de que hay una cuenta suspendida detrás — para él, el chat
    # simplemente no está. El `joinedload` de arriba ya trajo al cliente, así
    # que esto no agrega una consulta.
    if not agent or not agent.client.is_active:
        raise HTTPException(status_code=404, detail="Widget not found")
    return agent
```

- [ ] **Step 4: Correr y verificar que pasa**

Run: `cd apps/api && pytest tests/test_suspension.py::TestElWidgetDejaDeAtender -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add apps/api/app/routers/widget.py apps/api/tests/test_suspension.py
git commit -m "feat(api): stop serving the widget of a suspended company"
```

---

### Task 4: WhatsApp deja de contestar

**Files:**
- Modify: `apps/api/app/routers/whatsapp.py:215-218` (`inbound_message`)
- Test: `apps/api/tests/test_suspension.py`

Este es el que más importa del negocio: es el canal que sigue trabajando
gratis toda la noche.

- [ ] **Step 1: Escribir el test que falla**

```python
class TestWhatsappDejaDeContestar:
    """El canal que de verdad cuesta plata cuando no se corta."""

    def test_el_mensaje_entrante_se_rechaza(self, authenticated_client: TestClient):
        customer = _empresa_con_portal(authenticated_client)
        agent = authenticated_client.post(
            "/api/agents",
            json={
                "client_id": customer["id"],
                "name": "Bot Panaderia",
                "instructions": "Atende pedidos.",
                "provider": "openai",
                "model": "gpt-4o-mini",
            },
        ).json()
        channel = authenticated_client.post(
            f"/api/clients/{customer['id']}/channels/whatsapp",
            json={"agent_id": agent["id"]},
        ).json()

        _suspender(authenticated_client, customer["id"])

        puente = TestClient(authenticated_client.app)
        response = puente.post(
            f"/api/whatsapp/channels/{channel['id']}/inbound",
            json={"chat_id": "5491100000000@s.whatsapp.net", "content": "hola", "sender_name": "Cliente"},
            headers={"X-Bridge-Token": "test-only-bridge-token"},
        )

        assert response.status_code == 409
        assert "suspend" in response.json()["detail"].lower()
```

- [ ] **Step 2: Correr y verificar que falla**

Run: `cd apps/api && pytest tests/test_suspension.py::TestWhatsappDejaDeContestar -v`
Expected: FAIL.

Dos cosas que pueden desviarlo, y las dos se arreglan mirando el código, no el
plan:
- El nombre de la cabecera del puente: verificalo en `_require_bridge`
  (`apps/api/app/routers/whatsapp.py`). El valor sale de
  `WHATSAPP_BRIDGE_TOKEN`, que `conftest.py:24` fija en
  `test-only-bridge-token`.
- La forma del payload: verificala en `WhatsAppInbound`
  (`apps/api/app/schemas.py`).

- [ ] **Step 3: Implementar**

En `apps/api/app/routers/whatsapp.py`, dentro de `inbound_message`, agregar
justo después del control de `is_enabled` de la línea 217:

```python
    channel = _internal_channel(db, channel_id)
    if not channel.is_enabled:
        raise HTTPException(status_code=409, detail="The channel is disconnected")
    # 409 y no 403 para que el puente lo trate como lo que es: una condición
    # del canal, igual que estar desconectado. Ya sabe no reintentar ante un
    # 409. `_internal_channel` trae al cliente con joinedload (línea 74), así
    # que esto no agrega una consulta.
    if not channel.agent.client.is_active:
        raise HTTPException(status_code=409, detail="This company is suspended")
```

- [ ] **Step 4: Correr y verificar que pasa**

Run: `cd apps/api && pytest tests/test_suspension.py::TestWhatsappDejaDeContestar -v`
Expected: PASS.

- [ ] **Step 5: El webhook de WhatsApp Cloud — y NO se corta igual**

El canal de Meta entra por otro archivo,
`apps/api/app/routers/whatsapp_cloud_webhook.py:102` (`receive_webhook`), y
tiene una regla propia que cambia la respuesta correcta. Está escrita en el
código, línea 114:

> *«From here on always acknowledge with 200: Meta retries non-2xx responses,
> and a payload that fails once will fail on every retry.»*

Si devolvés 403 o 409 por empresa suspendida, **Meta reintenta el mismo mensaje
para siempre**. Una empresa suspendida se transforma en tráfico infinito contra
tu servidor: el corte de servicio te termina costando más que no cortar.

Entonces acá se responde **200 y se descarta el mensaje**. No es una excepción
a la regla del plan: es la misma decisión —no atender— dicha en el idioma que
entiende quien llama.

Agregar en `receive_webhook`, **después** de la verificación de firma (para no
darle a un desconocido una forma de averiguar qué canales existen) y antes de
procesar:

```python
    if not channel.client.is_active:
        # 200 y descartar, al revés que en el puente Baileys, que recibe 409.
        # Meta reintenta todo lo que no sea 2xx, así que un rechazo acá
        # convierte a una empresa suspendida en tráfico infinito. El mensaje se
        # pierde a propósito: no hay a quién entregárselo.
        return {"status": "ignored"}
```

- [ ] **Step 6: El test del webhook de Meta**

`tests/test_whatsapp_cloud.py` ya tiene los helpers que hacen falta. Agregar a
`apps/api/tests/test_suspension.py`:

```python
import json

from tests.test_whatsapp_cloud import APP_SECRET, _setup_channel, _sign, _webhook_payload


class TestElWebhookDeMetaDescarta:
    """El canal de las empresas grandes. Se responde 200 y se descarta, y NO se
    rechaza: Meta reintenta todo lo que no sea 2xx, así que un 403 convertiría a
    una empresa suspendida en tráfico infinito contra el servidor."""

    def test_responde_200_y_no_procesa(self, authenticated_client: TestClient):
        customer, agent, channel = _setup_channel(authenticated_client)
        _suspender(authenticated_client, customer["id"])

        payload = _webhook_payload(
            [{"from": "5730011", "id": "wamid.suspendida", "type": "text", "text": {"body": "hola"}}]
        )
        raw = json.dumps(payload).encode()

        meta = TestClient(authenticated_client.app)
        response = meta.post(
            f"/api/public/whatsapp-cloud/channels/{channel['id']}/webhook",
            content=raw,
            headers={"Content-Type": "application/json", "X-Hub-Signature-256": _sign(raw, APP_SECRET)},
        )

        assert response.status_code == 200

        # Y lo que de verdad importa: no se creó ninguna conversación.
        conversaciones = authenticated_client.get("/api/conversations/inbox").json()
        assert conversaciones == []

    def test_una_firma_invalida_sigue_dando_403(self, authenticated_client: TestClient):
        # El control de suspensión va DESPUÉS de la firma. Si se adelantara, le
        # daría a cualquiera una forma de averiguar qué canales existen y cuáles
        # están suspendidos, sin credencial alguna.
        customer, agent, channel = _setup_channel(authenticated_client)
        _suspender(authenticated_client, customer["id"])

        payload = _webhook_payload(
            [{"from": "5730011", "id": "wamid.falsa", "type": "text", "text": {"body": "hola"}}]
        )
        raw = json.dumps(payload).encode()

        meta = TestClient(authenticated_client.app)
        response = meta.post(
            f"/api/public/whatsapp-cloud/channels/{channel['id']}/webhook",
            content=raw,
            headers={"Content-Type": "application/json", "X-Hub-Signature-256": _sign(raw, "secreto-equivocado")},
        )

        assert response.status_code == 403
```

Run: `cd apps/api && pytest tests/test_suspension.py::TestElWebhookDeMetaDescarta -v`
Expected: el primero FAIL antes de implementar (crea la conversación), el
segundo PASS desde el principio. Después de implementar, los dos PASS.

Nota: `_setup_channel` carga una credencial de OpenAI (`tests/test_whatsapp_cloud.py:64`),
así que el agente **sí** está listo. Es a propósito: prueba que corta la
suspensión, no la falta de clave.

- [ ] **Step 7: Correr toda la suite**

Run: `cd apps/api && pytest -q`
Expected: PASS.

- [ ] **Step 8: Commit**

```bash
git add apps/api/app/routers/whatsapp.py apps/api/app/routers/whatsapp_cloud_webhook.py apps/api/tests/test_suspension.py
git commit -m "feat(api): refuse WhatsApp traffic for a suspended company"
```

---

### Task 5: La app mobile se cierra también

**Files:**
- Modify: `apps/api/app/routers/mobile.py:132-133` (login) y `:157-158` (sesión)
- Test: `apps/api/tests/test_suspension.py`

La app mobile es la **cuarta puerta** al mismo portal, y tiene su propio camino
de autenticación: no pasa por `_portal_client`, así que la Tarea 2 no la cubre.
Olvidarla deja el corte a medias — su gente entra igual desde el teléfono.

- [ ] **Step 1: Escribir el test que falla**

```python
class TestLaAppMobileSeCierra:
    """La cuarta puerta. Tiene su propio login y NO pasa por la dependencia del
    portal, así que cerrar el portal web no la cierra."""

    def test_el_login_mobile_se_rechaza(self, authenticated_client: TestClient):
        customer = _empresa_con_portal(authenticated_client)
        _suspender(authenticated_client, customer["id"])

        telefono = TestClient(authenticated_client.app)
        response = telefono.post(
            "/api/mobile/login",
            json={"email": "ada@panaderia.com", "password": PASSWORD},
        )

        assert response.status_code == 401
```

Verificá la ruta exacta del login mobile antes de correr:

Run: `cd apps/api && grep -n '@router.post' app/routers/mobile.py`

- [ ] **Step 2: Correr y verificar que falla**

Run: `cd apps/api && pytest tests/test_suspension.py::TestLaAppMobileSeCierra -v`
Expected: FAIL — devuelve `200` con una sesión válida.

- [ ] **Step 3: Implementar en el login**

En `apps/api/app/routers/mobile.py`, línea 132, extender la condición que ya
descarta los portales cerrados:

```python
        client = db.get(Client, user.client_id)
        # La suspensión se trata igual que un portal cerrado: se descarta este
        # candidato y se sigue buscando. El 401 final no dice por qué, y eso es
        # deliberado — esta respuesta ya está escrita para no revelar si una
        # dirección existe (ver el docstring de esta función).
        if not client or not client.portal_enabled or not client.is_active:
            continue
```

- [ ] **Step 4: Implementar en la sesión ya emitida**

En la línea 157, misma idea, para que un teléfono con la sesión abierta deje de
servir:

```python
    client = db.scalar(
        select(Client).where(Client.id == client_id, Client.portal_enabled.is_(True), Client.is_active.is_(True))
    )
```

- [ ] **Step 5: Correr y verificar que pasa**

Run: `cd apps/api && pytest tests/test_suspension.py::TestLaAppMobileSeCierra -v`
Expected: PASS.

- [ ] **Step 6: Correr toda la suite**

Run: `cd apps/api && pytest -q`
Expected: PASS. Mirá `tests/test_mobile_and_push.py`: si algún test crea su
empresa sin pasar por la API, puede quedar con `is_active` por defecto, que es
`True`, y entonces no se ve afectado.

- [ ] **Step 7: Commit**

```bash
git add apps/api/app/routers/mobile.py apps/api/tests/test_suspension.py
git commit -m "feat(api): close the mobile door for a suspended company"
```

---

### Task 6: El dueño no pierde acceso

**Files:**
- Test: `apps/api/tests/test_suspension.py`

No hay implementación. Este test existe para fijar que el corte es **en una
sola dirección**, y para que nadie lo rompa después «cortando mejor».

- [ ] **Step 1: Escribir los tests**

```python
class TestElDuenoNoPierdeAcceso:
    """El corte es para la empresa, no para quien la administra.

    Si suspender también te dejara a vos afuera, no podrías revisar su cuenta
    justo cuando hay que hablar de la deuda. Y los datos tienen que seguir ahí:
    suspender no es borrar.
    """

    def test_la_empresa_suspendida_sigue_en_el_listado(self, authenticated_client: TestClient):
        customer = _empresa_con_portal(authenticated_client)
        _suspender(authenticated_client, customer["id"])

        listado = authenticated_client.get("/api/clients").json()

        assert any(row["id"] == customer["id"] for row in listado)

    def test_su_ficha_se_sigue_abriendo(self, authenticated_client: TestClient):
        customer = _empresa_con_portal(authenticated_client)
        _suspender(authenticated_client, customer["id"])

        response = authenticated_client.get(f"/api/clients/{customer['id']}")

        assert response.status_code == 200
        assert response.json()["is_active"] is False

    def test_su_gente_sigue_existiendo(self, authenticated_client: TestClient):
        # Suspender no borra cuentas. Reactivar tiene que devolver el equipo
        # completo, sin que nadie vuelva a cargar a mano quién trabajaba ahí.
        customer = _empresa_con_portal(authenticated_client)
        _suspender(authenticated_client, customer["id"])

        gente = authenticated_client.get(f"/api/clients/{customer['id']}/portal-users").json()

        assert [row["email"] for row in gente] == ["ada@panaderia.com"]
```

- [ ] **Step 2: Correr**

Run: `cd apps/api && pytest tests/test_suspension.py::TestElDuenoNoPierdeAcceso -v`
Expected: PASS sin tocar código. Si alguno falla, algo de las Tareas 2 a 4
cortó de más: el corte se coló en el camino de la agencia.

- [ ] **Step 3: Commit**

```bash
git add apps/api/tests/test_suspension.py
git commit -m "test(api): pin that suspension never locks the owner out"
```

---

### Task 7: La pantalla de servicio suspendido

**Files:**
- Modify: `apps/web/app/portal/[slug]/page.tsx:64-66`
- Test: `apps/web/app/portal/suspended.test.tsx`
- Modify: `apps/web/lib/i18n/dicts/portal.ts` (dos claves nuevas)

Hoy, un 403 cae en `portal.loader.unavailable` — «el portal no está
disponible». Cierto y poco útil: su gente no sabe si es una caída o una
suspensión, y termina llamando a soporte técnico en vez de a quien factura.

- [ ] **Step 1: Agregar las claves de i18n**

En `apps/web/lib/i18n/dicts/portal.ts`, dentro del objeto `loader`, agregar:

```ts
    suspendedTitle: "Servicio suspendido",
    suspendedBody: "Este portal está suspendido. Comunicate con quien contrató el servicio para reactivarlo.",
```

Y su par en inglés, en el archivo del diccionario `en`. El sistema de i18n es
tipado: si falta una de las dos, `tsc --noEmit` falla. Esa es la idea.

- [ ] **Step 2: Escribir el test que falla**

Create `apps/web/app/portal/suspended.test.tsx`:

```tsx
import { describe, expect, it } from "vitest";
import { render, screen } from "@testing-library/react";
import { SuspendedNotice } from "./suspended";

describe("SuspendedNotice", () => {
  it("tells the person to contact whoever pays, not support", () => {
    render(<SuspendedNotice title="Servicio suspendido" body="Comunicate con quien contrató el servicio." />);
    expect(screen.getByRole("heading", { name: "Servicio suspendido" })).toBeVisible();
    expect(screen.getByText(/quien contrató el servicio/)).toBeVisible();
  });
});
```

- [ ] **Step 3: Correr y verificar que falla**

Run: `cd apps/web && npm test`
Expected: FAIL — `Cannot find module './suspended'`.

- [ ] **Step 4: Crear el componente**

Create `apps/web/app/portal/[slug]/suspended.tsx`:

```tsx
"use client";

export function SuspendedNotice({ title, body }: { title: string; body: string }) {
  return (
    <div className="portal-loader">
      <div>
        <h2>{title}</h2>
        <p>{body}</p>
      </div>
    </div>
  );
}
```

Ajustá el import del test a `./[slug]/suspended` si dejás el archivo dentro de
`[slug]/`; lo importante es que el test apunte al archivo real.

- [ ] **Step 5: Mostrarlo cuando el backend responde 403**

En `apps/web/app/portal/[slug]/page.tsx`, el efecto de la línea 56 guarda el
error con `messageFrom(err)`, que pierde el código de estado. Guardar también
el estado:

```tsx
  const [suspended, setSuspended] = useState(false);
```

y en el `.catch` de ese efecto:

```tsx
    .catch((err) => {
      if (err instanceof ApiError && err.status === 403) { setSuspended(true); return; }
      setError(messageFrom(err));
    })
```

y antes del `if (!portal)` de la línea 65:

```tsx
  if (suspended) return <SuspendedNotice title={t("portal.loader.suspendedTitle")} body={t("portal.loader.suspendedBody")} />;
```

- [ ] **Step 6: Correr todo lo del frontend**

```bash
cd apps/web
npm test
npx tsc --noEmit
npm run lint
npm run build
```
Expected: los cuatro en verde.

- [ ] **Step 7: Commit**

```bash
git add apps/web/app/portal apps/web/lib/i18n
git commit -m "feat(web): tell a suspended company what actually happened"
```

---

### Task 8: Verificación final

- [ ] **Step 1: Backend completo**

Run: `cd apps/api && pytest -q`
Expected: PASS, con los tests nuevos de `test_suspension.py` incluidos.

- [ ] **Step 2: Frontend completo**

```bash
cd apps/web && npm ci && npm run lint && npx tsc --noEmit && npm test && npm run build
```
Expected: los cinco pasos del job `web` en verde.

- [ ] **Step 3: Revisar que no se coló nada**

Run: `git diff main --stat`
Expected: solo `portal.py`, `widget.py`, `whatsapp.py`, `tests/test_suspension.py`,
y los archivos del frontend de la Tarea 6. **Ninguna migración**: este plan no
agrega ni cambia una columna.

- [ ] **Step 4: Abrir el PR y esperar el CI**

El repo tiene **siete** jobs, no tres. Esperá a que pasen todos:

```bash
gh pr create --base main --title "feat: suspending a company actually cuts service"
gh pr checks --watch
```

---

## Fuera de alcance

- Facturación, planes, cobro automático. El toggle se mueve a mano.
- Suspensión automática por falta de pago.
- Retención o borrado de datos de empresas suspendidas.
- Avisar por correo a la empresa que fue suspendida.
- El cupo `max_agents`: es de S5.
