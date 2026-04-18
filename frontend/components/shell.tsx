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
  Brain,
  Network,
} from "lucide-react";
import type { ReactNode } from "react";

const NAV_ITEMS = [
  { section: "Intelligence" },
  { href: "/",          label: "Dashboard",  icon: LayoutDashboard },
  { href: "/events",    label: "Events",     icon: Radar },
  { href: "/articles",  label: "Articles",   icon: Newspaper },
  { href: "/entities",              label: "Entities",         icon: Users },
  { href: "/entities/intelligence", label: "Entity Intel",     icon: Network },
  { href: "/entities/intelligence/graph",   label: "Graph Explorer",  icon: Network, indent: true },
  { href: "/entities/intelligence/signals", label: "Signals",         icon: Bell, indent: true },
  { href: "/map",       label: "Map",        icon: Map },
  { href: "/timeline",  label: "Timeline",   icon: Clock },
  { section: "Operations" },
  { href: "/alerts",    label: "Alerts",     icon: Bell },
  { href: "/cases",     label: "Cases",      icon: FolderOpen },
  { href: "/search",    label: "Search",     icon: Search },
  { section: "Learning" },
  { href: "/learning",  label: "Self-Learning", icon: Brain },
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
          const active = pathname === item.href;
          const indent = "indent" in item && item.indent;
          return (
            <Link
              key={item.href}
              href={item.href}
              className={active ? "active" : ""}
              style={indent ? { paddingLeft: "2.2rem", fontSize: "0.82rem" } : undefined}
            >
              {indent ? <Icon size={14} /> : <Icon />}
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
