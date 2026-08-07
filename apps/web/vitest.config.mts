import path from "node:path";
import { defineConfig } from "vitest/config";

// .mts：apps/web 沒有 "type": "module"，副檔名是讓這支設定以 ESM 載入的方式
// （Vite 7 起是 ESM-only，用 CJS require 會炸）。
export default defineConfig({
  // 不用 @vitejs/plugin-react：測試不需要 Fast Refresh，只需要 JSX transform。
  // tsconfig 是 `jsx: preserve`（給 Next 用），這裡要明確指定 automatic runtime。
  esbuild: { jsx: "automatic", jsxImportSource: "react" },
  resolve: {
    alias: { "@": path.resolve(import.meta.dirname) },
  },
  test: {
    environment: "jsdom",
    setupFiles: ["./vitest.setup.ts"],
    include: ["**/*.test.{ts,tsx}"],
    exclude: ["node_modules/**", ".next/**"],
  },
});
