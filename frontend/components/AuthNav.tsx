"use client";

import React, { useEffect, useState } from "react";
import Link from "next/link";
import type { User } from "@supabase/supabase-js";
import { createClient } from "@/lib/supabase/client";
import { supabaseConfigured } from "@/lib/supabase/env";

/**
 * Header auth control (B1 — #26): shows "Sign in" when anonymous and an account
 * link + sign-out when signed in. Subscribes to Supabase auth-state changes so it
 * updates live after login/logout. Renders nothing when auth isn't configured, so
 * the DB-less MVP path is unaffected.
 */
export default function AuthNav() {
  const [user, setUser] = useState<User | null>(null);
  const [ready, setReady] = useState(false);

  useEffect(() => {
    if (!supabaseConfigured()) {
      setReady(true);
      return;
    }
    const supabase = createClient();
    supabase.auth.getUser().then(({ data }) => {
      setUser(data.user);
      setReady(true);
    });
    const {
      data: { subscription },
    } = supabase.auth.onAuthStateChange((_event, session) => {
      setUser(session?.user ?? null);
    });
    return () => subscription.unsubscribe();
  }, []);

  if (!supabaseConfigured() || !ready) return null;

  if (!user) {
    return (
      <Link
        href="/login"
        className="rounded-lg border border-border-dark bg-bg-elevated px-3 py-1.5 text-sm font-medium text-text-warm hover:border-accent-orange"
      >
        Sign in
      </Link>
    );
  }

  return (
    <div className="flex items-center gap-3">
      <Link href="/account" className="hidden sm:inline max-w-[12rem] truncate text-sm text-text-muted hover:text-text-warm">
        {user.email}
      </Link>
      <form action="/auth/signout" method="post">
        <button
          type="submit"
          className="rounded-lg border border-border-dark bg-bg-elevated px-3 py-1.5 text-sm font-medium text-text-warm hover:border-accent-orange"
        >
          Sign out
        </button>
      </form>
    </div>
  );
}
