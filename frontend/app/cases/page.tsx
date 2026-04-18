"use client";

import { useEffect, useState, useCallback, Suspense } from "react";
import { PageShell } from "@/components/shell";
import { api, apiPost, apiDelete } from "@/lib/api";
import { FilterBar, type FilterDef } from "@/components/filter-bar";
import { StatusBadge, SeverityBadge } from "@/components/score-badge";
import {
  Plus, FileText, Users, Radar, Bell, MessageSquare, Clock, FolderOpen,
  Download, RotateCcw, Lock, Trash2, Lightbulb, GitBranch, ShieldAlert,
  Zap, StickyNote, History,
} from "lucide-react";
import type { CaseSummary, CaseDetailFull, CaseNote, CaseTimelineEntry, Hypothesis, CaseEvolutionEntry } from "@/lib/types";
import { PRIORITY_BADGE } from "@/lib/types";
import { HypothesisPanel } from "@/components/hypothesis-panel";
import { ReasoningChainPanel } from "@/components/reasoning-chain-panel";
import { DecisionSupportPanel } from "@/components/decision-support-panel";
import { AnomalyDetectionPanel } from "@/components/anomaly-detection-panel";
import { StructuredNotesPanel } from "@/components/structured-notes-panel";
import { CaseEvolutionTimeline, loadEvolution, appendEvolution } from "@/components/case-evolution-timeline";
import { FeedbackPanel } from "@/components/feedback-panel";
import { Pagination } from "@/components/pagination";

const FILTER_DEFS: FilterDef[] = [
  { key: "status", label: "Status", type: "select", options: [
    { value: "open", label: "Open" }, { value: "in_progress", label: "In Progress" },
    { value: "closed", label: "Closed" }, { value: "archived", label: "Archived" },
  ]},
  { key: "priority", label: "Priority", type: "select", options: [
    { value: "critical", label: "Critical" }, { value: "high", label: "High" },
    { value: "medium", label: "Medium" }, { value: "low", label: "Low" },
  ]},
];

function CasesPageInner() {
  const [cases, setCases] = useState<CaseSummary[]>([]);
  const [loading, setLoading] = useState(true);
  const [selectedId, setSelectedId] = useState<number | null>(null);
  const [detail, setDetail] = useState<CaseDetailFull | null>(null);
  const [caseTimeline, setCaseTimeline] = useState<CaseTimelineEntry[]>([]);
  const [showCreate, setShowCreate] = useState(false);
  const [newCase, setNewCase] = useState({ title: "", description: "", priority: "medium" });
  const [filters, setFilters] = useState<Record<string, string>>({ status: "", priority: "" });
  const [detailTab, setDetailTab] = useState<
    "overview" | "events" | "entities" | "articles" | "notes" | "timeline" |
    "hypotheses" | "reasoning" | "decisions" | "signals" | "structured-notes" | "evolution" | "feedback"
  >("overview");
  const [newNote, setNewNote] = useState("");
  const [hypotheses, setHypotheses] = useState<Hypothesis[]>([]);
  const [evolutionEntries, setEvolutionEntries] = useState<CaseEvolutionEntry[]>([]);
  const [page, setPage] = useState(1);
  const [count, setCount] = useState(0);

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const qs = new URLSearchParams();
      for (const [k, v] of Object.entries(filters)) { if (v) qs.set(k, v); }
      qs.set("ordering", "-updated_at");
      qs.set("page", String(page));
      const data = await api<{ results: CaseSummary[]; count: number }>(`/cases/?${qs.toString()}`);
      setCases(data.results ?? []);
      setCount(data.count ?? 0);
    } catch { /* empty */ } finally { setLoading(false); }
  }, [filters, page]);

  useEffect(() => { void load(); }, [load]);

  // Reset to page 1 when filters change
  useEffect(() => { setPage(1); }, [filters]);

  const loadDetail = useCallback(async (id: number) => {
    try {
      const [d, tl] = await Promise.all([
        api<CaseDetailFull>(`/cases/${id}/`),
        api<{ entries: CaseTimelineEntry[] }>(`/cases/${id}/timeline/`).catch(() => ({ entries: [] })),
      ]);
      setDetail(d);
      setCaseTimeline(tl.entries ?? []);
    } catch { setDetail(null); }
  }, []);

  useEffect(() => {
    if (!selectedId) { setDetail(null); return; }
    void loadDetail(selectedId);
    /* Load client-side reasoning data for this case */
    setEvolutionEntries(loadEvolution(selectedId));
    try {
      setHypotheses(JSON.parse(localStorage.getItem(`hyp_${selectedId}`) || "[]"));
    } catch { setHypotheses([]); }
  }, [selectedId, loadDetail]);

  const handleEvolution = useCallback((type: string, title: string, detail?: string) => {
    if (!selectedId) return;
    appendEvolution(selectedId, type, title, detail);
    setEvolutionEntries(loadEvolution(selectedId));
    /* Refresh hypotheses for decision panel */
    try {
      setHypotheses(JSON.parse(localStorage.getItem(`hyp_${selectedId}`) || "[]"));
    } catch { setHypotheses([]); }
  }, [selectedId]);

  const createCase = async () => {
    if (!newCase.title.trim()) return;
    try {
      const created = await apiPost<{ id: number }>("/cases/", newCase);
      setShowCreate(false);
      setNewCase({ title: "", description: "", priority: "medium" });
      void load();
      setSelectedId(created.id);
    } catch { /* empty */ }
  };

  const addNote = async () => {
    if (!newNote.trim() || !selectedId) return;
    try {
      await apiPost(`/cases/${selectedId}/notes/`, { text: newNote.trim() });
      setNewNote("");
      void loadDetail(selectedId);
    } catch { /* empty */ }
  };

  const closeCase = async () => {
    if (!selectedId) return;
    await apiPost(`/cases/${selectedId}/close/`, {});
    void load();
    void loadDetail(selectedId);
  };

  const reopenCase = async () => {
    if (!selectedId) return;
    await apiPost(`/cases/${selectedId}/reopen/`, {});
    void load();
    void loadDetail(selectedId);
  };

  const exportCase = async () => {
    if (!selectedId) return;
    try {
      const data = await api<Record<string, unknown>>(`/cases/${selectedId}/export/`);
      const blob = new Blob([JSON.stringify(data, null, 2)], { type: "application/json" });
      const url = URL.createObjectURL(blob);
      const a = document.createElement("a");
      a.href = url;
      a.download = `case-${selectedId}-export.json`;
      a.click();
      URL.revokeObjectURL(url);
    } catch { /* empty */ }
  };

  const removeEvent = async (eventId: number) => {
    if (!selectedId) return;
    await apiDelete(`/cases/${selectedId}/remove-event/${eventId}/`);
    void loadDetail(selectedId);
  };

  const removeEntity = async (entityId: number) => {
    if (!selectedId) return;
    await apiDelete(`/cases/${selectedId}/remove-entity/${entityId}/`);
    void loadDetail(selectedId);
  };

  return (
    <PageShell title="Case Workspace">
      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: "0.75rem" }}>
        <FilterBar filters={FILTER_DEFS} values={filters} onChange={setFilters} searchType="case" />
        <button className="action-btn action-btn-primary" onClick={() => setShowCreate(!showCreate)}>
          <Plus size={14} /> New Case
        </button>
      </div>

      {showCreate && (
        <div className="create-form">
          <input className="filter-input" style={{ width: "100%", marginBottom: 8 }} placeholder="Case title" value={newCase.title} onChange={(e) => setNewCase((c) => ({ ...c, title: e.target.value }))} />
          <textarea className="filter-input" style={{ width: "100%", marginBottom: 8, resize: "vertical" }} placeholder="Description" value={newCase.description} onChange={(e) => setNewCase((c) => ({ ...c, description: e.target.value }))} rows={3} />
          <div style={{ display: "flex", gap: 8 }}>
            <select className="filter-select" value={newCase.priority} onChange={(e) => setNewCase((c) => ({ ...c, priority: e.target.value }))}>
              <option value="low">Low</option><option value="medium">Medium</option>
              <option value="high">High</option><option value="critical">Critical</option>
            </select>
            <button className="action-btn action-btn-primary" onClick={createCase}>Create</button>
            <button className="action-btn" onClick={() => setShowCreate(false)}>Cancel</button>
          </div>
        </div>
      )}

      <div className="split-layout">
        {/* ── Case List ─────────────────────────────────── */}
        <div className="split-list" style={{ maxWidth: 440 }}>
          <div className="case-card-list">
            {loading ? (
              <div className="loading-state"><div className="loading-spinner" /> Loading…</div>
            ) : cases.length === 0 ? (
              <div className="empty-state">No cases yet</div>
            ) : cases.map((c) => (
              <div
                key={c.id}
                className={`case-card ${selectedId === c.id ? "case-card--active" : ""}`}
                onClick={() => { setSelectedId(c.id); setDetailTab("overview"); }}
              >
                <div className="case-card-header">
                  <span className="case-card-title">{c.title}</span>
                  <span className={`badge ${PRIORITY_BADGE[c.priority] ?? "badge-gray"}`}>{c.priority}</span>
                </div>
                <div className="case-card-meta">
                  <StatusBadge status={c.status} />
                  <span>{c.event_count ?? 0} events</span>
                  <span>{c.entity_count ?? 0} entities</span>
                  <span>{c.note_count ?? 0} notes</span>
                </div>
                <div className="case-card-date">Updated {new Date(c.updated_at).toLocaleDateString()}</div>
              </div>
            ))}
          </div>          <Pagination page={page} count={count} onChange={setPage} />        </div>

        {/* ── Case Detail ───────────────────────────────── */}
        {detail && (
          <div className="split-detail" style={{ flex: 1 }}>
            <div className="detail-panel">
              <div className="detail-header">
                <button className="close-btn" onClick={() => setSelectedId(null)}>✕</button>
                <h3>{detail.title}</h3>
                <div style={{ display: "flex", gap: 6, flexWrap: "wrap", marginBottom: "0.5rem" }}>
                  <StatusBadge status={detail.status} />
                  <span className={`badge ${PRIORITY_BADGE[detail.priority] ?? "badge-gray"}`}>{detail.priority}</span>
                  {detail.classification && <span className="badge badge-purple">{detail.classification}</span>}
                </div>
                <p className="detail-summary">{detail.description}</p>

                {/* Quick stats */}
                <div className="case-stats-row">
                  <div className="case-stat"><Radar size={14} /><span>{detail.events?.length ?? 0}</span> Events</div>
                  <div className="case-stat"><Users size={14} /><span>{detail.entities?.length ?? 0}</span> Entities</div>
                  <div className="case-stat"><FileText size={14} /><span>{detail.articles?.length ?? 0}</span> Articles</div>
                  <div className="case-stat"><Bell size={14} /><span>{detail.alerts?.length ?? 0}</span> Alerts</div>
                  <div className="case-stat"><MessageSquare size={14} /><span>{detail.notes?.length ?? 0}</span> Notes</div>
                </div>

                {/* Actions */}
                <div className="detail-actions">
                  {detail.status !== "closed" && (
                    <button className="action-btn" onClick={closeCase}><Lock size={14} /> Close Case</button>
                  )}
                  {detail.status === "closed" && (
                    <button className="action-btn" onClick={reopenCase}><RotateCcw size={14} /> Reopen</button>
                  )}
                  <button className="action-btn" onClick={exportCase}><Download size={14} /> Export</button>
                </div>
              </div>

              {/* Tabs */}
              <div className="detail-tabs">
                {([
                  ["overview", "Overview"], ["events", "Events"], ["entities", "Entities"],
                  ["articles", "Articles"], ["notes", "Notes"], ["timeline", "Activity"],
                  ["hypotheses", "Hypotheses"], ["reasoning", "Reasoning"], ["decisions", "Decisions"],
                  ["signals", "Signals"], ["structured-notes", "S-Notes"], ["evolution", "Evolution"],
                  ["feedback", "🧠 Feedback"],
                ] as const).map(([key, label]) => (
                  <button key={key} className={`detail-tab ${detailTab === key ? "detail-tab--active" : ""}`} onClick={() => setDetailTab(key)}>
                    {label}
                  </button>
                ))}
              </div>

              <div className="detail-tab-content">
                {detailTab === "overview" && (
                  <div className="tab-overview">
                    <div className="overview-row"><Clock size={14} /><span>Created: <strong>{new Date(detail.created_at).toLocaleString()}</strong></span></div>
                    <div className="overview-row"><Clock size={14} /><span>Updated: <strong>{new Date(detail.updated_at).toLocaleString()}</strong></span></div>
                    {detail.due_at && <div className="overview-row"><Clock size={14} /><span>Due: <strong>{new Date(detail.due_at).toLocaleString()}</strong></span></div>}
                    {detail.members && detail.members.length > 0 && (
                      <div className="detail-section">
                        <h4>Members</h4>
                        {detail.members.map((m) => (
                          <div key={m.id} className="factor-row">
                            <span className="factor-label">{m.user}</span>
                            <span className="badge badge-gray">{m.role}</span>
                          </div>
                        ))}
                      </div>
                    )}
                  </div>
                )}

                {detailTab === "events" && (
                  <div className="tab-list">
                    {(detail.events ?? []).length === 0 ? <div className="empty-state">No events attached</div> : detail.events.map((e) => (
                      <div key={e.id} className="tab-list-item">
                        <div className="tab-list-item-main">
                          <Radar size={14} />
                          <a href={`/events?highlight=${e.id}`} className="tab-link">{e.title}</a>
                          <span className="badge badge-blue">{e.event_type}</span>
                        </div>
                        <button className="triage-btn triage-btn--dismiss" title="Remove" onClick={() => removeEvent(e.id)}><Trash2 size={13} /></button>
                      </div>
                    ))}
                  </div>
                )}

                {detailTab === "entities" && (
                  <div className="tab-list">
                    {(detail.entities ?? []).length === 0 ? <div className="empty-state">No entities attached</div> : detail.entities.map((e) => (
                      <div key={e.id} className="tab-list-item">
                        <div className="tab-list-item-main">
                          <Users size={14} />
                          <a href={`/entities?highlight=${e.id}`} className="tab-link">{e.name}</a>
                          <span className="badge badge-purple">{e.entity_type}</span>
                        </div>
                        <button className="triage-btn triage-btn--dismiss" title="Remove" onClick={() => removeEntity(e.id)}><Trash2 size={13} /></button>
                      </div>
                    ))}
                  </div>
                )}

                {detailTab === "articles" && (
                  <div className="tab-list">
                    {(detail.articles ?? []).length === 0 ? <div className="empty-state">No articles</div> : detail.articles.map((a) => (
                      <div key={a.id} className="tab-list-item">
                        <div className="tab-list-item-main">
                          <FileText size={14} />
                          <span>{a.title}</span>
                        </div>
                        <div className="tab-list-item-meta">{a.source_name}</div>
                      </div>
                    ))}
                  </div>
                )}

                {detailTab === "notes" && (
                  <div>
                    <div style={{ display: "flex", gap: 8, marginBottom: "1rem" }}>
                      <input
                        className="filter-input"
                        style={{ flex: 1 }}
                        placeholder="Add investigation note…"
                        value={newNote}
                        onChange={(e) => setNewNote(e.target.value)}
                        onKeyDown={(e) => e.key === "Enter" && addNote()}
                      />
                      <button className="action-btn action-btn-primary" disabled={!newNote.trim()} onClick={addNote}>Add Note</button>
                    </div>
                    {(detail.notes ?? []).length === 0 ? <div className="empty-state">No notes yet</div> : detail.notes.map((n) => (
                      <div key={n.id} className="note-card">
                        <p className="note-text">{n.text}</p>
                        <div className="note-meta">
                          {n.author && <span>{n.author}</span>}
                          <span>{new Date(n.created_at).toLocaleString()}</span>
                        </div>
                      </div>
                    ))}
                  </div>
                )}

                {detailTab === "timeline" && (
                  <div className="tab-timeline">
                    {caseTimeline.length === 0 ? <div className="empty-state">No activity yet</div> : caseTimeline.map((entry, i) => (
                      <div key={i} className="timeline-mini-entry">
                        <div className="timeline-mini-dot" style={{
                          background: entry.type.includes("note") ? "#f59e0b" : entry.type.includes("event") ? "#2563eb" : entry.type.includes("entity") ? "#7c3aed" : "#64748b",
                        }} />
                        <div className="timeline-mini-content">
                          <span className="timeline-mini-time">{new Date(entry.ts).toLocaleString()}</span>
                          <span className="timeline-mini-title">{entry.title}</span>
                          {entry.actor && <span className="timeline-mini-meta">{entry.actor}</span>}
                        </div>
                      </div>
                    ))}
                  </div>
                )}

                {detailTab === "hypotheses" && (
                  <HypothesisPanel
                    caseId={selectedId!}
                    availableEvents={(detail.events ?? []).map(e => ({ id: e.id, title: e.title }))}
                    availableEntities={(detail.entities ?? []).map(e => ({ id: e.id, name: e.name }))}
                    availableArticles={(detail.articles ?? []).map(a => ({ id: a.id, title: a.title }))}
                    onEvolution={handleEvolution}
                  />
                )}

                {detailTab === "reasoning" && (
                  <ReasoningChainPanel
                    caseId={selectedId!}
                    onEvolution={handleEvolution}
                  />
                )}

                {detailTab === "decisions" && (
                  <DecisionSupportPanel
                    caseId={selectedId!}
                    hypotheses={hypotheses}
                    eventCount={detail.events?.length ?? 0}
                    entityCount={detail.entities?.length ?? 0}
                    sourceCount={new Set((detail.articles ?? []).map(a => a.source_name)).size}
                    onEvolution={handleEvolution}
                  />
                )}

                {detailTab === "signals" && (
                  <AnomalyDetectionPanel
                    caseId={selectedId!}
                    onEvolution={handleEvolution}
                  />
                )}

                {detailTab === "structured-notes" && (
                  <StructuredNotesPanel
                    caseId={selectedId!}
                    availableEvents={(detail.events ?? []).map(e => ({ id: e.id, title: e.title }))}
                    availableEntities={(detail.entities ?? []).map(e => ({ id: e.id, name: e.name }))}
                    onEvolution={handleEvolution}
                  />
                )}

                {detailTab === "evolution" && (
                  <CaseEvolutionTimeline
                    caseId={selectedId!}
                    entries={evolutionEntries}
                  />
                )}

                {detailTab === "feedback" && selectedId && (
                  <div style={{ padding: "1rem 0" }}>
                    <FeedbackPanel
                      targetType="case"
                      targetId={selectedId}
                      allowedTypes={["confirmed", "false_positive", "useful", "escalated_correctly"]}
                    />
                  </div>
                )}
              </div>
            </div>
          </div>
        )}
      </div>
    </PageShell>
  );
}

export default function CasesPage() {
  return <Suspense><CasesPageInner /></Suspense>;
}
