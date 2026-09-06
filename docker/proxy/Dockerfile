# El gateway, sin root.
#
# `api`, `web` y `whatsapp` ya traen su propio usuario desde su Dockerfile. El
# proxy era el único que quedaba como root, y no porque hiciera falta: la imagen
# oficial de Caddy no define usuario y Docker cae en root.
#
# Correr sin root obliga a escuchar en un puerto no privilegiado, porque un
# proceso sin root no puede abrir el 80. Por eso el Caddyfile escucha en 8080 y
# la parte privilegiada la hace el mapeo de puertos de compose, que corre en el
# host —donde el demonio ya es root— y no acá adentro.
#
# `/data` y `/config` se crean y se ceden acá y no en un volumen: un volumen con
# nombre recién creado hereda el dueño del directorio de la imagen, así que si no
# se cede en este punto, Caddy arranca sin poder escribir su autoguardado de
# configuración y se cae.
FROM caddy:2-alpine

RUN addgroup -S gateway \
    && adduser -S -G gateway gateway \
    && mkdir -p /data /config \
    && chown -R gateway:gateway /data /config

USER gateway

EXPOSE 8080
