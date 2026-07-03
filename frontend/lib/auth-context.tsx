"use client";

import { createContext, useContext, useEffect, useState, useCallback } from "react";
import { tokenStore } from "./api/client";
import { fetchProfile } from "./api/auth";
import type { CurrentUserProfile } from "./api/types";

interface AuthState {
  token: string | null;
  user: CurrentUserProfile | null;
  showAuthModal: boolean;
  openAuth: () => void;
  closeAuth: () => void;
  onAuthenticated: (accessToken: string, profile: CurrentUserProfile) => void;
  logout: () => void;
}

const AuthContext = createContext<AuthState | null>(null);

export function AuthProvider({ children }: { children: React.ReactNode }) {
  const [token, setToken] = useState<string | null>(null);
  const [user, setUser] = useState<CurrentUserProfile | null>(null);
  const [showAuthModal, setShowAuthModal] = useState(false);

  useEffect(() => {
    const t = tokenStore.get();
    if (!t) return;
    setToken(t);
    fetchProfile()
      .then((p) => setUser(p))
      .catch(() => {
        tokenStore.clear();
        setToken(null);
        setUser(null);
      });
  }, []);

  const onAuthenticated = useCallback((accessToken: string, profile: CurrentUserProfile) => {
    tokenStore.set(accessToken);
    setToken(accessToken);
    setUser(profile);
    setShowAuthModal(false);
  }, []);

  const logout = useCallback(() => {
    tokenStore.clear();
    setToken(null);
    setUser(null);
  }, []);

  return (
    <AuthContext.Provider
      value={{
        token,
        user,
        showAuthModal,
        openAuth: () => setShowAuthModal(true),
        closeAuth: () => setShowAuthModal(false),
        onAuthenticated,
        logout,
      }}
    >
      {children}
    </AuthContext.Provider>
  );
}

export function useAuth() {
  const ctx = useContext(AuthContext);
  if (!ctx) throw new Error("useAuth must be used within AuthProvider");
  return ctx;
}
