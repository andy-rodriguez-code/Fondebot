import { NextResponse } from "next/server";
import type { NextRequest } from "next/server";
import { cacheControlFor } from "@/lib/cache-policy";

// Maps a client's custom domain to its portal. When a request arrives on a
// verified custom domain, it is rewritten to that client's /portal/[slug] route
// so the browser URL stays on the client's own domain. Requests on the primary
// domain resolve to nothing and pass through untouched.

const BACKEND_URL = process.env.BACKEND_INTERNAL_URL || "http://api:8000";
const CACHE_TTL_MS = 60_000;

type Resolution = { slug: string | null; expires: number };
const cache = new Map<string, Resolution>();

async function resolveSlug(host: string): Promise<string | null> {
  const cached = cache.get(host);
  if (cached && cached.expires > Date.now()) return cached.slug;
  let slug: string | null = null;
  try {
    const res = await fetch(`${BACKEND_URL}/api/public/portal-domain?domain=${encodeURIComponent(host)}`, {
      headers: { accept: "application/json" },
    });
    if (res.ok) slug = ((await res.json()) as { portal_slug?: string }).portal_slug ?? null;
  } catch {
    slug = null;
  }
  cache.set(host, { slug, expires: Date.now() + CACHE_TTL_MS });
  return slug;
}


// El no-store de las pantallas con sesión. La regla de qué se guarda vive en
// lib/cache-policy.ts, aparte, para poder probarla sin el runtime de Next.
//
// Va acá y no en next.config.ts porque Next pisa `Cache-Control` para las
// páginas al construir en producción. El `matcher` de abajo ya deja afuera
// `_next/static`, `_next/image` y todo lo que tenga extensión, así que los
// assets inmutables conservan su cacheado.
function guarded(response: NextResponse, pathname: string): NextResponse {
  const policy = cacheControlFor(pathname);
  if (policy) response.headers.set("Cache-Control", policy);
  return response;
}

export async function proxy(request: NextRequest) {
  const rawHost = request.headers.get("x-forwarded-host") || request.headers.get("host") || "";
  const host = rawHost.split(":")[0].trim().toLowerCase();
  const { pathname } = request.nextUrl;
  if (!host || host === "localhost" || host === "127.0.0.1") return guarded(NextResponse.next(), pathname);
  // Already inside a portal route (e.g. reached via the primary domain).
  if (pathname.startsWith("/portal/")) return guarded(NextResponse.next(), pathname);

  const slug = await resolveSlug(host);
  if (!slug) return guarded(NextResponse.next(), pathname);

  const url = request.nextUrl.clone();
  url.pathname = `/portal/${slug}`;
  return guarded(NextResponse.rewrite(url), pathname);
}

export const config = {
  // Run on page requests only; skip API, Next internals, the widget script and assets.
  matcher: ["/((?!api|_next/static|_next/image|favicon.ico|widget.js|.*\\.[^/]+$).*)"],
};
