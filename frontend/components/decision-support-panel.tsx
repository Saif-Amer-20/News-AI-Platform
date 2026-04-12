"use client";

import { useState, useMemo } from "react";
import {
  ShieldAlert, Eye, ArrowUpCircle, CheckCircle2, HelpCircle,
} from "lucide-react";
import type { DecisionAction, DecisionSuggestion, DecisionRecord, Hypothesis } from "@/lib/types";

/* ── Persistence ───────────────────────────────────────────── */
function storageKey(caseId: number) { return `dec_${caseId}`; }
function loadDecisions(caseId: number): DecisionRecord[] {
  if (typeof window === "undefined") return [];
  try { return JSON.parse(localStorage.getItem(storageKey(caseId)) || "[]"); } catch { return []; }
}
function saveDecisions(caseId: number, d: DecisionRecord[]) { localStorage.setItem(storageKey(caseId), JSON.stringify(d)); }
function uid() { return `d_${Date.now()}_${Math.random().toString(36).slice(2, 7)}`; }

const ACTION_ICONS: Record<DecisionAction, React.ReactNode> = {
  monitor: <Eye size={14} />,
  escalate: <ArrowUpCircle size={14} />,
  verify: <HelpCircle size={14} />,
  close: <CheckCircle2 size={14} />,
};

const ACTION_COLORS: Record<DecisionAction, string> = {
  monitor: "#2563eb",
  escalate: "#dc2626",
  verify: "#d97706",
  close: "#059669",
};

/* ── Suggestion engine (client-side heuristics) ────────────── */
function computeSuggestions(
  hypotheses: Hypothesis[],
  eventCount: number,
  entityCount: number,
  sourceCount: number,
): DecisionSuggestion[] {
  const suggestions: DecisionSuggestion[] = [];

  /* Factors */
  const avgConfidence = hypotheses.length > 0
    ? hypotheses.reduce((s, h) => s + h.confidence, 0) / hypotheses.length : 0.5;
  const hasConflict = hypotheses.some((h) =>
    h.evidence.some((e) => e.stance === "contradicts"));
  const conflictRatio = hypotheses.length > 0
    ? hypotheses.filter((h) => h.evidence.some((e) => e.stance === "contradicts")).length / hypotheses.length : 0;
  const diversityScore = Math.min(1, sourceCount / 5);

  /* Monitor: low confidence, no conflict, limited data */
  const monitorScore = (1 - avgConfidence) * 0.4 + (1 - conflictRatio) * 0.3 + (1 - diversityScore) * 0.3;
  suggestions.push({
    action: "monitor",
    rationale: avgConfidence < 0.5
      ? "Confidence is low — continue monitoring for more data"
      : "Gather additional sources to strengthen the assessment",
    confidence_factor: avgConfidence,
    conflict_factor: conflictRatio,
    source_diversity_factor: diversityScore,
    overall_score: monitorScore,
  });

  /* Escalate: high conflict OR high importance with low confidence */
  const escalateScore = conflictRatio * 0.5 + (1 - avgConfidence) * 0.3 + diversityScore * 0.2;
  suggestions.push({
    action: "escalate",
    rationale: hasConflict
      ? "Conflicting evidence detected — escalate for senior review"
      : "Insufficient confidence to close — escalate for additional analysis",
    confidence_factor: avgConfidence,
    conflict_factor: conflictRatio,
    source_diversity_factor: diversityScore,
    overall_score: escalateScore,
  });

  /* Verify: medium confidence, some evidence */
  const verifyScore = Math.abs(avgConfidence - 0.5) < 0.3 ? 0.7 : 0.3;
  suggestions.push({
    action: "verify",
    rationale: "Cross-reference key findings with independent sources",
    confidence_factor: avgConfidence,
    conflict_factor: conflictRatio,
    source_diversity_factor: diversityScore,
    overall_score: verifyScore * 0.6 + (1 - diversityScore) * 0.4,
  });

  /* Close: high confidence, low conflict, good diversity */
  const closeScore = avgConfidence * 0.5 + (1 - conflictRatio) * 0.3 + diversityScore * 0.2;
  suggestions.push({
    action: "close",
    rationale: avgConfidence >= 0.7 && !hasConflict
      ? "High confidence with consistent evidence — safe to close"
      : "Consider closing with a qualified assessment",
    confidence_factor: avgConfidence,
    conflict_factor: conflictRatio,
    source_diversity_factor: diversityScore,
    overall_score: closeScore,
  });

  return suggestions.sort((a, b) => b.overall_score - a.overall_score);
}

/* ── Props ─────────────────────────────────────────────────── */
type Props = {
  caseId: number;
  hypotheses: Hypothesis[];
  eventCount: number;
  entityCount: number;
  sourceCount: number;
  onEvolution?: (type: string, title: string, detail?: string) => void;
};

/* ── Component ─────────────────────────────────────────────── */
export function DecisionSupportPanel({ caseId, hypotheses, eventCount, entityCount, sourceCount, onEvolution }: Props) {
  const [decisions, setDecisions] = useState<DecisionRecord[]>(() => loadDecisions(caseId));
  const [customRationale, setCustomRationale] = useState("");

  const suggestions = useMemo(
    () => computeSuggestions(hypotheses, eventCount, entityCount, sourceCount),
    [hypotheses, eventCount, entityCount, sourceCount],
  );

  const recordDecision = (action: DecisionAction, rationale: string) => {
    const rec: DecisionRecord = {
      id: uid(), case_id: caseId, action, rationale,
      decided_at: new Date().toISOString(),
    };
    const updated = [rec, ...decisions];
    setDecisions(updated);
    saveDecisions(caseId, updated);
    onEvolution?.("decision_made", `Decision: ${action}`, rationale);
  };

  const topSuggestion = suggestions[0];

  return (
    <div className="decision-panel">
      <div className="decision-header">
        <ShieldAlert size={16} />
        <h4>Decision Support</h4>
      </div>

      {/* Top recommendation */}
      <div className="decision-recommendation" style={{ borderLeftColor: ACTION_COLORS[topSuggestion.action] }}>
        <div className="decision-recommendation-icon">
          {ACTION_ICONS[topSuggestion.action]}
        </div>
        <div className="decision-recommendation-body">
          <div className="decision-recommendation-action">Recommended: <strong>{topSuggestion.action.toUpperCase()}</strong></div>
          <div className="decision-recommendation-rationale">{topSuggestion.rationale}</div>
          <div className="decision-factors">
            <span className="decision-factor">
              <span className="decision-factor-label">Confidence</span>
              <span className="decision-factor-bar">
                <span className="decision-factor-fill" style={{ width: `${topSuggestion.confidence_factor * 100}%`, background: "#2563eb" }} />
              </span>
            </span>
            <span className="decision-factor">
              <span className="decision-factor-label">Conflict</span>
              <span className="decision-factor-bar">
                <span className="decision-factor-fill" style={{ width: `${topSuggestion.conflict_factor * 100}%`, background: "#dc2626" }} />
              </span>
            </span>
            <span className="decision-factor">
              <span className="decision-factor-label">Src Diversity</span>
              <span className="decision-factor-bar">
                <span className="decision-factor-fill" style={{ width: `${topSuggestion.source_diversity_factor * 100}%`, background: "#059669" }} />
              </span>
            </span>
          </div>
        </div>
        <button className="action-btn action-btn-primary action-btn-sm"
          onClick={() => recordDecision(topSuggestion.action, topSuggestion.rationale)}>
          Accept
        </button>
      </div>

      {/* All suggestions */}
      <div className="decision-suggestion-grid">
        {suggestions.map((s) => (
          <button key={s.action} className="decision-suggestion-card"
            style={{ borderTopColor: ACTION_COLORS[s.action] }}
            onClick={() => recordDecision(s.action, s.rationale)}>
            <div className="decision-suggestion-icon" style={{ color: ACTION_COLORS[s.action] }}>
              {ACTION_ICONS[s.action]}
            </div>
            <div className="decision-suggestion-action">{s.action}</div>
            <div className="decision-suggestion-score">{Math.round(s.overall_score * 100)}%</div>
          </button>
        ))}
      </div>

      {/* Custom decision */}
      <div className="decision-custom">
        <input className="filter-input" placeholder="Custom rationale…" value={customRationale}
          onChange={(e) => setCustomRationale(e.target.value)} style={{ flex: 1 }} />
        <select className="filter-select" id="custom-action" defaultValue="monitor">
          <option value="monitor">Monitor</option>
          <option value="escalate">Escalate</option>
          <option value="verify">Verify</option>
          <option value="close">Close</option>
        </select>
        <button className="action-btn action-btn-sm" onClick={() => {
          const el = document.getElementById("custom-action") as HTMLSelectElement;
          if (customRationale.trim()) {
            recordDecision(el.value as DecisionAction, customRationale);
            setCustomRationale("");
          }
        }}>Record</button>
      </div>

      {/* Decision history */}
      {decisions.length > 0 && (
        <div className="decision-history">
          <h5>Decision Log</h5>
          {decisions.map((d) => (
            <div key={d.id} className="decision-history-row">
              <span className="decision-history-icon" style={{ color: ACTION_COLORS[d.action] }}>
                {ACTION_ICONS[d.action]}
              </span>
              <span className="decision-history-action">{d.action.toUpperCase()}</span>
              <span className="decision-history-rationale">{d.rationale}</span>
              <span className="decision-history-ts">{new Date(d.decided_at).toLocaleString()}</span>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}
