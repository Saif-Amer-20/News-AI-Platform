"use client";

import { useEffect, useState, useCallback, Suspense } from "react";
import { useSearchParams } from "next/navigation";
import { PageShell } from "@/components/shell";
import { api } from "@/lib/api";
import { FilterBar, type FilterDef } from "@/components/filter-bar";
import { AttachToCaseModal } from "@/components/attach-to-case-modal";
import { ExplainabilityDrawer } from "@/components/explainability-drawer";
import {
  Users, Radar, FileText, Link2, Clock, FolderOpen, Brain, Newspaper,
  Network, TrendingUp,
} from "lucide-react";
import { Pagination } from "@/components/pagination";
import Link from "next/link";
import type { EntitySummary, EntityCoOccurrence, EntityMention } from "@/lib/types";
import { ENTITY_TYPES } from "@/lib/types";
import { EntityGraph, type GraphNode, type GraphEdge } from "@/components/entity-graph";

type EntityDetail = EntitySummary & {
  description: string;
  aliases: string[];
  articles: { id: number; title: string; source_name: string; published_at: string }[];
  events: { id: number; title: string; event_type: string; first_reported_at: string }[];
};

type EntityTimelineEntry = { ts: string; title: string; type: string };

type EntityRelationshipRow = {
  relationship_id: number;
  entity_id: number;
  entity_name: string;
  entity_type: string;
  entity_country: string;
  relationship_type: string;
  strength_score: number;
  confidence: number;
  co_occurrence_count: number;
  growth_rate: number;
  last_seen_at: string | null;
};

type GraphData = {
  nodes: GraphNode[];
  edges: GraphEdge[];
};

const FILTER_DEFS: FilterDef[] = [
  { key: "entity_type", label: "Type", type: "select",
    options: ENTITY_TYPES.filter(Boolean).map((t) => ({ value: t, label: t })),
  },
  { key: "q", label: "Search", type: "text", placeholder: "Name or alias…" },
];

function EntitiesPageInner() {
  const searchParams = useSearchParams();
  const [entities, setEntities] = useState<EntitySummary[]>([]);
  const [loading, setLoading] = useState(true);
  const [selectedId, setSelectedId] = useState<number | null>(null);
  const [detail, setDetail] = useState<EntityDetail | null>(null);
  const [coOccurrences, setCoOccurrences] = useState<EntityCoOccurrence[]>([]);
  const [mentions, setMentions] = useState<EntityMention[]>([]);
  const [entityTimeline, setEntityTimeline] = useState<EntityTimelineEntry[]>([]);
  const [filters, setFilters] = useState<Record<string, string>>({ entity_type: "", q: "" });
  const [detailTab, setDetailTab] = useState<"overview" | "events" | "mentions" | "co_occ" | "timeline" | "relationships" | "graph">("overview");
  const [attachModal, setAttachModal] = useState<{ id: number; name: string } | null>(null);
  const [explainId, setExplainId] = useState<number | null>(null);
  const [page, setPage] = useState(1);
  const [count, setCount] = useState(0);
  const [relationships, setRelationships] = useState<EntityRelationshipRow[]>([]);
  const [graphData, setGraphData] = useState<GraphData | null>(null);

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const qs = new URLSearchParams();
      for (const [k, v] of Object.entries(filters)) { if (v) qs.set(k, v); }
      qs.set("page", String(page));
      const data = await api<{ results: EntitySummary[]; count: number }>(`/entities/?${qs.toString()}`);
      setEntities(data.results ?? []);
      setCount(data.count ?? 0);
    } catch { /* empty */ } finally { setLoading(false); }
  }, [filters, page]);

  useEffect(() => { void load(); }, [load]);

  // Reset to page 1 when filters change
  useEffect(() => { setPage(1); }, [filters]);

  // Auto-select entity from highlight param (cross-context navigation)
  useEffect(() => {
    const h = searchParams.get("highlight");
    if (h && entities.length > 0) {
      const id = Number(h);
      if (id && entities.some((e) => e.id === id)) {
        setSelectedId(id);
        setDetailTab("overview");
      }
    }
  }, [entities, searchParams]);

  const loadDetail = useCallback(async (id: number) => {
    try {
      const [d, co, mn, tl, rels, gd] = await Promise.all([
        api<EntityDetail>(`/entities/${id}/`),
        api<{ results: EntityCoOccurrence[] }>(`/entities/${id}/co-occurrences/`).catch(() => ({ results: [] })),
        api<{ results: EntityMention[] }>(`/entities/${id}/mentions/`).catch(() => ({ results: [] })),
        api<{ entries: EntityTimelineEntry[] }>(`/entities/${id}/timeline/`).catch(() => ({ entries: [] })),
        api<{ relationships: EntityRelationshipRow[] }>(`/entities/${id}/relationships/`).catch(() => ({ relationships: [] })),
        api<GraphData>(`/entities/${id}/graph-data/`).catch(() => ({ nodes: [], edges: [] })),
      ]);
      setDetail(d);
      setCoOccurrences(co.results ?? []);
      setMentions(mn.results ?? []);
      setEntityTimeline(tl.entries ?? []);
      setRelationships(rels.relationships ?? []);
      setGraphData(gd.nodes?.length ? gd : null);
    } catch { setDetail(null); }
  }, []);

  useEffect(() => {
    if (!selectedId) { setDetail(null); return; }
    void loadDetail(selectedId);
  }, [selectedId, loadDetail]);

  return (
    <PageShell title="Entity Explorer">
      <FilterBar filters={FILTER_DEFS} values={filters} onChange={setFilters} searchType="entities" />

      <div className="split-layout">
        {/* ── Entity List ─────────────────────────── */}
        <div className="split-list">
          <div className="data-table-wrap">
            {loading ? (
              <div className="loading-state"><div className="loading-spinner" /> Loading…</div>
            ) : (
              <table className="data-table">
                <thead>
                  <tr><th>Name</th><th>Type</th><th>Country</th><th>Articles</th><th>Events</th></tr>
                </thead>
                <tbody>
                  {entities.length === 0 ? (
                    <tr><td colSpan={5} className="empty-state">No entities found</td></tr>
                  ) : entities.map((en) => {
                    const displayName = en.canonical_name || en.name;
                    const isCanonicalised = en.canonical_name && en.canonical_name !== en.name;
                    const aliasCount = en.aliases?.length ?? 0;
                    return (
                    <tr key={en.id} className={selectedId === en.id ? "row-active" : ""} style={{ cursor: "pointer" }} onClick={() => { setSelectedId(en.id); setDetailTab("overview"); }}>
                      <td style={{ fontWeight: 600 }}>
                        {displayName}
                        {isCanonicalised && (
                          <span className="badge badge-gray" style={{ marginLeft: 4, fontSize: "0.68rem", opacity: 0.7 }} title={`Raw: ${en.name}`}>canonical</span>
                        )}
                        {aliasCount > 0 && (
                          <span className="badge badge-blue" style={{ marginLeft: 4, fontSize: "0.68rem" }} title={(en.aliases ?? []).join(", ")}>{aliasCount} alias{aliasCount !== 1 ? "es" : ""}</span>
                        )}
                        {en.merge_method && en.merge_method !== "none" && (
                          <span
                            className={`badge ${en.merge_method === "embedding" ? "badge-teal" : en.merge_method === "ai" || en.merge_method === "hybrid" ? "badge-purple" : "badge-gray"}`}
                            style={{ marginLeft: 4, fontSize: "0.65rem", opacity: 0.85 }}
                            title={`Merged via ${en.merge_method}${en.merge_confidence ? ` (${(Number(en.merge_confidence) * 100).toFixed(0)}% confidence)` : ""}`}
                          >
                            {en.merge_method === "embedding" ? "⬡ AI" : en.merge_method === "rule" ? "⊞ rule" : en.merge_method}
                          </span>
                        )}
                      </td>
                      <td><span className="badge badge-purple">{en.entity_type}</span></td>
                      <td>{en.country || "—"}</td>
                      <td>{en.article_count}</td>
                      <td>{en.event_count}</td>
                    </tr>
                    );
                  })}
                </tbody>
              </table>
            )}
          </div>
          <Pagination page={page} count={count} onChange={setPage} />
        </div>

        {/* ── Detail Panel ────────────────────────── */}
        {detail && (
          <div className="split-detail">
            <div className="detail-panel">
              <div className="detail-header">
                <button className="close-btn" onClick={() => setSelectedId(null)}>✕</button>
                <h3>{detail.canonical_name || detail.name}</h3>
                {detail.canonical_name && detail.canonical_name !== detail.name && (
                  <p style={{ fontSize: "0.78rem", color: "#94a3b8", marginTop: "-0.25rem", marginBottom: "0.25rem" }}>
                    Originally: <em>{detail.name}</em>
                  </p>
                )}
                <div style={{ display: "flex", gap: 6, flexWrap: "wrap", marginBottom: "0.5rem" }}>
                  <span className="badge badge-purple">{detail.entity_type}</span>
                  {detail.country && <span className="badge badge-gray">{detail.country}</span>}
                  {detail.merge_method && detail.merge_method !== "none" && (
                    <span
                      className={`badge ${detail.merge_method === "embedding" ? "badge-teal" : detail.merge_method === "ai" || detail.merge_method === "hybrid" ? "badge-purple" : "badge-gray"}`}
                      title={`Merge method: ${detail.merge_method}`}
                    >
                      {detail.merge_method === "embedding" ? "⬡ embedding" : detail.merge_method === "rule" ? "⊞ rule" : detail.merge_method}
                      {detail.merge_confidence && Number(detail.merge_confidence) > 0 && (
                        <span style={{ marginLeft: 4, opacity: 0.8 }}>
                          {(Number(detail.merge_confidence) * 100).toFixed(0)}%
                        </span>
                      )}
                    </span>
                  )}
                </div>
                {detail.description && <p className="detail-summary">{detail.description}</p>}

                {detail.aliases && detail.aliases.length > 0 && (
                  <div style={{ display: "flex", gap: 4, flexWrap: "wrap", marginBottom: "0.5rem" }}>
                    <span style={{ fontSize: "0.78rem", color: "#64748b" }}>Also known as:</span>
                    {detail.aliases.map((a) => <span key={a} className="badge badge-gray">{a}</span>)}
                  </div>
                )}

                <div className="case-stats-row">
                  <div className="case-stat"><FileText size={14} /><span>{detail.article_count}</span> Articles</div>
                  <div className="case-stat"><Radar size={14} /><span>{detail.event_count}</span> Events</div>
                  <div className="case-stat"><Link2 size={14} /><span>{relationships.length}</span> Relationships</div>
                  <div className="case-stat"><Network size={14} /><span>{coOccurrences.length}</span> Co-occurs</div>
                </div>

                <div className="detail-actions">
                  <button className="action-btn" onClick={() => setExplainId(detail.id)}>
                    <Brain size={14} /> Explain
                  </button>
                  <button className="action-btn action-btn-primary" onClick={() => setAttachModal({ id: detail.id, name: detail.name })}>
                    <FolderOpen size={14} /> Attach to Case
                  </button>
                </div>
              </div>

              <div className="detail-tabs">
                {([
                  ["overview", "Overview"], ["events", "Events"], ["mentions", "Mentions"],
                  ["relationships", "Relationships"], ["graph", "Graph"],
                  ["co_occ", "Co-occurrences"], ["timeline", "Timeline"],
                ] as const).map(([key, label]) => (
                  <button key={key} className={`detail-tab ${detailTab === key ? "detail-tab--active" : ""}`} onClick={() => setDetailTab(key)}>
                    {label}
                  </button>
                ))}
              </div>

              <div className="detail-tab-content">
                {detailTab === "overview" && (
                  <div className="tab-list">
                    {(detail.articles ?? []).length === 0 ? <div className="empty-state">No articles</div> : detail.articles.slice(0, 10).map((a) => (
                      <Link key={a.id} href={`/articles/${a.id}`} className="tab-list-item" style={{ textDecoration: "none", color: "inherit" }}>
                        <div className="tab-list-item-main"><Newspaper size={14} /><span>{a.title}</span></div>
                        <div className="tab-list-item-meta">{a.source_name} · {new Date(a.published_at).toLocaleDateString()}</div>
                        <span className="article-open-link"><FileText size={13} /> Open</span>
                      </Link>
                    ))}
                  </div>
                )}

                {detailTab === "events" && (
                  <div className="tab-list">
                    {(detail.events ?? []).length === 0 ? <div className="empty-state">No events</div> : detail.events.map((e) => (
                      <div key={e.id} className="tab-list-item">
                        <div className="tab-list-item-main">
                          <Radar size={14} />
                          <a href={`/events?highlight=${e.id}`} className="tab-link">{e.title}</a>
                          <span className="badge badge-blue">{e.event_type}</span>
                        </div>
                        <div className="tab-list-item-meta">{new Date(e.first_reported_at).toLocaleDateString()}</div>
                      </div>
                    ))}
                  </div>
                )}

                {detailTab === "mentions" && (
                  <div className="tab-list">
                    {mentions.length === 0 ? <div className="empty-state">No mentions data</div> : mentions.map((m, i) => (
                      <Link key={i} href={`/articles/${m.article_id}`} className="tab-list-item" style={{ textDecoration: "none", color: "inherit" }}>
                        <div className="tab-list-item-main"><Newspaper size={14} /><span>{m.article_title}</span></div>
                        <div className="tab-list-item-meta">{m.source} · Relevance: {m.relevance_score?.toFixed(2)}</div>
                        <span className="article-open-link"><FileText size={13} /> Open</span>
                      </Link>
                    ))}
                  </div>
                )}

                {detailTab === "co_occ" && (
                  <div className="tab-list">
                    {coOccurrences.length === 0 ? <div className="empty-state">No co-occurrences</div> : coOccurrences.map((c, i) => (
                      <div key={i} className="tab-list-item" style={{ cursor: "pointer" }} onClick={() => { setSelectedId(c.co_entity_id); setDetailTab("overview"); }}>
                        <div className="tab-list-item-main">
                          <Users size={14} />
                          <span>{c.co_entity_name}</span>
                          <span className="badge badge-purple">{c.co_entity_type}</span>
                        </div>
                        <div className="tab-list-item-meta">{c.shared_articles} shared articles</div>
                      </div>
                    ))}
                  </div>
                )}

                {detailTab === "timeline" && (
                  <div className="tab-timeline">
                    {entityTimeline.length === 0 ? <div className="empty-state">No timeline data</div> : entityTimeline.map((entry, i) => (
                      <div key={i} className="timeline-mini-entry">
                        <div className="timeline-mini-dot" />
                        <div className="timeline-mini-content">
                          <span className="timeline-mini-time">{new Date(entry.ts).toLocaleDateString()}</span>
                          <span className="timeline-mini-title">{entry.title}</span>
                        </div>
                      </div>
                    ))}
                  </div>
                )}

                {detailTab === "relationships" && (
                  <div className="tab-list">
                    {relationships.length === 0 ? (
                      <div className="empty-state">No stored relationships yet.<br />They are built automatically during ingestion.</div>
                    ) : relationships.map((rel) => {
                      const relColors: Record<string, string> = {
                        political: "badge-blue", military: "badge-red", economic: "badge-teal",
                        diplomatic: "badge-purple", conflict: "badge-orange", social: "badge-cyan",
                        unknown: "badge-gray",
                      };
                      const strengthPct = Math.round(rel.strength_score * 100);
                      return (
                        <div
                          key={rel.relationship_id}
                          className="tab-list-item"
                          style={{ cursor: "pointer" }}
                          onClick={() => { setSelectedId(rel.entity_id); setDetailTab("overview"); }}
                        >
                          <div className="tab-list-item-main">
                            <Link2 size={14} />
                            <span style={{ fontWeight: 600 }}>{rel.entity_name}</span>
                            <span className="badge badge-purple">{rel.entity_type}</span>
                            <span className={`badge ${relColors[rel.relationship_type] ?? "badge-gray"}`}>{rel.relationship_type}</span>
                            {rel.growth_rate > 0.5 && <span className="badge badge-orange" title="Growing fast">⚡</span>}
                          </div>
                          <div className="tab-list-item-meta">
                            Strength: <strong>{strengthPct}%</strong>
                            &nbsp;·&nbsp; {rel.co_occurrence_count} articles
                            {rel.last_seen_at && <>&nbsp;·&nbsp; Last: {new Date(rel.last_seen_at).toLocaleDateString()}</>}
                          </div>
                          {/* Strength bar */}
                          <div style={{ height: 3, background: "#1e293b", borderRadius: 2, marginTop: 4 }}>
                            <div style={{ height: 3, width: `${strengthPct}%`, background: "#6366f1", borderRadius: 2 }} />
                          </div>
                        </div>
                      );
                    })}
                  </div>
                )}

                {detailTab === "graph" && (
                  <div style={{ overflowX: "auto" }}>
                    {graphData ? (
                      <EntityGraph
                        nodes={graphData.nodes}
                        edges={graphData.edges}
                        width={580}
                        height={420}
                        onNodeClick={(nd) => {
                          if (!nd.is_root) { setSelectedId(nd.id); setDetailTab("overview"); }
                        }}
                      />
                    ) : (
                      <div className="empty-state">
                        No graph data yet.  Entity relationship scoring runs every 30 minutes.
                      </div>
                    )}
                  </div>
                )}
              </div>
            </div>
          </div>
        )}
      </div>

      {attachModal && (
        <AttachToCaseModal
          objectType="entity"
          objectId={attachModal.id}
          objectTitle={attachModal.name}
          onClose={() => setAttachModal(null)}
          onSuccess={() => { setAttachModal(null); void load(); }}
        />
      )}

      {explainId != null && (
        <ExplainabilityDrawer type="entity" id={explainId} onClose={() => setExplainId(null)} />
      )}
    </PageShell>
  );
}

export default function EntitiesPage() {
  return <Suspense><EntitiesPageInner /></Suspense>;
}
