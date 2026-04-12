"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import {
  LayoutDashboard,
  Radar,
  Users,
  Bell,
  FolderOpen,
  Map,
  Clock,
  Search,
  Activity,
  Newspaper,
} from "lucide-react";
import type { ReactNode } from "react";

const NAV_ITEMS = [
  { section: "Intelligence" },
  { href: "/",          label: "Dashboard",  icon: LayoutDashboard },
  { href: "/events",    label: "Events",     icon: Radar },
  { href: "/articles",  label: "Articles",   icon: Newspaper },
  { href: "/entities",  label: "Entities",   icon: Users },
  { href: "/map",       label: "Map",        icon: Map },
  { href: "/timeline",  label: "Timeline",   icon: Clock },
  { section: "Operations" },
  { href: "/alerts",    label: "Alerts",     icon: Bell },
  { href: "/cases",     label: "Cases",      icon: FolderOpen },
  { href: "/search",    label: "Search",     icon: Search },
] as const;

export function Sidebar() {
  const pathname = usePathname();

  return (
    <aside className="sidebar">
      <div className="sidebar-brand">
        <Activity size={22} />
        <span>NewsIntel</span>
      </div>
      <nav>
        {NAV_ITEMS.map((item, i) => {
          if ("section" in item) {
            return (
              <div key={i} className="sidebar-section">
                {item.section}
              </div>
            );
          }
          const Icon = item.icon;
          const active =
            item.href === "/"
              ? pathname === "/"
              : pathname.startsWith(item.href);
          return (
            <Link
              key={item.href}
              href={item.href}
              className={active ? "active" : ""}
            >
              <Icon />
              {item.label}
            </Link>
          );
        })}
      </nav>
    </aside>
  );
}

export function PageShell({
  title,
  children,
}: {
  title: string;
  children: ReactNode;
}) {
  return (
    <div className="main-area">
      <header className="topbar">
        <span className="topbar-title">{title}</span>
      </header>
      <div className="page-content">{children}</div>
    </div>
  );
}
