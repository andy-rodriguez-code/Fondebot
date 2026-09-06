import type { Conversation } from "@/types";

// Las reglas del tablero, aparte de la pantalla: son lo único que puede estar
// mal de una forma que no se ve mirando. La interfaz solo dibuja lo que estas
// funciones dicen.

export type BoardColumn = "ai" | "active" | "done";

export const BOARD_COLUMNS: BoardColumn[] = ["ai", "active", "done"];

/** En qué columna cae una conversación. */
export function columnOf(conversation: Conversation): BoardColumn {
  if (conversation.status === "resolved") return "done";
  return conversation.mode === "ai" ? "ai" : "active";
}

/** Quién la tiene, cuando la tiene alguien.
 *
 * Una conversación en modo humano PUEDE no tener dueño: pasa cuando alguien la
 * tomó desde la bandeja de la agencia. Desde el portal no se puede dejar así
 * —`portal_assign` responde 422: o es de la IA o es de una persona— pero la
 * fila existe igual, y esconderla sería peor que mostrarla para agarrar.
 */
export function isUnclaimed(conversation: Conversation): boolean {
  return conversation.status !== "resolved" && conversation.mode === "human" && !conversation.assignee_id;
}

export type Move =
  | { endpoint: "mode"; body: { mode: "ai" | "human" } }
  | { endpoint: "status"; body: { status: "resolved" } }
  | { endpoint: "assignment"; body: { assignee_id: string } };

/** Qué llamada hace falta para llevar una conversación a ``target``, o null si
 * ese movimiento no existe.
 *
 * Devolver null es tan importante como devolver la llamada: la pantalla usa
 * esto para no ofrecer un destino que la API va a rechazar. Un tablero que te
 * deja soltar una tarjeta y después falla con un 409 es peor que uno que no te
 * deja agarrarla.
 */
export function moveFor(
  conversation: Conversation,
  target: BoardColumn,
  myUserId: string | null,
): Move | null {
  const from = columnOf(conversation);
  if (from === target && !(target === "active" && isUnclaimed(conversation))) return null;

  // De "Terminadas" no sale nada. `set_status` a "open" levanta
  // ConversationClosed: un caso termina y no vuelve. Lo único que la reabre es
  // que el contacto escriba de nuevo, y eso no lo decide quien atiende.
  if (from === "done") return null;

  if (target === "done") return { endpoint: "status", body: { status: "resolved" } };
  if (target === "ai") return { endpoint: "mode", body: { mode: "ai" } };

  // Hacia "En curso": tomarla. Desde la IA alcanza con cambiar el modo, que
  // ya la asigna a quien lo pide (`set_mode` con user). Una que está en modo
  // humano sin dueño se toma asignándosela.
  if (from === "ai") return { endpoint: "mode", body: { mode: "human" } };
  if (isUnclaimed(conversation) && myUserId) return { endpoint: "assignment", body: { assignee_id: myUserId } };
  return null;
}

/** Los destinos que tiene sentido ofrecer para esta tarjeta. */
export function targetsFor(conversation: Conversation, myUserId: string | null): BoardColumn[] {
  return BOARD_COLUMNS.filter((column) => moveFor(conversation, column, myUserId) !== null);
}
