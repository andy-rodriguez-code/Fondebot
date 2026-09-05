import { defineConfig } from "vitest/config";

// Node environment on purpose: these tests cover the logic modules under lib/,
// which run on both sides of the wire and render nothing. Component tests would
// need jsdom and a DOM testing library; that is a separate decision, not a
// prerequisite for having a test suite at all.
export default defineConfig({
  test: {
    environment: "node",
    include: ["lib/**/*.test.ts", "lib/**/*.test.tsx"],
  },
});
