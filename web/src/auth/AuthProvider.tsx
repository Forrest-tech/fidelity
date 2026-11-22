import { createContext, useContext } from "react";
import type { ReactNode } from "react";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { api, ApiError } from "../net/client";

export type Role = "admin" | "reviewer" | "viewer";
export interface Me {
  id: string;
  email: string;
  role: Role;
}

interface AuthState {
  me: Me | null;
  loading: boolean;
  error: Error | null;
  login: (email: string, password: string, captcha?: string | null) => Promise<void>;
  /** Read the session again (after the first-run set-up signed the new administrator in). */
  refresh: () => Promise<void>;
  logout: () => Promise<void>;
}

const Ctx = createContext<AuthState | null>(null);

export function AuthProvider({ children }: { children: ReactNode }) {
  const qc = useQueryClient();
  const q = useQuery<Me | null>({
    queryKey: ["me"],
    retry: false,
    staleTime: 60_000,
    queryFn: async () => {
      try {
        return await api<Me>("/me");
      } catch (e) {
        if (e instanceof ApiError && e.status === 401) return null; // not signed in
        throw e;
      }
    },
  });

  const login = async (email: string, password: string, captcha?: string | null) => {
    const body = new URLSearchParams({ username: email.trim(), password });
    if (captcha) body.set("altcha", captcha);
    await api("/auth/login", {
      method: "POST",
      body,
      headers: { "Content-Type": "application/x-www-form-urlencoded" },
    });
    await qc.invalidateQueries({ queryKey: ["me"] });
  };
  const refresh = () => qc.invalidateQueries({ queryKey: ["me"] });
  const logout = async () => {
    try {
      await api("/auth/logout", { method: "POST" });
    } finally {
      qc.setQueryData(["me"], null);
      qc.removeQueries({ predicate: (x) => x.queryKey[0] !== "me" });
    }
  };

  return (
    <Ctx.Provider value={{ me: q.data ?? null, loading: q.isLoading, error: q.error as Error | null, login, logout, refresh }}>
      {children}
    </Ctx.Provider>
  );
}

export function useAuth(): AuthState {
  const v = useContext(Ctx);
  if (!v) throw new Error("useAuth outside AuthProvider");
  return v;
}
