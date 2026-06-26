/** @type {import('next').NextConfig} */

// Content-Security-Policy for the public surface. 'unsafe-inline' is required for
// Next.js's hydration bootstrap scripts and React inline style attributes; tighten
// to nonces later if needed. The backend is still reached server-side via /api
// proxies, but the browser DOES talk directly to Supabase Auth (B1 — #26), so its
// origin is added to connect-src when configured. In development only, Next.js's
// Fast Refresh / HMR runtime uses eval(), so 'unsafe-eval' must be allowed there or
// the dev bundle is blocked and the page never hydrates. Production
// (`next build && next start`) does not use eval, so it stays out of the policy.
const isDev = process.env.NODE_ENV !== "production";
const scriptSrc = isDev
  ? "script-src 'self' 'unsafe-inline' 'unsafe-eval'"
  : "script-src 'self' 'unsafe-inline'";

// Allow XHR/fetch + websocket to the Supabase project origin (auth + realtime),
// derived from the public URL so nothing is hard-coded. Empty when unset.
let supabaseOrigin = "";
try {
  if (process.env.NEXT_PUBLIC_SUPABASE_URL) {
    supabaseOrigin = new URL(process.env.NEXT_PUBLIC_SUPABASE_URL).origin;
  }
} catch {
  /* malformed URL — leave connect-src at 'self' */
}
const connectSrc = ["connect-src 'self'", supabaseOrigin].filter(Boolean).join(" ");

const csp = [
  "default-src 'self'",
  scriptSrc,
  "style-src 'self' 'unsafe-inline'",
  "img-src 'self' data:",
  "font-src 'self' data:",
  connectSrc,
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
