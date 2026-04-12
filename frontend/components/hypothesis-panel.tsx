"use client";

import { useState, useCallback } from "react";
import {
  Lightbulb, Plus, ChevronDown, ChevronRight, ThumbsUp, ThumbsDown, Minus,
  TrendingUp, Trash2, Edit3, Check, X,
} from "lucide-react";
import type {
  Hypothesis, HypothesisStatus, EvidenceLink, ConfidenceSnapshot,
} from "@/lib/types";
import { HYPOTHESIS_STATUS_BADGE } from "@/lib/types";

/* ── Local state helpers (client-only persistence via case key) ── */

function storageKey(caseId: number) { return `hyp_${caseId}`; }

function loadHypotheses(caseId: number): Hypothesis[] {
  if (typeof window === "undefined") return [];
  try { return JSON.parse(localStorage.getItem(storageKey(caseId)) || "[]"); }
  catch { return []; }
}

function saveHypotheses(caseId: number, data: Hypothesis[]) {
  localStorage.setItem(storageKey(caseId), JSON.stringify(data));
}

function uid() { return `h_${Date.now()}_${Math.random().toString(36).slice(2, 7)}`; }

/* ── Props ─────────────────────────────────────────────────── */
type Props = {
  caseId: number;
  /** Available items that can be linked as evidence */
  availableEvents: { id: number; title: string }[];
  availableEntities: { id: number; name: string }[];
  availableArticles: { id: number; title: string }[];
  /** Notify parent when an evolution entry should be recorded */
  onEvolution?: (type: string, title: string, detail?: string) => void;
};

/* ── Confidence Sparkline ──────────────────────────────────── */
function ConfidenceSparkline({ history }: { history: ConfidenceSnapshot[] }) {
  if (history.length < 2) return null;
  const w = 120, h = 28, pad = 2;
  const pts = history.map((s, i) => {
    const x = pad + (i / (history.length - 1)) * (w - 2 * pad);
    const y = h - pad - s.confidence * (h - 2 * pad);
    return `${x},${y}`;
  });
  return (
    <svg width={w} height={h} className="confidence-sparkline">
      <polyline points={pts.join(" ")} fill="none" stroke="var(--color-brand)" strokeWidth="1.5" />
      {history.map((s, i) => {
        const x = pad + (i / (history.length - 1)) * (w - 2 * pad);
        const y = h - pad - s.confidence * (h - 2 * pad);
        return <circle key={i} cx={x} cy={y} r="2" fill="var(--color-brand)" />;
      })}
    </svg>
  );
}

/* ── Evidence Row ──────────────────────────────────────────── */
function EvidenceRow({ ev, onRemove }: { ev: EvidenceLink; onRemove: () => void }) {
  const stanceIcon = ev.stance === "supports"
    ? <ThumbsUp size={12} className="evidence-icon evidence-icon--supports" />
    : ev.stance === "contradicts"
    ? <ThumbsDown size={12} className="evidence-icon evidence-icon--contradicts" />
    : <Minus size={12} className="evidence-icon evidence-icon--neutral" />;

  return (
    <div className="evidence-row">
      {stanceIcon}
      <span className="evidence-ref-type badge badge-gray" style={{ fontSize: "0.65rem" }}>{ev.ref_type}</span>
      <span className="evidence-title">{ev.ref_title}</span>
      <div className="evidence-strength-bar">
        <div className="evidence-strength-fill" style={{ width: `${ev.strength * 100}%` }} />
      </div>
      {ev.analyst_note && <span className="evidence-note" title={ev.analyst_note}>📝</span>}
      <button className="evidence-remove" onClick={onRemove} title="Remove"><Trash2 size={11} /></button>
    </div>
  );
}

/* ── Main Hypothesis Panel ─────────────────────────────────── */
export function HypothesisPanel({ caseId, availableEvents, availableEntities, availableArticles, onEvolution }: Props) {
  const [hypotheses, setHypotheses] = useState<Hypothesis[]>(() => loadHypotheses(caseId));
  const [expandedId, setExpandedId] = useState<string | null>(null);
  const [showCreate, setShowCreate] = useState(false);
  const [editingId, setEditingId] = useState<string | null>(null);
  const [form, setForm] = useState({ title: "", statement: "" });

  /* add evidence form */
  const [addEvRefType, setAddEvRefType] = useState<"event" | "entity" | "article">("event");
  const [addEvRefId, setAddEvRefId] = useState<number | "">("");
  const [addEvStance, setAddEvStance] = useState<"supports" | "contradicts" | "neutral">("supports");
  const [addEvStrength, setAddEvStrength] = useState(0.7);
  const [addEvNote, setAddEvNote] = useState("");

  const persist = useCallback((list: Hypothesis[]) => {
    setHypotheses(list);
    saveHypotheses(caseId, list);
  }, [caseId]);

  /* ── CRUD ─────────────────────────────────────────────────── */
  const createHypothesis = () => {
    if (!form.title.trim()) return;
    const now = new Date().toISOString();
    const h: Hypothesis = {
      id: uid(), case_id: caseId, title: form.title, statement: form.statement,
      status: "draft", confidence: 0.5, evidence: [],
      confidence_history: [{ ts: now, confidence: 0.5, reason: "Initial" }],
      created_at: now, updated_at: now,
    };
    persist([h, ...hypotheses]);
    setForm({ title: "", statement: "" });
    setShowCreate(false);
    setExpandedId(h.id);
    onEvolution?.("hypothesis_created", `Hypothesis created: ${h.title}`);
  };

  const updateStatus = (id: string, status: HypothesisStatus) => {
    persist(hypotheses.map((h) => {
      if (h.id !== id) return h;
      const now = new Date().toISOString();
      const conf = status === "supported" ? Math.max(h.confidence, 0.8) :
                   status === "refuted" ? Math.min(h.confidence, 0.2) : h.confidence;
      const snap: ConfidenceSnapshot = { ts: now, confidence: conf, reason: `Status → ${status}` };
      const updated = { ...h, status, confidence: conf, updated_at: now,
        confidence_history: [...h.confidence_history, snap] };
      onEvolution?.("hypothesis_updated", `Hypothesis "${h.title}" → ${status}`);
      return updated;
    }));
  };

  const updateConfidence = (id: string, confidence: number, reason: string) => {
    persist(hypotheses.map((h) => {
      if (h.id !== id) return h;
      const now = new Date().toISOString();
      const snap: ConfidenceSnapshot = { ts: now, confidence, reason };
      const updated = { ...h, confidence, updated_at: now,
        confidence_history: [...h.confidence_history, snap] };
      onEvolution?.("hypothesis_updated", `Confidence → ${Math.round(confidence * 100)}%: ${h.title}`, reason);
      return updated;
    }));
  };

  const addEvidence = (hypId: string) => {
    if (addEvRefId === "") return;
    const list = addEvRefType === "event" ? availableEvents.map((e) => ({ id: e.id, t: e.title })) :
                 addEvRefType === "entity" ? availableEntities.map((e) => ({ id: e.id, t: e.name })) :
                 availableArticles.map((a) => ({ id: a.id, t: a.title }));
    const found = list.find((x) => x.id === addEvRefId);
    if (!found) return;
    const ev: EvidenceLink = {
      id: uid(), ref_type: addEvRefType, ref_id: found.id, ref_title: found.t,
      stance: addEvStance, strength: addEvStrength, analyst_note: addEvNote,
      added_at: new Date().toISOString(),
    };
    persist(hypotheses.map((h) => {
      if (h.id !== hypId) return h;
      return { ...h, evidence: [...h.evidence, ev], updated_at: new Date().toISOString() };
    }));
    onEvolution?.("evidence_added", `Evidence (${addEvStance}): ${found.t}`, `For hypothesis "${hypotheses.find((h) => h.id === hypId)?.title}"`);
    setAddEvRefId(""); setAddEvNote("");
  };

  const removeEvidence = (hypId: string, evId: string) => {
    persist(hypotheses.map((h) => {
      if (h.id !== hypId) return h;
      return { ...h, evidence: h.evidence.filter((e) => e.id !== evId), updated_at: new Date().toISOString() };
    }));
  };

  const deleteHypothesis = (id: string) => {
    persist(hypotheses.filter((h) => h.id !== id));
  };

  /* ── Evidence summary ─────────────────────────────────────── */
  const evidenceSummary = (h: Hypothesis) => {
    const sup = h.evidence.filter((e) => e.stance === "supports").length;
    const con = h.evidence.filter((e) => e.stance === "contradicts").length;
    const neu = h.evidence.filter((e) => e.stance === "neutral").length;
    return { sup, con, neu, total: h.evidence.length };
  };

  const refOptions = addEvRefType === "event"
    ? availableEvents.map((e) => ({ value: e.id, label: e.title }))
    : addEvRefType === "entity"
    ? availableEntities.map((e) => ({ value: e.id, label: e.name }))
    : availableArticles.map((a) => ({ value: a.id, label: a.title }));

  return (
    <div className="hypothesis-panel">
      <div className="hypothesis-header">
        <Lightbulb size={16} />
        <h4>Hypotheses</h4>
        <span className="badge badge-blue">{hypotheses.length}</span>
        <button className="action-btn action-btn-sm" onClick={() => setShowCreate(!showCreate)}>
          <Plus size={12} /> New
        </button>
      </div>

      {showCreate && (
        <div className="hypothesis-create-form">
          <input className="filter-input" placeholder="Hypothesis title" value={form.title}
            onChange={(e) => setForm((f) => ({ ...f, title: e.target.value }))} />
          <textarea className="filter-input" placeholder="Detailed statement…" rows={2} value={form.statement}
            onChange={(e) => setForm((f) => ({ ...f, statement: e.target.value }))} style={{ resize: "vertical" }} />
          <div style={{ display: "flex", gap: 6 }}>
            <button className="action-btn action-btn-primary action-btn-sm" onClick={createHypothesis}>Create</button>
            <button className="action-btn action-btn-sm" onClick={() => setShowCreate(false)}>Cancel</button>
          </div>
        </div>
      )}

      <div className="hypothesis-list">
        {hypotheses.length === 0 && <div className="empty-state">No hypotheses yet — create one to start reasoning</div>}
        {hypotheses.map((h) => {
          const expanded = expandedId === h.id;
          const es = evidenceSummary(h);
          return (
            <div key={h.id} className={`hypothesis-card ${expanded ? "hypothesis-card--expanded" : ""}`}>
              {/* header row */}
              <div className="hypothesis-card-header" onClick={() => setExpandedId(expanded ? null : h.id)}>
                {expanded ? <ChevronDown size={14} /> : <ChevronRight size={14} />}
                <span className="hypothesis-card-title">{h.title}</span>
                <span className={`badge ${HYPOTHESIS_STATUS_BADGE[h.status]}`}>{h.status}</span>
                <span className="hypothesis-confidence-pill">{Math.round(h.confidence * 100)}%</span>
                <ConfidenceSparkline history={h.confidence_history} />
              </div>

              {expanded && (
                <div className="hypothesis-card-body">
                  {h.statement && <p className="hypothesis-statement">{h.statement}</p>}

                  {/* Status controls */}
                  <div className="hypothesis-status-controls">
                    {(["draft", "active", "supported", "refuted", "inconclusive"] as const).map((s) => (
                      <button key={s}
                        className={`hypothesis-status-btn ${h.status === s ? "hypothesis-status-btn--active" : ""}`}
                        onClick={() => updateStatus(h.id, s)}>{s}</button>
                    ))}
                  </div>

                  {/* Confidence adjustment */}
                  <div className="hypothesis-confidence-control">
                    <label>Confidence:</label>
                    <input type="range" min={0} max={100} value={Math.round(h.confidence * 100)}
                      onChange={(e) => updateConfidence(h.id, Number(e.target.value) / 100, "Manual adjustment")} />
                    <span>{Math.round(h.confidence * 100)}%</span>
                  </div>

                  {/* Evidence summary banner */}
                  <div className="evidence-summary-bar">
                    <span className="evidence-count evidence-count--supports"><ThumbsUp size={11} /> {es.sup}</span>
                    <span className="evidence-count evidence-count--contradicts"><ThumbsDown size={11} /> {es.con}</span>
                    <span className="evidence-count evidence-count--neutral"><Minus size={11} /> {es.neu}</span>
                    <span className="evidence-total">{es.total} evidence items</span>
                  </div>

                  {/* Evidence list */}
                  <div className="evidence-list">
                    {h.evidence.map((ev) => (
                      <EvidenceRow key={ev.id} ev={ev} onRemove={() => removeEvidence(h.id, ev.id)} />
                    ))}
                  </div>

                  {/* Add evidence form */}
                  <div className="evidence-add-form">
                    <select className="filter-select" value={addEvRefType}
                      onChange={(e) => { setAddEvRefType(e.target.value as "event" | "entity" | "article"); setAddEvRefId(""); }}>
                      <option value="event">Event</option>
                      <option value="entity">Entity</option>
                      <option value="article">Article</option>
                    </select>
                    <select className="filter-select" value={addEvRefId}
                      onChange={(e) => setAddEvRefId(Number(e.target.value))}>
                      <option value="">— select —</option>
                      {refOptions.map((o) => <option key={o.value} value={o.value}>{o.label}</option>)}
                    </select>
                    <select className="filter-select" value={addEvStance}
                      onChange={(e) => setAddEvStance(e.target.value as "supports" | "contradicts" | "neutral")}>
                      <option value="supports">Supports</option>
                      <option value="contradicts">Contradicts</option>
                      <option value="neutral">Neutral</option>
                    </select>
                    <input type="text" className="filter-input" placeholder="Note…" value={addEvNote}
                      onChange={(e) => setAddEvNote(e.target.value)} style={{ flex: 1 }} />
                    <button className="action-btn action-btn-sm action-btn-primary" onClick={() => addEvidence(h.id)}>
                      <Plus size={11} /> Link
                    </button>
                  </div>

                  {/* Confidence history */}
                  {h.confidence_history.length > 1 && (
                    <details className="confidence-history-details">
                      <summary><TrendingUp size={12} /> Confidence history ({h.confidence_history.length})</summary>
                      <div className="confidence-history-list">
                        {[...h.confidence_history].reverse().map((snap, i) => (
                          <div key={i} className="confidence-history-row">
                            <span className="confidence-history-ts">{new Date(snap.ts).toLocaleString()}</span>
                            <span className="confidence-history-val">{Math.round(snap.confidence * 100)}%</span>
                            <span className="confidence-history-reason">{snap.reason}</span>
                          </div>
                        ))}
                      </div>
                    </details>
                  )}

                  {/* Delete */}
                  <div style={{ marginTop: 8, textAlign: "right" }}>
                    <button className="action-btn action-btn-sm" style={{ color: "#dc2626" }}
                      onClick={() => deleteHypothesis(h.id)}>
                      <Trash2 size={11} /> Delete hypothesis
                    </button>
                  </div>
                </div>
              )}
            </div>
          );
        })}
      </div>
    </div>
  );
}
