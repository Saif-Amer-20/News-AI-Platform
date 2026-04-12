"use client";

import { ShieldAlert, TrendingUp, Target, AlertTriangle } from "lucide-react";

export function ScoreBadge({ label, value, max = 1 }: { label: string; value: number; max?: number }) {
  const v = Number(value) || 0;
  const pct = Math.min(100, (v / max) * 100);
  const color = pct >= 75 ? "#dc2626" : pct >= 50 ? "#f59e0b" : pct >= 25 ? "#2563eb" : "#64748b";
  return (
    <div className="score-badge">
      <div className="score-badge-bar">
        <div className="score-badge-fill" style={{ width: `${pct}%`, background: color }} />
      </div>
      <div className="score-badge-info">
        <span className="score-badge-value" style={{ color }}>{v.toFixed(2)}</span>
        <span className="score-badge-label">{label}</span>
      </div>
    </div>
  );
}

export function ConfidenceBadge({ value }: { value: number }) {
  const pct = Math.round(Number(value) * 100) || 0;
  return (
    <span className="inline-score" title={`Confidence: ${pct}%`}>
      <Target size={13} />
      <span>{pct}%</span>
    </span>
  );
}

export function ImportanceBadge({ value }: { value: number }) {
  const display = (Number(value) || 0).toFixed(2);
  return (
    <span className="inline-score inline-score--importance" title={`Importance: ${display}`}>
      <TrendingUp size={13} />
      <span>{display}</span>
    </span>
  );
}

export function ConflictBadge() {
  return (
    <span className="badge badge-red" style={{ gap: 3, display: "inline-flex", alignItems: "center" }}>
      <ShieldAlert size={12} /> conflict
    </span>
  );
}

export function SeverityBadge({ severity }: { severity: string }) {
  const cls: Record<string, string> = {
    critical: "badge-red", high: "badge-amber", medium: "badge-blue", low: "badge-gray",
  };
  return (
    <span className={`badge ${cls[severity] ?? "badge-gray"}`}>
      {severity === "critical" && <AlertTriangle size={11} style={{ marginRight: 3 }} />}
      {severity}
    </span>
  );
}

export function StatusBadge({ status }: { status: string }) {
  const cls: Record<string, string> = {
    open: "badge-red", acknowledged: "badge-amber", resolved: "badge-green",
    dismissed: "badge-gray", closed: "badge-green", in_progress: "badge-amber",
    archived: "badge-gray", escalated: "badge-red",
  };
  return <span className={`badge ${cls[status] ?? "badge-gray"}`}>{status.replace("_", " ")}</span>;
}
