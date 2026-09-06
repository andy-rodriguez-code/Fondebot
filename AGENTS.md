# AGENTS.md

Guidance for coding agents working in this repository. `AGENTS.md` is the file
agents look for; `CLAUDE.md` is a one-line pointer to it, the same pairing this
repo already uses in `apps/web`.

## Project

OpenLivery is a multi-tenant platform where agencies create and manage AI agents for their clients, with a chat playground, a client portal, and WhatsApp integration. Three services + PostgreSQL:

- `apps/api/` — FastAPI (Python 3.12) + SQLAlchemy + Alembic
- `apps/web/` — Next.js 16 (App Router) + React 19 + TypeScript + Tailwind
- `apps/whatsapp/` — Node.js bridge over Baileys (WhatsApp Web protocol)

**Convención de idioma (seguir siempre).** Este fork se mantiene en español. La
regla se parte en dos, y la división es deliberada:

- **En inglés, siempre:** identificadores (variables, funciones, clases),
  rutas de la API, nombres de tablas y columnas, y mensajes de commit. Son
  contrato: las rutas las consumen `apps/web`, `apps/mobile` y
  `apps/whatsapp`; los nombres de columna viven en las 26 migraciones de
  Alembic. Traducirlos no es traducir, es romper el contrato.
- **En español:** comentarios, docstrings, documentación en `docs/`, y toda la
  copia visible para la persona usuaria.

La UI se localiza con el sistema de i18n tipado (`apps/web/lib/i18n`): español
por defecto, inglés disponible con el selector de idioma. Nunca metas copia
visible directamente en el código: va detrás de una clave de i18n. Para código
que no es un componente de React (por ejemplo `lib/api.ts`), usá `translate()`
en vez del hook `useT()`.

`apps/mobile` no tiene selector a propósito: sigue el idioma del teléfono
(`apps/mobile/src/i18n.ts`).

El prompt de sistema que se le manda al LLM en
`apps/api/app/services/knowledge.py` ya estaba en español y se queda así: es el
idioma de la persona que atiende el negocio, no una cadena de interfaz.

## Repo hygiene

Enable the pre-commit guard once per clone: `git config core.hooksPath .githooks` — it fails fast, before a bad commit exists. CI runs the same hook on every pull request (the `guard` job), so forgetting the local setup delays the answer rather than removing it. CI cannot check the private word list, since that list must never reach this repository; it checks the built-in markers and the local-only paths. It blocks committing local-only files (`work/`, `internal/`, `*.local.md`) and any staged content matching terms in `work/forbidden-words.txt` (gitignored) or a commit-blocking marker (spelled out in `.githooks/pre-commit`; this file cannot quote it without tripping the guard it describes). Keep internal notes/roadmap in `work/` (gitignored) — never in the repo.

## Commands

### Docker (recommended)

A `Makefile` wraps compose: `make up` builds and starts everything; also `make down/logs/migrate/test/help`. Override host ports inline to avoid clashes: `API_PORT=8001 WEB_PORT=3001 make up` (`API_PORT`/`WEB_PORT`/`DB_PORT`/`BIND_HOST`).

```bash
./scripts/generate-docker-env.sh                       # create .env.docker with random secrets
docker compose --env-file .env.docker up --build -d
docker compose --env-file .env.docker logs -f api  # or: web, whatsapp, db
docker compose --env-file .env.docker exec api pytest -q
```

### Local

```bash
# Backend (needs PostgreSQL and a .env, see .env.example)
cd apps/api
pip install -r requirements.txt
alembic upgrade head                 # migrations must run before starting
uvicorn app.main:app --reload --port 8000

# Frontend
cd apps/web && npm install && npm run dev    # http://localhost:3000
npm run lint                                 # eslint
npm run build

# WhatsApp bridge
cd apps/whatsapp && npm install && npm run dev    # tsx watch, listens on :3101
npm test                                     # node test runner via tsx
npm run build                                # tsc typecheck
```

### Backend tests

`requirements.txt` holds only what the app needs to run — it is what the published image installs. `pytest` lives in `requirements-dev.txt`, so install that one to run the suite locally (`pip install -r requirements-dev.txt`). The Docker stack builds the `dev` target, which is why `make test` can run pytest inside the running container.

Tests need a separate `openlivery_test` database (default URL in `apps/api/tests/conftest.py`, override with `TEST_DATABASE_URL`). Tables are created/dropped per test — never point it at the dev DB.

```bash
cd apps/api
pytest -q
pytest tests/test_flows.py::test_register_login_logout_and_me -v   # single test
```

## Architecture

### Data model (apps/api/app/models.py)

Everything is agency-scoped: `Agency → Users, Clients, AIConnections`; `Client → Agents, WhatsAppChannel, Conversations`; `Agent → Conversations, KnowledgeDocuments`; `Conversation → Messages`. Every router query filters by the authenticated user's `agency_id` — preserve this in any new endpoint; it's the tenant-isolation boundary.

### Backend layout

- `app/database.py` — the engine and the one place a session is created. Routes receive one through `get_db`, which FastAPI lets a deployment substitute (the test suite does); anything running outside a request calls `new_session()`. Never call `SessionLocal()` elsewhere: it opts that code out of the substitution, so a swapped session never reaches it, and the failure surfaces inside a background task rather than in a response. `tests/test_session_factory.py` enforces this.
- `app/main.py` — app creation, CORS, router registration
- `app/routers/` — one file per domain (auth, agency, clients, agents, connections, conversations, dashboard, portal, whatsapp); `domains.py` holds the public, unauthenticated `/api/public/portal-domain` used by the frontend `proxy.ts` and the gateway's on-demand-TLS `ask` hook to map a client's custom domain to its portal
- `app/services/ai.py` — `chat_completion()` calls any OpenAI-compatible endpoint (base_url + model are per-connection config); connection testing lists `{base_url}/models`
- `app/services/knowledge.py` — PDF text (pypdf on upload) is chunked and embedded; retrieval is semantic (cosine over embeddings stored as JSON) with keyword ranking as a fallback, then assembled into the system prompt
- `app/security.py` — JWT in httpOnly cookies; AI API keys and WhatsApp session state are encrypted with a key derived from `ENCRYPTION_KEY` before hitting the DB
- `app/services/realtime.py` — el portal recibe avisos en vivo por SSE (`GET /api/portal/{slug}/events`). Se publica una señal (id de conversación), nunca su contenido: quien la recibe vuelve a pedir por los endpoints de siempre, que son los que aplican `_visible(user)`, así la frontera por dependencia vive en un solo lado. El bus es en memoria, igual que `ratelimit.py` y `_pending_replies`: con más de un worker un aviso no cruza de proceso, y lo que tapa el hueco es el refresco por intervalo que quedó de respaldo (`apps/web/lib/live.ts`). `publish()` se llama tanto desde handlers `async def` como desde los `def` que FastAPI corre en el threadpool, por eso usa `call_soon_threadsafe`. El gateway necesita `flush_interval -1` o los eventos salen en lote.
- `app/services/audit.py` — registro append-only de acciones sensibles (`GET /api/audit`, agency-scoped). Se escribe desde el handler, en la misma sesión y **antes** del commit, así la fila y el cambio que describe entran juntos o no entra ninguno — lo contrario de `error_log.record_error`, que abre su propia sesión porque escribe cuando la del pedido ya se rompió. `actor_label` y `target_label` se copian tal como son en ese momento en vez de resolverse con un join: una fila que se vuelve ilegible cuando se borra la cuenta que la generó no sirve, y ese es justo el caso en que se la lee. **No hay columna con el detalle del cambio**: en un cambio de credencial, lo que cambió *es* la credencial. No existe endpoint para editar ni borrar una fila; lo único que las borra es el `ON DELETE CASCADE` desde `agencies`.
- `app/ratelimit.py` — per-IP in-memory limiter used as a route dependency on public/unauthenticated endpoints (auth + portal login, widget messages); reads the client from `X-Forwarded-For` (set by the gateway); toggle with `RATE_LIMIT_ENABLED` (disabled in tests)
- `migrations/` — Alembic; schema changes require a new migration, and Docker runs `alembic upgrade head` on backend start

### WhatsApp flow

The bridge (`apps/whatsapp/src/manager.ts`) holds live Baileys sessions and is stateful — encrypted session/auth state lives in PostgreSQL (via the backend), and the bridge reloads enabled sessions on startup. Incoming messages: bridge → `POST /api/whatsapp/channels/{channel_id}/inbound` on the backend → AI reply sent back through the bridge. Replies are debounced (`REPLY_DEBOUNCE_SECONDS`, default 8s): the shared pipeline in `app/services/whatsapp_inbound.py` waits for a quiet window that restarts on each new visitor message, then answers the whole burst with one reply delivered via `send_channel_message()`; with the window at 0 the reply returns synchronously in the inbound response instead. Backend↔bridge calls authenticate with `WHATSAPP_BRIDGE_TOKEN`. Conversations have a `mode` field: switching to `"human"` pauses the AI so an operator answers from the portal.

### Frontend

`apps/web/lib/api.ts` is the single fetch wrapper (cookie auth, `NEXT_PUBLIC_API_URL`); `apps/web/lib/providers.ts` holds per-provider model presets. `apps/web/AGENTS.md` warns that Next.js 16 has breaking changes vs. training data — check `node_modules/next/dist/docs/` before writing non-trivial Next.js code.

## Environment gotchas

- `ENCRYPTION_KEY` must never change after secrets are stored — it decrypts AI API keys and WhatsApp sessions.
- The app is served single-origin through a Caddy gateway (`docker/Caddyfile`): `/api/*` → backend, everything else → frontend. The browser uses relative `/api` (`lib/api.ts` falls back to `""`), so `NEXT_PUBLIC_API_URL` is empty by default and only set to point the frontend at an API on a separate origin (baked at build time — rebuild the web image to change it).
- TLS is operator-provided: put your own reverse proxy in front of the gateway port; the stack itself only serves plain HTTP. No bundled TLS/`make deploy`.
- Custom per-client portal domains are opt-in: mount `docker/Caddyfile.ondemand` (on-demand TLS gated by `/api/public/portal-domain`) via a compose override; `apps/web/proxy.ts` (Next.js 16 renamed `middleware`→`proxy`) rewrites a verified custom host to `/portal/[slug]`. `BACKEND_INTERNAL_URL` lets the web container reach the API server-side.
- Ports: gateway `WEB_PORT` (default 3000, the app), backend 8000 (OpenAPI docs at `/docs`, exposed locally for tooling), bridge 3101 (not exposed in Docker).
