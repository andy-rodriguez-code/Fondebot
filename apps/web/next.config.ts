import type { NextConfig } from "next";

// Cabeceras de seguridad para todo lo que sirve Next. Van acá y no en el
// Caddyfile porque el gateway se reemplaza: la guía de auto-hospedaje dice que
// el operador pone su propio reverse proxy adelante, así que una cabecera
// puesta solo en Caddy desaparece en cuanto alguien cambia de proxy. Puesta en
// la app, viaja con la app.
const BASE_HEADERS = [
  { key: "X-Content-Type-Options", value: "nosniff" },
  { key: "Referrer-Policy", value: "strict-origin-when-cross-origin" },
];

// frame-ancestors 'self' y no X-Frame-Options: la cabecera vieja no acepta una
// lista y los navegadores actuales le dan prioridad a la CSP.
const FRAME_ANCESTORS = { key: "Content-Security-Policy", value: "frame-ancestors 'self'" };

// HSTS solo cuando el operador ya termina TLS adelante. Por HTTP simple no hace
// nada, pero mandarla desde un deployment que todavía no tiene certificado deja
// el dominio inalcanzable para quien ya la haya cacheado.
const HSTS = { key: "Strict-Transport-Security", value: "max-age=31536000; includeSubDomains" };

// `Cache-Control` NO va acá, aunque sea el lugar donde uno lo buscaría: Next
// pisa esa cabecera para las páginas al construir en producción, así que una
// regla puesta acá queda escrita, se ve razonable y no hace nada. Se comprobó:
// con la regla puesta, /clients seguía respondiendo `s-maxage=31536000`.
// El no-store de las pantallas con sesión vive en proxy.ts.

const nextConfig: NextConfig = {
  reactStrictMode: true,
  output: "standalone",
  outputFileTracingRoot: process.cwd(),
  async headers() {
    const shared = process.env.ENABLE_HSTS === "true" ? [...BASE_HEADERS, HSTS] : BASE_HEADERS;
    return [
      {
        // El panel y el portal: nada de embeberlos, y ningún permiso de
        // dispositivo, porque ninguna de sus pantallas pide uno.
        source: "/((?!widget).*)",
        headers: [
          ...shared,
          FRAME_ANCESTORS,
          { key: "Permissions-Policy", value: "camera=(), microphone=(), geolocation=()" },
        ],
      },
      {
        // El widget existe para ser embebido en sitios de terceros, así que no
        // lleva frame-ancestors. Y conserva el micrófono: manda notas de voz
        // (mirá el `allow` del iframe en public/widget.js). Cámara y ubicación
        // sí se cierran — no las usa.
        source: "/widget/:path*",
        headers: [...shared, { key: "Permissions-Policy", value: "camera=(), geolocation=()" }],
      },
    ];
  },
};

export default nextConfig;
