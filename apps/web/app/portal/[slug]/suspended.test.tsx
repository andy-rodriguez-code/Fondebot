import { describe, expect, it } from "vitest";
import { render, screen } from "@testing-library/react";
import { SuspendedNotice } from "./suspended";

describe("SuspendedNotice", () => {
  it("sends the person to whoever pays, not to technical support", () => {
    render(<SuspendedNotice title="Servicio suspendido" body="Comunicate con quien contrató el servicio." />);
    expect(screen.getByRole("heading", { name: "Servicio suspendido" })).toBeVisible();
    expect(screen.getByText(/quien contrató el servicio/)).toBeVisible();
  });
});
