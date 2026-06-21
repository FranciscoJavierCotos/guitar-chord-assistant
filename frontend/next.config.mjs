/** @type {import('next').NextConfig} */

// Content-Security-Policy for the public surface. 'unsafe-inline' is required for
// Next.js's hydration bootstrap scripts and React inline style attributes; tighten
// to nonces later if needed. connect-src is 'self' because the browser only ever
// talks to our own origin — the backend is reached server-side via /api proxies.
// In development only, Next.js's Fast Refresh / HMR runtime uses eval(), so
// 'unsafe-eval' must be allowed there or the dev bundle is blocked and the page
// never hydrates. Production (`next build && next start`) does not use eval, so it
// stays out of the deployed policy.
const isDev = process.env.NODE_ENV !== "production";
const scriptSrc = isDev
  ? "script-src 'self' 'unsafe-inline' 'unsafe-eval'"
  : "script-src 'self' 'unsafe-inline'";

const csp = [
  "default-src 'self'",
  scriptSrc,
  "style-src 'self' 'unsafe-inline'",
  "img-src 'self' data:",
  "font-src 'self' data:",
  "connect-src 'self'",
  "frame-ancestors 'none'",
  "base-uri 'self'",
  "form-action 'self'",
].join("; ");

const securityHeaders = [
  { key: "Content-Security-Policy", value: csp },
  { key: "X-Frame-Options", value: "DENY" },
  { key: "X-Content-Type-Options", value: "nosniff" },
  { key: "Referrer-Policy", value: "strict-origin-when-cross-origin" },
  { key: "Strict-Transport-Security", value: "max-age=63072000; includeSubDomains; preload" },
  { key: "Permissions-Policy", value: "camera=(), microphone=(), geolocation=()" },
];

const nextConfig = {
  // Backend calls go through the Next.js route handlers in app/api/* (which attach
  // the server-only X-Internal-Token), NOT a rewrite — a rewrite can't inject the
  // secret header. So there is intentionally no rewrite here anymore.
  async headers() {
    return [{ source: "/:path*", headers: securityHeaders }];
  },
};

export default nextConfig;
