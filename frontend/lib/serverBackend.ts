/**
 * Server-only helpers for talking to the FastAPI backend.
 *
 * SECURITY: this module must never be imported by client components. It reads
 * BACKEND_URL and INTERNAL_API_TOKEN, which are deliberately NOT prefixed with
 * NEXT_PUBLIC_ so they stay on the server and never ship in the browser bundle.
 * The browser only ever calls our own same-origin /api routes, which proxy here.
 */
import type { NextRequest } from "next/server";

/**
 * Backend base URL. On Render, BACKEND_URL is wired from the backend service's
 * `host` property — a bare hostname with no scheme — so we prepend https:// when
 * a scheme is absent. Locally it's a full http://localhost URL and passes through.
 */
function resolveBackendUrl(): string {
  const raw = (process.env.BACKEND_URL || "http://localhost:8000").trim();
  if (/^https?:\/\//i.test(raw)) return raw.replace(/\/+$/, "");
  return `https://${raw}`.replace(/\/+$/, "");
}

export const BACKEND_URL = resolveBackendUrl();

/**
 * Build the headers for a server→backend request: the shared-secret token plus
 * the real client IP forwarded as X-Forwarded-For so the backend rate-limiter
 * keys on the end user rather than on this proxy's IP.
 */
export function backendHeaders(
  req: NextRequest,
  extra?: Record<string, string>,
): Record<string, string> {
  const headers: Record<string, string> = {
    "X-Internal-Token": process.env.INTERNAL_API_TOKEN || "",
    ...(extra || {}),
  };
  const clientIp =
    req.headers.get("x-forwarded-for") || req.headers.get("x-real-ip");
  if (clientIp) headers["X-Forwarded-For"] = clientIp;
  return headers;
}

/** Pass the backend's response straight through, preserving status and body. */
export async function relay(res: Response): Promise<Response> {
  const body = await res.text();
  return new Response(body, {
    status: res.status,
    headers: { "Content-Type": res.headers.get("content-type") || "application/json" },
  });
}
