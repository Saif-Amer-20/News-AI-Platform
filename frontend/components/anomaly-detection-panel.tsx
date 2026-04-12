"use client";

import { useState, useMemo } from "react";
import {
  Zap, TrendingUp, AlertTriangle, X, ChevronDown, ChevronRight,
  Globe, UserPlus, Activity,
} from "lucide-react";
import type { AnomalySignal, AnomalyType } from "@/lib/types";
import { ANOMALY_TYPE_LABELS } from "@/lib/types";

/* ── Persistence ───────────────────────────────────────────── */
function storageKey(caseId: number) { return `anomaly_${caseId}`; }
function loadSignals(caseId: number): AnomalySignal[] {
  if (typeof window === "undefined") return [];
  try { return JSON.parse(localStorage.getItem(storageKey(caseId)) || "[]"); } catch { return []; }
}
function saveSignals(caseId: number, d: AnomalySignal[]) { localStorage.setItem(storageKey(caseId), JSON.stringify(d)); }
function uid() { return `sig_${Date.now()}_${Math.random().toString(36).slice(2, 7)}`; }

const SEVERITY_COLOR: Record<string, string> = {
  low: "#2563eb", medium: "#d97706", high: "#dc2626",
};

const TYPE_ICONS: Record<AnomalyType, React.ReactNode> = {
  spike: <TrendingUp size={14} />,
  pattern_break: <Activity size={14} />,
  new_actor: <UserPlus size={14} />,
  geographic_shift: <Globe size={14} />,
  sentiment_shift: <AlertTriangle size={14} />,
};

type Props = {
  caseId: number;
  /** Feed from dashboard / event data to auto-detect anomalies */
  eventTimeline?: { date: string; count: number }[];
  entityTimeline?: { date: string; count: number }[];
  onEvolution?: (type: string, title: string, detail?: string) => void;
};

/* ── Simple spike detector ─────────────────────────────────── */
function detectSpikes(timeline: { date: string; count: number }[], metricName: string): AnomalySignal[] {
  if (timeline.length < 3) return [];
  const vals = timeline.map((t) => t.count);
  const mean = vals.reduce((a, b) => a + b, 0) / vals.length;
  const std = Math.sqrt(vals.reduce((a, v) => a + (v - mean) ** 2, 0) / vals.length) || 1;
  const signals: AnomalySignal[] = [];
  vals.forEach((v, i) => {
    const zScore = (v - mean) / std;
    if (zScore > 1.5) {
      signals.push({
        id: uid(),
        type: "spike",
        title: `${metricName} spike on ${timeline[i].date}`,
        description: `Value ${v} is ${zScore.toFixed(1)}σ above mean (${mean.toFixed(0)})`,
        severity: zScore > 3 ? "high" : zScore > 2 ? "medium" : "low",
        metric_name: metricName,
        baseline_value: mean,
        current_value: v,
        detected_at: new Date().toISOString(),
        related_events: [],
        related_entities: [],
        dismissed: false,
      });
    }
  });
  return signals;
}

/* ── Component ─────────────────────────────────────────────── */
export function AnomalyDetectionPanel({ caseId, eventTimeline, entityTimeline, onEvolution }: Props) {
  const [signals, setSignals] = useState<AnomalySignal[]>(() => loadSignals(caseId));
  const [expandedId, setExpandedId] = useState<string | null>(null);
  const [showDismissed, setShowDismissed] = useState(false);

  /* Manual add form */
  const [showAdd, setShowAdd] = useState(false);
  const [addForm, setAddForm] = useState({
    type: "spike" as AnomalyType,
    title: "",
    description: "",
    severity: "medium" as "low" | "medium" | "high",
  });

  /* Auto-detect from timeline data */
  const autoDetected = useMemo(() => {
    const evSpikes = eventTimeline ? detectSpikes(eventTimeline, "Events") : [];
    const enSpikes = entityTimeline ? detectSpikes(entityTimeline, "Entities") : [];
    return [...evSpikes, ...enSpikes];
  }, [eventTimeline, entityTimeline]);

  const allSignals = [...signals, ...autoDetected.filter(
    (a) => !signals.some((s) => s.title === a.title),
  )];

  const visible = showDismissed ? allSignals : allSignals.filter((s) => !s.dismissed);
  const activeCount = allSignals.filter((s) => !s.dismissed).length;

  const persist = (list: AnomalySignal[]) => { setSignals(list); saveSignals(caseId, list); };

  const dismiss = (id: string) => {
    persist(signals.map((s) => s.id === id ? { ...s, dismissed: true } : s));
  };

  const addSignal = () => {
    if (!addForm.title.trim()) return;
    const sig: AnomalySignal = {
      id: uid(),
      type: addForm.type,
      title: addForm.title,
      description: addForm.description,
      severity: addForm.severity,
      metric_name: addForm.type,
      baseline_value: 0,
      current_value: 0,
      detected_at: new Date().toISOString(),
      related_events: [],
      related_entities: [],
      dismissed: false,
    };
    persist([sig, ...signals]);
    setAddForm({ type: "spike", title: "", description: "", severity: "medium" });
    setShowAdd(false);
  };

  return (
    <div className="anomaly-panel">
      <div className="anomaly-header">
        <Zap size={16} />
        <h4>Signals &amp; Anomalies</h4>
        {activeCount > 0 && <span className="anomaly-count-badge">{activeCount}</span>}
        <button className="action-btn action-btn-sm" onClick={() => setShowAdd(!showAdd)}>
          <TrendingUp size={12} /> Add Signal
        </button>
        <label className="anomaly-dismissed-toggle">
          <input type="checkbox" checked={showDismissed} onChange={(e) => setShowDismissed(e.target.checked)} />
          Show dismissed
        </label>
      </div>

      {showAdd && (
        <div className="anomaly-add-form">
          <select className="filter-select" value={addForm.type}
            onChange={(e) => setAddForm((f) => ({ ...f, type: e.target.value as AnomalyType }))}>
            {(Object.entries(ANOMALY_TYPE_LABELS)).map(([k, v]) => (
              <option key={k} value={k}>{v}</option>
            ))}
          </select>
          <input className="filter-input" placeholder="Signal title" value={addForm.title}
            onChange={(e) => setAddForm((f) => ({ ...f, title: e.target.value }))} />
          <input className="filter-input" placeholder="Description" value={addForm.description}
            onChange={(e) => setAddForm((f) => ({ ...f, description: e.target.value }))} />
          <select className="filter-select" value={addForm.severity}
            onChange={(e) => setAddForm((f) => ({ ...f, severity: e.target.value as "low" | "medium" | "high" }))}>
            <option value="low">Low</option><option value="medium">Medium</option><option value="high">High</option>
          </select>
          <div style={{ display: "flex", gap: 6 }}>
            <button className="action-btn action-btn-primary action-btn-sm" onClick={addSignal}>Add</button>
            <button className="action-btn action-btn-sm" onClick={() => setShowAdd(false)}>Cancel</button>
          </div>
        </div>
      )}

      <div className="anomaly-signal-list">
        {visible.length === 0 && <div className="empty-state">No anomalies detected</div>}
        {visible.map((sig) => {
          const expanded = expandedId === sig.id;
          return (
            <div key={sig.id} className={`anomaly-signal-card ${sig.dismissed ? "anomaly-signal-card--dismissed" : ""}`}
              style={{ borderLeftColor: SEVERITY_COLOR[sig.severity] }}>
              <div className="anomaly-signal-header" onClick={() => setExpandedId(expanded ? null : sig.id)}>
                {expanded ? <ChevronDown size={12} /> : <ChevronRight size={12} />}
                <span className="anomaly-signal-type-icon">{TYPE_ICONS[sig.type]}</span>
                <span className="anomaly-signal-type-label">{ANOMALY_TYPE_LABELS[sig.type]}</span>
                <span className="anomaly-signal-title">{sig.title}</span>
                <span className={`badge badge-${sig.severity === "high" ? "red" : sig.severity === "medium" ? "amber" : "blue"}`}>
                  {sig.severity}
                </span>
                {!sig.dismissed && (
                  <button className="anomaly-dismiss-btn" title="Dismiss"
                    onClick={(e) => { e.stopPropagation(); dismiss(sig.id); }}>
                    <X size={12} />
                  </button>
                )}
              </div>
              {expanded && (
                <div className="anomaly-signal-body">
                  <p>{sig.description}</p>
                  {sig.baseline_value > 0 && (
                    <div className="anomaly-metric-compare">
                      <div className="anomaly-metric">
                        <span className="anomaly-metric-label">Baseline</span>
                        <span className="anomaly-metric-value">{Number(sig.baseline_value || 0).toFixed(0)}</span>
                      </div>
                      <span className="anomaly-metric-arrow">→</span>
                      <div className="anomaly-metric">
                        <span className="anomaly-metric-label">Current</span>
                        <span className="anomaly-metric-value" style={{ color: SEVERITY_COLOR[sig.severity] }}>
                          {Number(sig.current_value || 0).toFixed(0)}
                        </span>
                      </div>
                      <div className="anomaly-metric">
                        <span className="anomaly-metric-label">Change</span>
                        <span className="anomaly-metric-value">
                          {sig.baseline_value > 0
                            ? `+${Math.round(((sig.current_value - sig.baseline_value) / sig.baseline_value) * 100)}%`
                            : "N/A"}
                        </span>
                      </div>
                    </div>
                  )}
                  <div className="anomaly-signal-ts">Detected: {new Date(sig.detected_at).toLocaleString()}</div>
                </div>
              )}
            </div>
          );
        })}
      </div>
    </div>
  );
}
