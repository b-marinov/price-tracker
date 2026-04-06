/** @type {import('next').NextConfig} */
const nextConfig = {
  /**
   * Enable React strict mode for highlighting potential problems.
   */
  reactStrictMode: true,

  /**
   * Proxy API requests in development so the browser never needs to know
   * the backend origin.  In production, NEXT_PUBLIC_API_BASE_URL is used
   * directly from the API client.
   */
  async rewrites() {
    return process.env.NODE_ENV === "development"
      ? [
          {
            source: "/api/:path*",
            destination: `${process.env.NEXT_PUBLIC_API_BASE_URL || "http://localhost:8000"}/:path*`,
          },
        ]
      : [];
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
