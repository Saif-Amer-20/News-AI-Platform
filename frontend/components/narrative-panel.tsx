"use client";

import { AlertTriangle, Shield, Globe, MessageSquare, ChevronRight } from "lucide-react";
import type { ConflictAnalysis, NarrativeGroup } from "@/lib/types";

type Props = { analysis: ConflictAnalysis };

export function NarrativePanel({ analysis }: Props) {
  const { has_conflict, conflict_summary, narratives } = analysis;

  return (
    <div className="narrative-panel">
      {/* Conflict banner */}
      {has_conflict ? (
        <div className="narrative-conflict-banner">
          <AlertTriangle size={16} />
          <div>
            <strong>Conflicting narratives detected</strong>
            {conflict_summary && <p className="narrative-conflict-summary">{conflict_summary}</p>}
          </div>
        </div>
      ) : (
        <div className="narrative-no-conflict">
          <Shield size={16} />
          <span>Sources broadly agree on key facts — no narrative conflict detected.</span>
        </div>
      )}

      {/* Narrative groups */}
      {narratives.length === 0 ? (
        <div className="empty-state" style={{ padding: "1rem" }}>No narrative groups available</div>
      ) : (
        <div className="narrative-groups">
          {narratives.map((n) => (
            <NarrativeCard key={n.narrative_id} narrative={n} />
          ))}
        </div>
      )}
    </div>
  );
}

function NarrativeCard({ narrative }: { narrative: NarrativeGroup }) {
  const confPct = Math.round(narrative.confidence * 100);
  const confColor = confPct >= 70 ? "#16a34a" : confPct >= 40 ? "#f59e0b" : "#64748b";

  return (
    <div className="narrative-card">
      <div className="narrative-card-header">
        <div className="narrative-card-label">
          <MessageSquare size={14} />
          <strong>{narrative.label}</strong>
        </div>
        <div className="narrative-card-meta">
          <span className={`badge ${narrative.stance === "opposing" ? "badge-red" : narrative.stance === "supporting" ? "badge-green" : "badge-gray"}`}>
            {narrative.stance}
          </span>
          <span className="narrative-confidence" style={{ color: confColor }}>
            {confPct}% confidence
          </span>
        </div>
      </div>

      {narrative.summary && (
        <p className="narrative-summary">{narrative.summary}</p>
      )}

      {/* Key claims */}
      {narrative.key_claims.length > 0 && (
        <div className="narrative-claims">
          <span className="narrative-claims-label">Key Claims</span>
          <ul className="narrative-claim-list">
            {narrative.key_claims.map((claim, i) => (
              <li key={i}>{claim}</li>
            ))}
          </ul>
        </div>
      )}

      {/* Sources */}
      {narrative.sources.length > 0 && (
        <div className="narrative-sources">
          <span className="narrative-sources-label">
            <Globe size={12} /> {narrative.sources.length} source{narrative.sources.length > 1 ? "s" : ""} · {narrative.article_count} article{narrative.article_count > 1 ? "s" : ""}
          </span>
          <div className="narrative-source-chips">
            {narrative.sources.map((s, i) => (
              <span key={i} className="narrative-source-chip">
                {s.name}
                {s.country && <span className="badge badge-gray" style={{ marginLeft: 4 }}>{s.country}</span>}
              </span>
            ))}
          </div>
        </div>
      )}
    </div>
  );
}
