# Configuración

> Read in English: [configuration.md](../en/configuration.md)

OpenLivery se configura mediante variables de entorno. En Docker, todas viven en un único archivo `.env.docker` en la raíz del repositorio; un script auxiliar lo genera con secretos aleatorios robustos para que nunca tengas que inventarlos.

## El archivo .env.docker

Ejecuta el generador una vez por clon:

```bash
./scripts/generate-docker-env.sh   # crea .env.docker y se niega a sobrescribir uno existente
```

Crea el archivo con permisos restrictivos (`umask 077`) y rellena los valores sensibles con `openssl rand`: una contraseña de Postgres, `SECRET_KEY`, `ENCRYPTION_KEY` y `WHATSAPP_BRIDGE_TOKEN`. Compose lee este archivo (`docker compose --env-file .env.docker`, que `make` hace por ti). El archivo está en gitignore: mantenlo fuera del control de versiones y guárdalo en un lugar seguro.

Para una instalación local sin Docker, las mismas variables van en un `.env` en la raíz del repositorio o en `apps/api/.env`; consulta `.env.example`.

## Variables principales

| Variable | Propósito | Valor por defecto |
| --- | --- | --- |
| `DATABASE_URL` | Cadena de conexión de SQLAlchemy. En Docker se arma a partir de `POSTGRES_USER` / `POSTGRES_PASSWORD` / `POSTGRES_DB` apuntando al servicio `db` | Postgres local |
| `SECRET_KEY` | Firma los tokens de sesión JWT. Rotarla cierra la sesión de todos | placeholder de desarrollo |
| `ENCRYPTION_KEY` | Cifra las claves de API de IA y el estado de sesión de WhatsApp antes de guardarlos en la base de datos | placeholder de desarrollo |
| `ACCESS_TOKEN_MINUTES` | Duración de la sesión | `10080` (7 días) |
| `COOKIE_SECURE` | Enviar la cookie de sesión solo por HTTPS. Ponla en `true` en producción | `false` |
| `COOKIE_SAMESITE` | Política SameSite de la cookie. Usa `none` cuando el frontend y la API están en sitios distintos (requiere `COOKIE_SECURE=true`) | `lax` |
| `RATE_LIMIT_ENABLED` | Límite de peticiones por IP en endpoints públicos (auth, login del portal, widget) | `true` |
| `FRONTEND_URL` | La URL publica del deployment. Ademas de CORS, arma el enlace para aceptar una invitacion y la URL del webhook que se pega en Meta, asi que tiene que ser alcanzable desde afuera. Cambiala junto con `WEB_PORT` | `http://localhost:3000` |
| `WHATSAPP_BRIDGE_TOKEN` | Secreto compartido que autentica las llamadas entre backend ↔ puente de WhatsApp. Usa el mismo valor en ambos | aleatorio |
| `NEXT_PUBLIC_API_URL` | Origen público de la API incrustado en el frontend en tiempo de compilación. Déjalo vacío para usar el mismo origen a través del gateway | vacío |
| `BACKEND_INTERNAL_URL` | Cómo alcanza el contenedor web a la API desde el servidor (usado por `proxy.ts` para dominios de portal personalizados) | `http://api:8000` |

### La advertencia sobre ENCRYPTION_KEY

`ENCRYPTION_KEY` **nunca** debe cambiar una vez que se han almacenado secretos. Deriva la clave que descifra cada clave de API de IA guardada y cada sesión de WhatsApp. Si la rotas o la pierdes, esos secretos quedan irrecuperables: tendrás que volver a introducir las claves de API y a vincular los números de WhatsApp. Trátala como permanente durante toda la vida de tu base de datos.

## Puertos del host

Compose enlaza cada servicio a un puerto del host, todos sobrescribibles. Pásalos en línea a `make up`:

```bash
API_PORT=8001 WEB_PORT=3001 DB_PORT=5433 make up
```

| Variable | Qué controla | Valor por defecto |
| --- | --- | --- |
| `WEB_PORT` | El puerto del gateway: esta es la app | `3000` |
| `API_PORT` | Backend, expuesto localmente para la documentación OpenAPI y herramientas | `8000` |
| `DB_PORT` | PostgreSQL | `5432` |
| `BIND_HOST` | Interfaz a la que enlazar: `127.0.0.1` solo local, `0.0.0.0` para exponer en un servidor | `127.0.0.1` |

El puente de WhatsApp escucha en `3101` pero no se publica al host en Docker.

## El gateway de origen único

Un contenedor Caddy (`docker/Caddyfile`) sirve toda la pila en un único origen. Enruta `/api/*` al backend y todo lo demás al frontend, de modo que el navegador habla con un solo puerto y `NEXT_PUBLIC_API_URL` puede quedar vacío. La pila sirve solo HTTP plano: coloca tu propio reverse proxy delante del gateway para TLS en producción. Consulta [Autoalojamiento](self-hosting.md) para un despliegue público.

## Límites de recursos

Cada contenedor tiene un techo de memoria y de CPU, para que un servicio
desbocado no se lleve puesta la máquina entera. Son límites, no reservas: no se
aparta nada, y solo se sienten bajo presión real.

Se suben desde `.env.docker`, sin editar `docker-compose.yml`. Si un contenedor
muere con código 137, tocó su techo de memoria: ese es el número a subir, y la
API es la que hay que mirar cuando una base de conocimiento crece.

| Variable | Servicio | Por defecto |
| --- | --- | --- |
| `DB_MEMORY_LIMIT` / `DB_CPU_LIMIT` | PostgreSQL | `1g` / `1.0` |
| `API_MEMORY_LIMIT` / `API_CPU_LIMIT` | Backend | `1g` / `2.0` |
| `WEB_MEMORY_LIMIT` / `WEB_CPU_LIMIT` | Frontend | `512m` / `1.0` |
| `WHATSAPP_MEMORY_LIMIT` / `WHATSAPP_CPU_LIMIT` | Puente de WhatsApp | `512m` / `1.0` |
| `PROXY_MEMORY_LIMIT` / `PROXY_CPU_LIMIT` | Gateway | `128m` / `0.5` |

Además, los cinco contenedores corren con `no-new-privileges`, y ninguno corre
como root: `api`, `web` y `whatsapp` traen su propio usuario, el gateway corre
como `gateway` escuchando en 8080, y PostgreSQL baja al suyo en el arranque. La
única excepción es el gateway con dominios propios, y está explicada en
`self-hosting.md`.

## Registro de agencias

Por defecto el registro se cierra solo: en cuanto existe una agencia,
`POST /api/auth/register` responde 403 para cualquiera. La primera persona que
llega configura la instancia y nadie más puede crear una cuenta desde afuera.

| Variable | Qué hace | Por defecto |
| --- | --- | --- |
| `ALLOW_MULTI_AGENCY` | Deja el registro abierto para siempre, para alojar varias agencias en un mismo deployment | `false` |

Antes de encenderlo conviene saber qué abre, porque son dos cosas y la segunda
suele pasar desapercibida:

- **Cualquiera con la URL puede crear una agencia.** No hay invitación ni código
  de alta. Si la instancia mira a internet, poné tu propia puerta adelante.
- **El registro pasa a distinguir direcciones.** Con el registro cerrado, una
  dirección que ya tiene cuenta y una que no reciben la misma respuesta; con el
  registro abierto, una dirección ya registrada devuelve 409 y eso se puede usar
  para averiguar quién tiene cuenta acá. El límite de tasa de la ruta —10
  intentos por minuto y por IP— es lo que le pone precio a probar.

Con el valor por defecto ninguna de las dos aplica.
