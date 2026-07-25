"use client";

import { useState } from "react";
import { useAuth } from "@/lib/auth-context";
import { login, register } from "@/lib/api/auth";
import { setHomeDistrict } from "@/lib/api/auth";
import { useDistricts } from "@/lib/api/search";
import { ApiError } from "@/lib/api/client";

export function AuthModal() {
  const { showAuthModal, closeAuth, onAuthenticated } = useAuth();
  const [mode, setMode] = useState<"login" | "register">("login");
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [step, setStep] = useState(0); // 0 = form, 1 = onboarding
  const [homeDistrict, setHomeDistrictId] = useState("");
  const districts = useDistricts(step === 1);

  if (!showAuthModal) return null;

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    setError(null);
    setBusy(true);
    try {
      const resp = mode === "register" ? await register(email, password) : await login(email, password);
      onAuthenticated(resp.access_token, { email, tier: resp.tier, user_id: resp.user_id });
      if (mode === "register") setStep(1);
      else closeAuth();
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Authentication failed");
    } finally {
      setBusy(false);
    }
  }

  async function finishOnboarding() {
    if (homeDistrict) {
      try {
        await setHomeDistrict(Number(homeDistrict));
      } catch {
        /* non-fatal */
      }
    }
    closeAuth();
  }

  return (
    <div className="fixed inset-0 z-[200] flex items-center justify-center bg-ink/50 p-6" onClick={closeAuth}>
      <div className="w-full max-w-[480px] rounded-2xl bg-slab p-8 shadow-lg" onClick={(e) => e.stopPropagation()}>
        {step === 0 ? (
          <>
            <h2 className="mb-5 font-display text-2xl font-normal">
              {mode === "login" ? "Welcome back" : "Create your account"}
            </h2>
            <form onSubmit={handleSubmit}>
              <div className="mb-5">
                <label className="mb-1.5 block text-sm font-medium">Email</label>
                <input
                  type="email"
                  required
                  value={email}
                  onChange={(e) => setEmail(e.target.value)}
                  className="w-full rounded-lg border border-line bg-slab px-3.5 py-2.5 outline-none focus:border-ink"
                  placeholder="you@example.com"
                />
              </div>
              <div className="mb-5">
                <label className="mb-1.5 block text-sm font-medium">Password</label>
                <input
                  type="password"
                  required
                  value={password}
                  onChange={(e) => setPassword(e.target.value)}
                  className="w-full rounded-lg border border-line bg-slab px-3.5 py-2.5 outline-none focus:border-ink"
                  placeholder="••••••••"
                />
              </div>
              {error && <div className="mb-3 rounded-md bg-risk-pale px-3 py-2 text-sm text-risk">{error}</div>}
              <button
                type="submit"
                disabled={busy}
                className="w-full rounded-lg bg-ink px-4 py-3 text-sm font-medium text-on-ink disabled:opacity-70"
              >
                {busy ? "Please wait…" : mode === "login" ? "Sign In →" : "Create Account →"}
              </button>
            </form>
            <div className="mt-4 text-center text-sm text-provenance">
              {mode === "login" ? "No account? " : "Already registered? "}
              <button
                type="button"
                className="font-medium text-ink"
                onClick={() => setMode(mode === "login" ? "register" : "login")}
              >
                {mode === "login" ? "Register free" : "Sign in"}
              </button>
            </div>
          </>
        ) : (
          <div className="flex flex-col items-center gap-6 py-4 text-center">
            <div className="text-4xl">📍</div>
            <h2 className="font-display text-2xl">Where do you eat?</h2>
            <p className="max-w-[300px] text-provenance">Select your home district for personalised alerts.</p>
            <select
              className="w-full rounded-lg border border-line bg-slab px-3.5 py-2.5"
              value={homeDistrict}
              onChange={(e) => setHomeDistrictId(e.target.value)}
            >
              <option value="">{districts.data ? "Select a district…" : "Loading districts…"}</option>
              {(districts.data || []).map((d) => (
                <option key={d.id} value={d.id}>
                  {d.name}, {d.state}
                </option>
              ))}
            </select>
            <button type="button" onClick={finishOnboarding} className="rounded-lg bg-ink px-5 py-2.5 text-sm font-medium text-on-ink">
              Get Started →
            </button>
          </div>
        )}
      </div>
    </div>
  );
}
