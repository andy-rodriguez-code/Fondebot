"use client";

import { FormEvent, Suspense, useEffect, useState } from "react";
import { useParams, useRouter, useSearchParams } from "next/navigation";
import { LoaderCircle, ShieldCheck } from "lucide-react";
import { Alert } from "@/components/ui";
import { api, messageFrom } from "@/lib/api";
import { acceptInvitation } from "@/lib/invitations";
import { useT } from "@/lib/i18n";
import type { PortalPublic } from "@/types";

// `useSearchParams` needs a Suspense boundary around it in the App Router.
export default function InvitationAcceptPage() {
  return (
    <Suspense fallback={<div className="portal-loader"><LoaderCircle className="spin" /></div>}>
      <InvitationAcceptForm />
    </Suspense>
  );
}

// No preflight GET on the token here on purpose (design D4): a
// token-validating request would re-open the same enumeration oracle the
// accept endpoint's identical failure body closes. This screen only reads
// the already-public `/portal/{slug}` (client name/branding) and posts the
// token blind, exactly once, when the person submits a password.
function InvitationAcceptForm() {
  const t = useT();
  const router = useRouter();
  const { slug } = useParams<{ slug: string }>();
  const token = useSearchParams().get("token") ?? "";
  const [portal, setPortal] = useState<PortalPublic | null>(null);
  const [loading, setLoading] = useState(true);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");

  useEffect(() => {
    api<PortalPublic>(`/portal/${slug}`)
      .then(setPortal)
      .catch(() => setPortal(null))
      .finally(() => setLoading(false));
  }, [slug]);

  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!token) return;
    setBusy(true);
    setError("");
    const data = new FormData(event.currentTarget);
    try {
      await acceptInvitation(slug, { token, password: String(data.get("password") ?? "") });
      // The token-bearing URL leaves the address bar and the back stack.
      router.replace(`/portal/${slug}`);
    } catch (err) {
      setError(messageFrom(err));
    } finally {
      setBusy(false);
    }
  }

  if (loading) return <div className="portal-loader"><LoaderCircle className="spin" /> {t("portal.loader.loading")}</div>;
  if (!portal) return <div className="portal-loader">{t("portal.loader.unavailable")}</div>;

  return (
    <main className="access-page portal-access" style={{ "--portal-color": portal.agency_brand_color } as React.CSSProperties}>
      <header className="access-topbar">
        <div className="access-brand portal-access-brand">
          {portal.agency_logo_url ? <img src={portal.agency_logo_url} alt={portal.agency_name} /> : <span>{portal.agency_name.slice(0, 1)}</span>}
          <strong>{portal.agency_name}</strong>
        </div>
        <small>{t("portal.access.secureBadge")}</small>
      </header>
      <div className="access-layout">
        <section className="access-form-wrap">
          <form className="access-card access-form" onSubmit={submit}>
            <span className="portal-client-avatar">{portal.client_name.slice(0, 2).toUpperCase()}</span>
            <span className="access-card-label"><ShieldCheck size={15} /> {t("portal.invite.cardLabel")}</span>
            <h2>{t("portal.invite.welcome", { name: portal.client_name })}</h2>
            <p>{t("portal.invite.subtitle")}</p>
            <label>
              {t("portal.invite.passwordLabel")}
              <input
                name="password"
                type="password"
                required
                autoFocus
                minLength={8}
                // 72 and not 128: bcrypt refuses anything longer than 72
                // bytes. The browser can only count characters, so the server
                // still validates the byte length.
                maxLength={72}
                placeholder={t("portal.invite.passwordPlaceholder")}
              />
            </label>
            {!token && <Alert>{t("portal.invite.missingToken")}</Alert>}
            {error && <Alert>{error}</Alert>}
            <button className="button primary full" disabled={busy || !token}>
              {busy ? <LoaderCircle className="spin" size={17} /> : t("portal.invite.submit")}
            </button>
          </form>
        </section>
      </div>
    </main>
  );
}
