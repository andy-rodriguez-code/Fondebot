import { describe, expect, it } from "vitest";
import { columnOf, isUnclaimed, moveFor, targetsFor } from "./board";
import type { Conversation } from "@/types";

const ME = "11111111-1111-1111-1111-111111111111";
const SOMEONE_ELSE = "22222222-2222-2222-2222-222222222222";

function conversation(overrides: Partial<Conversation> = {}): Conversation {
  return {
    id: "c1",
    client_id: "cl1",
    agent_id: "a1",
    title: "Caso",
    mode: "ai",
    status: "open",
    channel: "whatsapp_cloud",
    external_chat_id: "5730011",
    contact_name: "Ana",
    created_at: "2026-01-01T00:00:00Z",
    updated_at: "2026-01-01T00:00:00Z",
    ...overrides,
  } as Conversation;
}

describe("columnOf", () => {
  it("manda a Terminadas todo lo resuelto, sin mirar el modo", () => {
    expect(columnOf(conversation({ status: "resolved", mode: "human" }))).toBe("done");
    expect(columnOf(conversation({ status: "resolved", mode: "ai" }))).toBe("done");
  });

  it("separa lo abierto entre la IA y las personas", () => {
    expect(columnOf(conversation({ mode: "ai" }))).toBe("ai");
    expect(columnOf(conversation({ mode: "human", assignee_id: ME }))).toBe("active");
  });
});

describe("nada sale de Terminadas", () => {
  // La regla que más importa: set_status a "open" levanta ConversationClosed,
  // así que ofrecer ese movimiento sería prometer un 409. Solo el contacto
  // reabre un caso, escribiendo de nuevo.
  const done = conversation({ status: "resolved", mode: "human", assignee_id: ME });

  it("no ofrece ningún destino", () => {
    expect(targetsFor(done, ME)).toEqual([]);
  });

  it("devuelve null para cada columna, una por una", () => {
    expect(moveFor(done, "ai", ME)).toBeNull();
    expect(moveFor(done, "active", ME)).toBeNull();
    expect(moveFor(done, "done", ME)).toBeNull();
  });
});

describe("moveFor", () => {
  it("tomar una de la IA cambia el modo, que ya la asigna a quien pide", () => {
    expect(moveFor(conversation({ mode: "ai" }), "active", ME)).toEqual({
      endpoint: "mode",
      body: { mode: "human" },
    });
  });

  it("devolverla a la IA cambia el modo", () => {
    const mine = conversation({ mode: "human", assignee_id: ME });
    expect(moveFor(mine, "ai", ME)).toEqual({ endpoint: "mode", body: { mode: "ai" } });
  });

  it("terminarla cambia el estado, venga de donde venga", () => {
    for (const row of [conversation({ mode: "ai" }), conversation({ mode: "human", assignee_id: ME })]) {
      expect(moveFor(row, "done", ME)).toEqual({ endpoint: "status", body: { status: "resolved" } });
    }
  });

  it("no ofrece mover a la columna en la que ya está", () => {
    expect(moveFor(conversation({ mode: "ai" }), "ai", ME)).toBeNull();
    expect(moveFor(conversation({ mode: "human", assignee_id: ME }), "active", ME)).toBeNull();
  });
});

describe("las que quedaron sin dueño", () => {
  // Solo llegan desde la bandeja de la agencia: el portal no puede dejar una
  // sin dueño, porque `portal_assign` responde 422 con "o es de la IA o es de
  // una persona". Existen igual, y hay que poder agarrarlas.
  const unclaimed = conversation({ mode: "human", assignee_id: null });

  it("se reconocen", () => {
    expect(isUnclaimed(unclaimed)).toBe(true);
    expect(isUnclaimed(conversation({ mode: "human", assignee_id: SOMEONE_ELSE }))).toBe(false);
    expect(isUnclaimed(conversation({ mode: "ai" }))).toBe(false);
  });

  it("se toman asignándoselas, aunque ya estén en su misma columna", () => {
    expect(moveFor(unclaimed, "active", ME)).toEqual({
      endpoint: "assignment",
      body: { assignee_id: ME },
    });
  });

  it("una sesión sin persona no puede tomarlas", () => {
    // Sesiones emitidas antes de que existieran las personas del portal.
    expect(moveFor(unclaimed, "active", null)).toBeNull();
  });

  it("una resuelta sin dueño no cuenta como libre", () => {
    expect(isUnclaimed(conversation({ status: "resolved", mode: "human", assignee_id: null }))).toBe(false);
  });
});

describe("la de otra persona", () => {
  it("se puede tomar cambiando de dueño", () => {
    const theirs = conversation({ mode: "human", assignee_id: SOMEONE_ELSE });
    // Ya está en "En curso" y tiene dueño, así que el tablero no la mueve de
    // columna: reasignarla es una acción explícita, no un arrastre.
    expect(moveFor(theirs, "active", ME)).toBeNull();
    expect(moveFor(theirs, "done", ME)).toEqual({ endpoint: "status", body: { status: "resolved" } });
  });
});
