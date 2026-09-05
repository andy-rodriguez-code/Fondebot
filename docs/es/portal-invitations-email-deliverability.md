# Entregabilidad de los mails de invitación (SPF, DKIM, DMARC)

> Read in English: [portal-invitations-email-deliverability.md](../en/portal-invitations-email-deliverability.md)

Cuando invitas a alguien a un portal (ver [Portal del cliente y dominios](client-portal.md)) con `EMAIL_PROVIDER=none` (el valor por defecto), OpenLivery no manda nada: crea la invitación igual y te devuelve el link para que lo reenvíes vos mismo. Esta página es para cuando activas `EMAIL_PROVIDER=smtp` y OpenLivery empieza a mandar ese mail por su cuenta.

## Por qué esto importa

Un servidor de correo que recibe un mail no confía en el campo `From:` a ciegas: le pregunta al DNS del dominio remitente si el servidor que lo entregó tenía permiso para hacerlo, y si el cuerpo fue alterado en el camino. Un remitente sin esas respuestas en el DNS **no rebota** — casi siempre se entrega igual, pero a la carpeta de spam, o directamente se descarta en silencio. Es la falla más difícil de detectar: la invitación "se mandó" (no hubo excepción, `delivered_at` queda seteado) y la persona invitada nunca la ve.

Tres registros DNS, en el dominio que pongas en `SMTP_FROM`, resuelven esto:

- **SPF** (`Sender Policy Framework`) — lista qué servidores tienen permiso para mandar en nombre de tu dominio.
- **DKIM** (`DomainKeys Identified Mail`) — el servidor de salida firma el mail con una clave privada; quien lo recibe verifica la firma contra una clave pública publicada en el DNS. Prueba que el cuerpo no fue alterado y que salió de donde dice que salió.
- **DMARC** (`Domain-based Message Authentication, Reporting and Conformance`) — le dice al que recibe qué hacer cuando SPF o DKIM fallan (nada, ponerlo en spam, o rechazarlo), y a quién mandarle un reporte cuando eso pasa.

Sin los tres, la mayoría de los proveedores grandes (Gmail, Outlook, Yahoo) tratan el mail como sospechoso por default — no es una configuración opcional para "mejorar" la entrega, es lo mínimo para que no termine descartado.

## La respuesta corta: usá un relay autenticado

La forma práctica de resolver esto en una instalación autoalojada **no es** configurar SPF/DKIM/DMARC a mano para un dominio propio: es mandar el correo a través de un proveedor de correo transaccional (Postmark, SendGrid, Amazon SES, Mailgun, o el SMTP de tu propio proveedor de hosting) que ya tiene su infraestructura de salida correctamente autenticada, y simplemente sumás tu dominio como remitente verificado ahí. La mayoría de estos proveedores te da:

1. Un host/usuario/contraseña SMTP para poner en `SMTP_HOST` / `SMTP_USERNAME` / `SMTP_PASSWORD`.
2. Uno o dos registros DNS (`CNAME` o `TXT`) para verificar que sos dueño del dominio en `SMTP_FROM`, que el proveedor gestiona y rota por vos.

Con eso, DKIM y SPF quedan resueltos por el proveedor; DMARC lo agregás vos una sola vez (ver abajo) porque es una política sobre *tu* dominio, no algo que un proveedor de correo pueda declarar en tu nombre.

## Si preferís mandar directo desde tu propio dominio

Si en cambio tenés tu propio servidor SMTP saliente (por ejemplo Postfix en el mismo servidor, o un relay interno de tu organización) y no vas a usar un proveedor transaccional, necesitás los tres registros en el dominio de `SMTP_FROM`:

### SPF

Un registro `TXT` en la raíz del dominio (`example.com`, no un subdominio), que autoriza las IPs o el host que van a mandar:

```
example.com.  TXT  "v=spf1 ip4:203.0.113.10 include:_spf.tu-proveedor.com -all"
```

- `ip4:` / `ip6:` para IPs propias; `include:` cuando el que manda es un proveedor tercero (cada proveedor publica el suyo).
- `-all` al final rechaza duro lo que no está en la lista. `~all` ("softfail") es más permisivo mientras estás probando, pero no lo dejes así en producción: es la diferencia entre "rechazado" y "aceptado pero sospechoso".
- Solo puede haber **un** registro SPF por dominio — si ya tenés uno (por ejemplo para otro servicio de correo), sumá tu fuente al mismo registro en vez de crear uno nuevo.

### DKIM

Requiere que tu MTA (Postfix + OpenDKIM, o lo que uses) firme cada mensaje con una clave privada, y que publiques la clave pública correspondiente:

```
selector._domainkey.example.com.  TXT  "v=DKIM1; k=rsa; p=<clave-pública-base64>"
```

`selector` es un nombre que elegís vos (tu MTA lo define al generar el par de claves); puede haber varios selectores activos a la vez, lo que permite rotar la clave sin cortar el envío. Configurar la firma DKIM en el propio MTA está fuera del alcance de esta guía porque depende del software elegido — la documentación de OpenDKIM (o la de tu proveedor de hosting) tiene el paso a paso.

### DMARC

Un registro `TXT` en `_dmarc.example.com` que declara la política y dónde mandar los reportes de fallos:

```
_dmarc.example.com.  TXT  "v=DMARC1; p=quarantine; rua=mailto:dmarc-reports@example.com"
```

- `p=none` — solo observar y recibir reportes, sin afectar la entrega. Es el punto de partida razonable mientras confirmás que SPF/DKIM están bien.
- `p=quarantine` — lo que falla va a spam. Es el destino recomendado para producción.
- `p=reject` — lo que falla se rechaza directamente. Solo una vez que estés seguro de que ningún mail legítimo está fallando.
- `rua=mailto:...` es opcional pero recomendado: sin reportes, no hay forma de saber si SPF/DKIM están fallando hasta que alguien te avise que nunca le llegó la invitación.

## Verificar

Antes de confiar en la configuración, mandate una invitación de prueba a una cuenta de Gmail u Outlook y mirá los encabezados del mail recibido ("Ver original" / "Mostrar código fuente" en el cliente de correo): tienen que aparecer `spf=pass`, `dkim=pass` y `dmarc=pass`. Herramientas como `dig txt example.com` / `dig txt _dmarc.example.com`, o un verificador SPF/DKIM/DMARC online, confirman que los registros DNS se ven como se espera antes incluso de mandar un mail real.
