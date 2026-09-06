import { readFileSync } from "node:fs";
import { join } from "node:path";
import { fileURLToPath } from "node:url";
import { describe, expect, it } from "vitest";

// `public/widget.js` no se importa desde ningún lado: se sirve tal cual y lo
// carga el sitio de la clientela con un <script>. Se lee como texto porque es
// la única forma de afirmar algo sobre él, y lo que se afirma es una decisión
// de seguridad que alguien podría "limpiar" más adelante sin saber qué sostiene.
const here = fileURLToPath(new URL(".", import.meta.url));
const source = readFileSync(join(here, "..", "public", "widget.js"), "utf8");
const sandbox = /setAttribute\("sandbox",\s*"([^"]+)"\)/.exec(source)?.[1] ?? "";

describe("el sandbox del iframe del widget", () => {
  it("está puesto", () => {
    expect(sandbox).not.toBe("");
  });

  it.each([
    ["allow-scripts", "la página del widget es una app de React"],
    ["allow-same-origin", "con origen opaco no puede llamar a su propia API"],
    ["allow-forms", "el compositor de mensajes es un <form onSubmit>"],
    ["allow-downloads", "exportar la conversación usa un <a download>"],
  ])("concede %s, porque %s", (token) => {
    expect(sandbox.split(" ")).toContain(token);
  });

  it.each([
    // Este es el permiso que le da valor al sandbox: sin él, el widget no puede
    // sacar a los visitantes del sitio que lo hospeda.
    "allow-top-navigation",
    "allow-top-navigation-by-user-activation",
    // El widget no abre ventanas ni usa alert/confirm. Cada permiso de más
    // debilita el sandbox sin que nadie gane nada.
    "allow-popups",
    "allow-modals",
  ])("no concede %s", (token) => {
    expect(sandbox.split(" ")).not.toContain(token);
  });
});
