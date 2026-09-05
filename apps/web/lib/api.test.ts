import { afterEach, describe, expect, it, vi } from "vitest";
import { ApiError, api, apiUrl, messageFrom } from "./api";

type Call = { url: string; init: RequestInit };

function stubFetch(response: Response): Call[] {
  const calls: Call[] = [];
  vi.stubGlobal("fetch", (url: string, init: RequestInit) => {
    calls.push({ url, init });
    return Promise.resolve(response);
  });
  return calls;
}

function json(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { "Content-Type": "application/json" },
  });
}

afterEach(() => {
  vi.unstubAllGlobals();
});

describe("api", () => {
  it("llama a una ruta relativa bajo /api y manda las cookies", async () => {
    const calls = stubFetch(json({ ok: true }));
    await api("/clients");
    expect(calls[0].url).toBe("/api/clients");
    expect(calls[0].init.credentials).toBe("include");
  });

  it("pone Content-Type json en un cuerpo normal", async () => {
    const calls = stubFetch(json({ ok: true }));
    await api("/clients", { method: "POST", body: JSON.stringify({ name: "Fondo" }) });
    expect((calls[0].init.headers as Record<string, string>)["Content-Type"]).toBe("application/json");
  });

  it("no pone Content-Type en un FormData", async () => {
    // The browser has to set the multipart boundary itself; forcing the header
    // here produces an upload the backend cannot parse.
    const calls = stubFetch(json({ ok: true }));
    await api("/clients/1/logo", { method: "POST", body: new FormData() });
    expect((calls[0].init.headers as Record<string, string>)["Content-Type"]).toBeUndefined();
  });

  it("convierte un detail de texto en ApiError con su status", async () => {
    stubFetch(json({ detail: "That agent does not belong to this client" }, 422));
    await expect(api("/departments")).rejects.toMatchObject({
      message: "That agent does not belong to this client",
      status: 422,
    });
  });

  it("usa el primer mensaje cuando el detail es la lista de pydantic", async () => {
    stubFetch(json({ detail: [{ msg: "field required", loc: ["body", "name"] }] }, 422));
    await expect(api("/departments")).rejects.toThrow(/field required/);
  });

  it("cae a un mensaje genérico cuando el cuerpo del error no es json", async () => {
    stubFetch(new Response("<html>502</html>", { status: 502 }));
    const error = await api("/departments").catch((err) => err);
    expect(error).toBeInstanceOf(ApiError);
    expect(error.status).toBe(502);
    expect(error.message).toBeTruthy();
  });

  it("devuelve undefined en un 204 sin intentar parsear", async () => {
    stubFetch(new Response(null, { status: 204 }));
    await expect(api("/departments/1")).resolves.toBeUndefined();
  });
});

describe("apiUrl", () => {
  it("arma la ruta absoluta que usan los src de img y audio", () => {
    expect(apiUrl("/portal/x/conversations/1/attachments/2")).toBe(
      "/api/portal/x/conversations/1/attachments/2",
    );
  });
});

describe("messageFrom", () => {
  it("usa el mensaje de un Error", () => {
    expect(messageFrom(new Error("boom"))).toBe("boom");
  });

  it("no explota con algo que no es Error", () => {
    expect(messageFrom("boom")).toBeTruthy();
  });
});
