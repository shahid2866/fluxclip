/** @type {import('next').NextConfig} */
const API = process.env.FLUXCLIP_API_URL || "http://localhost:8000";

const nextConfig = {
  output: "standalone",
  // The browser only talks to this Next.js server; it proxies /api and /files to the Python API.
  async rewrites() {
    return [
      { source: "/api/:path*", destination: `${API}/api/:path*` },
      { source: "/files/:path*", destination: `${API}/files/:path*` },
    ];
  },
  experimental: { proxyTimeout: 30 * 60 * 1000 },
};

export default nextConfig;
