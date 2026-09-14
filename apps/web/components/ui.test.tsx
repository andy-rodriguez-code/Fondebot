import { describe, expect, it } from "vitest";
import { render, screen } from "@testing-library/react";
import { Modal, StatusBadge } from "./ui";

// Queries go through accessible roles and names, never CSS classes or test ids.
// That is not a style preference: the changes queued behind this one are
// accessibility fixes, and a test that finds its target by class name would stay
// green with the accessibility tree broken — which is the exact defect it is
// supposed to catch.

describe("Modal", () => {
  it("renders nothing while closed", () => {
    render(<Modal open={false} title="Editar contacto" onClose={() => {}}>body</Modal>);
    expect(screen.queryByRole("dialog")).toBeNull();
  });

  it("exposes a dialog whose accessible name is its title", () => {
    render(<Modal open title="Editar contacto" onClose={() => {}}>body</Modal>);
    const dialog = screen.getByRole("dialog");
    expect(dialog).toHaveAttribute("aria-modal", "true");
    expect(dialog).toHaveAccessibleName("Editar contacto");
  });
});

describe("StatusBadge", () => {
  // These two pin the CURRENT behaviour: hardcoded Spanish, no i18n, which is
  // the defect the next change fixes. They are meant to break when that happens.
  // A test that survives the change it is supposed to guard was never testing
  // anything — so when this one goes red, that is the fix landing, not a
  // regression.
  it("reads Activo when active", () => {
    render(<StatusBadge active />);
    expect(screen.getByText("Activo")).toBeVisible();
  });

  it("reads Inactivo when inactive", () => {
    render(<StatusBadge active={false} />);
    expect(screen.getByText("Inactivo")).toBeVisible();
  });
});
