"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import type { ReactNode } from "react";
import { logout } from "@/lib/api";
import { useBusiness } from "@/lib/business";
import { cls } from "@/lib/format";
import { Toaster } from "@/components/ui";

const NAV: { section?: string; href: string; label: string; superOnly?: boolean }[] = [
  { href: "/", label: "Today" },
  { href: "/patients", label: "Patients" },
  { href: "/plans", label: "Plans" },
  { href: "/appointments", label: "Appointments" },
  { href: "/reports", label: "Reports" },
  { section: "Settings", href: "/setup", label: "Setup" },
  { href: "/messages", label: "Messages" },
  { href: "/simulator", label: "Simulator" },
  { href: "/templates", label: "WhatsApp templates" },
  { href: "/audit", label: "Audit log" },
  { href: "/businesses", label: "Businesses", superOnly: true },
];

export function Shell({ children }: { children: ReactNode }) {
  const pathname = usePathname();
  const { user, businesses, business, select, loading } = useBusiness();
  const isSuper = user?.business_id === null;
  return (
    <div className="shell">
      <aside className="sidebar">
        <div className="brand">
          <span className="brand-dot" aria-hidden>W</span> WAM
        </div>
        <nav className="nav" aria-label="Main">
          {NAV.filter((n) => !n.superOnly || isSuper).map((n) => (
            <div key={n.href}>
              {n.section && <div className="nav-section">{n.section}</div>}
              <Link
                href={n.href}
                className={cls((n.href === "/" ? pathname === "/" : pathname.startsWith(n.href)) && "active")}
              >
                {n.label}
              </Link>
            </div>
          ))}
        </nav>
        <div className="sidebar-foot">
          {businesses.length > 1 && (
            <select aria-label="Business" value={business?.id ?? ""} onChange={(e) => select(Number(e.target.value))}>
              {businesses.map((b) => (
                <option key={b.id} value={b.id}>
                  {b.name}
                </option>
              ))}
            </select>
          )}
          {businesses.length === 1 && <div className="small muted">{business?.name}</div>}
          <div className="small muted" title={user?.email}>{user?.email}</div>
          <button className="btn small" onClick={() => void logout()}>Sign out</button>
        </div>
      </aside>
      <main className="main">
        {loading ? (
          <div className="empty">Loading…</div>
        ) : !business && !pathname.startsWith("/businesses") ? (
          <div className="card">
            <h2>No business yet</h2>
            <p className="muted">
              {isSuper ? (
                <>
                  Create your first clinic on the <Link href="/businesses">Businesses</Link> page.
                </>
              ) : (
                "Your account isn't linked to a business. Ask the WAM administrator."
              )}
            </p>
          </div>
        ) : (
          children
        )}
      </main>
      <Toaster />
    </div>
  );
}
