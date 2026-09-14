import { defineConfig } from "vitest/config";

// Two projects, one `npm test`. They are split because they need different
// environments, and the difference is load-bearing in both directions.
export default defineConfig({
  test: {
    projects: [
      {
        // Node environment on purpose: these tests cover the logic modules under
        // lib/, which run on both sides of the wire and render nothing. Handing
        // them a DOM would not break them — it would stop them from proving they
        // never needed one.
        test: {
          name: "logic",
          environment: "node",
          include: ["lib/**/*.test.ts", "lib/**/*.test.tsx"],
        },
      },
      {
        test: {
          name: "components",
          environment: "jsdom",
          // `globals: true` here and nowhere else. React Testing Library wires
          // its own teardown by probing for a GLOBAL afterEach:
          //
          //   if (typeof afterEach === 'function') { afterEach(() => cleanup()) }
          //
          // With globals off — the default, and what the lib/ tests rely on —
          // that probe misses. Nothing registers, every render() leaves its tree
          // mounted, and the second test that renders the same component fails on
          // duplicate matches with an error that never mentions the real cause.
          // The same probe is what sets IS_REACT_ACT_ENVIRONMENT, without which
          // React 19 warns on every state update.
          //
          // Tests still import describe/it/expect from "vitest" explicitly, the
          // way lib/ does. This only adds the globals the library looks for.
          globals: true,
          setupFiles: ["./test/setup.ts"],
          include: ["components/**/*.test.tsx", "app/**/*.test.tsx"],
        },
      },
    ],
  },
});
