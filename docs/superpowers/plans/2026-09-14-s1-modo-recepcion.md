# S1 — Modo recepción Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Que una empresa sin clave de IA siga siendo un producto que funciona — saludo con su nombre, menú de dependencias y traspaso a una persona — en todos los canales, no solo en WhatsApp.

**Architecture:** El modo recepción ya está implementado y bien, pero solo en el camino de WhatsApp. Este plan hace tres cosas: saca el saludo de una constante de módulo y lo pone por empresa, lleva el mismo comportamiento al widget, y se asegura de que el contacto nunca quede sin respuesta. La maquinaria de menú y ruteo (`services/departments.py`) **no se toca**: se reutiliza.

**Tech Stack:** FastAPI, SQLAlchemy, Alembic, pytest.

**Depende de:** nada. Es independiente de S0 y se puede hacer en paralelo.

---

## Contexto que el implementador necesita

### Lo que ya funciona, y no hay que rehacer

`apps/api/app/services/departments.py` implementa el flujo completo:

| Función | Línea | Qué hace |
|---|---|---|
| `send_menu()` | 141 | Ofrece el menú una vez por conversación (`menu_sent_at`) y lo guarda en el hilo |
| `_deliver_menu()` | 115 | Botones nativos de WhatsApp Cloud si hay ≤3 dependencias, lista si hay más, texto en Baileys |
| `menu_text()` | 108 | El menú como texto plano |
| `match_choice()` | — | Entiende el número, el nombre o el slug |
| `route()` | 168 | Rutea el caso y cambia el agente que contesta |

Y en `services/whatsapp_inbound.py:379-405`, cuando el agente no puede
contestar, el caso **ya** pasa a modo humano, se anota el motivo en el canal,
se avisa en vivo a la dependencia y suena una notificación. Su comentario
explica el porqué mejor que este plan:

> *«El bot es una opción, no un requisito. El menú de dependencias y el ruteo
> funcionan sin IA —son código, no un modelo—, así que cuando el agente no
> puede contestar el caso tiene que pasar a una PERSONA en lugar de quedarse
> esperando una respuesta que no va a llegar.»*

**No reescribas nada de eso.** El trabajo de acá es extenderlo.

### Los tres huecos

1. **El saludo es igual para todas las empresas.** `departments.py:33`:
   ```python
   MENU_INTRO = "¡Hola! ¿Con cuál dependencia deseas comunicarte?"
   ```
   Constante de módulo. La panadería y la clínica saludan idéntico.
2. **El widget no participa.** `widget.py:159` devuelve `None` y se acabó: no
   pasa a modo humano, no notifica, no ofrece menú. El visitante escribe y no
   pasa nada. Compará con `widget.py:202`, donde el modo humano **sí** notifica
   — o sea que la mitad del camino ya existe, solo que nadie la activa.
3. **El contacto nunca recibe un acuse.** Aun cuando el traspaso interno
   funciona, del otro lado hay silencio hasta que una persona escriba.

---

### Task 1: El saludo de recepción, por empresa

**Files:**
- Create: `apps/api/migrations/versions/0032_reception_greeting.py`
- Modify: `apps/api/app/models.py` (clase `Client`, después de `general_context`)
- Modify: `apps/api/app/services/departments.py:33-35` y `:108-112`
- Modify: `apps/api/app/schemas.py` (`ClientBase` y `ClientUpdate`)
- Test: `apps/api/tests/test_reception.py`

- [ ] **Step 1: Escribir el test que falla**

Create `apps/api/tests/test_reception.py`:

```python
"""El saludo de recepción es de cada empresa, no del software.

El menú de dependencias funciona sin IA desde siempre, pero saludaba igual para
todos: la panadería y la clínica decían la misma frase. En un producto que se
vende por tener marca propia, eso no cierra.

Vacío significa "usá el de fábrica", no "no saludes": una empresa que nunca
tocó el campo tiene que seguir funcionando igual que antes.
"""

from fastapi.testclient import TestClient

from app.models import Client
from app.services.departments import MENU_INTRO, menu_text


class TestElSaludoEsDeCadaEmpresa:
    def test_usa_el_texto_propio_cuando_esta_cargado(self):
        empresa = Client(name="Panaderia Lopez", reception_intro="Buen dia, soy la panaderia. Con que area querés hablar?")
        assert menu_text([], empresa).startswith("Buen dia, soy la panaderia.")

    def test_cae_al_de_fabrica_cuando_esta_vacio(self):
        empresa = Client(name="Panaderia Lopez", reception_intro="")
        assert menu_text([], empresa).startswith(MENU_INTRO)

    def test_se_guarda_y_se_devuelve_por_la_api(self, authenticated_client: TestClient):
        customer = authenticated_client.post(
            "/api/clients",
            json={"name": "Panaderia Lopez", "industry": "", "description": "", "general_context": "", "is_active": True},
        ).json()

        actualizado = authenticated_client.patch(
            f"/api/clients/{customer['id']}",
            json={"reception_intro": "Buen dia, soy la panaderia."},
        )

        assert actualizado.status_code == 200
        assert actualizado.json()["reception_intro"] == "Buen dia, soy la panaderia."
```

- [ ] **Step 2: Correr y verificar que falla**

Run: `cd apps/api && pytest tests/test_reception.py -v`
Expected: FAIL — `TypeError: 'reception_intro' is an invalid keyword argument for Client`.

- [ ] **Step 3: Agregar las columnas al modelo**

En `apps/api/app/models.py`, clase `Client`, justo después de `general_context`:

```python
    # El saludo de recepción, el de esta empresa. Vacío significa "usá el de
    # fábrica" y no "no saludes": la mayoría de las empresas no lo va a tocar
    # nunca, y esa mayoría tiene que seguir funcionando sin cargar nada.
    reception_intro: Mapped[str] = mapped_column(Text, default="", server_default="")
    reception_footer: Mapped[str] = mapped_column(Text, default="", server_default="")
```

- [ ] **Step 4: Escribir la migración**

Create `apps/api/migrations/versions/0032_reception_greeting.py`:

```python
"""Reception greeting, per company.

The department menu has always worked without an AI key, but it greeted every
company with the same sentence, because the text was a module constant. In a
product sold on having your own brand, that does not hold.

Empty means "use the built-in text", not "say nothing": most companies will
never touch these, and those companies have to keep working unchanged. That is
why the columns are NOT NULL with an empty default rather than nullable — there
is no third state to represent.

Revision ID: 0032_reception_greeting
Revises: 0031_portal_user_avatar
"""

import sqlalchemy as sa
from alembic import op

revision: str = "0032_reception_greeting"
down_revision: str | None = "0031_portal_user_avatar"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("clients", sa.Column("reception_intro", sa.Text(), nullable=False, server_default=""))
    op.add_column("clients", sa.Column("reception_footer", sa.Text(), nullable=False, server_default=""))


def downgrade() -> None:
    op.drop_column("clients", "reception_footer")
    op.drop_column("clients", "reception_intro")
```

- [ ] **Step 5: Hacer que `menu_text` reciba la empresa**

En `apps/api/app/services/departments.py`, reemplazar `menu_text` (línea 108):

```python
def menu_text(departments: list[Department], client: Client | None = None) -> str:
    """El menú como texto. Es lo que se manda por Baileys y, en los dos canales,
    lo que queda guardado en el hilo para quien lo lea después desde el portal.

    El saludo sale de la empresa cuando lo tiene cargado. Las constantes de
    abajo siguen existiendo como valor de fábrica: son el texto de la enorme
    mayoría, que nunca va a tocar el campo.
    """
    intro = (client.reception_intro if client else "").strip() or MENU_INTRO
    footer = (client.reception_footer if client else "").strip() or MENU_FOOTER
    lines = [f"{index}. {department.name}" for index, department in enumerate(departments, start=1)]
    return "\n".join([intro, "", *lines, "", footer])
```

Agregá `Client` al import de modelos que ya tiene el archivo.

- [ ] **Step 6: Pasar la empresa desde los llamadores**

Run: `cd apps/api && grep -rn "menu_text(\|MENU_INTRO" app/`

Cada llamada tiene que pasar el `Client`. En `_deliver_menu` (línea 115) la
conversación ya está a mano: `conversation.client`. Los usos de `MENU_INTRO`
dentro de `_deliver_menu` —los de botones y lista de WhatsApp Cloud— también
tienen que usar el texto de la empresa, o el saludo va a ser propio en Baileys
y genérico en WhatsApp API, que es peor que no hacerlo.

- [ ] **Step 7: Exponerlas en la API**

En `apps/api/app/schemas.py`, agregar a `ClientBase` (para que salga en las
respuestas) y a `ClientUpdate` (para poder editarlas):

```python
    reception_intro: str = ""
    reception_footer: str = ""
```

En `ClientUpdate`, como opcionales:

```python
    reception_intro: str | None = None
    reception_footer: str | None = None
```

- [ ] **Step 8: Correr los tests**

Run: `cd apps/api && pytest tests/test_reception.py -v`
Expected: PASS, 3 tests.

- [ ] **Step 9: Probar la migración de verdad**

```bash
cd apps/api && alembic upgrade head && alembic downgrade -1 && alembic upgrade head
```
Expected: los tres sin error. CI corre `alembic upgrade head` contra una base
limpia (job `api`), así que una migración rota llega en rojo.

- [ ] **Step 10: Commit**

```bash
git add apps/api/app/models.py apps/api/app/schemas.py apps/api/app/services/departments.py apps/api/migrations/versions/0032_reception_greeting.py apps/api/tests/test_reception.py
git commit -m "feat(api): let each company write its own reception greeting"
```

---

### Task 2: El widget deja de quedarse mudo

**Files:**
- Modify: `apps/api/app/routers/widget.py:153-160` (`_widget_ai_reply`)
- Test: `apps/api/tests/test_reception.py`

Hoy `_widget_ai_reply` devuelve `None` cuando el agente no está listo, y ahí
termina todo. En el camino de WhatsApp, el mismo caso pasa a modo humano y
notifica (`whatsapp_inbound.py:395-404`). El widget tiene que hacer lo mismo.

Fijate que la mitad ya está: `widget.py:202` llama a `notify_needs_human` en
cuanto la conversación está en modo humano. Lo único que falta es que algo la
ponga en ese modo.

- [ ] **Step 1: Escribir el test que falla**

Agregar a `apps/api/tests/test_reception.py`:

```python
class TestElWidgetNoSeQuedaMudo:
    """Sin clave, el chat web tiene que pasar el caso a una persona — igual que
    WhatsApp— en vez de tragarse el mensaje."""

    def test_sin_clave_la_conversacion_pasa_a_modo_humano(self, authenticated_client: TestClient):
        customer = authenticated_client.post(
            "/api/clients",
            json={"name": "Panaderia Lopez", "industry": "", "description": "", "general_context": "", "is_active": True},
        ).json()
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

        # No se cargó ninguna credencial de proveedor: es el estado de toda
        # empresa recién dada de alta.
        visitante = TestClient(authenticated_client.app)
        response = visitante.post(
            f"/api/widget/{public_id}/messages",
            json={"session_id": "sesion-de-prueba", "content": "hola, hacen tortas?"},
        )

        assert response.status_code == 200
        assert response.json()["mode"] == "human"
```

- [ ] **Step 2: Correr y verificar que falla**

Run: `cd apps/api && pytest tests/test_reception.py::TestElWidgetNoSeQuedaMudo -v`
Expected: FAIL — `mode` llega como `"ai"`.

- [ ] **Step 3: Implementar**

En `apps/api/app/routers/widget.py`, reemplazar las líneas 158-160:

```python
    credentials = resolve_agent_credentials(db, agent)
    if not agent.is_active or not credentials or not agent.model.strip():
        # Mismo criterio que en el camino de WhatsApp
        # (services/whatsapp_inbound.py:381): el bot es una opción, no un
        # requisito. Cuando no puede contestar, el caso pasa a una PERSONA en
        # vez de quedarse esperando una respuesta que no va a llegar.
        #
        # Antes esto devolvía None y nada más: la conversación quedaba en modo
        # "ai", así que en el portal figuraba como atendida por el bot y nadie
        # se enteraba. El visitante escribía y no le contestaba nadie.
        set_mode(db, conversation, "human", actor="system")
        db.commit()
        await notify_needs_human(db, conversation, query)
        return None
```

Agregá `set_mode` al import desde `..services.conversation_state`, si el
archivo todavía no lo trae.

- [ ] **Step 4: Correr y verificar que pasa**

Run: `cd apps/api && pytest tests/test_reception.py::TestElWidgetNoSeQuedaMudo -v`
Expected: PASS.

- [ ] **Step 5: Correr toda la suite**

Run: `cd apps/api && pytest -q`
Expected: PASS. Prestá atención a los tests del widget que ya existían: alguno
puede estar afirmando que sin clave la respuesta viene vacía y en modo `"ai"`.
Si aparece, **es el test el que estaba fijando el defecto**: actualizalo y
dejá dicho en el mensaje del commit por qué cambió.

- [ ] **Step 6: Commit**

```bash
git add apps/api/app/routers/widget.py apps/api/tests/test_reception.py
git commit -m "feat(api): hand a widget chat to a person when the agent cannot answer"
```

---

### Task 3: El contacto siempre recibe un acuse

**Files:**
- Modify: `apps/api/app/routers/widget.py` (dentro de `_widget_ai_reply`)
- Modify: `apps/api/app/services/whatsapp_inbound.py:393-405`
- Test: `apps/api/tests/test_reception.py`

El traspaso interno ya funciona en los dos canales, pero del lado del contacto
hay silencio. Con dependencias cargadas, `send_menu` cubre el caso. Sin
dependencias, nadie dice nada.

- [ ] **Step 1: Escribir el test que falla**

```python
class TestElContactoSiempreRecibeAlgo:
    """Sin clave y sin dependencias, el contacto igual tiene que saber que
    alguien lo va a atender. El traspaso interno ya funcionaba; lo que faltaba
    era decírselo a quien escribió."""

    def test_el_widget_responde_un_acuse(self, authenticated_client: TestClient):
        customer = authenticated_client.post(
            "/api/clients",
            json={"name": "Panaderia Lopez", "industry": "", "description": "", "general_context": "", "is_active": True},
        ).json()
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
        cuerpo = visitante.post(
            f"/api/widget/{public_id}/messages",
            json={"session_id": "sesion-de-prueba", "content": "hola"},
        ).json()

        assert cuerpo["mode"] == "human"
        assert cuerpo["reply"], "el contacto tiene que recibir algo, no silencio"
```

- [ ] **Step 2: Correr y verificar que falla**

Run: `cd apps/api && pytest tests/test_reception.py::TestElContactoSiempreRecibeAlgo -v`
Expected: FAIL — `reply` viene en `None`.

- [ ] **Step 3: Agregar el texto de acuse a `departments.py`**

En `apps/api/app/services/departments.py`, junto a las otras constantes de la
línea 33:

```python
# Lo que recibe el contacto cuando no hay bot que conteste y tampoco hay
# dependencias entre las cuales elegir. No es un error: es una recepción
# atendida por personas, que es un producto válido.
HANDOFF_ACK = "¡Hola! Ya recibimos tu mensaje y en un momento te atiende una persona."
```

Y una función que resuelva el texto de la empresa, con el mismo criterio que
`menu_text`:

```python
def handoff_ack(client: Client | None = None) -> str:
    return (client.reception_intro if client else "").strip() or HANDOFF_ACK
```

- [ ] **Step 4: Usarlo en el widget**

Dentro del bloque de la Tarea 2, en `apps/api/app/routers/widget.py`, antes del
`return`, guardar el acuse como mensaje y devolverlo:

```python
        ack = handoff_ack(agent.client)
        db.add(Message(conversation_id=conversation.id, role="assistant", content=ack, sender_type="system", sender_name=agent.name))
        conversation.updated_at = now_utc()
        set_mode(db, conversation, "human", actor="system")
        db.commit()
        await notify_needs_human(db, conversation, query)
        return ack
```

`sender_type="system"` y no `"ai"`: no lo escribió un modelo, y el portal
distingue esos dos casos al pintar el hilo.

- [ ] **Step 5: Correr y verificar que pasa**

Run: `cd apps/api && pytest tests/test_reception.py -v`
Expected: PASS, todos.

- [ ] **Step 6: Hacer lo mismo en WhatsApp**

En `apps/api/app/services/whatsapp_inbound.py`, dentro del bloque de la línea
381, **solo cuando no se mandó menú** — si hay dependencias, el menú ya es el
acuse y mandar los dos es ruido:

```python
        if conversation.menu_sent_at is None:
            await send_channel_message(db, conversation, handoff_ack(conversation.client))
```

Ponelo antes de `set_mode`. Escribí su test copiando la forma de
`tests/test_reply_debounce.py`, que ya simula el puente.

- [ ] **Step 7: Commit**

```bash
git add apps/api/app/routers/widget.py apps/api/app/services/whatsapp_inbound.py apps/api/app/services/departments.py apps/api/tests/test_reception.py
git commit -m "feat(api): acknowledge the contact when no bot can answer"
```

---

### Task 4: El widget ofrece el menú de dependencias

**Files:**
- Modify: `apps/api/app/routers/widget.py`
- Test: `apps/api/tests/test_reception.py`

Con dependencias cargadas, el widget tiene que ofrecer las mismas opciones que
WhatsApp. La diferencia de canal: el widget no entrega por una API externa,
devuelve el texto en la respuesta HTTP. Por eso usa `menu_text()` directo y no
`send_menu()`, que está atado al envío por canal.

- [ ] **Step 1: Escribir el test que falla**

```python
class TestElWidgetOfreceElMenu:
    """Con dependencias cargadas, el chat web ofrece las mismas opciones que
    WhatsApp. Un canal que rutea y otro que no es un producto distinto según
    por dónde te escriban."""

    def test_el_menu_llega_con_las_dependencias(self, authenticated_client: TestClient):
        customer = authenticated_client.post(
            "/api/clients",
            json={"name": "Panaderia Lopez", "industry": "", "description": "", "general_context": "", "is_active": True},
        ).json()
        authenticated_client.post(f"/api/clients/{customer['id']}/departments", json={"name": "Pedidos"})
        authenticated_client.post(f"/api/clients/{customer['id']}/departments", json={"name": "Reclamos"})
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
        reply = visitante.post(
            f"/api/widget/{public_id}/messages",
            json={"session_id": "sesion-de-prueba", "content": "hola"},
        ).json()["reply"]

        assert "1. Pedidos" in reply
        assert "2. Reclamos" in reply
```

Verificá la forma del payload de `POST /departments` en
`tests/test_departments.py` antes de correr: si pide más campos, ajustalos.

- [ ] **Step 2: Correr y verificar que falla**

Run: `cd apps/api && pytest tests/test_reception.py::TestElWidgetOfreceElMenu -v`
Expected: FAIL — llega el acuse de la Tarea 3, sin las opciones.

- [ ] **Step 3: Implementar**

En el bloque de `_widget_ai_reply`, reemplazar el acuse fijo por el menú cuando
haya dependencias:

```python
        from ..services.departments import client_departments, handoff_ack, menu_text

        departments = client_departments(db, agent.client)
        if departments and conversation.menu_sent_at is None:
            texto = menu_text(departments, agent.client)
            conversation.menu_sent_at = now_utc()
        else:
            texto = handoff_ack(agent.client)
        db.add(Message(conversation_id=conversation.id, role="assistant", content=texto, sender_type="system", sender_name=agent.name))
        conversation.updated_at = now_utc()
        set_mode(db, conversation, "human", actor="system")
        db.commit()
        await notify_needs_human(db, conversation, query)
        return texto
```

Movés los imports arriba del archivo si no generan ciclo; si lo generan, dejalos
adentro y escribí en un comentario por qué.

Verificá la firma real de `client_departments` con
`grep -n "def client_departments" app/services/departments.py`.

- [ ] **Step 4: Correr y verificar que pasa**

Run: `cd apps/api && pytest tests/test_reception.py -v`
Expected: PASS, todos.

- [ ] **Step 5: Commit**

```bash
git add apps/api/app/routers/widget.py apps/api/tests/test_reception.py
git commit -m "feat(api): offer the department menu on the web widget too"
```

---

### Task 5: Verificación final

- [ ] **Step 1: La suite completa**

Run: `cd apps/api && pytest -q`
Expected: PASS.

- [ ] **Step 2: La cadena de migraciones, de punta a punta**

```bash
cd apps/api && alembic upgrade head
```
Expected: sin error. Es lo que corre CI contra una base limpia.

- [ ] **Step 3: Elegir una dependencia desde el widget sigue funcionando**

Prueba manual, porque es el caso que une las cuatro tareas:

1. Levantá el stack: `make up`
2. Creá una empresa con dos dependencias y un agente con widget, **sin cargar
   credencial de proveedor**.
3. Abrí el widget y escribí «hola». Tiene que llegar el menú con las dos
   opciones.
4. Respondé «1». La conversación tiene que quedar ruteada a esa dependencia y
   visible en su bandeja del portal.

Si el paso 4 no rutea: `match_choice` se llama hoy solo desde el camino de
WhatsApp. Rutear la elección en el widget es trabajo real, **no lo metas acá**.
Anotalo como tarea de seguimiento y dejalo escrito en el PR: el menú ya orienta
al contacto y una persona ya recibe el caso, que es el objetivo de S1.

- [ ] **Step 4: Abrir el PR y esperar los siete jobs**

```bash
gh pr create --base main --title "feat: reception mode works without an AI key, on every channel"
gh pr checks --watch
```

---

## Fuera de alcance

- Rutear la elección de dependencia **dentro del widget** (ver Tarea 5, paso 3).
- Editar el saludo desde el portal de la empresa: por ahora lo carga la agencia.
  El portal se abre a configuración en S5.
- Traducir el saludo de fábrica: sale del diccionario de la empresa o de la
  constante en español, que es el idioma del producto.
- Avisarle a la empresa que le falta la clave. Es S2.
