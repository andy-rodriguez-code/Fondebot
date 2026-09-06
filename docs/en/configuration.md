# Configuration

> Leer en español: [configuration.md](../es/configuration.md)

OpenLivery is configured through environment variables. In Docker, they all live in a single `.env.docker` file at the repository root; a helper script generates it with strong random secrets so you never have to invent them yourself.

## The .env.docker file

Run the generator once per clone:

```bash
./scripts/generate-docker-env.sh   # writes .env.docker, refuses to overwrite an existing one
```

It creates the file with restrictive permissions (`umask 077`) and fills the sensitive values with `openssl rand`: a Postgres password, `SECRET_KEY`, `ENCRYPTION_KEY` and `WHATSAPP_BRIDGE_TOKEN`. Compose reads this file (`docker compose --env-file .env.docker`, which `make` does for you). The file is gitignored — keep it out of version control and back it up somewhere safe.

For a non-Docker local setup, the same variables go in a `.env` at the repo root or in `apps/api/.env`; see `.env.example`.

## Key variables

| Variable | Purpose | Default |
| --- | --- | --- |
| `DATABASE_URL` | SQLAlchemy connection string. In Docker it is assembled from `POSTGRES_USER` / `POSTGRES_PASSWORD` / `POSTGRES_DB` pointing at the `db` service | local Postgres |
| `SECRET_KEY` | Signs the JWT session tokens. Rotating it logs everyone out | dev placeholder |
| `ENCRYPTION_KEY` | Encrypts AI API keys and WhatsApp session state before they hit the database | dev placeholder |
| `ACCESS_TOKEN_MINUTES` | Session lifetime | `10080` (7 days) |
| `COOKIE_SECURE` | Send the session cookie only over HTTPS. Set `true` in production | `false` |
| `COOKIE_SAMESITE` | Cookie SameSite policy. Use `none` when the frontend and API are on different sites (requires `COOKIE_SECURE=true`) | `lax` |
| `RATE_LIMIT_ENABLED` | Per-IP rate limiting on public endpoints (auth, portal login, widget) | `true` |
| `FRONTEND_URL` | The public URL of this deployment. Besides CORS it builds the invitation accept link and the webhook URL you paste into Meta, so it has to be reachable from outside. Change it together with `WEB_PORT` | `http://localhost:3000` |
| `WHATSAPP_BRIDGE_TOKEN` | Shared secret authenticating backend ↔ WhatsApp bridge calls. Use the same value on both | random |
| `NEXT_PUBLIC_API_URL` | Public API origin baked into the frontend at build time. Leave empty to use the same origin via the gateway | empty |
| `BACKEND_INTERNAL_URL` | How the web container reaches the API server-side (used by `proxy.ts` for custom portal domains) | `http://api:8000` |

### The ENCRYPTION_KEY warning

`ENCRYPTION_KEY` must **never** change once secrets have been stored. It derives the key that decrypts every saved AI API key and WhatsApp session. If you rotate or lose it, those secrets become unrecoverable — you will have to re-enter API keys and re-link WhatsApp numbers. Treat it as permanent for the lifetime of your database.

## Host ports

Compose binds each service to a host port, all overridable. Pass them inline to `make up`:

```bash
API_PORT=8001 WEB_PORT=3001 DB_PORT=5433 make up
```

| Variable | What it controls | Default |
| --- | --- | --- |
| `WEB_PORT` | The gateway port — this is the app | `3000` |
| `API_PORT` | Backend, exposed locally for OpenAPI docs and tooling | `8000` |
| `DB_PORT` | PostgreSQL | `5432` |
| `BIND_HOST` | Interface to bind to: `127.0.0.1` for local only, `0.0.0.0` to expose on a server | `127.0.0.1` |

The WhatsApp bridge listens on `3101` but is not published to the host in Docker.

## The single-origin gateway

A Caddy container (`docker/Caddyfile`) fronts the whole stack on one origin. It routes `/api/*` to the backend and everything else to the frontend, so the browser talks to a single port and `NEXT_PUBLIC_API_URL` can stay empty. The stack serves plain HTTP only — put your own reverse proxy in front of the gateway for TLS in production. See [Self-hosting](self-hosting.md) for a public deployment.

## Resource limits

Every container has a memory and CPU ceiling, so one runaway service cannot take
the whole host down with it. These are limits, not reservations: nothing is held
aside, and a container only feels them under real pressure.

Raise them from `.env.docker` rather than editing `docker-compose.yml`. If a
container dies with exit code 137, it hit its memory ceiling — that is the number
to raise, and the API is the one to watch when a knowledge base grows.

| Variable | Service | Default |
| --- | --- | --- |
| `DB_MEMORY_LIMIT` / `DB_CPU_LIMIT` | PostgreSQL | `1g` / `1.0` |
| `API_MEMORY_LIMIT` / `API_CPU_LIMIT` | Backend | `1g` / `2.0` |
| `WEB_MEMORY_LIMIT` / `WEB_CPU_LIMIT` | Frontend | `512m` / `1.0` |
| `WHATSAPP_MEMORY_LIMIT` / `WHATSAPP_CPU_LIMIT` | WhatsApp bridge | `512m` / `1.0` |
| `PROXY_MEMORY_LIMIT` / `PROXY_CPU_LIMIT` | Gateway | `128m` / `0.5` |

All five containers also run with `no-new-privileges`, and none runs as root:
`api`, `web` and `whatsapp` carry their own user, the gateway runs as `gateway`
listening on 8080, and PostgreSQL drops to its own user at startup. The one
exception is the gateway under custom domains, explained in `self-hosting.md`.

## Agency registration

Registration closes itself by default: once one agency exists,
`POST /api/auth/register` answers 403 to everyone. The first person to arrive
sets the instance up and nobody else can create an account from outside.

| Variable | What it does | Default |
| --- | --- | --- |
| `ALLOW_MULTI_AGENCY` | Leaves registration open permanently, to host several agencies on one deployment | `false` |

Two things open when you turn it on, and the second one is easy to miss:

- **Anyone with the URL can create an agency.** There is no invitation and no
  signup code. If the instance faces the internet, put your own gate in front.
- **Registration starts telling addresses apart.** With registration closed, an
  address that already has an account and one that does not get the same answer;
  with it open, an already-registered address returns 409, which can be used to
  find out who has an account here. The route's rate limit — 10 attempts per
  minute per IP — is what puts a price on probing.

Neither applies at the default value.

## Attachment retention

`message_attachments` is the only table that grows without a ceiling as the
product is used: every image and every voice note a contact sends is stored in
full. Logos are one per agency, and PDFs are uploaded by an administrator on
purpose; this is neither.

| Variable | What it does | Default |
| --- | --- | --- |
| `ATTACHMENT_RETENTION_DAYS` | How many days image and voice-note binaries are kept. `0` deletes nothing | `0` |

**It ships off on purpose.** Upgrading the application must never start deleting
data for someone who did not ask for it. Turning it on needs no restart: the
sweep runs anyway and picks the new value up on its next pass, every six hours.

The file goes, the conversation stays: the message keeps its text and its
transcription, so the case still reads end to end. Only the original file is
missing afterwards.

## Logs

Every request gets an identifier that appears on every line that request
produces — uvicorn's access lines included — and comes back in the response's
`X-Request-Id` header. That header is the point: whoever reports a problem can
quote it, and it leads straight to their lines instead of everything that
happened at that hour.

| Variable | What it does | Default |
| --- | --- | --- |
| `LOG_FORMAT` | `text` reads well in `docker compose logs`; `json` is for shipping them somewhere | `text` |
| `LOG_LEVEL` | Minimum level | `INFO` |

An incoming `X-Request-Id` is honoured, so a trace that started in another
service is not cut here — but only if its shape is harmless. A header value
that ends up written to a log lets the caller insert newlines and forge entries
that never happened.

The identifier travels to the WhatsApp bridge too, so lines from both processes
can be tied together.
