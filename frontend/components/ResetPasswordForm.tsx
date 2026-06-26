"use client";

import React, { useState } from "react";
import Link from "next/link";
import { createClient } from "@/lib/supabase/client";
import { supabaseConfigured } from "@/lib/supabase/env";

/**
 * Request a password-reset email (B1 — #26). Supabase emails a recovery link that
 * lands on /auth/callback, which establishes a short recovery session and forwards
 * to /update-password. Always shows the same generic confirmation regardless of
 * whether the email exists (no account enumeration).
 */
export default function ResetPasswordForm() {
  const [email, setEmail] = useState("");
  const [sent, setSent] = useState(false);
  const [loading, setLoading] = useState(false);
  const configured = supabaseConfigured();

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    setLoading(true);
    try {
      const supabase = createClient();
      await supabase.auth.resetPasswordForEmail(email, {
        redirectTo: `${window.location.origin}/auth/callback?next=/update-password`,
      });
    } finally {
      setSent(true);
      setLoading(false);
    }
  }

  return (
    <div className="w-full max-w-sm">
      <h1 className="font-display text-2xl font-bold text-text-warm">Reset password</h1>
      {sent ? (
        <p className="mt-4 text-sm text-accent-gold">
          If an account exists for that email, a reset link is on its way.
        </p>
      ) : (
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
          <button
            type="submit"
            disabled={loading || !configured}
            className="w-full rounded-lg bg-accent-orange px-4 py-2 font-medium text-bg-primary transition-opacity hover:opacity-90 disabled:opacity-50"
          >
            {loading ? "Sending…" : "Send reset link"}
          </button>
        </form>
      )}
      <Link href="/login" className="mt-5 inline-block text-sm text-text-muted hover:text-text-warm">
        Back to sign in
      </Link>
    </div>
  );
}
