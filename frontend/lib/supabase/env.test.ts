import { describe, it, expect, afterEach, vi } from "vitest";

/**
 * `supabaseConfigured` gates whether the auth UI activates and whether middleware
 * runs the session refresh — so the DB-less MVP path must report "not configured".
 * The module reads env at import time, so we reset the module registry per case.
 */
const ORIGINAL = {
  url: process.env.NEXT_PUBLIC_SUPABASE_URL,
  key: process.env.NEXT_PUBLIC_SUPABASE_ANON_KEY,
};

afterEach(() => {
  if (ORIGINAL.url === undefined) delete process.env.NEXT_PUBLIC_SUPABASE_URL;
  else process.env.NEXT_PUBLIC_SUPABASE_URL = ORIGINAL.url;
  if (ORIGINAL.key === undefined) delete process.env.NEXT_PUBLIC_SUPABASE_ANON_KEY;
  else process.env.NEXT_PUBLIC_SUPABASE_ANON_KEY = ORIGINAL.key;
  vi.resetModules();
});

async function loadEnv() {
  vi.resetModules();
  return import("@/lib/supabase/env");
}

describe("supabaseConfigured", () => {
  it("is false when both vars are missing", async () => {
    delete process.env.NEXT_PUBLIC_SUPABASE_URL;
    delete process.env.NEXT_PUBLIC_SUPABASE_ANON_KEY;
    const { supabaseConfigured } = await loadEnv();
    expect(supabaseConfigured()).toBe(false);
  });

  it("is false when only the URL is set", async () => {
    process.env.NEXT_PUBLIC_SUPABASE_URL = "https://proj.supabase.co";
    delete process.env.NEXT_PUBLIC_SUPABASE_ANON_KEY;
    const { supabaseConfigured } = await loadEnv();
    expect(supabaseConfigured()).toBe(false);
  });

  it("is true when both URL and anon key are set", async () => {
    process.env.NEXT_PUBLIC_SUPABASE_URL = "https://proj.supabase.co";
    process.env.NEXT_PUBLIC_SUPABASE_ANON_KEY = "anon-key";
    const { supabaseConfigured } = await loadEnv();
    expect(supabaseConfigured()).toBe(true);
  });
});
