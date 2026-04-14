"use client";

import { useEffect, useState, useCallback } from "react";
import { PageShell } from "@/components/shell";
import { api } from "@/lib/api";
import {
  TrendingUp, AlertTriangle, CheckCircle,
  Activity, Shield, BarChart3, RefreshCw, Gauge, Brain,
} from "lucide-react";
import type { LearningDashboardSummary, AdaptiveThreshold, SourceReputationLog } from "@/lib/types";
import {
  FEEDBACK_TYPE_LABELS,
  FEEDBACK_TYPE_COLORS,
  ACCURACY_STATUS_LABELS,
  ACCURACY_STATUS_COLORS,
} from "@/lib/types";

/* helper — group thresholds by category prefix */
function groupThresholds(list: AdaptiveThreshold[]) {
  const groups: Record<string, AdaptiveThreshold[]> = {};
  for (const t of list) {
    const cat = t.param_name.split(".")[0] ?? "other";
    (groups[cat] ??= []).push(t);
  }
  return groups;
}

const CATEGORY_LABELS: Record<string, string> = {
  anomaly: "Anomaly Detection",
  predict: "Predictive Weights",
  escalation: "Escalation Sensitivity",
  source: "Source Trust",
};

export default function LearningPage() {
  const [data, setData] = useState<LearningDashboardSummary | null>(null);
  const [loading, setLoading] = useState(true);

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const d = await api<LearningDashboardSummary>("/learning/dashboard/summary/");
      setData(d);
    } catch { /* empty */ } finally { setLoading(false); }
  }, []);

  useEffect(() => { void load(); }, [load]);

  if (loading) {
    return (
      <PageShell title="Self-Learning Intelligence">
        <div className="loading-state"><div className="loading-spinner" />Loading…</div>
      </PageShell>
    );
  }

  if (!data) {
    return (
      <PageShell title="Self-Learning Intelligence">
        <div className="empty-state">No data available</div>
      </PageShell>
    );
  }

  const { feedback_stats, accuracy_stats, learning_stats, accuracy_history, recent_reputation_changes, active_thresholds } = data;
  const thresholdGroups = groupThresholds(active_thresholds);
  const fpRate = (feedback_stats.false_positive_rate * 100);
  const accRate = (accuracy_stats.accuracy_rate * 100);

  return (
    <PageShell title="Self-Learning Intelligence">
      {/* ── KPI Row ───────────────────────────────────────────── */}
      <div className="stat-grid" style={{ marginBottom: "1.5rem" }}>
        <StatCard icon={<BarChart3 size={18} />} label="Total Feedback" value={feedback_stats.total_feedback} sub={`${Object.keys(feedback_stats.by_feedback_type ?? {}).length} types recorded`} />
        <StatCard icon={<AlertTriangle size={18} />} label="False Positive Rate" value={fpRate} suffix="%" sub={fpRate > 20 ? "Above target threshold" : "Within acceptable range"} accent={fpRate > 20} />
        <StatCard icon={<CheckCircle size={18} />} label="Prediction Accuracy" value={accRate} suffix="%" sub={`${accuracy_stats.total_resolved} outcomes resolved`} />
        <StatCard icon={<Activity size={18} />} label="Learning Records" value={learning_stats.total_records} sub={learning_stats.latest_at ? `Last: ${new Date(learning_stats.latest_at).toLocaleDateString()}` : "No records yet"} />
      </div>

      <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: "1.5rem" }}>
        {/* ── Feedback Distribution ───────────────────────────── */}
        <div className="data-table-wrap">
          <div className="sl-card-header">
            <h3><TrendingUp size={15} /> Feedback Distribution</h3>
          </div>
          <div className="sl-card-body">
            {Object.keys(feedback_stats.by_feedback_type ?? {}).length === 0 ? (
              <div className="empty-state">No feedback submitted yet</div>
            ) : (
              <div className="sl-bar-list">
                {Object.entries(feedback_stats.by_feedback_type ?? {}).map(([type, count]) => {
                  const pct = feedback_stats.total_feedback > 0 ? ((count as number) / feedback_stats.total_feedback) * 100 : 0;
                  return (
                    <div key={type} className="sl-bar-row">
                      <span className={`badge ${FEEDBACK_TYPE_COLORS[type as keyof typeof FEEDBACK_TYPE_COLORS] ?? "badge-gray"}`}>
                        {FEEDBACK_TYPE_LABELS[type as keyof typeof FEEDBACK_TYPE_LABELS] ?? type}
                      </span>
                      <div className="sl-bar-track">
                        <div className="sl-bar-fill" style={{ width: `${pct}%` }} />
                      </div>
                      <span className="sl-bar-value">{count as number}</span>
                    </div>
                  );
                })}
              </div>
            )}
          </div>
        </div>

        {/* ── Accuracy Status ─────────────────────────────────── */}
        <div className="data-table-wrap">
          <div className="sl-card-header">
            <h3><Shield size={15} /> Accuracy Status</h3>
          </div>
          <div className="sl-card-body">
            <div className="sl-accuracy-ring-row">
              <div className="sl-ring-wrap">
                <svg viewBox="0 0 36 36" className="sl-ring">
                  <path className="sl-ring-bg" d="M18 2.0845a15.9155 15.9155 0 0 1 0 31.831a15.9155 15.9155 0 0 1 0-31.831" />
                  <path className="sl-ring-fill" strokeDasharray={`${accRate}, 100`} d="M18 2.0845a15.9155 15.9155 0 0 1 0 31.831a15.9155 15.9155 0 0 1 0-31.831" />
                </svg>
                <span className="sl-ring-label">{accRate.toFixed(0)}%</span>
              </div>
              <div className="sl-accuracy-breakdown">
                {Object.entries(accuracy_stats.by_status ?? {}).map(([status, count]) => (
                  <div key={status} className="sl-accuracy-row">
                    <span className={`badge-sm ${ACCURACY_STATUS_COLORS[status as keyof typeof ACCURACY_STATUS_COLORS] ?? "badge-gray"}`}>
                      {ACCURACY_STATUS_LABELS[status as keyof typeof ACCURACY_STATUS_LABELS] ?? status}
                    </span>
                    <span className="sl-accuracy-count">{count as number}</span>
                  </div>
                ))}
              </div>
            </div>
          </div>
        </div>

        {/* ── Accuracy History Chart ──────────────────────────── */}
        <div className="data-table-wrap" style={{ gridColumn: "1 / -1" }}>
          <div className="sl-card-header">
            <h3><BarChart3 size={15} /> Accuracy Trend — Last 14 Days</h3>
          </div>
          <div className="sl-card-body">
            {accuracy_history.length === 0 ? (
              <div className="empty-state">No accuracy history data yet</div>
            ) : (
              <div className="sl-chart">
                {accuracy_history.map((entry, i) => {
                  const pct = entry.rate * 100;
                  return (
                    <div key={i} className="sl-chart-col" title={`${entry.date}: ${pct.toFixed(0)}% (${entry.accurate}/${entry.total})`}>
                      <div className="sl-chart-bar-wrap">
                        <div className="sl-chart-bar" style={{ height: `${Math.max(pct, 2)}%`, background: pct >= 80 ? "#22c55e" : pct >= 50 ? "#f59e0b" : "#ef4444" }} />
                      </div>
                      <span className="sl-chart-day">
                        {new Date(entry.date).toLocaleDateString("en-US", { month: "short", day: "numeric" })}
                      </span>
                    </div>
                  );
                })}
              </div>
            )}
          </div>
        </div>

        {/* ── Adaptive Thresholds ─────────────────────────────── */}
        <div className="data-table-wrap">
          <div className="sl-card-header">
            <h3><Gauge size={15} /> Adaptive Thresholds</h3>
            <span className="sl-header-badge">{active_thresholds.length} active</span>
          </div>
          <div className="sl-card-body" style={{ padding: 0 }}>
            {active_thresholds.length === 0 ? (
              <div className="empty-state" style={{ padding: "1.5rem" }}>No thresholds configured</div>
            ) : (
              Object.entries(thresholdGroups).map(([cat, items]) => (
                <div key={cat} className="sl-threshold-group">
                  <div className="sl-threshold-cat">{CATEGORY_LABELS[cat] ?? cat}</div>
                  <table className="data-table">
                    <thead>
                      <tr><th>Parameter</th><th>Current</th><th>Default</th><th>Range</th><th>Ver</th></tr>
                    </thead>
                    <tbody>
                      {items.map((t) => {
                        const name = t.param_name.split(".").slice(1).join(".").replace(/_/g, " ");
                        const changed = t.previous_value && t.previous_value !== t.current_value;
                        return (
                          <tr key={t.id}>
                            <td style={{ fontWeight: 500, textTransform: "capitalize" }}>{name}</td>
                            <td>
                              <span className={`sl-th-value ${changed ? "sl-th-changed" : ""}`}>
                                {Number(t.current_value).toFixed(3)}
                              </span>
                              {changed && (
                                <span className="sl-th-prev">← {Number(t.previous_value).toFixed(3)}</span>
                              )}
                            </td>
                            <td style={{ color: "#64748b" }}>{Number(t.default_value).toFixed(3)}</td>
                            <td style={{ color: "#94a3b8", fontSize: "0.78rem" }}>{Number(t.min_value).toFixed(2)} – {Number(t.max_value).toFixed(2)}</td>
                            <td><span className="badge badge-gray">v{t.version}</span></td>
                          </tr>
                        );
                      })}
                    </tbody>
                  </table>
                </div>
              ))
            )}
          </div>
        </div>

        {/* ── Source Reputation Changes ────────────────────────── */}
        <div className="data-table-wrap">
          <div className="sl-card-header">
            <h3><RefreshCw size={15} /> Recent Reputation Changes</h3>
          </div>
          <div className="sl-card-body" style={{ padding: 0 }}>
            {recent_reputation_changes.length === 0 ? (
              <div className="empty-state" style={{ padding: "1.5rem" }}>No reputation changes recorded</div>
            ) : (
              <table className="data-table">
                <thead>
                  <tr><th>Source</th><th>Change</th><th>Trust</th><th>Reason</th></tr>
                </thead>
                <tbody>
                  {recent_reputation_changes.map((log: SourceReputationLog) => {
                    const delta = Number(log.change_delta);
                    const sign = delta >= 0 ? "+" : "";
                    return (
                      <tr key={log.id}>
                        <td style={{ fontWeight: 600 }}>{log.source_name}</td>
                        <td>
                          <span className={delta >= 0 ? "text-green" : "text-red"} style={{ fontWeight: 700 }}>
                            {sign}{delta.toFixed(3)}
                          </span>
                        </td>
                        <td style={{ color: "#64748b" }}>{Number(log.previous_trust).toFixed(2)} → {Number(log.new_trust).toFixed(2)}</td>
                        <td><span className="badge badge-gray">{log.reason.replace(/_/g, " ")}</span></td>
                      </tr>
                    );
                  })}
                </tbody>
              </table>
            )}
          </div>
        </div>
      </div>
    </PageShell>
  );
}

/* ── Stat Card (same pattern as main dashboard) ────────────── */
function StatCard({ icon, label, value, suffix, sub, accent }: {
  icon: React.ReactNode; label: string; value: number; suffix?: string; sub?: string; accent?: boolean;
}) {
  return (
    <div className="stat-card">
      <div style={{ display: "flex", alignItems: "center", gap: 6, color: "#64748b" }}>
        {icon}
        <span className="label">{label}</span>
      </div>
      <span className="value" style={accent ? { color: "#dc2626" } : undefined}>
        {Number.isInteger(value) ? value.toLocaleString() : value.toFixed(1)}{suffix ?? ""}
      </span>
      {sub && <span className="sub">{sub}</span>}
    </div>
  );
}
