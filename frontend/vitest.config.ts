import path from "node:path";
import { defineConfig } from "vitest/config";

export default defineConfig({
  test: {
    environment: "node",
    include: ["src/**/*.test.ts", "src/**/*.test.tsx"],
    // Hook/component tests that need a DOM (React Testing Library) opt in via
    // a `.test.tsx` extension; plain logic tests stay on the faster "node"
    // environment above.
    environmentMatchGlobs: [["src/**/*.test.tsx", "jsdom"]],
  },
  resolve: {
    alias: {
      "@": path.resolve(__dirname, "./src"),
    },
  },
});
