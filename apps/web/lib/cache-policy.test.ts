import { describe, expect, it } from "vitest";
import { cacheControlFor, isPublicPage } from "./cache-policy";

describe("cacheControlFor", () => {
  it.each(["/", "/clients", "/agents", "/inbox", "/settings", "/login", "/portal/cooperativa-sur"])(
    "refuses to let the browser store %s",
    (pathname) => {
      // Si una de estas se pudiera guardar, volvería con la flecha atrás
      // despues de cerrar sesión, con el estado de la sesión anterior.
      expect(cacheControlFor(pathname)).toBe("no-store, must-revalidate");
    },
  );

  it("leaves the public widget alone", () => {
    // Se embebe en sitios ajenos y no tiene sesión que proteger: cachearlo es
    // lo que corresponde.
    expect(cacheControlFor("/widget/abc123")).toBeNull();
    expect(isPublicPage("/widget/abc123")).toBe(true);
  });

  it("does not treat a lookalike path as public", () => {
    // "/widgets" no es "/widget/". Un prefijo mal comparado convierte una
    // pantalla con sesión en una pública.
    expect(isPublicPage("/widgets")).toBe(false);
    expect(cacheControlFor("/widgets")).toBe("no-store, must-revalidate");
  });
})
