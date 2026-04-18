"use client";

import { useEffect, useState, useCallback, Suspense } from "react";
import { PageShell } from "@/components/shell";
import { api, apiPost } from "@/lib/api";
import { FilterBar, type FilterDef } from "@/components/filter-bar";
import { SeverityBadge, StatusBadge, ConfidenceBadge } from "@/components/score-badge";
import { ExplainabilityDrawer } from "@/components/explainability-drawer";
import { AttachToCaseModal } from "@/components/attach-to-case-modal";
import {
  Brain, FolderOpen, CheckCircle, CheckCheck, XCircle, AlertTriangle,
  ArrowUpCircle, MessageSquare, Clock, Plus, Newspaper,
} from "lucide-react";
import Link from "next/link";
import type { AlertSummary, AlertDetail } from "@/lib/types";
import { FeedbackPanel } from "@/components/feedback-panel";
import { Pagination } from "@/components/pagination";

const FILTER_DEFS: FilterDef[] = [
  { key: "severity", label: "Severity", type: "select", options: [
    { value: "critical", label: "Critical" }, { value: "high", label: "High" },
    { value: "medium", label: "Medium" }, { value: "low", label: "Low" },
  ]},
  { key: "status", label: "Status", type: "select", options: [
    { value: "open", label: "Open" }, { value: "acknowledged", label: "Acknowledged" },
    { value: "resolved", label: "Resolved" }, { value: "dismissed", label: "Dismissed" },
  ]},
  { key: "alert_type", label: "Alert Type", type: "text", placeholder: "Type" },
];

type AlertStats = { total: number; by_status: Record<string, number>; by_severity: Record<string, number>; open_critical: number };

function AlertsPageInner() {
  const [alerts, setAlerts] = useState<AlertSummary[]>([]);
  const [loading, setLoading] = useState(true);
  const [filters, setFilters] = useState<Record<string, string>>({ severity: "", status: "", alert_type: "" });
  const [selectedId, setSelectedId] = useState<number | null>(null);
  const [detail, setDetail] = useState<AlertDetail | null>(null);
  const [stats, setStats] = useState<AlertStats | null>(null);
  const [commentText, setCommentText] = useState("");
  const [page, setPage] = useState(1);
  const [count, setCount] = useState(0);

  // Drawers
  const [explainId, setExplainId] = useState<number | null>(null);
  const [attachId, setAttachId] = useState<number | null>(null);

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const qs = new URLSearchParams();
      for (const [k, v] of Object.entries(filters)) { if (v) qs.set(k, v); }
      qs.set("ordering", "-triggered_at");
      qs.set("page", String(page));
      const [data, st] = await Promise.all([
        api<{ results: AlertSummary[]; count: number }>(`/alerts/?${qs.toString()}`),
        api<AlertStats>("/alerts/stats/").catch(() => null),
      ]);
      setAlerts(data.results ?? []);
      setCount(data.count ?? 0);
      if (st) setStats(st);
    } catch { /* empty */ } finally { setLoading(false); }
  }, [filters, page]);

  useEffect(() => { void load(); }, [load]);

  // Reset to page 1 when filters change
  useEffect(() => { setPage(1); }, [filters]);

  useEffect(() => {
    if (!selectedId) { setDetail(null); return; }
    api<AlertDetail>(`/alerts/${selectedId}/`).then(setDetail).catch(() => setDetail(null));
  }, [selectedId]);

  const doAction = async (id: number, action: string, message?: string) => {
    try {
      await apiPost(`/alerts/${id}/${action}/`, message ? { message } : {});
      void load();
      if (selectedId === id) {
        api<AlertDetail>(`/alerts/${id}/`).then(setDetail).catch(() => {});
      }
    } catch { /* empty */ }
  };

  const selected = detail;

  return (
    <PageShell title="Alert Triage">
      {/* Stats bar */}
      {stats && (
        <div className="alert-stats-bar">
          <div className="alert-stat">
            <span className="alert-stat-value alert-stat--critical">{stats.open_critical}</span>
            <span className="alert-stat-label">Open Critical</span>
          </div>
          <div className="alert-stat">
            <span className="alert-stat-value">{stats.by_status?.open ?? 0}</span>
            <span className="alert-stat-label">Open</span>
          </div>
          <div className="alert-stat">
            <span className="alert-stat-value">{stats.by_status?.acknowledged ?? 0}</span>
            <span className="alert-stat-label">Acknowledged</span>
          </div>
          <div className="alert-stat">
            <span className="alert-stat-value">{stats.total ?? 0}</span>
            <span className="alert-stat-label">Total</span>
          </div>
        </div>
      )}

      <FilterBar filters={FILTER_DEFS} values={filters} onChange={setFilters} searchType="alert" />

      <div className="split-layout">
        {/* ── Alert List ────────────────────────────────────── */}
        <div className="split-list">
          <div className="data-table-wrap">
            {loading ? (
              <div className="loading-state"><div className="loading-spinner" /> Loading alerts…</div>
            ) : alerts.length === 0 ? (
              <div className="empty-state">No alerts found</div>
            ) : (
              <table className="data-table">
                <thead>
                  <tr><th>Alert</th><th>Type</th><th>Severity</th><th>Status</th><th>Time</th><th>Actions</th></tr>
                </thead>
                <tbody>
                  {alerts.map((a) => (
                    <tr
                      key={a.id}
                      className={`${selectedId === a.id ? "row-active" : ""} ${a.severity === "critical" && a.status === "open" ? "row-critical" : ""}`}
                      style={{ cursor: "pointer" }}
                      onClick={() => setSelectedId(a.id)}
                    >
                      <td>
                        <div className="event-cell-title">{a.title}</div>
                        {a.summary && <div className="event-cell-meta" style={{ maxWidth: 280, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>{a.summary}</div>}
                      </td>
                      <td><span className="badge badge-gray">{a.alert_type}</span></td>
                      <td><SeverityBadge severity={a.severity} /></td>
                      <td><StatusBadge status={a.status} /></td>
                      <td className="cell-date">{new Date(a.triggered_at).toLocaleString()}</td>
                      <td>
                        <div className="triage-actions" onClick={(e) => e.stopPropagation()}>
                          {a.status === "open" && (
                            <button className="triage-btn triage-btn--ack" title="Acknowledge" onClick={() => doAction(a.id, "acknowledge")}>
                              <CheckCircle size={15} />
                            </button>
                          )}
                          {(a.status === "open" || a.status === "acknowledged") && (
                            <button className="triage-btn triage-btn--resolve" title="Resolve" onClick={() => doAction(a.id, "resolve")}>
                              <CheckCheck size={15} />
                            </button>
                          )}
                          {a.status !== "dismissed" && a.status !== "resolved" && (
                            <button className="triage-btn triage-btn--dismiss" title="Dismiss" onClick={() => doAction(a.id, "dismiss")}>
                              <XCircle size={15} />
                            </button>
                          )}
                        </div>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            )}
          </div>
          <Pagination page={page} count={count} onChange={setPage} />
        </div>

        {/* ── Alert Detail ──────────────────────────────────── */}
        {selected && (
          <div className="split-detail">
            <div className="detail-panel">
              <button className="close-btn" onClick={() => setSelectedId(null)}>✕</button>
              <h3>{selected.title}</h3>

              <div style={{ display: "flex", gap: 6, flexWrap: "wrap", marginBottom: "0.75rem" }}>
                <SeverityBadge severity={selected.severity} />
                <StatusBadge status={selected.status} />
                <span className="badge badge-gray">{selected.alert_type}</span>
              </div>

              <p className="detail-summary">{selected.description || selected.summary}</p>

              {/* Trigger info */}
              <div className="detail-section">
                <h4><Clock size={13} /> Timeline</h4>
                <div className="factor-row"><span className="factor-label">Triggered</span><span className="factor-value">{new Date(selected.triggered_at).toLocaleString()}</span></div>
                {selected.acknowledged_at && <div className="factor-row"><span className="factor-label">Acknowledged</span><span className="factor-value">{new Date(selected.acknowledged_at).toLocaleString()}</span></div>}
                {selected.resolved_at && <div className="factor-row"><span className="factor-label">Resolved</span><span className="factor-value">{new Date(selected.resolved_at).toLocaleString()}</span></div>}
                {selected.source__name && <div className="factor-row"><span className="factor-label">Source</span><span className="factor-value">{selected.source__name}</span></div>}
                {selected.topic__name && <div className="factor-row"><span className="factor-label">Topic</span><span className="factor-value">{selected.topic__name}</span></div>}
              </div>

              {/* Actions */}
              <div className="detail-actions">
                <button className="action-btn" onClick={() => setExplainId(selected.id)}>
                  <Brain size={14} /> Explain
                </button>
                <button className="action-btn" onClick={() => setAttachId(selected.id)}>
                  <FolderOpen size={14} /> Attach to Case
                </button>
                {selected.article && (
                  <Link href={`/articles/${selected.article}`} className="action-btn">
                    <Newspaper size={14} /> View Article
                  </Link>
                )}
                {selected.event && (
                  <Link href={`/events?highlight=${selected.event}`} className="action-btn">
                    View Event
                  </Link>
                )}
                {selected.status === "open" && (
                  <button className="action-btn action-btn-green" onClick={() => doAction(selected.id, "acknowledge")}>
                    <CheckCircle size={14} /> Acknowledge
                  </button>
                )}
                {(selected.status === "open" || selected.status === "acknowledged") && (
                  <>
                    <button className="action-btn action-btn-primary" onClick={() => doAction(selected.id, "resolve")}>
                      <CheckCheck size={14} /> Resolve
                    </button>
                    <button className="action-btn" onClick={() => doAction(selected.id, "escalate")}>
                      <ArrowUpCircle size={14} /> Escalate
                    </button>
                  </>
                )}
              </div>

              {/* Analyst Feedback */}
              <FeedbackPanel
                targetType="alert"
                targetId={selected.id}
                allowedTypes={["confirmed", "false_positive", "misleading", "useful", "escalated_correctly"]}
              />

              {/* Comment */}
              <div className="detail-section">
                <h4><MessageSquare size={13} /> Add Comment</h4>
                <div style={{ display: "flex", gap: 8 }}>
                  <input
                    className="filter-input"
                    style={{ flex: 1 }}
                    placeholder="Add a note or comment…"
                    value={commentText}
                    onChange={(e) => setCommentText(e.target.value)}
                    onKeyDown={(e) => {
                      if (e.key === "Enter" && commentText.trim()) {
                        doAction(selected.id, "comment", commentText.trim());
                        setCommentText("");
                      }
                    }}
                  />
                  <button
                    className="action-btn action-btn-primary"
                    disabled={!commentText.trim()}
                    onClick={() => { doAction(selected.id, "comment", commentText.trim()); setCommentText(""); }}
                  >
                    Send
                  </button>
                </div>
              </div>
            </div>
          </div>
        )}
      </div>

      {explainId != null && (
        <ExplainabilityDrawer type="alert" id={explainId} onClose={() => setExplainId(null)} />
      )}

      {attachId != null && selected && (
        <AttachToCaseModal
          objectType="alert"
          objectId={attachId}
          objectTitle={selected.title}
          onClose={() => setAttachId(null)}
          onSuccess={load}
        />
      )}
    </PageShell>
  );
}

export default function AlertsPage() {
  return <Suspense><AlertsPageInner /></Suspense>;
}
