import { afterEach, describe, expect, it, vi } from "vitest";
import { acceptInvitation } from "./invitations";

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

describe("acceptInvitation", () => {
  it("posts the token and password to the accept endpoint under the given slug", async () => {
    const calls = stubFetch(
      json({ client_id: "1", client_name: "Acme", portal_slug: "acme", agency_name: "Agency", user_id: "u1", user_name: "Ana" }),
    );
    const session = await acceptInvitation("acme", { token: "abc", password: "supersecret" });
    expect(calls[0].url).toBe("/api/portal/acme/invitations/accept");
    expect(JSON.parse(calls[0].init.body as string)).toEqual({ token: "abc", password: "supersecret" });
    expect(session.user_name).toBe("Ana");
  });

  it("propagates the generic 400 as an ApiError without extra parsing (Spec: Enumeration-Resistant Accept Endpoint)", async () => {
    stubFetch(json({ detail: "This invitation link is no longer valid. Ask for a new one." }, 400));
    await expect(acceptInvitation("acme", { token: "bad", password: "supersecret" })).rejects.toMatchObject({
      status: 400,
      message: "This invitation link is no longer valid. Ask for a new one.",
    });
  });
});
