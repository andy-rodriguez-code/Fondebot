import { describe, expect, it } from "vitest";
import { render, screen } from "@testing-library/react";
import { RichText } from "./rich-text";

// RichText is where visitor-written text reaches the screen: WhatsApp messages,
// widget chats, anything a stranger typed. It builds React nodes and never
// touches dangerouslySetInnerHTML, and its regex only accepts http/https — so
// markup cannot execute and a javascript: URL cannot become a link.
//
// Both of those are properties the code has today by construction, and nothing
// states them out loud. These tests do, so that a future edit to that regex has
// to break something visible before it can break the property.

describe("RichText", () => {
  it("renders markup as text instead of executing it", () => {
    const { container } = render(<RichText text="<script>alert(1)</script>" />);
    expect(screen.getByText("<script>alert(1)</script>")).toBeVisible();
    expect(container.querySelector("script")).toBeNull();
  });

  it("does not turn a javascript: target into a link", () => {
    const { container } = render(<RichText text="[click](javascript:alert(1))" />);
    expect(container.querySelector("a")).toBeNull();
    expect(screen.getByText("[click](javascript:alert(1))")).toBeVisible();
  });

  it("still links an ordinary https URL", () => {
    render(<RichText text="see https://example.com/docs" />);
    expect(screen.getByRole("link", { name: "https://example.com/docs" })).toHaveAttribute(
      "href",
      "https://example.com/docs",
    );
  });
});
