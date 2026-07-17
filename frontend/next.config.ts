import type { NextConfig } from "next";

const nextConfig: NextConfig = {
  output: "standalone",
  // Disable Next.js trailing-slash redirection. Without this, POST requests
  // to "/api/v1/ledgers/" get 308-redirected to "/api/v1/ledgers"; the 308
  // response makes the browser follow to a URL that breaks the same-origin
  // rewrites proxy (CSP blocks the cross-origin hop) → "Failed to fetch".
  // Skipping the redirect lets rewrites handle the URL as-is.
  skipTrailingSlashRedirect: true,
  // Proxy /api/* to the FastAPI backend so the browser issues same-origin
  // requests (localhost:3001/api/* → 127.0.0.1:8005/api/*). This completely
  // bypasses CSP connect-src and CORS restrictions, which is the fix for the
  // "Failed to fetch" error when API_BASE points at 127.0.0.1:8005.
  async rewrites() {
    const backend = process.env.BACKEND_URL || "http://127.0.0.1:8005";
    return [
      { source: "/api/:path*", destination: `${backend}/api/:path*` },
    ];
  },
  async headers() {
    return [
      {
        source: "/:path*",
        headers: [
          // Prevent clickjacking — financial UI must never be framed.
          { key: "X-Frame-Options", value: "DENY" },
          // Block MIME-type sniffing on responses declared as text/html etc.
          { key: "X-Content-Type-Options", value: "nosniff" },
          // Referrer-Policy: only send origin to same-origin; full URL nowhere.
          // Critical because the URL/query may contain ledger/voucher IDs.
          { key: "Referrer-Policy", value: "same-origin" },
          // HSTS: force HTTPS for 1 year, including subdomains.
          { key: "Strict-Transport-Security", value: "max-age=31536000; includeSubDomains" },
          // Permissions-Policy: deny access to device APIs the finance UI
          // doesn't need (camera, mic, geolocation, etc.).
          {
            key: "Permissions-Policy",
            value: "camera=(), microphone=(), geolocation=(), payment=(), usb=()",
          },
          // Content-Security-Policy:
          // - default-src 'self' — baseline deny-all
          // - script-src 'self' 'unsafe-inline' 'unsafe-eval' — Next.js dev
          //   requires unsafe-eval/inline; tighten in production via nonces
          //   when moving to a strict CSP.
          // - style-src 'self' 'unsafe-inline' — Tailwind injects inline styles
          // - img-src 'self' data: blob: https://trae-api-cn.mchost.guru —
          //   allow generated images from the text-to-image API + data URIs
          //   used by file preview blobs.
          // - connect-src 'self' — API calls go through Next.js rewrites
          //   (/api/* → backend), so they are same-origin. No external host
          //   needs to be whitelisted.
          // - font-src 'self' data: — Next.js font optimization
          // - frame-ancestors 'none' — equivalent to X-Frame-Options DENY
          // - base-uri 'self' — prevent <base> hijacking
          // - form-action 'self' — prevent form submission to external origins
          {
            key: "Content-Security-Policy",
            value: [
              "default-src 'self'",
              "script-src 'self' 'unsafe-inline' 'unsafe-eval'",
              "style-src 'self' 'unsafe-inline'",
              "img-src 'self' data: blob: https://trae-api-cn.mchost.guru",
              "connect-src 'self'",
              "font-src 'self' data:",
              "frame-ancestors 'none'",
              "base-uri 'self'",
              "form-action 'self'",
              "object-src 'none'",
            ].join("; "),
          },
        ],
      },
    ];
  },
};

export default nextConfig;
