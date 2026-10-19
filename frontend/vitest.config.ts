import path from "node:path";
import { defineConfig } from "vitest/config";

const alias = { "@": path.resolve(__dirname, "./src") };

export default defineConfig({
  test: {
    // Coverage is measured by `npm run test:coverage` (the CI step). `include` lists untested
    // files too, so the gaps show up as 0 % rows.
    coverage: {
      provider: "v8",
      reporter: ["text-summary", "json-summary", "html"],
      include: ["src/**/*.{ts,tsx}"],
      exclude: [
        "src/**/*.test.{ts,tsx}",
        "src/**/*.d.ts",
        "src/test/**",
        "src/components/ui/**",
        "src/app/**",
      ],
      // Ratchet: the run fails when coverage drops below these numbers. They sit just under the
      // measured values (29.39 / 22.34 / 22.40 / 28.96 on 2026-10-19), so only a real regression
      // trips them. Raise them whenever coverage has grown, never lower them to make a run pass.
      // Running a subset of tests? Use `npx vitest run <file>` (no coverage, no threshold check).
      thresholds: {
        statements: 31,
        branches: 24,
        functions: 23,
        lines: 30,
      },
    },
    // Hook/component tests that need a DOM (React Testing Library) opt in via
    // a `.test.tsx` extension; plain logic tests stay on the faster "node"
    // environment.
    projects: [
      {
        resolve: { alias },
        test: {
          name: "node",
          environment: "node",
          include: ["src/**/*.test.ts"],
        },
      },
      {
        resolve: { alias },
        test: {
          name: "dom",
          environment: "jsdom",
          setupFiles: ["./src/test/setup-dom.ts"],
          include: ["src/**/*.test.tsx"],
        },
      },
    ],
  },
});
