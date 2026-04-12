"use client";

import { useEffect, useState, useCallback, Suspense } from "react";
import { useSearchParams } from "next/navigation";
import { PageShell } from "@/components/shell";
import { api } from "@/lib/api";
import { FilterBar, type FilterDef } from "@/components/filter-bar";
import { ConfidenceBadge, ImportanceBadge, ConflictBadge, SeverityBadge } from "@/components/score-badge";
import { ExplainabilityDrawer } from "@/components/explainability-drawer";
import { AttachToCaseModal } from "@/components/attach-to-case-modal";
import { NarrativePanel } from "@/components/narrative-panel";
import {
  Brain, FolderOpen, Clock, MapPin, Users, Newspaper, Link2, Layers,
  ChevronRight, ArrowUpDown, ExternalLink, Bell, Globe, Map as MapIcon, Eye,
} from "lucide-react";
import { ArticlePreviewPanel } from "@/components/article-preview";
import Link from "next/link";
import type {
  EventSummary, EventEntity, EventSource, RelatedEvent, EventTimeline,
  ConflictAnalysis,
} from "@/lib/types";
import { EVENT_TYPES } from "@/lib/types";

type ArticleBrief = { id: number; title: string; published_at: string; source__name: string; importance_score: number };
type StoryBrief = { story_id: number; title: string; story_key: string; article_count: number; importance_score: number };
type LinkedAlert = { id: number; title: string; alert_type: string; severity: string; status: string; triggered_at: string };

const FILTER_DEFS: FilterDef[] = [
  { key: "event_type", label: "Event Type", type: "select", options: EVENT_TYPES.map((t) => ({ value: t, label: t })) },
  { key: "country", label: "Country", type: "text", placeholder: "Country code" },
  { key: "conflict", label: "Conflicts", type: "bool" },
  { key: "min_importance", label: "Min Importance", type: "text", placeholder: "e.g. 0.5" },
  { key: "min_sources", label: "Min Sources", type: "text", placeholder: "e.g. 3" },
];

function EventsPageInner() {
  const searchParams = useSearchParams();
  const [events, setEvents] = useState<EventSummary[]>([]);
  const [loading, setLoading] = useState(true);
  const [selectedId, setSelectedId] = useState<number | null>(null);
  const [filters, setFilters] = useState<Record<string, string>>({
    event_type: "", country: "", conflict: "", min_importance: "", min_sources: "",
  });
  const [ordering, setOrdering] = useState("-importance_score");

  // Detail tabs
  const [detailTab, setDetailTab] = useState<"overview" | "entities" | "articles" | "stories" | "sources" | "timeline" | "related" | "narratives" | "geo" | "alerts">("overview");
  const [entities, setEntities] = useState<EventEntity[]>([]);
  const [articles, setArticles] = useState<ArticleBrief[]>([]);
  const [stories, setStories] = useState<StoryBrief[]>([]);
  const [sources, setSources] = useState<EventSource[]>([]);
  const [timeline, setTimeline] = useState<EventTimeline | null>(null);
  const [related, setRelated] = useState<RelatedEvent[]>([]);
  const [narratives, setNarratives] = useState<ConflictAnalysis | null>(null);
  const [linkedAlerts, setLinkedAlerts] = useState<LinkedAlert[]>([]);
  const [detailLoading, setDetailLoading] = useState(false);

  // Drawers / modals
  const [explainId, setExplainId] = useState<number | null>(null);
  const [attachId, setAttachId] = useState<number | null>(null);
  const [articlePreviewId, setArticlePreviewId] = useState<number | null>(null);

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const qs = new URLSearchParams();
      for (const [k, v] of Object.entries(filters)) { if (v) qs.set(k, v); }
      if (ordering) qs.set("ordering", ordering);
      const data = await api<{ results: EventSummary[] }>(`/events/?${qs.toString()}`);
      setEvents(data.results ?? []);
    } catch { /* empty */ } finally { setLoading(false); }
  }, [filters, ordering]);

  useEffect(() => { void load(); }, [load]);

  // Auto-select event from highlight param (cross-context navigation)
  useEffect(() => {
    const h = searchParams.get("highlight");
    if (h && events.length > 0) {
      const id = Number(h);
      if (id && events.some((e) => e.id === id)) {
        setSelectedId(id);
        setDetailTab("overview");
      }
    }
  }, [events, searchParams]);

  const selected = events.find((e) => e.id === selectedId) ?? null;

  // Load detail tab data
  useEffect(() => {
    if (!selectedId) return;
    setDetailLoading(true);
    const id = selectedId;

    if (detailTab === "entities") {
      api<{ entities: EventEntity[] }>(`/events/${id}/entities/`)
        .then((d) => setEntities(d.entities ?? []))
        .catch(() => setEntities([]))
        .finally(() => setDetailLoading(false));
    } else if (detailTab === "articles") {
      api<{ results: ArticleBrief[] }>(`/events/${id}/articles/`)
        .then((d) => setArticles(d.results ?? []))
        .catch(() => setArticles([]))
        .finally(() => setDetailLoading(false));
    } else if (detailTab === "stories") {
      api<{ stories: StoryBrief[] }>(`/events/${id}/stories/`)
        .then((d) => setStories(d.stories ?? []))
        .catch(() => setStories([]))
        .finally(() => setDetailLoading(false));
    } else if (detailTab === "sources") {
      api<{ sources: EventSource[] }>(`/events/${id}/sources/`)
        .then((d) => setSources(d.sources ?? []))
        .catch(() => setSources([]))
        .finally(() => setDetailLoading(false));
    } else if (detailTab === "timeline") {
      api<EventTimeline>(`/events/${id}/timeline/`)
        .then(setTimeline)
        .catch(() => setTimeline(null))
        .finally(() => setDetailLoading(false));
    } else if (detailTab === "related") {
      api<{ related: RelatedEvent[] }>(`/events/${id}/related/`)
        .then((d) => setRelated(d.related ?? []))
        .catch(() => setRelated([]))
        .finally(() => setDetailLoading(false));
    } else if (detailTab === "narratives") {
      api<ConflictAnalysis>(`/events/${id}/narratives/`)
        .then(setNarratives)
        .catch(() => setNarratives(null))
        .finally(() => setDetailLoading(false));
    } else if (detailTab === "alerts") {
      api<{ results: LinkedAlert[] }>(`/events/${id}/alerts/`)
        .then((d) => setLinkedAlerts(d.results ?? []))
        .catch(() => setLinkedAlerts([]))
        .finally(() => setDetailLoading(false));
    } else {
      setDetailLoading(false);
    }
  }, [selectedId, detailTab]);

  const selectEvent = (id: number) => {
    setSelectedId(id);
    setDetailTab("overview");
  };

  const toggleSort = (field: string) => {
    setOrdering((o) => o === field ? `-${field}` : o === `-${field}` ? field : `-${field}`);
  };

  return (
    <PageShell title="Events Explorer">
      <FilterBar filters={FILTER_DEFS} values={filters} onChange={setFilters} searchType="event" />

      <div className="split-layout">
        {/* ── Event List ────────────────────────────────────── */}
        <div className="split-list">
          <div className="data-table-wrap">
            {loading ? (
              <div className="loading-state"><div className="loading-spinner" /> Loading events…</div>
            ) : events.length === 0 ? (
              <div className="empty-state">No events found matching filters</div>
            ) : (
              <table className="data-table">
                <thead>
                  <tr>
                    <th>Event</th>
                    <th>Type</th>
                    <th className="sortable-th" onClick={() => toggleSort("source_count")}>
                      Sources <ArrowUpDown size={11} />
                    </th>
                    <th className="sortable-th" onClick={() => toggleSort("importance_score")}>
                      Importance <ArrowUpDown size={11} />
                    </th>
                    <th className="sortable-th" onClick={() => toggleSort("confidence_score")}>
                      Confidence <ArrowUpDown size={11} />
                    </th>
                    <th>Date</th>
                  </tr>
                </thead>
                <tbody>
                  {events.map((ev) => (
                    <tr
                      key={ev.id}
                      className={selectedId === ev.id ? "row-active" : ""}
                      style={{ cursor: "pointer" }}
                      onClick={() => selectEvent(ev.id)}
                    >
                      <td>
                        <div className="event-cell-title">{ev.title}</div>
                        <div className="event-cell-meta">
                          {ev.conflict_flag && <ConflictBadge />}
                          {ev.location_country && <span className="badge badge-gray">{ev.location_country}</span>}
                        </div>
                      </td>
                      <td><span className="badge badge-blue">{ev.event_type}</span></td>
                      <td>{ev.source_count}</td>
                      <td><ImportanceBadge value={ev.importance_score} /></td>
                      <td><ConfidenceBadge value={ev.confidence_score} /></td>
                      <td className="cell-date">{new Date(ev.first_reported_at).toLocaleDateString()}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            )}
          </div>
        </div>

        {/* ── Event Detail ──────────────────────────────────── */}
        {selected && (
          <div className="split-detail">
            <div className="detail-panel">
              {/* Header */}
              <div className="detail-header">
                <button className="close-btn" onClick={() => setSelectedId(null)}>✕</button>
                <h3>{selected.title}</h3>
                <div style={{ display: "flex", gap: 6, flexWrap: "wrap", marginBottom: "0.5rem" }}>
                  <span className="badge badge-blue">{selected.event_type}</span>
                  {selected.conflict_flag && <ConflictBadge />}
                  {selected.location_country && <span className="badge badge-gray"><MapPin size={11} /> {selected.location_name || selected.location_country}</span>}
                </div>
                <p className="detail-summary">{selected.description}</p>

                {/* Score row */}
                <div className="detail-score-row">
                  <div className="detail-score-item">
                    <span className="detail-score-label">Importance</span>
                    <ImportanceBadge value={selected.importance_score} />
                  </div>
                  <div className="detail-score-item">
                    <span className="detail-score-label">Confidence</span>
                    <ConfidenceBadge value={selected.confidence_score} />
                  </div>
                  <div className="detail-score-item">
                    <span className="detail-score-label">Sources</span>
                    <span className="detail-score-num">{selected.source_count}</span>
                  </div>
                  <div className="detail-score-item">
                    <span className="detail-score-label">Stories</span>
                    <span className="detail-score-num">{selected.story_count}</span>
                  </div>
                </div>

                {/* Actions */}
                <div className="detail-actions">
                  <button className="action-btn" onClick={() => setExplainId(selected.id)}>
                    <Brain size={14} /> Explain
                  </button>
                  <button className="action-btn" onClick={() => setAttachId(selected.id)}>
                    <FolderOpen size={14} /> Attach to Case
                  </button>
                  {selected.location_country && (
                    <a className="action-btn" href={`/map?highlight=${selected.id}`}>
                      <MapIcon size={14} /> View on Map
                    </a>
                  )}
                  <a className="action-btn" href={`/timeline?highlight=${selected.id}`}>
                    <Clock size={14} /> View in Timeline
                  </a>
                </div>
              </div>

              {/* Tabs */}
              <div className="detail-tabs">
                {([
                  ["overview", "Overview"],
                  ["entities", "Entities"],
                  ["articles", "Articles"],
                  ["stories", "Stories"],
                  ["sources", "Sources"],
                  ["narratives", "Narratives"],
                  ["geo", "Geo"],
                  ["alerts", "Alerts"],
                  ["timeline", "Timeline"],
                  ["related", "Related"],
                ] as const).map(([key, label]) => (
                  <button
                    key={key}
                    className={`detail-tab ${detailTab === key ? "detail-tab--active" : ""}`}
                    onClick={() => setDetailTab(key)}
                  >
                    {label}
                  </button>
                ))}
              </div>

              {/* Tab content */}
              <div className="detail-tab-content">
                {detailLoading && detailTab !== "overview" ? (
                  <div className="loading-state" style={{ padding: "1.5rem" }}><div className="loading-spinner" /> Loading…</div>
                ) : (
                  <>
                    {detailTab === "overview" && (
                      <OverviewTab event={selected} />
                    )}
                    {detailTab === "entities" && (
                      <EntitiesTab entities={entities} />
                    )}
                    {detailTab === "articles" && (
                      <ArticlesTab articles={articles} previewId={articlePreviewId} onPreview={setArticlePreviewId} />
                    )}
                    {detailTab === "stories" && (
                      <StoriesTab stories={stories} />
                    )}
                    {detailTab === "sources" && (
                      <SourcesTab sources={sources} />
                    )}
                    {detailTab === "timeline" && (
                      <TimelineTab timeline={timeline} />
                    )}
                    {detailTab === "related" && (
                      <RelatedTab related={related} onSelect={selectEvent} />
                    )}
                    {detailTab === "narratives" && (
                      <NarrativesTab data={narratives} />
                    )}
                    {detailTab === "geo" && (
                      <GeoTab event={selected} />
                    )}
                    {detailTab === "alerts" && (
                      <AlertsTab alerts={linkedAlerts} />
                    )}
                  </>
                )}
              </div>
            </div>
          </div>
        )}
      </div>

      {/* Explainability Drawer */}
      {explainId != null && (
        <ExplainabilityDrawer type="event" id={explainId} onClose={() => setExplainId(null)} />
      )}

      {/* Attach to Case Modal */}
      {attachId != null && selected && (
        <AttachToCaseModal
          objectType="event"
          objectId={attachId}
          objectTitle={selected.title}
          onClose={() => setAttachId(null)}
          onSuccess={load}
        />
      )}
    </PageShell>
  );
}

export default function EventsPage() {
  return <Suspense><EventsPageInner /></Suspense>;
}

/* ── Tab Sub-components ────────────────────────────────────── */

function OverviewTab({ event }: { event: EventSummary }) {
  return (
    <div className="tab-overview">
      <div className="overview-row">
        <Clock size={14} />
        <span>First reported: <strong>{new Date(event.first_reported_at).toLocaleString()}</strong></span>
      </div>
      <div className="overview-row">
        <Clock size={14} />
        <span>Last reported: <strong>{new Date(event.last_reported_at).toLocaleString()}</strong></span>
      </div>
      <div className="overview-row">
        <MapPin size={14} />
        <span>Location: <strong>{event.location_name || "—"}, {event.location_country || "—"}</strong></span>
      </div>
      {event.narrative_conflicts && (
        <div className="overview-row overview-row--warn">
          <span className="badge badge-red">Narrative Conflict</span>
          <span>{event.narrative_conflicts}</span>
        </div>
      )}
    </div>
  );
}

function EntitiesTab({ entities }: { entities: EventEntity[] }) {
  if (entities.length === 0) return <div className="empty-state">No entities linked</div>;
  return (
    <div className="tab-list">
      {entities.map((e) => (
        <a key={e.entity_id} href={`/entities?highlight=${e.entity_id}`} className="tab-list-item">
          <div className="tab-list-item-main">
            <Users size={14} />
            <strong>{e.entity_name}</strong>
            <span className="badge badge-purple">{e.entity_type}</span>
            {e.entity_country && <span className="badge badge-gray">{e.entity_country}</span>}
          </div>
          <div className="tab-list-item-meta">
            {e.mention_count} mentions · relevance {Number(e.avg_relevance || 0).toFixed(2)}
          </div>
          <ChevronRight size={14} className="tab-list-arrow" />
        </a>
      ))}
    </div>
  );
}

function ArticlesTab({ articles, previewId, onPreview }: { articles: ArticleBrief[]; previewId: number | null; onPreview: (id: number | null) => void }) {
  if (articles.length === 0) return <div className="empty-state">No articles</div>;
  return (
    <div className="tab-list">
      {articles.map((a) => (
        <div key={a.id}>
          <div className="tab-list-item">
            <div className="tab-list-item-main">
              <Newspaper size={14} />
              <Link href={`/articles/${a.id}`} className="tab-link">{a.title}</Link>
            </div>
            <div className="tab-list-item-meta">
              {a.source__name} · {new Date(a.published_at).toLocaleDateString()} · importance {Number(a.importance_score).toFixed(2)}
            </div>
            <button className="article-open-link" style={{ background: "none", border: "none", cursor: "pointer" }} onClick={() => onPreview(previewId === a.id ? null : a.id)}>
              <Eye size={13} /> {previewId === a.id ? "Hide" : "Preview"}
            </button>
          </div>
          {previewId === a.id && <ArticlePreviewPanel articleId={a.id} />}
        </div>
      ))}
    </div>
  );
}

function StoriesTab({ stories }: { stories: StoryBrief[] }) {
  if (stories.length === 0) return <div className="empty-state">No stories</div>;
  return (
    <div className="tab-list">
      {stories.map((s) => (
        <div key={s.story_id} className="tab-list-item">
          <div className="tab-list-item-main">
            <Layers size={14} />
            <strong>{s.title || `Story #${s.story_id}`}</strong>
            <span className="badge badge-gray">{s.article_count} articles</span>
          </div>
          <div className="tab-list-item-meta">
            key: {s.story_key} · importance {Number(s.importance_score).toFixed(2)}
          </div>
        </div>
      ))}
    </div>
  );
}

function SourcesTab({ sources }: { sources: EventSource[] }) {
  if (sources.length === 0) return <div className="empty-state">No sources</div>;
  return (
    <div className="tab-list">
      {sources.map((s) => (
        <div key={s.source_id} className="tab-list-item">
          <div className="tab-list-item-main">
            <ExternalLink size={14} />
            <strong>{s.name}</strong>
            <span className="badge badge-gray">{s.source_type}</span>
            {s.country && <span className="badge badge-gray">{s.country}</span>}
          </div>
          <div className="tab-list-item-meta">
            trust {Number(s.trust_score || 0).toFixed(2)} · {s.article_count} articles · {new Date(s.earliest).toLocaleDateString()} – {new Date(s.latest).toLocaleDateString()}
          </div>
        </div>
      ))}
    </div>
  );
}

function TimelineTab({ timeline }: { timeline: EventTimeline | null }) {
  if (!timeline) return <div className="empty-state">No timeline data</div>;
  return (
    <div className="tab-timeline">
      <div className="overview-row">
        <Clock size={14} />
        <span>Coverage: {new Date(timeline.first_reported_at).toLocaleDateString()} – {new Date(timeline.last_reported_at).toLocaleDateString()}</span>
      </div>
      {timeline.article_timeline.map((a) => (
        <div key={a.id} className="timeline-mini-entry">
          <div className="timeline-mini-dot" />
          <div className="timeline-mini-content">
            <span className="timeline-mini-time">{new Date(a.published_at).toLocaleString()}</span>
            <Link href={`/articles/${a.id}`} className="timeline-mini-title" style={{ color: "var(--color-brand)", textDecoration: "none" }}>{a.title}</Link>
            <span className="timeline-mini-meta">{a.source__name} · importance {Number(a.importance_score).toFixed(2)}</span>
          </div>
        </div>
      ))}
    </div>
  );
}

function RelatedTab({ related, onSelect }: { related: RelatedEvent[]; onSelect: (id: number) => void }) {
  if (related.length === 0) return <div className="empty-state">No related events</div>;
  return (
    <div className="tab-list">
      {related.map((r) => (
        <div key={r.event_id} className="tab-list-item" style={{ cursor: "pointer" }} onClick={() => onSelect(r.event_id)}>
          <div className="tab-list-item-main">
            <Link2 size={14} />
            <span>{r.title}</span>
            <span className="badge badge-blue">{r.event_type}</span>
          </div>
          <div className="tab-list-item-meta">
            {r.relation} · {r.country} · importance {Number(r.importance).toFixed(2)}
          </div>
          <ChevronRight size={14} className="tab-list-arrow" />
        </div>
      ))}
    </div>
  );
}

function NarrativesTab({ data }: { data: ConflictAnalysis | null }) {
  if (!data) return <div className="empty-state">No narrative analysis available</div>;
  return <NarrativePanel analysis={data} />;
}

function GeoTab({ event }: { event: EventSummary }) {
  return (
    <div className="tab-overview">
      <div className="overview-row">
        <MapPin size={14} />
        <span>Location: <strong>{event.location_name || "Unknown"}</strong></span>
      </div>
      <div className="overview-row">
        <Globe size={14} />
        <span>Country: <strong>{event.location_country || "Unknown"}</strong></span>
      </div>
      {event.location_country && (
        <a className="action-btn" href={`/map?country=${event.location_country}&highlight=${event.id}`} style={{ display: "inline-flex", alignItems: "center", gap: 4, marginTop: "0.5rem" }}>
          <MapIcon size={14} /> Open on Map
        </a>
      )}
      <div style={{ marginTop: "0.75rem", fontSize: "0.85rem", color: "#64748b" }}>
        <strong>Confidence</strong>
        <div className="detail-score-row" style={{ marginTop: "0.35rem" }}>
          <div className="detail-score-item">
            <span className="detail-score-label">Confidence</span>
            <ConfidenceBadge value={event.confidence_score} />
          </div>
          <div className="detail-score-item">
            <span className="detail-score-label">Sources</span>
            <span className="detail-score-num">{event.source_count}</span>
          </div>
        </div>
      </div>
    </div>
  );
}

function AlertsTab({ alerts }: { alerts: LinkedAlert[] }) {
  if (alerts.length === 0) return <div className="empty-state">No linked alerts</div>;
  return (
    <div className="tab-list">
      {alerts.map((a) => (
        <a key={a.id} href={`/alerts?highlight=${a.id}`} className="tab-list-item">
          <div className="tab-list-item-main">
            <Bell size={14} />
            <span>{a.title}</span>
            <span className={`badge ${a.severity === "critical" ? "badge-red" : a.severity === "high" ? "badge-amber" : "badge-blue"}`}>{a.severity}</span>
            <span className={`badge ${a.status === "open" ? "badge-red" : a.status === "resolved" ? "badge-green" : "badge-gray"}`}>{a.status}</span>
          </div>
          <div className="tab-list-item-meta">
            {a.alert_type} · {new Date(a.triggered_at).toLocaleDateString()}
          </div>
          <ChevronRight size={14} className="tab-list-arrow" />
        </a>
      ))}
    </div>
  );
}
