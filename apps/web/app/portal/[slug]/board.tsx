"use client";

import { useCallback, useEffect, useState } from "react";
import { Bot, CheckCircle2, LoaderCircle, UserRound } from "lucide-react";
import { Alert } from "@/components/ui";
import { api, messageFrom } from "@/lib/api";
import { BOARD_COLUMNS, columnOf, isUnclaimed, moveFor, targetsFor, type BoardColumn } from "@/lib/board";
import { useT } from "@/lib/i18n";
import type { Conversation } from "@/types";

const COLUMN_LABEL: Record<BoardColumn, "portal.board.columnAi" | "portal.board.columnActive" | "portal.board.columnDone"> = {
  ai: "portal.board.columnAi",
  active: "portal.board.columnActive",
  done: "portal.board.columnDone",
};

const COLUMN_ICON: Record<BoardColumn, React.ReactNode> = {
  ai: <Bot size={15} />,
  active: <UserRound size={15} />,
  done: <CheckCircle2 size={15} />,
};

export function BoardView({
  slug,
  myUserId,
  openConversation,
}: {
  slug: string;
  myUserId: string | null;
  openConversation: (conversation: Conversation) => void;
}) {
  const t = useT();
  const [rows, setRows] = useState<Conversation[] | null>(null);
  const [error, setError] = useState("");
  const [busyId, setBusyId] = useState<string | null>(null);
  const [dragging, setDragging] = useState<string | null>(null);

  const load = useCallback(async () => {
    // Dos llamadas porque el endpoint filtra por estado: lo abierto llena las
    // dos primeras columnas, y de lo terminado alcanza con lo reciente — la
    // columna existe para ver que algo salió del tablero, no de archivo.
    const [open, done] = await Promise.all([
      api<Conversation[]>(`/portal/${slug}/conversations?status=open&limit=100`),
      api<Conversation[]>(`/portal/${slug}/conversations?status=resolved&limit=25`),
    ]);
    setRows([...open, ...done]);
  }, [slug]);

  useEffect(() => {
    load().catch((err) => setError(messageFrom(err)));
  }, [load]);

  async function move(conversation: Conversation, target: BoardColumn) {
    const step = moveFor(conversation, target, myUserId);
    if (!step) return;
    setBusyId(conversation.id);
    setError("");
    try {
      await api(`/portal/${slug}/conversations/${conversation.id}/${step.endpoint}`, {
        method: step.endpoint === "assignment" ? "POST" : "PATCH",
        body: JSON.stringify(step.body),
      });
      await load();
    } catch (err) {
      // El servidor tiene la última palabra sobre qué transición existe; si
      // rechaza una, se dice y se recarga en vez de dejar la tarjeta donde el
      // arrastre la soltó.
      setError(messageFrom(err));
      await load().catch(() => {});
    } finally {
      setBusyId(null);
    }
  }

  if (rows === null) return <div className="portal-loader"><LoaderCircle className="spin" /> {t("portal.loader.loading")}</div>;

  return (
    <div className="conversation-board">
      {error && <Alert>{error}</Alert>}
      <div className="board-columns">
        {BOARD_COLUMNS.map((column) => {
          const cards = rows.filter((row) => columnOf(row) === column);
          const dragged = rows.find((row) => row.id === dragging) ?? null;
          const accepts = dragged !== null && moveFor(dragged, column, myUserId) !== null;
          return (
            <section
              key={column}
              className={`board-column${accepts ? " accepts" : ""}`}
              onDragOver={(event) => { if (accepts) event.preventDefault(); }}
              onDrop={(event) => {
                event.preventDefault();
                if (dragged && accepts) void move(dragged, column);
                setDragging(null);
              }}
            >
              <header>
                {COLUMN_ICON[column]}
                <strong>{t(COLUMN_LABEL[column])}</strong>
                <em>{cards.length}</em>
              </header>
              {cards.length === 0 && <p className="board-empty">{t("portal.board.empty")}</p>}
              {cards.map((row) => (
                <article
                  key={row.id}
                  className={`board-card${busyId === row.id ? " busy" : ""}`}
                  draggable={targetsFor(row, myUserId).length > 0}
                  onDragStart={() => setDragging(row.id)}
                  onDragEnd={() => setDragging(null)}
                >
                  <button type="button" className="board-card-open" onClick={() => openConversation(row)}>
                    <strong>{row.title}</strong>
                    <small>{row.preview || row.contact_name || ""}</small>
                  </button>
                  <div className="board-card-meta">
                    {isUnclaimed(row) && <span className="board-tag">{t("portal.board.unclaimed")}</span>}
                    {row.assignee_name && <span className="board-owner">{row.assignee_name}</span>}
                    {row.unread_count ? <span className="board-unread">{row.unread_count}</span> : null}
                  </div>
                  {/* Los mismos movimientos que el arrastre, como botones: sin
                      esto la única forma de mover una tarjeta sería con mouse. */}
                  <div className="board-card-actions">
                    {targetsFor(row, myUserId).map((target) => (
                      <button
                        key={target}
                        type="button"
                        className="text-button"
                        disabled={busyId === row.id}
                        onClick={() => void move(row, target)}
                      >
                        {t(
                          target === "done"
                            ? "portal.board.moveDone"
                            : target === "ai"
                              ? "portal.board.moveAi"
                              : "portal.board.moveActive",
                        )}
                      </button>
                    ))}
                  </div>
                </article>
              ))}
            </section>
          );
        })}
      </div>
      <p className="field-help">{t("portal.board.doneIsFinal")}</p>
    </div>
  );
}
