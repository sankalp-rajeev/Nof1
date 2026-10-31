import type { NextConfig } from "next";
const config: NextConfig = {
  output: "standalone",
  async rewrites() {
    // Server-only build setting; never expose the upstream through NEXT_PUBLIC_*.
    const upstream = new URL(process.env.API_INTERNAL_URL ?? "http://localhost:8000");
    if (!["http:", "https:"].includes(upstream.protocol) || upstream.username || upstream.password || upstream.pathname !== "/" || upstream.search || upstream.hash) throw new Error("API_INTERNAL_URL must be an HTTP origin without credentials or a path");
    return [{ source: "/api/:path*", destination: `${upstream.origin}/api/:path*` }, { source: "/health", destination: `${upstream.origin}/health` }];
  },
  async headers() { return [{ source: "/:path*", headers: [{ key: "Content-Security-Policy", value: "connect-src 'self'" }] }]; },
};
export default config;
