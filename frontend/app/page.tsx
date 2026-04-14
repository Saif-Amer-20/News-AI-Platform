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
  Activity,
  TrendingUp,
  MapPin,
  Zap,
  Shield,
} from "lucide-react";
import type {
  EarlyWarningDashboardSummary,
  EarlyWarningAnomaly,
  PredictiveScore,
  GeoRadarZone,
} from "@/lib/types";
import {
  EARLY_WARNING_ANOMALY_LABELS,
  RISK_TREND_LABELS,
  RISK_TREND_COLORS,
  TEMPORAL_TREND_LABELS,
  SEVERITY_BADGE,
} from "@/lib/types";

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

export default function DashboardPage() {
  const [overview, setOverview] = useState<Overview | null>(null);
  const [events, setEvents] = useState<PriorityEvent[]>([]);
  const [alerts, setAlerts] = useState<RecentAlert[]>([]);
  const [earlyWarning, setEarlyWarning] = useState<EarlyWarningDashboardSummary | null>(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    async function load() {
      try {
        const [ov, ev, al, ew] = await Promise.all([
          api<Overview>("/dashboard/overview/"),
          api<{ events: PriorityEvent[] }>("/dashboard/high-priority-events/?limit=8"),
          api<{ alerts: RecentAlert[] }>("/dashboard/recent-alerts/?limit=8"),
          api<EarlyWarningDashboardSummary>("/early-warning/dashboard/summary/").catch(() => null),
        ]);
        setOverview(ov);
        setEvents(ev.events);
        setAlerts(al.alerts);
        setEarlyWarning(ew);
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

      {/* ── Early Warning Section ─────────────────────────────── */}
      {earlyWarning && (
        <div className="ew-section" style={{ marginTop: "1.5rem" }}>
          <h3 style={{ fontSize: "1rem", fontWeight: 700, marginBottom: "1rem", display: "flex", alignItems: "center", gap: 6 }}>
            <Shield size={18} /> Early Warning & Predictive Intelligence
          </h3>

          {/* EW KPI Row */}
          <div className="stat-grid" style={{ marginBottom: "1rem" }}>
            <StatCard icon={<Activity size={18} />} label="Active Anomalies" value={earlyWarning.anomaly_stats.total_active} sub={`${earlyWarning.anomaly_stats.critical} critical`} accent={earlyWarning.anomaly_stats.critical > 0} />
            <StatCard icon={<TrendingUp size={18} />} label="Rising Risk" value={earlyWarning.rising_risk_events} sub="Events with rising risk" accent={earlyWarning.rising_risk_events > 0} />
            <StatCard icon={<MapPin size={18} />} label="Hot Zones" value={earlyWarning.active_hot_zones} sub="Active geographic zones" />
            <StatCard icon={<Zap size={18} />} label="Correlations" value={earlyWarning.active_correlations} sub="Signal links detected" />
          </div>

          <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: "1.5rem" }}>
            {/* Top Anomalies */}
            <div className="data-table-wrap">
              <div style={{ padding: "1rem 1rem 0" }}>
                <h3 style={{ margin: 0, fontSize: "0.95rem", fontWeight: 700 }}>
                  <Activity size={14} style={{ marginRight: 4, verticalAlign: "middle" }} />
                  Top Anomaly Signals
                </h3>
              </div>
              <table className="data-table">
                <thead>
                  <tr><th>Signal</th><th>Type</th><th>Severity</th><th>Deviation</th></tr>
                </thead>
                <tbody>
                  {earlyWarning.top_anomalies.length === 0 ? (
                    <tr><td colSpan={4} className="empty-state">No active anomalies</td></tr>
                  ) : earlyWarning.top_anomalies.map((a) => (
                    <tr key={a.id}>
                      <td style={{ fontWeight: 500, maxWidth: 240, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>{a.title}</td>
                      <td><span className="badge badge-blue">{EARLY_WARNING_ANOMALY_LABELS[a.anomaly_type] || a.anomaly_type}</span></td>
                      <td><span className={`badge ${SEVERITY_BADGE[a.severity] ?? "badge-gray"}`}>{a.severity}</span></td>
                      <td style={{ fontFamily: "monospace" }}>{Number(a.deviation_factor).toFixed(1)}σ</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>

            {/* Top Predictive Scores */}
            <div className="data-table-wrap">
              <div style={{ padding: "1rem 1rem 0" }}>
                <h3 style={{ margin: 0, fontSize: "0.95rem", fontWeight: 700 }}>
                  <TrendingUp size={14} style={{ marginRight: 4, verticalAlign: "middle" }} />
                  Highest Monitoring Priority
                </h3>
              </div>
              <table className="data-table">
                <thead>
                  <tr><th>Event</th><th>Escalation</th><th>Priority</th><th>Trend</th></tr>
                </thead>
                <tbody>
                  {earlyWarning.top_predictions.length === 0 ? (
                    <tr><td colSpan={4} className="empty-state">No predictions yet</td></tr>
                  ) : earlyWarning.top_predictions.map((p) => (
                    <tr key={p.id}>
                      <td style={{ fontWeight: 500 }}>Event #{p.event}</td>
                      <td>
                        <span className="ew-prob-bar">
                          <span className="ew-prob-fill ew-prob-fill--esc" style={{ width: `${parseFloat(p.escalation_probability) * 100}%` }} />
                        </span>
                        <span style={{ fontSize: "0.8rem", marginLeft: 4 }}>{(parseFloat(p.escalation_probability) * 100).toFixed(0)}%</span>
                      </td>
                      <td>
                        <span className="ew-prob-bar">
                          <span className="ew-prob-fill ew-prob-fill--pri" style={{ width: `${parseFloat(p.monitoring_priority) * 100}%` }} />
                        </span>
                        <span style={{ fontSize: "0.8rem", marginLeft: 4 }}>{(parseFloat(p.monitoring_priority) * 100).toFixed(0)}%</span>
                      </td>
                      <td>
                        <span style={{ color: RISK_TREND_COLORS[p.risk_trend] || "#6b7280", fontWeight: 600, fontSize: "0.85rem" }}>
                          {RISK_TREND_LABELS[p.risk_trend] || p.risk_trend}
                        </span>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </div>

          {/* Hot Zones */}
          {earlyWarning.hot_zones.length > 0 && (
            <div className="data-table-wrap" style={{ marginTop: "1rem" }}>
              <div style={{ padding: "1rem 1rem 0" }}>
                <h3 style={{ margin: 0, fontSize: "0.95rem", fontWeight: 700 }}>
                  <MapPin size={14} style={{ marginRight: 4, verticalAlign: "middle" }} />
                  Geographic Hot Zones
                </h3>
              </div>
              <table className="data-table">
                <thead>
                  <tr><th>Zone</th><th>Country</th><th>Events</th><th>Concentration</th><th>Trend</th></tr>
                </thead>
                <tbody>
                  {earlyWarning.hot_zones.map((z) => (
                    <tr key={z.id}>
                      <td style={{ fontWeight: 500 }}>{z.title}</td>
                      <td><span className="badge badge-gray">{z.location_country || "—"}</span></td>
                      <td>{z.event_count}</td>
                      <td style={{ fontFamily: "monospace" }}>{Number(z.event_concentration).toFixed(1)}/100km²</td>
                      <td>
                        <span style={{ fontSize: "0.85rem" }}>
                          {TEMPORAL_TREND_LABELS[z.temporal_trend] || z.temporal_trend}
                        </span>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </div>
      )}
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
