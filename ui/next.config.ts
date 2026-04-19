import type { NextConfig } from "next";

const isExport = process.env.NEXT_OUTPUT === "export";

const nextConfig: NextConfig = {
  ...(isExport && {
    output: "export" as const,
    distDir: "../src/astra/ui/out",
  }),
  ...(!isExport && {
    async rewrites() {
      return [
        {
          source: "/api/:path*",
          destination: "http://127.0.0.1:8080/api/:path*",
        },
      ];
    },
  }),
};

export default nextConfig;
