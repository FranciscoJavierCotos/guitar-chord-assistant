import { describe, it, expect, beforeEach, afterEach } from "vitest";
import type { NextRequest } from "next/server";
import { resolveBackendUrl, backendHeaders } from "@/lib/serverBackend";

/** Minimal NextRequest stand-in — backendHeaders only reads `headers.get`. */
function mockRequest(headers: Record<string, string>): NextRequest {
  return {
    headers: { get: (k: string) => headers[k.toLowerCase()] ?? null },
  } as unknown as NextRequest;
}

describe("resolveBackendUrl", () => {
  const original = process.env.BACKEND_URL;
  afterEach(() => {
    if (original === undefined) delete process.env.BACKEND_URL;
    else process.env.BACKEND_URL = original;
  });

  it("defaults to localhost when BACKEND_URL is unset", () => {
    delete process.env.BACKEND_URL;
    expect(resolveBackendUrl()).toBe("http://localhost:8000");
  });

  it("passes through a full http/https URL unchanged", () => {
    process.env.BACKEND_URL = "https://api.example.com";
    expect(resolveBackendUrl()).toBe("https://api.example.com");
  });

  it("prepends https:// for a bare Render-style hostname", () => {
    process.env.BACKEND_URL = "chord-coach-backend.onrender.com";
    expect(resolveBackendUrl()).toBe("https://chord-coach-backend.onrender.com");
  });

  it("strips trailing slashes", () => {
    process.env.BACKEND_URL = "https://api.example.com///";
    expect(resolveBackendUrl()).toBe("https://api.example.com");
  });

  it("trims surrounding whitespace", () => {
    process.env.BACKEND_URL = "  https://api.example.com  ";
    expect(resolveBackendUrl()).toBe("https://api.example.com");
  });
});

describe("backendHeaders", () => {
  const original = process.env.INTERNAL_API_TOKEN;
  beforeEach(() => {
    process.env.INTERNAL_API_TOKEN = "secret-token";
  });
  afterEach(() => {
    if (original === undefined) delete process.env.INTERNAL_API_TOKEN;
    else process.env.INTERNAL_API_TOKEN = original;
  });

  it("attaches the shared-secret token", () => {
    const headers = backendHeaders(mockRequest({}));
    expect(headers["X-Internal-Token"]).toBe("secret-token");
  });

  it("forwards x-forwarded-for as the client IP", () => {
    const headers = backendHeaders(mockRequest({ "x-forwarded-for": "203.0.113.7" }));
    expect(headers["X-Forwarded-For"]).toBe("203.0.113.7");
  });

  it("falls back to x-real-ip when x-forwarded-for is absent", () => {
    const headers = backendHeaders(mockRequest({ "x-real-ip": "198.51.100.4" }));
    expect(headers["X-Forwarded-For"]).toBe("198.51.100.4");
  });

  it("omits X-Forwarded-For when no client IP is present", () => {
    const headers = backendHeaders(mockRequest({}));
    expect(headers).not.toHaveProperty("X-Forwarded-For");
  });

  it("merges extra headers alongside the token", () => {
    const headers = backendHeaders(mockRequest({}), { "Content-Type": "application/json" });
    expect(headers["Content-Type"]).toBe("application/json");
    expect(headers["X-Internal-Token"]).toBe("secret-token");
  });

  it("sends an empty token rather than undefined when the env var is unset", () => {
    delete process.env.INTERNAL_API_TOKEN;
    const headers = backendHeaders(mockRequest({}));
    expect(headers["X-Internal-Token"]).toBe("");
  });
});
