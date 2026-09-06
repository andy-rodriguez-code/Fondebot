FROM python:3.12.11-slim-bookworm AS base

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PYTHONPATH=/app/backend \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PIP_NO_CACHE_DIR=1

# ffmpeg transcodes operator voice notes to ogg/opus, the only format WhatsApp
# plays as a voice message (browsers record webm/mp4).
RUN apt-get update \
    && apt-get install -y --no-install-recommends ffmpeg \
    && rm -rf /var/lib/apt/lists/*

RUN groupadd --gid 10001 openlivery \
    && useradd --uid 10001 --gid openlivery --create-home openlivery

WORKDIR /app/backend

COPY requirements.txt ./requirements.txt
COPY pyproject.toml ./pyproject.toml
RUN pip install --no-cache-dir -r requirements.txt

COPY alembic.ini ./alembic.ini
COPY migrations ./migrations
COPY app ./app

RUN mkdir -p /app/backend/storage \
    && chown -R openlivery:openlivery /app

USER openlivery

EXPOSE 8000

CMD ["sh", "-c", "alembic upgrade head && exec uvicorn app.main:app --host 0.0.0.0 --port 8000"]


# Etapa de desarrollo: agrega pytest y la suite. La construye compose
# (`target: dev`), para que `make test` pueda correr los tests dentro del
# contenedor levantado.
FROM base AS dev

USER root
COPY requirements-dev.txt ./requirements-dev.txt
RUN pip install --no-cache-dir -r requirements-dev.txt
COPY tests ./tests
RUN chown -R openlivery:openlivery /app
USER openlivery


# La imagen que se publica es exactamente `base`. Esta etapa existe solo para
# ser la ultima y, por lo tanto, la que se construye por defecto: la de
# desarrollo hay que pedirla a proposito, asi nadie publica pytest sin querer.
FROM base AS runtime
