/** @type {import('next').NextConfig} */
const nextConfig = {
  /**
   * Enable React strict mode for highlighting potential problems.
   */
  reactStrictMode: true,

  /**
   * Proxy API requests in development so the browser hits a same-origin
   * URL (no CORS, no preflight) and the dev server forwards to the
   * backend over the Docker network.  In production, the API client
   * uses NEXT_PUBLIC_API_BASE_URL directly.
   *
   * The destination is resolved by the Next.js Node server (inside the
   * frontend container in dev), so it must use the *internal* hostname
   * for the api service — `http://api:8000` — not `localhost`, which
   * would resolve to the frontend container itself.
   */
  async rewrites() {
    if (process.env.NODE_ENV !== "development") return [];
    const target =
      process.env.INTERNAL_API_BASE_URL ||
      process.env.NEXT_PUBLIC_API_BASE_URL ||
      "http://localhost:8000";
    return [
      {
        source: "/api/:path*",
        destination: `${target.replace(/\/$/, "")}/:path*`,
      },
    ];
  },

  images: {
    remotePatterns: [
      { protocol: "https", hostname: "www.kaufland.bg" },
      { protocol: "https", hostname: "www.lidl.bg" },
      { protocol: "https", hostname: "ssm.billa.bg" },
      { protocol: "https", hostname: "fantastico.bg" },
    ],
  },
};

module.exports = nextConfig;
