import { defineConfig, globalIgnores } from "eslint/config";
import nextVitals from "eslint-config-next/core-web-vitals";
import nextTs from "eslint-config-next/typescript";

const eslintConfig = defineConfig([
  ...nextVitals,
  ...nextTs,
  {
    // Shadcn primitives only: the shared Checkbox gives uniform focus/disabled/a11y
    // behaviour. components/ui/** is where the primitives themselves live.
    files: ["src/**/*.{ts,tsx}"],
    ignores: ["src/components/ui/**"],
    rules: {
      "no-restricted-syntax": [
        "error",
        {
          selector:
            "JSXOpeningElement[name.name='input'] > JSXAttribute[name.name='type'][value.value='checkbox']",
          message: 'Use <Checkbox> from "@/components/ui/checkbox" instead of <input type="checkbox">.',
        },
      ],
    },
  },
  // Override default ignores of eslint-config-next.
  globalIgnores([
    // Default ignores of eslint-config-next:
    ".next/**",
    "out/**",
    "build/**",
    "next-env.d.ts",
    // Self-hosted Monaco editor vendor assets (minified third-party JS, not application code).
    "public/vs/**",
  ]),
]);

export default eslintConfig;
