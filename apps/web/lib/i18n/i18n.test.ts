import { describe, expect, it } from "vitest";
import { en } from "./en";
import { es } from "./es";
import { translate } from "./index";

function dottedKeys(node: unknown, prefix = ""): string[] {
  if (typeof node !== "object" || node === null) return [prefix];
  return Object.entries(node).flatMap(([key, value]) =>
    dottedKeys(value, prefix ? `${prefix}.${key}` : key),
  );
}

describe("dictionaries", () => {
  // `es` is typed as `Dictionary` (= typeof en), so tsc already rejects a
  // missing key. This test is not the primary guard: it exists because the
  // compiler reports the drift as a structural mismatch on a 400-key object,
  // while this prints the offending paths. It also survives someone widening
  // that type. lookup() throws rather than falling back, so drift that reaches
  // runtime crashes in front of whoever switched language.
  it("define exactamente las mismas claves en los dos idiomas", () => {
    const enKeys = dottedKeys(en).sort();
    const esKeys = dottedKeys(es).sort();
    const missingInEs = enKeys.filter((key) => !esKeys.includes(key));
    const missingInEn = esKeys.filter((key) => !enKeys.includes(key));
    expect({ missingInEs, missingInEn }).toEqual({ missingInEs: [], missingInEn: [] });
  });

  it("no deja ninguna cadena vacía", () => {
    const empty = dottedKeys(en).filter((key) => {
      const value = key.split(".").reduce<unknown>((node, part) => (node as Record<string, unknown>)[part], en);
      return typeof value === "string" && value.trim() === "";
    });
    expect(empty).toEqual([]);
  });
});

describe("translate", () => {
  it("cae al español fuera del navegador", () => {
    // There is no document in this environment, which is the server case.
    expect(translate("errors.unexpected")).toBe(es.errors.unexpected);
  });

  it("reemplaza todas las apariciones de una variable", () => {
    const rendered = translate("clients.detail.departmentConfirmDelete", { name: "Tesorería" });
    expect(rendered).toContain("Tesorería");
    expect(rendered).not.toContain("{name}");
  });

  it("explota con una clave que no existe, en vez de devolver algo vacío", () => {
    // Cast: the point of the test is the runtime guard behind the type check.
    expect(() => translate("no.existe.esta.clave" as never)).toThrow(/Missing i18n key/);
  });
});
