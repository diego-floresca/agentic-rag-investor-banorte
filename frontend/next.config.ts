import type { NextConfig } from "next";

const isDev = process.env.NODE_ENV === "development";

const nextConfig: NextConfig = {
  // En dev: servidor Node.js (sin output=export para que funcionen env vars).
  // En build: export estático servido por FastAPI.
  output: isDev ? undefined : "export",
  trailingSlash: true,
  // NEXT_PUBLIC_API_BASE apunta directo al backend en dev; en build no se usa.
  env: {
    NEXT_PUBLIC_API_BASE: process.env.NEXT_PUBLIC_API_BASE ?? (isDev ? "http://localhost:8000/api" : ""),
  },
};

export default nextConfig;
