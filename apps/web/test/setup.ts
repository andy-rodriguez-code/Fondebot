// Setup for the `components` project (see vitest.config.ts).
//
// This file lives outside app/ and components/ on purpose: anything under those
// directories is part of the graph `next build` compiles, and a test-only import
// has no business in the production bundle.
//
// The /vitest entry point registers the matchers on Vitest's `expect` and brings
// their types along. tsconfig.json includes **/*.ts, so this single import is
// what makes `tsc --noEmit` accept toBeVisible() and toHaveAccessibleName().
//
// Cleanup is not wired here. React Testing Library registers it itself, which is
// exactly why the components project sets `globals: true`.
import "@testing-library/jest-dom/vitest";
