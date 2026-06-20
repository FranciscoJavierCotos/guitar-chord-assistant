import { defineConfig } from "vitest/config";
import { fileURLToPath } from "node:url";

export default defineConfig({
  resolve: {
    // Mirror the `@/*` -> frontend root alias from tsconfig.json so tests can
    // import modules the same way the app does.
    alias: {
      "@": fileURLToPath(new URL("./", import.meta.url)),
    },
  },
  test: {
    environment: "node",
    globals: true,
    include: ["**/*.test.ts"],
    coverage: { reporter: ["text", "html"], provider: "v8" },
  },
});
