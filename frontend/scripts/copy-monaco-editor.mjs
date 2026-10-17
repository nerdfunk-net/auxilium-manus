// Copies the Monaco Editor AMD bundle into public/vs so @monaco-editor/react
// can load it from same-origin static assets instead of the jsdelivr CDN,
// which is unreachable in air-gapped deployments.
import { cpSync, existsSync } from "node:fs";
import { fileURLToPath } from "node:url";
import path from "node:path";

const frontendRoot = path.dirname(path.dirname(fileURLToPath(import.meta.url)));
const source = path.join(frontendRoot, "node_modules", "monaco-editor", "min", "vs");
const destination = path.join(frontendRoot, "public", "vs");

if (!existsSync(source)) {
  console.warn(`[copy-monaco-editor] source not found, skipping: ${source}`);
  process.exit(0);
}

cpSync(source, destination, { recursive: true });
console.log(`[copy-monaco-editor] copied ${source} -> ${destination}`);
