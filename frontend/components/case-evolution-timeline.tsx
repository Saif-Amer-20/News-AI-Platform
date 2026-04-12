"use client";

import { useMemo } from "react";
import {
  Clock, Lightbulb, GitBranch, ShieldAlert, StickyNote,
  Radar, Users, TrendingUp, CheckCircle2,
} from "lucide-react";
import type { CaseEvolutionEntry } from "@/lib/types";

const TYPE_ICON: Record<string, React.ReactNode> = {
  event_added: <Radar size={12} />,
  entity_added: <Users size={12} />,
  hypothesis_created: <Lightbulb size={12} />,
  hypothesis_updated: <TrendingUp size={12} />,
  evidence_added: <TrendingUp size={12} />,
  decision_made: <ShieldAlert size={12} />,
  note_added: <StickyNote size={12} />,
  status_changed: <CheckCircle2 size={12} />,
  chain_created: <GitBranch size={12} />,
};

const TYPE_COLOR: Record<string, string> = {
  event_added: "#2563eb",
  entity_added: "#7c3aed",
  hypothesis_created: "#059669",
  hypothesis_updated: "#059669",
  evidence_added: "#d97706",
  decision_made: "#dc2626",
  note_added: "#64748b",
  status_changed: "#0ea5e9",
  chain_created: "#7c3aed",
};

/* ── Persistence ───────────────────────────────────────────── */
function storageKey(caseId: number) { return `evo_${caseId}`; }

export function loadEvolution(caseId: number): CaseEvolutionEntry[] {
  if (typeof window === "undefined") return [];
  try { return JSON.parse(localStorage.getItem(storageKey(caseId)) || "[]"); } catch { return []; }
}

export function appendEvolution(caseId: number, type: string, title: string, detail?: string) {
  const entries = loadEvolution(caseId);
  const entry: CaseEvolutionEntry = {
    ts: new Date().toISOString(), type: type as CaseEvolutionEntry["type"],
    title, detail,
  };
  const updated = [entry, ...entries].slice(0, 500); // cap
  localStorage.setItem(storageKey(caseId), JSON.stringify(updated));
  return updated;
}

/* ── Component ─────────────────────────────────────────────── */
type Props = {
  caseId: number;
  entries: CaseEvolutionEntry[];
};

export function CaseEvolutionTimeline({ caseId, entries }: Props) {
  /* Group by date */
  const grouped = useMemo(() => {
    const map = new Map<string, CaseEvolutionEntry[]>();
    entries.forEach((e) => {
      const day = new Date(e.ts).toLocaleDateString();
      if (!map.has(day)) map.set(day, []);
      map.get(day)!.push(e);
    });
    return [...map.entries()];
  }, [entries]);

  /* Stats */
  const stats = useMemo(() => {
    const counts: Record<string, number> = {};
    entries.forEach((e) => { counts[e.type] = (counts[e.type] ?? 0) + 1; });
    return counts;
  }, [entries]);

  return (
    <div className="case-evolution-panel">
      <div className="case-evolution-header">
        <Clock size={16} />
        <h4>Case Evolution</h4>
        <span className="badge badge-blue">{entries.length} events</span>
      </div>

      {/* Stats bar */}
      <div className="case-evolution-stats">
        {Object.entries(stats).map(([type, count]) => (
          <div key={type} className="case-evolution-stat">
            <span className="case-evolution-stat-icon" style={{ color: TYPE_COLOR[type] ?? "#64748b" }}>
              {TYPE_ICON[type] ?? <Clock size={12} />}
            </span>
            <span className="case-evolution-stat-count">{count}</span>
            <span className="case-evolution-stat-label">{type.replace(/_/g, " ")}</span>
          </div>
        ))}
      </div>

      {/* Timeline */}
      <div className="case-evolution-timeline">
        {grouped.length === 0 && <div className="empty-state">No evolution history yet — make changes to see the case evolve</div>}
        {grouped.map(([day, ents]) => (
          <div key={day} className="case-evolution-day">
            <div className="case-evolution-day-label">{day}</div>
            {ents.map((e, i) => (
              <div key={i} className="case-evolution-entry">
                <div className="case-evolution-dot" style={{ background: TYPE_COLOR[e.type] ?? "#64748b" }} />
                <div className="case-evolution-entry-body">
                  <div className="case-evolution-entry-header">
                    <span className="case-evolution-entry-icon" style={{ color: TYPE_COLOR[e.type] ?? "#64748b" }}>
                      {TYPE_ICON[e.type] ?? <Clock size={12} />}
                    </span>
                    <span className="case-evolution-entry-title">{e.title}</span>
                    <span className="case-evolution-entry-time">
                      {new Date(e.ts).toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" })}
                    </span>
                  </div>
                  {e.detail && <div className="case-evolution-entry-detail">{e.detail}</div>}
                  {e.snapshot && (
                    <div className="case-evolution-snapshot">
                      {e.snapshot.confidence !== undefined && (
                        <span className="badge badge-blue">conf: {Math.round(e.snapshot.confidence * 100)}%</span>
                      )}
                      {e.snapshot.status && (
                        <span className="badge badge-gray">{e.snapshot.status}</span>
                      )}
                    </div>
                  )}
                </div>
              </div>
            ))}
          </div>
        ))}
      </div>
    </div>
  );
}
