"use client";

import { useEffect, useState } from "react";
import { PageShell } from "@/components/shell";
import { api } from "@/lib/api";
import {
  Radar,
  Newspaper,
  Bell,
  FolderOpen,
  Users,
  BookOpen,
  AlertTriangle,
  Server,
} from "lucide-react";

type Overview = {
  generated_at: string;
  events: { total: number; last_24h: number; last_7d: number; conflicts: number; high_importance: number };
  articles: { total: number; last_24h: number };
  stories: { total: number; last_24h: number };
  sources: { active: number; unhealthy: number; avg_trust_score: number };
  alerts: { open: number; critical: number; last_24h: number };
  cases: { open: number };
  entities: { total: number };
};

type PriorityEvent = {
  id: number;
  title: string;
  event_type: string;
  location_country: string;
  importance_score: number;
  source_count: number;
  conflict_flag: boolean;
  first_reported_at: string;
};

type RecentAlert = {
  id: number;
  title: string;
  alert_type: string;
  severity: string;
  status: string;
  triggered_at: string;
};

const SEVERITY_BADGE: Record<string, string> = {
  critical: "badge-red",
  high: "badge-amber",
  medium: "badge-blue",
  low: "badge-gray",
};

export default function DashboardPage() {
  const [overview, setOverview] = useState<Overview | null>(null);
  const [events, setEvents] = useState<PriorityEvent[]>([]);
  const [alerts, setAlerts] = useState<RecentAlert[]>([]);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    async function load() {
      try {
        const [ov, ev, al] = await Promise.all([
          api<Overview>("/dashboard/overview/"),
          api<{ events: PriorityEvent[] }>("/dashboard/high-priority-events/?limit=8"),
          api<{ alerts: RecentAlert[] }>("/dashboard/recent-alerts/?limit=8"),
        ]);
        setOverview(ov);
        setEvents(ev.events);
        setAlerts(al.alerts);
      } catch {
        // API not available yet — show empty state
      } finally {
        setLoading(false);
      }
    }
    void load();
  }, []);

  if (loading) {
    return (
      <PageShell title="Dashboard">
        <div className="loading-state">
          <div className="loading-spinner" />
          Loading dashboard…
        </div>
      </PageShell>
    );
  }

  const ov = overview;

  return (
    <PageShell title="Dashboard — Command Center">
      {/* ── KPI Grid ──────────────────────────────────────────── */}
      <div className="stat-grid" style={{ marginBottom: "1.5rem" }}>
        <StatCard icon={<Radar size={18} />} label="Events" value={ov?.events.total ?? 0} sub={`${ov?.events.last_24h ?? 0} in last 24h`} />
        <StatCard icon={<Newspaper size={18} />} label="Articles" value={ov?.articles.total ?? 0} sub={`${ov?.articles.last_24h ?? 0} in last 24h`} />
        <StatCard icon={<BookOpen size={18} />} label="Stories" value={ov?.stories.total ?? 0} sub={`${ov?.stories.last_24h ?? 0} new today`} />
        <StatCard icon={<Users size={18} />} label="Entities" value={ov?.entities.total ?? 0} />
        <StatCard icon={<Bell size={18} />} label="Open Alerts" value={ov?.alerts.open ?? 0} sub={`${ov?.alerts.critical ?? 0} critical`} accent={!!ov?.alerts.critical} />
        <StatCard icon={<AlertTriangle size={18} />} label="Conflicts" value={ov?.events.conflicts ?? 0} sub="Narrative conflicts" accent />
        <StatCard icon={<FolderOpen size={18} />} label="Open Cases" value={ov?.cases.open ?? 0} />
        <StatCard icon={<Server size={18} />} label="Active Sources" value={ov?.sources.active ?? 0} sub={`${ov?.sources.unhealthy ?? 0} unhealthy`} />
      </div>

      <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: "1.5rem" }}>
        {/* ── High-Priority Events ────────────────────────────── */}
        <div className="data-table-wrap">
          <div style={{ padding: "1rem 1rem 0" }}>
            <h3 style={{ margin: 0, fontSize: "0.95rem", fontWeight: 700 }}>High-Priority Events</h3>
          </div>
          <table className="data-table">
            <thead>
              <tr><th>Event</th><th>Type</th><th>Sources</th><th>Score</th></tr>
            </thead>
            <tbody>
              {events.length === 0 ? (
                <tr><td colSpan={4} className="empty-state">No events yet</td></tr>
              ) : events.map((e) => (
                <tr key={e.id}>
                  <td>
                    <span style={{ fontWeight: 600 }}>{e.title}</span>
                    {e.conflict_flag && <span className="badge badge-red" style={{ marginLeft: 6 }}>conflict</span>}
                  </td>
                  <td><span className="badge badge-blue">{e.event_type}</span></td>
                  <td>{e.source_count}</td>
                  <td>{Number(e.importance_score).toFixed(2)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>

        {/* ── Recent Alerts ───────────────────────────────────── */}
        <div className="data-table-wrap">
          <div style={{ padding: "1rem 1rem 0" }}>
            <h3 style={{ margin: 0, fontSize: "0.95rem", fontWeight: 700 }}>Recent Alerts</h3>
          </div>
          <table className="data-table">
            <thead>
              <tr><th>Alert</th><th>Type</th><th>Severity</th><th>Time</th></tr>
            </thead>
            <tbody>
              {alerts.length === 0 ? (
                <tr><td colSpan={4} className="empty-state">No alerts yet</td></tr>
              ) : alerts.map((a) => (
                <tr key={a.id}>
                  <td style={{ fontWeight: 500 }}>{a.title}</td>
                  <td><span className="badge badge-gray">{a.alert_type}</span></td>
                  <td><span className={`badge ${SEVERITY_BADGE[a.severity] ?? "badge-gray"}`}>{a.severity}</span></td>
                  <td style={{ fontSize: "0.82rem", color: "#64748b" }}>{new Date(a.triggered_at).toLocaleString()}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </div>
    </PageShell>
  );
}

function StatCard({ icon, label, value, sub, accent }: {
  icon: React.ReactNode; label: string; value: number; sub?: string; accent?: boolean;
}) {
  return (
    <div className="stat-card">
      <div style={{ display: "flex", alignItems: "center", gap: 6, color: "#64748b" }}>
        {icon}
        <span className="label">{label}</span>
      </div>
      <span className="value" style={accent ? { color: "#dc2626" } : undefined}>
        {value.toLocaleString()}
      </span>
      {sub && <span className="sub">{sub}</span>}
    </div>
  );
}
