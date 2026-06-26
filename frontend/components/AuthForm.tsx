"use client";

import React, { useState } from "react";
import { useRouter } from "next/navigation";
import Link from "next/link";
import { createClient } from "@/lib/supabase/client";
import { supabaseConfigured } from "@/lib/supabase/env";

type Mode = "signin" | "signup";

/**
 * Email/password auth form (B1 — #26) shared by /login and /signup. Talks to
 * Supabase Auth from the browser; @supabase/ssr persists the session into cookies
 * so it's visible server-side. Sign-up requires email confirmation, so it shows a
 * "check your inbox" state rather than logging the user straight in.
 */
export default function AuthForm({ mode }: { mode: Mode }) {
  const router = useRouter();
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);

  const configured = supabaseConfigured();

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    setError(null);
    setNotice(null);
    setLoading(true);
    try {
      const supabase = createClient();
      if (mode === "signup") {
        const { error } = await supabase.auth.signUp({
          email,
          password,
          options: { emailRedirectTo: `${window.location.origin}/auth/callback` },
        });
        if (error) throw error;
        setNotice("Check your inbox to confirm your email, then sign in.");
      } else {
        const { error } = await supabase.auth.signInWithPassword({ email, password });
        if (error) throw error;
        router.push("/account");
        router.refresh();
      }
    } catch (err) {
      // Generic message — don't reveal whether an email exists (no enumeration).
      setError(err instanceof Error ? err.message : "Something went wrong. Please try again.");
    } finally {
      setLoading(false);
    }
  }

  const isSignup = mode === "signup";

  return (
    <div className="w-full max-w-sm">
      <h1 className="font-display text-2xl font-bold text-text-warm">
        {isSignup ? "Create your account" : "Welcome back"}
      </h1>
      <p className="mt-1 text-sm text-text-muted">
        {isSignup ? "Sign up to save your progress and history." : "Sign in to ChordCoach."}
      </p>

      {!configured && (
        <p className="mt-4 rounded-lg border border-border-dark bg-bg-surface px-3 py-2 text-sm text-accent-gold">
          Auth isn&apos;t configured in this environment.
        </p>
      )}

      <form onSubmit={handleSubmit} className="mt-6 space-y-4">
        <label className="block">
          <span className="text-xs font-mono uppercase tracking-widest text-text-muted">Email</span>
          <input
            type="email"
            required
            autoComplete="email"
            value={email}
            onChange={(e) => setEmail(e.target.value)}
            className="mt-1 w-full rounded-lg border border-border-dark bg-bg-surface px-3 py-2 text-text-warm outline-none focus:border-accent-orange"
          />
        </label>

        <label className="block">
          <span className="text-xs font-mono uppercase tracking-widest text-text-muted">Password</span>
          <input
            type="password"
            required
            minLength={8}
            autoComplete={isSignup ? "new-password" : "current-password"}
            value={password}
            onChange={(e) => setPassword(e.target.value)}
            className="mt-1 w-full rounded-lg border border-border-dark bg-bg-surface px-3 py-2 text-text-warm outline-none focus:border-accent-orange"
          />
        </label>

        {error && <p className="text-sm text-red-400">{error}</p>}
        {notice && <p className="text-sm text-accent-gold">{notice}</p>}

        <button
          type="submit"
          disabled={loading || !configured}
          className="w-full rounded-lg bg-accent-orange px-4 py-2 font-medium text-bg-primary transition-opacity hover:opacity-90 disabled:opacity-50"
        >
          {loading ? "Please wait…" : isSignup ? "Sign up" : "Sign in"}
        </button>
      </form>

      <div className="mt-5 flex items-center justify-between text-sm">
        {isSignup ? (
          <Link href="/login" className="text-text-muted hover:text-text-warm">
            Already have an account? Sign in
          </Link>
        ) : (
          <>
            <Link href="/signup" className="text-text-muted hover:text-text-warm">
              Create account
            </Link>
            <Link href="/reset-password" className="text-text-muted hover:text-text-warm">
              Forgot password?
            </Link>
          </>
        )}
      </div>
    </div>
  );
}
