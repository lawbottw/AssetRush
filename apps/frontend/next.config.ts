import path from "node:path";
import type { NextConfig } from "next";

const nextConfig: NextConfig = {
  // monorepo：明確指定工作區根目錄，避免 Next 自行推測 tracing root
  outputFileTracingRoot: path.join(__dirname, "../.."),
};

export default nextConfig;
