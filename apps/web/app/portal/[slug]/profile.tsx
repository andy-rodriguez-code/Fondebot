"use client";

import { FormEvent, useRef, useState } from "react";
import { Camera, LoaderCircle, Trash2 } from "lucide-react";
import { api, apiUrl, messageFrom } from "@/lib/api";
import { Alert } from "@/components/ui";
import { useT } from "@/lib/i18n";

type Session = {
  user_id?: string | null;
  user_name?: string | null;
  user_email?: string | null;
  department_name?: string | null;
  avatar_url?: string | null;
};

/**
 * Lo que cada quien puede cambiar de sí: su nombre, su dirección, su clave y
 * su foto.
 *
 * La dependencia se muestra pero no se edita, y eso es a propósito: cambiarla
 * sería elegir qué conversaciones ve, y esa decisión es de quien administra.
 */
export function ProfilePanel({ slug, session, onSaved, onClose }: {
  slug: string;
  session: Session;
  onSaved: (session: Session) => void;
  onClose: () => void;
}) {
  const t = useT();
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [done, setDone] = useState("");
  const fileRef = useRef<HTMLInputElement>(null);

  async function run(work: () => Promise<Session>) {
    setBusy(true); setError(""); setDone("");
    try {
      onSaved(await work());
      setDone(t("portal.inbox.profile.saved"));
    } catch (err) { setError(messageFrom(err)); } finally { setBusy(false); }
  }

  async function save(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const data = new FormData(event.currentTarget);
    const password = String(data.get("password") || "");
    await run(() => api<Session>(`/portal/${slug}/me`, {
      method: "PATCH",
      // La clave solo viaja si se escribió una: mandarla vacía la reescribiría
      // en cada guardado sin que nadie lo pidiera.
      body: JSON.stringify({
        name: String(data.get("name") || ""),
        email: String(data.get("email") || ""),
        ...(password ? { password } : {}),
      }),
    }));
  }

  async function upload(file: File) {
    const body = new FormData();
    body.append("file", file);
    await run(() => api<Session>(`/portal/${slug}/me/avatar`, { method: "PUT", body }));
  }

  async function removePhoto() {
    await run(async () => {
      await api(`/portal/${slug}/me/avatar`, { method: "DELETE" });
      return { ...session, avatar_url: null };
    });
  }

  const initial = (session.user_name || session.user_email || "?").slice(0, 1).toUpperCase();
  return (
    <div className="modal-backdrop" onMouseDown={onClose}>
      <section className="modal" role="dialog" aria-modal="true" aria-label={t("portal.inbox.profile.title")} onMouseDown={(e) => e.stopPropagation()}>
        <div className="modal-head">
          <div>
            <h2>{t("portal.inbox.profile.title")}</h2>
            <p>{t("portal.inbox.profile.subtitle")}</p>
          </div>
        </div>
        <form className="modal-form" onSubmit={save}>
          <div className="profile-avatar-row">
            {session.avatar_url
              ? <img className="profile-avatar" src={apiUrl(session.avatar_url.replace(/^\/api/, ""))} alt="" />
              : <span className="profile-avatar empty" aria-hidden>{initial}</span>}
            <div className="profile-avatar-actions">
              <input
                ref={fileRef}
                type="file"
                accept="image/png,image/jpeg,image/webp,image/gif"
                hidden
                onChange={(event) => { const file = event.target.files?.[0]; if (file) upload(file); event.target.value = ""; }}
              />
              <button type="button" className="button secondary" disabled={busy} onClick={() => fileRef.current?.click()}>
                <Camera size={15} /> {t("portal.inbox.profile.changePhoto")}
              </button>
              {session.avatar_url && (
                <button type="button" className="text-button danger-text" disabled={busy} onClick={removePhoto}>
                  <Trash2 size={14} /> {t("portal.inbox.profile.removePhoto")}
                </button>
              )}
              {session.department_name && <span className="profile-department">{session.department_name}</span>}
            </div>
          </div>

          <label>{t("portal.inbox.profile.name")}
            <input name="name" defaultValue={session.user_name ?? ""} maxLength={160} />
          </label>
          <label>{t("portal.inbox.profile.email")}
            <input name="email" type="email" defaultValue={session.user_email ?? ""} required />
          </label>
          <label>{t("portal.inbox.profile.password")}
            <input name="password" type="password" minLength={8} placeholder={t("portal.inbox.profile.passwordHint")} />
          </label>

          {error && <Alert>{error}</Alert>}
          {done && <Alert type="success">{done}</Alert>}
          <div className="modal-actions">
            <button type="button" className="button secondary" onClick={onClose}>{t("common.cancel")}</button>
            <button className="button primary" disabled={busy}>
              {busy ? <LoaderCircle className="spin" size={16} /> : t("common.save")}
            </button>
          </div>
        </form>
      </section>
    </div>
  );
}
