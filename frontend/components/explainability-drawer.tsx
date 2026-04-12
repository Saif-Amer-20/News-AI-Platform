"use client";

import { useEffect, useState } from "react";
import {
  Brain, Shield, AlertTriangle, Newspaper, FileText, Layers,
  Globe, Users, TrendingUp, Target, BarChart3, Radar,
} from "lucide-react";
import Link from "next/link";
import { api } from "@/lib/api";
import type { EventExplain, AlertExplain, EntityExplain } from "@/lib/types";
import { ScoreBadge } from "./score-badge";

type Props =
  | { type: "event"; id: number; onClose: () => void }
  | { type: "alert"; id: number; onClose: () => void }
  | { type: "entity"; id: number; onClose: () => void };

export function ExplainabilityDrawer(props: Props) {
  const { type, id, onClose } = props;
  const [eventData, setEventData] = useState<EventExplain | null>(null);
  const [alertData, setAlertData] = useState<AlertExplain | null>(null);
  const [entityData, setEntityData] = useState<EntityExplain | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [section, setSection] = useState<string>("overview");

  useEffect(() => {
    setLoading(true);
    setError(null);
    setSection("overview");
    const pathMap = { event: `/events/${id}/explain/`, alert: `/alerts/${id}/explain/`, entity: `/entities/${id}/explain/` };
    api<EventExplain & AlertExplain & EntityExplain>(pathMap[type])
      .then((d) => {
        if (type === "event") setEventData(d as unknown as EventExplain);
        else if (type === "alert") setAlertData(d as unknown as AlertExplain);
        else setEntityData(d as unknown as EntityExplain);
      })
      .catch(() => setError("Could not load explanation data."))
      .finally(() => setLoading(false));
  }, [type, id]);

  const sections = type === "event"
    ? [["overview","Overview"],["confidence","Confidence"],["sources","Sources"],["conflicts","Conflicts"],["stories","Story Chain"]]
    : type === "alert"
    ? [["overview","Overview"],["actions","Actions"],["trigger","Trigger"],["context","Context"]]
    : [["overview","Overview"],["importance","Importance"],["diversity","Source Diversity"],["network","Network"]];

  return (
    <>
      <div className="drawer-overlay" onClick={onClose} />
      <aside className="drawer">
        <div className="drawer-header">
          <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
            <Brain size={18} />
            <span className="drawer-title">Explainability</span>
            <span className="badge badge-blue">{type}</span>
          </div>
          <button className="close-btn" onClick={onClose} aria-label="Close">✕</button>
        </div>

        {/* Section tabs */}
        <div className="drawer-tabs">
          {sections.map(([key, label]) => (
            <button
              key={key}
              className={`drawer-tab ${section === key ? "drawer-tab--active" : ""}`}
              onClick={() => setSection(key)}
            >
              {label}
            </button>
          ))}
        </div>

        <div className="drawer-body">
          {loading && (
            <div className="loading-state"><div className="loading-spinner" /> Analysing…</div>
          )}
          {error && <div className="empty-state">{error}</div>}

          {type === "event" && eventData && <EventExplainContent data={eventData} section={section} />}
          {type === "alert" && alertData && <AlertExplainContent data={alertData} section={section} />}
          {type === "entity" && entityData && <EntityExplainContent data={entityData} section={section} />}
        </div>
      </aside>
    </>
  );
}

/* ── Event explanation ─────────────────────────────────────── */
function EventExplainContent({ data, section }: { data: EventExplain; section: string }) {
  const cf = data.confidence_factors;

  if (section === "confidence") {
    return (
      <div className="explain-content">
        <div className="explain-card">
          <h4><Shield size={14} /> Confidence Breakdown</h4>
          <div className="explain-scores">
            <ScoreBadge label="Overall Confidence" value={cf.confidence_score} />
            <ScoreBadge label="Geo Confidence" value={cf.geo_confidence} />
          </div>
          <div className="explain-meter-group">
            <ExplainMeter label="Source Corroboration" value={Math.min(cf.source_count / 10, 1)} detail={`${cf.source_count} independent sources`} />
            <ExplainMeter label="Story Coverage" value={Math.min(cf.story_count / 5, 1)} detail={`${cf.story_count} story threads`} />
            <ExplainMeter label="Narrative Consistency" value={cf.narrative_conflicts ? 0.3 : 0.9} detail={cf.narrative_conflicts || "No conflicts detected"} warn={!!cf.narrative_conflicts} />
          </div>
        </div>
        <div className="explain-card">
          <h4><BarChart3 size={14} /> Importance Factors</h4>
          <div className="explain-factors">
            <div className="factor-row"><span className="factor-label">Source Count</span><span className="factor-value">{cf.source_count}</span></div>
            <div className="factor-row"><span className="factor-label">Story Threads</span><span className="factor-value">{cf.story_count}</span></div>
            <div className="factor-row"><span className="factor-label">Conflict Flag</span><span className="factor-value">{cf.conflict_flag ? "⚠ Yes" : "No"}</span></div>
          </div>
        </div>
      </div>
    );
  }

  if (section === "sources") {
    const srcData = data.source_correlation as { sources?: { name: string; trust_score: number; country: string; article_count: number }[] } | null;
    const sources = srcData?.sources ?? [];
    return (
      <div className="explain-content">
        <div className="explain-card">
          <h4><Globe size={14} /> Source Diversity Analysis</h4>
          <div className="explain-meter-group">
            <ExplainMeter label="Unique Sources" value={Math.min(cf.source_count / 8, 1)} detail={`${cf.source_count} sources reporting`} />
            <ExplainMeter label="Geographic Spread" value={cf.geo_confidence} detail={`Geo confidence: ${Number(cf.geo_confidence || 0).toFixed(2)}`} />
          </div>
        </div>
        {sources.length > 0 && (
          <div className="explain-card">
            <h4><Newspaper size={14} /> Contributing Sources</h4>
            <div className="explain-source-list">
              {sources.map((s, i) => (
                <div key={i} className="explain-source-row">
                  <div className="explain-source-name">{s.name}</div>
                  <div className="explain-source-meta">
                    {s.country && <span className="badge badge-gray">{s.country}</span>}
                    <span className="explain-trust">trust {Number(s.trust_score || 0).toFixed(2)}</span>
                    <span>{s.article_count} articles</span>
                  </div>
                </div>
              ))}
            </div>
          </div>
        )}
      </div>
    );
  }

  if (section === "conflicts") {
    return (
      <div className="explain-content">
        <div className="explain-card">
          <h4><AlertTriangle size={14} /> Conflict & Narrative Analysis</h4>
          {cf.narrative_conflicts ? (
            <>
              <div className="explain-conflict-banner">
                <AlertTriangle size={16} />
                <span>Conflicting narratives detected in source reporting</span>
              </div>
              <p className="explain-desc">{cf.narrative_conflicts}</p>
              <div className="explain-meter-group">
                <ExplainMeter label="Narrative Agreement" value={0.3} detail="Low agreement across sources" warn />
              </div>
            </>
          ) : (
            <div className="explain-no-conflict">
              <Shield size={16} />
              <span>No narrative conflicts detected. Sources broadly agree on key facts.</span>
            </div>
          )}
        </div>
        {cf.conflict_flag && (
          <div className="explain-card">
            <h4><Radar size={14} /> Conflict Flag Reasoning</h4>
            <p className="explain-desc">
              This event has been flagged as conflict-related based on event type classification,
              entity involvement, and reporting patterns from the source articles.
            </p>
          </div>
        )}
      </div>
    );
  }

  if (section === "stories") {
    return (
      <div className="explain-content">
        {data.story_chain.length === 0 ? (
          <div className="empty-state">No story chain data available</div>
        ) : (
          data.story_chain.map((story) => (
            <div key={story.story_id} className="explain-card">
              <div className="story-chain-header">
                <Layers size={14} />
                <strong>{story.title || `Story #${story.story_id}`}</strong>
                <span className="badge badge-gray">{story.article_count} articles</span>
              </div>
              <div className="story-chain-articles">
                {story.articles.slice(0, 6).map((a) => (
                  <div key={a.id} className="chain-article">
                    <Link href={`/articles/${a.id}`} className="chain-article-title" style={{ color: "var(--color-brand)", textDecoration: "none" }}>{a.title}</Link>
                    <span className="chain-article-meta">
                      {a.source__name} · {new Date(a.published_at).toLocaleDateString()} · quality {Number(a.quality_score ?? 0).toFixed(2)}
                    </span>
                  </div>
                ))}
                {story.articles.length > 6 && (
                  <span className="chain-more">+{story.articles.length - 6} more articles</span>
                )}
              </div>
            </div>
          ))
        )}
      </div>
    );
  }

  // Overview (default)
  return (
    <div className="explain-content">
      <div className="explain-card">
        <h4><FileText size={14} /> Event Summary</h4>
        <p className="explain-desc">{data.description || data.event_title}</p>
        <div className="explain-meta">
          <span className="badge badge-blue">{data.event_type}</span>
          {cf.conflict_flag && <span className="badge badge-red"><AlertTriangle size={11} /> conflict</span>}
        </div>
      </div>

      <div className="explain-card">
        <h4><Shield size={14} /> Quick Confidence</h4>
        <div className="explain-scores">
          <ScoreBadge label="Confidence" value={cf.confidence_score} />
          <ScoreBadge label="Geo Confidence" value={cf.geo_confidence} />
        </div>
        <div className="explain-factors">
          <div className="factor-row">
            <span className="factor-label">Sources</span>
            <span className="factor-value">{cf.source_count}</span>
          </div>
          <div className="factor-row">
            <span className="factor-label">Stories</span>
            <span className="factor-value">{cf.story_count}</span>
          </div>
          {cf.narrative_conflicts && (
            <div className="factor-row factor-row--warn">
              <span className="factor-label"><AlertTriangle size={12} /> Narrative Conflicts</span>
              <span className="factor-value">{cf.narrative_conflicts}</span>
            </div>
          )}
        </div>
      </div>

      {data.story_chain.length > 0 && (
        <div className="explain-card">
          <h4><Layers size={14} /> Story Chain ({data.story_chain.length})</h4>
          {data.story_chain.slice(0, 3).map((story) => (
            <div key={story.story_id} className="story-chain-item">
              <div className="story-chain-header">
                <strong>{story.title || `Story #${story.story_id}`}</strong>
                <span className="badge badge-gray">{story.article_count} articles</span>
              </div>
            </div>
          ))}
          {data.story_chain.length > 3 && (
            <span className="chain-more">+{data.story_chain.length - 3} more stories</span>
          )}
        </div>
      )}
    </div>
  );
}

/* ── Alert explanation ─────────────────────────────────────── */
function AlertExplainContent({ data, section }: { data: AlertExplain; section: string }) {
  if (section === "actions") {
    return (
      <div className="explain-content">
        <div className="explain-card">
          <h4><Shield size={14} /> Recommended Actions</h4>
          {data.recommended_actions.length === 0 ? (
            <p className="explain-desc">No specific actions recommended.</p>
          ) : (
            <ol className="explain-action-list">
              {data.recommended_actions.map((action, i) => (
                <li key={i} className="explain-action-item">{action}</li>
              ))}
            </ol>
          )}
        </div>
      </div>
    );
  }

  if (section === "trigger") {
    return (
      <div className="explain-content">
        <div className="explain-card">
          <h4><FileText size={14} /> Trigger Data</h4>
          {data.trigger_data.article ? (
            <pre className="explain-pre">{JSON.stringify(data.trigger_data, null, 2)}</pre>
          ) : (
            <p className="explain-desc">No trigger data available.</p>
          )}
        </div>
      </div>
    );
  }

  if (section === "context") {
    return (
      <div className="explain-content">
        <div className="explain-card">
          <h4><Layers size={14} /> Related Context</h4>
          {data.context.event ? (
            <pre className="explain-pre">{JSON.stringify(data.context, null, 2)}</pre>
          ) : (
            <p className="explain-desc">No additional context available.</p>
          )}
        </div>
      </div>
    );
  }

  // Overview
  return (
    <div className="explain-content">
      <div className="explain-card">
        <h4><Newspaper size={14} /> Rationale</h4>
        <p className="explain-desc">{data.rationale || "No rationale available."}</p>
        <div className="explain-meta">
          <span className="badge badge-blue">{data.alert_type}</span>
          <span className={`badge ${data.severity === "critical" ? "badge-red" : data.severity === "high" ? "badge-amber" : "badge-blue"}`}>
            {data.severity}
          </span>
        </div>
      </div>

      {data.recommended_actions.length > 0 && (
        <div className="explain-card">
          <h4><Shield size={14} /> Quick Actions</h4>
          <ul className="explain-actions">
            {data.recommended_actions.slice(0, 3).map((action, i) => (
              <li key={i}>{action}</li>
            ))}
          </ul>
          {data.recommended_actions.length > 3 && (
            <span className="chain-more">+{data.recommended_actions.length - 3} more</span>
          )}
        </div>
      )}
    </div>
  );
}

/* ── Entity explanation ────────────────────────────────────── */
function EntityExplainContent({ data, section }: { data: EntityExplain; section: string }) {
  if (section === "importance") {
    const f = data.importance_factors;
    return (
      <div className="explain-content">
        <div className="explain-card">
          <h4><TrendingUp size={14} /> Importance Breakdown</h4>
          <div className="explain-meter-group">
            <ExplainMeter label="Article Coverage" value={Math.min(f.article_count / 50, 1)} detail={`${f.article_count} articles mention this entity`} />
            <ExplainMeter label="Event Involvement" value={Math.min(f.event_count / 20, 1)} detail={`Linked to ${f.event_count} events`} />
            <ExplainMeter label="Network Centrality" value={Math.min(f.co_occurrence_count / 30, 1)} detail={`${f.co_occurrence_count} co-occurring entities`} />
            <ExplainMeter label="Source Mentions" value={f.mention_diversity} detail={`Diversity score: ${Number(f.mention_diversity || 0).toFixed(2)}`} />
            <ExplainMeter label="Avg Relevance" value={f.avg_relevance} detail={`Relevance: ${Number(f.avg_relevance || 0).toFixed(2)}`} />
          </div>
        </div>
      </div>
    );
  }

  if (section === "diversity") {
    const sd = data.source_diversity;
    return (
      <div className="explain-content">
        <div className="explain-card">
          <h4><Globe size={14} /> Source Diversity</h4>
          <div className="explain-meter-group">
            <ExplainMeter label="Unique Sources" value={Math.min(sd.unique_sources / 10, 1)} detail={`${sd.unique_sources} distinct sources`} />
          </div>
          {sd.source_types.length > 0 && (
            <div className="explain-tag-row">
              <span className="explain-tag-label">Source Types</span>
              {sd.source_types.map((t) => (
                <span key={t} className="badge badge-blue">{t}</span>
              ))}
            </div>
          )}
          {sd.countries.length > 0 && (
            <div className="explain-tag-row">
              <span className="explain-tag-label">Countries</span>
              {sd.countries.map((c) => (
                <span key={c} className="badge badge-gray">{c}</span>
              ))}
            </div>
          )}
        </div>
      </div>
    );
  }

  if (section === "network") {
    return (
      <div className="explain-content">
        {data.top_events.length > 0 && (
          <div className="explain-card">
            <h4><Radar size={14} /> Key Events ({data.top_events.length})</h4>
            <div className="explain-entity-list">
              {data.top_events.map((e) => (
                <a key={e.id} href={`/events?highlight=${e.id}`} className="explain-entity-row">
                  <span className="explain-entity-name">{e.title}</span>
                  <div className="explain-entity-meta">
                    <span className="badge badge-blue">{e.event_type}</span>
                    <span className="explain-trust">{Number(e.importance || 0).toFixed(2)}</span>
                  </div>
                </a>
              ))}
            </div>
          </div>
        )}
        {data.top_co_entities.length > 0 && (
          <div className="explain-card">
            <h4><Users size={14} /> Top Co-occurring Entities</h4>
            <div className="explain-entity-list">
              {data.top_co_entities.map((e) => (
                <a key={e.id} href={`/entities?highlight=${e.id}`} className="explain-entity-row">
                  <span className="explain-entity-name">{e.name}</span>
                  <div className="explain-entity-meta">
                    <span className="badge badge-purple">{e.entity_type}</span>
                    <span>{e.shared_articles} shared articles</span>
                  </div>
                </a>
              ))}
            </div>
          </div>
        )}
        {data.top_events.length === 0 && data.top_co_entities.length === 0 && (
          <div className="empty-state">No network data available</div>
        )}
      </div>
    );
  }

  // Overview
  return (
    <div className="explain-content">
      <div className="explain-card">
        <h4><Users size={14} /> Entity Profile</h4>
        <p className="explain-desc">{data.description || data.entity_name}</p>
        <div className="explain-meta">
          <span className="badge badge-purple">{data.entity_type}</span>
        </div>
      </div>
      <div className="explain-card">
        <h4><TrendingUp size={14} /> Quick Importance</h4>
        <div className="explain-factors">
          <div className="factor-row"><span className="factor-label">Articles</span><span className="factor-value">{data.importance_factors.article_count}</span></div>
          <div className="factor-row"><span className="factor-label">Events</span><span className="factor-value">{data.importance_factors.event_count}</span></div>
          <div className="factor-row"><span className="factor-label">Co-entities</span><span className="factor-value">{data.importance_factors.co_occurrence_count}</span></div>
          <div className="factor-row"><span className="factor-label">Avg Relevance</span><span className="factor-value">{Number(data.importance_factors.avg_relevance || 0).toFixed(2)}</span></div>
        </div>
      </div>
    </div>
  );
}

/* ── Shared sub-components ─────────────────────────────────── */
function ExplainMeter({ label, value, detail, warn }: { label: string; value: number; detail: string; warn?: boolean }) {
  const pct = Math.round(Math.min(1, Math.max(0, value)) * 100);
  const color = warn ? "#dc2626" : pct >= 70 ? "#16a34a" : pct >= 40 ? "#f59e0b" : "#64748b";
  return (
    <div className="explain-meter">
      <div className="explain-meter-header">
        <span className="explain-meter-label">{label}</span>
        <span className="explain-meter-pct" style={{ color }}>{pct}%</span>
      </div>
      <div className="explain-meter-track">
        <div className="explain-meter-fill" style={{ width: `${pct}%`, background: color }} />
      </div>
      <span className="explain-meter-detail">{detail}</span>
    </div>
  );
}
