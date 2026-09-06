"use client";

import { createContext, useCallback, useContext, useEffect, useRef, useState, type ReactNode } from "react";
import { AlertTriangle } from "lucide-react";
import { useT } from "@/lib/i18n";

export type ConfirmRequest = {
  /** La pregunta. Corta, y que se entienda sola. */
  title: string;
  /** Qué va a pasar exactamente. Opcional cuando el título ya lo dice. */
  body?: string;
  /**
   * La advertencia destacada. Se pone SOLO cuando de verdad no se puede
   * deshacer: escribirla en una acción reversible enseña a ignorarla, y
   * entonces deja de servir justo donde hace falta.
   */
  consequence?: string;
  confirmLabel: string;
  tone?: "danger" | "default";
};

type ConfirmFn = (request: ConfirmRequest) => Promise<boolean>;

const ConfirmContext = createContext<ConfirmFn | null>(null);

type Pending = { request: ConfirmRequest; resolve: (answer: boolean) => void };

export function ConfirmProvider({ children }: { children: ReactNode }) {
  const t = useT();
  const [pending, setPending] = useState<Pending | null>(null);
  // El botón de cancelar arranca con el foco, igual que hace el diálogo del
  // navegador: en algo que borra, la tecla Enter no puede ser la que borra.
  const cancelRef = useRef<HTMLButtonElement>(null);

  const confirm = useCallback<ConfirmFn>(
    (request) => new Promise<boolean>((resolve) => setPending({ request, resolve })),
    [],
  );

  const answer = useCallback((value: boolean) => {
    setPending((current) => {
      current?.resolve(value);
      return null;
    });
  }, []);

  useEffect(() => {
    if (!pending) return;
    cancelRef.current?.focus();
    const onKey = (event: KeyboardEvent) => {
      if (event.key === "Escape") answer(false);
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [pending, answer]);

  return (
    <ConfirmContext.Provider value={confirm}>
      {children}
      {pending && (
        <div className="modal-backdrop" onMouseDown={() => answer(false)}>
          <section
            className="modal confirm-modal"
            role="alertdialog"
            aria-modal="true"
            aria-label={pending.request.title}
            onMouseDown={(event) => event.stopPropagation()}
          >
            <div className="modal-head">
              <div>
                <h2>{pending.request.title}</h2>
                {pending.request.body && <p>{pending.request.body}</p>}
              </div>
            </div>
            <div className="confirm-body">
              {pending.request.consequence && (
                <p className="confirm-consequence">
                  <AlertTriangle size={16} aria-hidden />
                  <span>{pending.request.consequence}</span>
                </p>
              )}
              <div className="modal-actions">
                <button type="button" ref={cancelRef} className="button secondary" onClick={() => answer(false)}>
                  {t("common.cancel")}
                </button>
                <button
                  type="button"
                  className={`button ${pending.request.tone === "danger" ? "danger" : "primary"}`}
                  onClick={() => answer(true)}
                >
                  {pending.request.confirmLabel}
                </button>
              </div>
            </div>
          </section>
        </div>
      )}
    </ConfirmContext.Provider>
  );
}

/**
 * Reemplaza a `window.confirm`. Devuelve una promesa, así el sitio que llama
 * queda casi igual que antes: `if (!(await confirm({...}))) return;`
 */
export function useConfirm(): ConfirmFn {
  const ctx = useContext(ConfirmContext);
  if (!ctx) throw new Error("useConfirm must be used within a ConfirmProvider");
  return ctx;
}
