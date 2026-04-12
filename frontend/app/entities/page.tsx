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
} from "lucide-react";
import Link from "next/link";
import type { EntitySummary, EntityCoOccurrence, EntityMention } from "@/lib/types";
import { ENTITY_TYPES } from "@/lib/types";

type EntityDetail = EntitySummary & {
  description: string;
  aliases: string[];
  articles: { id: number; title: string; source_name: string; published_at: string }[];
  events: { id: number; title: string; event_type: string; first_reported_at: string }[];
};

type EntityTimelineEntry = { ts: string; title: string; type: string };

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
  const [detailTab, setDetailTab] = useState<"overview" | "events" | "mentions" | "co_occ" | "timeline">("overview");
  const [attachModal, setAttachModal] = useState<{ id: number; name: string } | null>(null);
  const [explainId, setExplainId] = useState<number | null>(null);

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const qs = new URLSearchParams();
      for (const [k, v] of Object.entries(filters)) { if (v) qs.set(k, v); }
      const data = await api<{ results: EntitySummary[] }>(`/entities/?${qs.toString()}`);
      setEntities(data.results ?? []);
    } catch { /* empty */ } finally { setLoading(false); }
  }, [filters]);

  useEffect(() => { void load(); }, [load]);

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
      const [d, co, mn, tl] = await Promise.all([
        api<EntityDetail>(`/entities/${id}/`),
        api<{ results: EntityCoOccurrence[] }>(`/entities/${id}/co-occurrences/`).catch(() => ({ results: [] })),
        api<{ results: EntityMention[] }>(`/entities/${id}/mentions/`).catch(() => ({ results: [] })),
        api<{ entries: EntityTimelineEntry[] }>(`/entities/${id}/timeline/`).catch(() => ({ entries: [] })),
      ]);
      setDetail(d);
      setCoOccurrences(co.results ?? []);
      setMentions(mn.results ?? []);
      setEntityTimeline(tl.entries ?? []);
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
                  ) : entities.map((en) => (
                    <tr key={en.id} className={selectedId === en.id ? "row-active" : ""} style={{ cursor: "pointer" }} onClick={() => { setSelectedId(en.id); setDetailTab("overview"); }}>
                      <td style={{ fontWeight: 600 }}>{en.name}</td>
                      <td><span className="badge badge-purple">{en.entity_type}</span></td>
                      <td>{en.country || "—"}</td>
                      <td>{en.article_count}</td>
                      <td>{en.event_count}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            )}
          </div>
        </div>

        {/* ── Detail Panel ────────────────────────── */}
        {detail && (
          <div className="split-detail">
            <div className="detail-panel">
              <div className="detail-header">
                <button className="close-btn" onClick={() => setSelectedId(null)}>✕</button>
                <h3>{detail.name}</h3>
                <div style={{ display: "flex", gap: 6, flexWrap: "wrap", marginBottom: "0.5rem" }}>
                  <span className="badge badge-purple">{detail.entity_type}</span>
                  {detail.country && <span className="badge badge-gray">{detail.country}</span>}
                </div>
                {detail.description && <p className="detail-summary">{detail.description}</p>}

                {detail.aliases && detail.aliases.length > 0 && (
                  <div style={{ display: "flex", gap: 4, flexWrap: "wrap", marginBottom: "0.5rem" }}>
                    <span style={{ fontSize: "0.78rem", color: "#64748b" }}>AKA:</span>
                    {detail.aliases.map((a) => <span key={a} className="badge badge-gray">{a}</span>)}
                  </div>
                )}

                <div className="case-stats-row">
                  <div className="case-stat"><FileText size={14} /><span>{detail.article_count}</span> Articles</div>
                  <div className="case-stat"><Radar size={14} /><span>{detail.event_count}</span> Events</div>
                  <div className="case-stat"><Link2 size={14} /><span>{coOccurrences.length}</span> Co-occurs</div>
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
