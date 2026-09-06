import { describe, expect, it } from "vitest";
import { formatDuration } from "./datetime";

describe("formatDuration", () => {
  it("usa segundos abajo del minuto", () => {
    expect(formatDuration(0)).toBe("0 s");
    expect(formatDuration(59)).toBe("59 s");
  });

  it("pasa a minutos y no arrastra los segundos sueltos", () => {
    expect(formatDuration(60)).toBe("1 min");
    expect(formatDuration(155)).toBe("2 min");
  });

  it("muestra las horas con sus minutos, y las omite cuando son cero", () => {
    expect(formatDuration(3600)).toBe("1 h");
    expect(formatDuration(3900)).toBe("1 h 5 min");
  });

  it("no inventa una espera negativa", () => {
    // percentile_cont nunca la devolvería, pero un dato torcido no debería
    // pintar "-3 s" en el panel.
    expect(formatDuration(-10)).toBe("0 s");
  });
});
