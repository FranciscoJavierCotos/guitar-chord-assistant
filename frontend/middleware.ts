import { NextRequest, NextResponse } from "next/server";

/**
 * Lightweight per-IP edge rate limit for /api/* — a coarse first line of defence
 * in front of the backend's authoritative slowapi limits. In-memory and per
 * instance (best-effort, resets on redeploy); the backend remains the real cap.
 */
const WINDOW_MS = 60_000;
const MAX_REQUESTS = 60; // per IP per minute across all /api routes

const hits = new Map<string, { count: number; resetAt: number }>();

function rateLimited(ip: string): boolean {
  const now = Date.now();
  const entry = hits.get(ip);
  if (!entry || now > entry.resetAt) {
    hits.set(ip, { count: 1, resetAt: now + WINDOW_MS });
    return false;
  }
  entry.count += 1;
  return entry.count > MAX_REQUESTS;
}

export function middleware(req: NextRequest) {
  const ip =
    req.headers.get("x-forwarded-for")?.split(",")[0].trim() ||
    req.headers.get("x-real-ip") ||
    "unknown";

  if (rateLimited(ip)) {
    return NextResponse.json({ detail: "Too many requests." }, { status: 429 });
  }
  return NextResponse.next();
}

export const config = {
  matcher: "/api/:path*",
};
