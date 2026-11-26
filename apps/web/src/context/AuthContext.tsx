"use client";

import React, { createContext, useContext, useEffect, useState } from "react";
import { apiFetch } from "@/lib/api";

export interface DemoUser {
  id: string;
  email: string;
  name: string;
  role: string;
  tenant_id: string;
  partner_id?: string | null;
  branch?: string;
}

interface AuthState {
  token: string | null;
  user: DemoUser | null;
  demoUsers: DemoUser[];
  loading: boolean;
  error: string | null;
  switchUser: (email: string) => Promise<void>;
}

const AuthContext = createContext<AuthState>({
  token: null,
  user: null,
  demoUsers: [],
  loading: true,
  error: null,
  switchUser: async () => {},
});

export function AuthProvider({ children }: { children: React.ReactNode }) {
  const [token, setToken] = useState<string | null>(null);
  const [user, setUser] = useState<DemoUser | null>(null);
  const [demoUsers, setDemoUsers] = useState<DemoUser[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const loginAs = async (email: string) => {
    setError(null);
    const data = await apiFetch<{
      access_token: string;
      user: {
        user_id: string;
        email: string;
        name: string;
        role: string;
        tenant_id: string;
        partner_id?: string | null;
        branch?: string;
      };
    }>("/api/v1/auth/login", {
      method: "POST",
      body: JSON.stringify({ email }),
    });
    const u: DemoUser = {
      id: data.user.user_id,
      email: data.user.email,
      name: data.user.name,
      role: data.user.role,
      tenant_id: data.user.tenant_id,
      partner_id: data.user.partner_id,
      branch: data.user.branch,
    };
    setToken(data.access_token);
    setUser(u);
    if (typeof window !== "undefined") {
      window.localStorage.setItem("mc_demo_email", email);
    }
  };

  useEffect(() => {
    (async () => {
      try {
        const usersResp = await apiFetch<{ items: DemoUser[] }>("/api/v1/auth/users");
        setDemoUsers(usersResp.items);
        const savedEmail =
          typeof window !== "undefined"
            ? window.localStorage.getItem("mc_demo_email")
            : null;
        await loginAs(savedEmail || "handler@demo.in");
      } catch (e) {
        setError(e instanceof Error ? e.message : "Failed to connect to backend API");
      } finally {
        setLoading(false);
      }
    })();
  }, []);

  return (
    <AuthContext.Provider
      value={{ token, user, demoUsers, loading, error, switchUser: loginAs }}
    >
      {children}
    </AuthContext.Provider>
  );
}

export function useAuth() {
  return useContext(AuthContext);
}
