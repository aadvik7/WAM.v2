"use client";

import { createContext, useCallback, useContext, useEffect, useState, type ReactNode } from "react";
import { api } from "@/lib/api";
import type { AdminUser, Business } from "@/lib/types";

interface Ctx {
  user: AdminUser | null;
  businesses: Business[];
  business: Business | null;
  select: (id: number) => void;
  reload: () => Promise<void>;
  loading: boolean;
}

const BusinessContext = createContext<Ctx | null>(null);
const KEY = "wam_business";

function storedId(): number | null {
  try {
    const v = window.localStorage.getItem(KEY);
    return v ? Number(v) : null;
  } catch {
    return null;
  }
}

export function BusinessProvider({ children }: { children: ReactNode }) {
  const [user, setUser] = useState<AdminUser | null>(null);
  const [businesses, setBusinesses] = useState<Business[]>([]);
  const [selected, setSelected] = useState<number | null>(null);
  const [loading, setLoading] = useState(true);

  const reload = useCallback(async () => {
    const [me, list] = await Promise.all([api<AdminUser>("/api/auth/me"), api<Business[]>("/api/businesses")]);
    setUser(me);
    setBusinesses(list);
    setSelected((current) => {
      const wanted = current ?? storedId();
      if (wanted && list.some((b) => b.id === wanted)) return wanted;
      return list[0]?.id ?? null;
    });
  }, []);

  useEffect(() => {
    reload()
      .catch(() => undefined)
      .finally(() => setLoading(false));
  }, [reload]);

  const select = useCallback((id: number) => {
    setSelected(id);
    try {
      window.localStorage.setItem(KEY, String(id));
    } catch {
      /* storage unavailable */
    }
  }, []);

  const business = businesses.find((b) => b.id === selected) ?? null;
  return (
    <BusinessContext.Provider value={{ user, businesses, business, select, reload, loading }}>
      {children}
    </BusinessContext.Provider>
  );
}

export function useBusiness(): Ctx {
  const ctx = useContext(BusinessContext);
  if (!ctx) throw new Error("useBusiness outside BusinessProvider");
  return ctx;
}

/** Path prefix for business-scoped API calls. */
export function bpath(business: Business | null, path: string): string {
  if (!business) throw new Error("No business selected");
  return `/api/businesses/${business.id}${path}`;
}
