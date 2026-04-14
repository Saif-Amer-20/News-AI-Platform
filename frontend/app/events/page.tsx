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
import { FeedbackPanel } from "@/components/feedback-panel";
import type {
  EventSummary, EventEntity, EventSource, RelatedEvent, EventTimeline,
  ConflictAnalysis, IntelAssessment, EventEarlyWarning,
} from "@/lib/types";
import {
  EVENT_TYPES, VERIFICATION_LABELS, VERIFICATION_COLORS,
  EARLY_WARNING_ANOMALY_LABELS, RISK_TREND_LABELS, RISK_TREND_COLORS,
  CORRELATION_TYPE_LABELS, CORRELATION_STRENGTH_COLORS,
  SEVERITY_BADGE,
} from "@/lib/types";

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
  const [detailTab, setDetailTab] = useState<"overview" | "entities" | "articles" | "stories" | "sources" | "timeline" | "related" | "narratives" | "geo" | "alerts" | "intel" | "early_warning" | "feedback">("overview");
  const [entities, setEntities] = useState<EventEntity[]>([]);
  const [articles, setArticles] = useState<ArticleBrief[]>([]);
  const [stories, setStories] = useState<StoryBrief[]>([]);
  const [sources, setSources] = useState<EventSource[]>([]);
  const [timeline, setTimeline] = useState<EventTimeline | null>(null);
  const [related, setRelated] = useState<RelatedEvent[]>([]);
  const [narratives, setNarratives] = useState<ConflictAnalysis | null>(null);
  const [linkedAlerts, setLinkedAlerts] = useState<LinkedAlert[]>([]);
  const [intelAssessment, setIntelAssessment] = useState<IntelAssessment | null>(null);
  const [intelGenerating, setIntelGenerating] = useState(false);
  const [earlyWarningData, setEarlyWarningData] = useState<EventEarlyWarning | null>(null);
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
    } else if (detailTab === "intel") {
      api<IntelAssessment>(`/events/${id}/intel-assessment/`)
        .then(setIntelAssessment)
        .catch(() => setIntelAssessment(null))
        .finally(() => setDetailLoading(false));
    } else if (detailTab === "early_warning") {
      api<EventEarlyWarning>(`/events/${id}/early-warning/`)
        .then(setEarlyWarningData)
        .catch(() => setEarlyWarningData(null))
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
                  ["intel", "Intel"],
                  ["early_warning", "⚡ Early Warning"],
                  ["feedback", "🧠 Feedback"],
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
                    {detailTab === "intel" && (
                      <IntelTab
                        eventId={selected.id}
                        assessment={intelAssessment}
                        generating={intelGenerating}
                        onGenerate={async () => {
                          setIntelGenerating(true);
                          try {
                            const res = await api<IntelAssessment>(`/events/${selected.id}/intel-assessment/`, { method: "POST" });
                            setIntelAssessment(res);
                          } catch { /* empty */ } finally {
                            setIntelGenerating(false);
                          }
                        }}
                        onRegenerate={async () => {
                          setIntelGenerating(true);
                          try {
                            const res = await api<IntelAssessment>(`/events/${selected.id}/intel-assessment/?force=1`, { method: "POST" });
                            setIntelAssessment(res);
                          } catch { /* empty */ } finally {
                            setIntelGenerating(false);
                          }
                        }}
                      />
                    )}
                    {detailTab === "early_warning" && (
                      <EarlyWarningTab data={earlyWarningData} />
                    )}
                    {detailTab === "feedback" && selectedId && (
                      <div style={{ padding: "1rem 0" }}>
                        <FeedbackPanel
                          targetType="event"
                          targetId={selectedId}
                          allowedTypes={["confirmed", "false_positive", "misleading", "useful"]}
                        />
                      </div>
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

/* ── Intel Tab ─────────────────────────────────────────────── */

function IntelTab({
  eventId,
  assessment,
  generating,
  onGenerate,
  onRegenerate,
}: {
  eventId: number;
  assessment: IntelAssessment | null;
  generating: boolean;
  onGenerate: () => void;
  onRegenerate: () => void;
}) {
  if (!assessment) {
    return (
      <div className="tab-overview" style={{ textAlign: "center", padding: "2rem" }}>
        <Brain size={32} style={{ margin: "0 auto 0.75rem", opacity: 0.5 }} />
        <p style={{ marginBottom: "1rem", color: "#64748b" }}>No intelligence assessment yet for this event.</p>
        <button className="action-btn action-btn--primary" onClick={onGenerate} disabled={generating}>
          {generating ? "Generating…" : "Generate Assessment"}
        </button>
      </div>
    );
  }

  if (assessment.status === "failed") {
    return (
      <div className="tab-overview" style={{ textAlign: "center", padding: "2rem" }}>
        <p style={{ color: "#ef4444", marginBottom: "0.5rem" }}>Assessment failed</p>
        <p style={{ color: "#64748b", fontSize: "0.85rem", marginBottom: "1rem" }}>{assessment.error_message}</p>
        <button className="action-btn" onClick={onRegenerate} disabled={generating}>
          {generating ? "Retrying…" : "Retry"}
        </button>
      </div>
    );
  }

  const cred = parseFloat(assessment.credibility_score);
  const conf = parseFloat(assessment.confidence_score);
  const esc = parseFloat(assessment.escalation_probability);
  const cont = parseFloat(assessment.continuation_probability);
  const hidden = parseFloat(assessment.hidden_link_probability);
  const verColor = VERIFICATION_COLORS[assessment.verification_status] || "#6b7280";
  const verLabel = VERIFICATION_LABELS[assessment.verification_status] || assessment.verification_status;

  return (
    <div className="intel-assessment">
      {/* Regenerate button */}
      <div style={{ display: "flex", justifyContent: "flex-end", marginBottom: "0.75rem" }}>
        <button className="action-btn" onClick={onRegenerate} disabled={generating} style={{ fontSize: "0.75rem" }}>
          {generating ? "Regenerating…" : "↻ Regenerate"}
        </button>
      </div>

      {/* ── Diffusion / Coverage ─────────────────── */}
      <section className="intel-section">
        <h4 className="intel-section-title">📊 Story Diffusion</h4>
        <div className="intel-stats-row">
          <div className="intel-stat">
            <span className="intel-stat-num">{assessment.coverage_count}</span>
            <span className="intel-stat-label">Articles</span>
          </div>
          <div className="intel-stat">
            <span className="intel-stat-num">{assessment.distinct_source_count}</span>
            <span className="intel-stat-label">Sources</span>
          </div>
          <div className="intel-stat">
            <span className="intel-stat-num">{assessment.first_seen ? new Date(assessment.first_seen).toLocaleDateString() : "—"}</span>
            <span className="intel-stat-label">First Seen</span>
          </div>
          <div className="intel-stat">
            <span className="intel-stat-num">{assessment.last_seen ? new Date(assessment.last_seen).toLocaleDateString() : "—"}</span>
            <span className="intel-stat-label">Last Seen</span>
          </div>
        </div>

        {/* Source spread */}
        {assessment.source_list.length > 0 && (
          <div className="intel-source-list">
            <h5>Source Spread</h5>
            <div className="intel-source-grid">
              {assessment.source_list.map((s) => (
                <div key={s.source_id} className="intel-source-card">
                  <strong>{s.name}</strong>
                  <span className="badge badge-gray">{s.country || "—"}</span>
                  <span style={{ fontSize: "0.8rem", color: "#64748b" }}>{s.articles} articles · trust {s.trust.toFixed(2)}</span>
                </div>
              ))}
            </div>
          </div>
        )}

        {/* Publication timeline */}
        {assessment.publication_timeline.length > 0 && (
          <div style={{ marginTop: "0.75rem" }}>
            <h5>Publication Timeline</h5>
            <div className="intel-timeline-mini">
              {assessment.publication_timeline.slice(0, 15).map((t, i) => (
                <div key={i} className="timeline-mini-entry">
                  <div className="timeline-mini-dot" />
                  <div className="timeline-mini-content">
                    <span className="timeline-mini-time">{t.ts ? new Date(t.ts).toLocaleString() : "—"}</span>
                    <span className="timeline-mini-title">{t.title}</span>
                    <span className="timeline-mini-meta">{t.source}</span>
                  </div>
                </div>
              ))}
              {assessment.publication_timeline.length > 15 && (
                <div style={{ fontSize: "0.8rem", color: "#64748b", padding: "0.25rem 0 0 1.5rem" }}>
                  … and {assessment.publication_timeline.length - 15} more
                </div>
              )}
            </div>
          </div>
        )}
      </section>

      {/* ── Cross-Source Comparison ───────────────── */}
      <section className="intel-section">
        <h4 className="intel-section-title">🔀 Cross-Source Comparison</h4>

        {/* Claims */}
        {assessment.claims.length > 0 && (
          <div className="intel-claims">
            <h5>Claims ({assessment.claims.length})</h5>
            {assessment.claims.map((c, i) => (
              <div key={i} className="intel-claim-row">
                <span className={`badge ${c.status === "agreed" ? "badge-green" : c.status === "contradicted" ? "badge-red" : "badge-amber"}`}>
                  {c.status}
                </span>
                <span className="intel-claim-text">{c.claim}</span>
                <span className="intel-claim-sources">{c.sources.join(", ")}</span>
              </div>
            ))}
          </div>
        )}

        {/* Agreements */}
        {assessment.agreements.length > 0 && (
          <div style={{ marginTop: "0.75rem" }}>
            <h5>✅ Agreements</h5>
            <ul className="intel-bullet-list">
              {assessment.agreements.map((a, i) => <li key={i}>{a}</li>)}
            </ul>
          </div>
        )}

        {/* Contradictions */}
        {assessment.contradictions.length > 0 && (
          <div style={{ marginTop: "0.75rem" }}>
            <h5>⚠️ Contradictions</h5>
            {assessment.contradictions.map((c, i) => (
              <div key={i} className="intel-contradiction-card">
                <div><strong>{c.source_a}:</strong> {c.claim_a}</div>
                <div style={{ color: "#ef4444", fontWeight: 600, fontSize: "0.8rem" }}>vs</div>
                <div><strong>{c.source_b}:</strong> {c.claim_b}</div>
              </div>
            ))}
          </div>
        )}

        {/* Missing details */}
        {assessment.missing_details.length > 0 && (
          <div style={{ marginTop: "0.75rem" }}>
            <h5>❓ Missing Details</h5>
            <ul className="intel-bullet-list">
              {assessment.missing_details.map((m, i) => <li key={i}>{m}</li>)}
            </ul>
          </div>
        )}

        {/* Late emerging */}
        {assessment.late_emerging_claims.length > 0 && (
          <div style={{ marginTop: "0.75rem" }}>
            <h5>🕐 Late-Emerging Claims</h5>
            <ul className="intel-bullet-list">
              {assessment.late_emerging_claims.map((l, i) => <li key={i}>{l}</li>)}
            </ul>
          </div>
        )}
      </section>

      {/* ── AI Assessment ────────────────────────── */}
      <section className="intel-section">
        <h4 className="intel-section-title">🧠 AI Assessment</h4>
        {assessment.summary && (
          <div className="intel-text-block">
            <h5>Summary</h5>
            <p>{assessment.summary}</p>
            {assessment.summary_ar && <p className="intel-arabic">{assessment.summary_ar}</p>}
          </div>
        )}
        {assessment.source_agreement_summary && (
          <div className="intel-text-block">
            <h5>Source Agreement</h5>
            <p>{assessment.source_agreement_summary}</p>
            {assessment.source_agreement_summary_ar && <p className="intel-arabic">{assessment.source_agreement_summary_ar}</p>}
          </div>
        )}
        {assessment.dominant_narrative && (
          <div className="intel-text-block">
            <h5>Dominant Narrative</h5>
            <p>{assessment.dominant_narrative}</p>
            {assessment.dominant_narrative_ar && <p className="intel-arabic">{assessment.dominant_narrative_ar}</p>}
          </div>
        )}
        {assessment.uncertain_elements && (
          <div className="intel-text-block">
            <h5>Uncertain Elements</h5>
            <p>{assessment.uncertain_elements}</p>
            {assessment.uncertain_elements_ar && <p className="intel-arabic">{assessment.uncertain_elements_ar}</p>}
          </div>
        )}
        {assessment.analyst_reasoning && (
          <div className="intel-text-block">
            <h5>Analyst Reasoning</h5>
            <p>{assessment.analyst_reasoning}</p>
            {assessment.analyst_reasoning_ar && <p className="intel-arabic">{assessment.analyst_reasoning_ar}</p>}
          </div>
        )}
      </section>

      {/* ── Credibility & Forecast ────────────────── */}
      <section className="intel-section">
        <h4 className="intel-section-title">🛡️ Credibility & Forecast</h4>
        <div className="intel-stats-row">
          <div className="intel-stat">
            <span className="intel-stat-num" style={{ color: verColor }}>{(cred * 100).toFixed(0)}%</span>
            <span className="intel-stat-label">Credibility</span>
          </div>
          <div className="intel-stat">
            <span className="intel-stat-num">{(conf * 100).toFixed(0)}%</span>
            <span className="intel-stat-label">Confidence</span>
          </div>
          <div className="intel-stat">
            <span className="intel-stat-num" style={{ background: verColor, color: "#fff", padding: "2px 8px", borderRadius: "4px", fontSize: "0.8rem" }}>{verLabel}</span>
            <span className="intel-stat-label">Status</span>
          </div>
        </div>

        {/* Credibility factors */}
        {assessment.credibility_factors && (
          <div className="intel-factors">
            <h5>Factors</h5>
            <div className="intel-factor-grid">
              <div className="intel-factor-item">Source Diversity: <strong>{assessment.credibility_factors.source_diversity}</strong></div>
              <div className="intel-factor-item">Coverage Volume: <strong>{assessment.credibility_factors.coverage_volume}</strong></div>
              <div className="intel-factor-item">Contradictions: <strong>{assessment.credibility_factors.contradiction_count}</strong></div>
              <div className="intel-factor-item">Agreements: <strong>{assessment.credibility_factors.agreement_count}</strong></div>
              <div className="intel-factor-item">Time Span: <strong>{assessment.credibility_factors.time_span_hours}h</strong></div>
            </div>
          </div>
        )}

        {/* Probability bars */}
        <div style={{ marginTop: "1rem" }}>
          <h5>Forecast Probabilities</h5>
          <ProbabilityBar label="Escalation" value={esc} color="#ef4444" />
          <ProbabilityBar label="Continuation" value={cont} color="#f59e0b" />
          <ProbabilityBar label="Hidden Links" value={hidden} color="#8b5cf6" />
        </div>

        {assessment.monitoring_recommendation && (
          <div className="intel-text-block" style={{ marginTop: "0.75rem" }}>
            <h5>📡 Monitoring Recommendation</h5>
            <p>{assessment.monitoring_recommendation}</p>
          </div>
        )}
      </section>

      {/* Meta */}
      <div style={{ fontSize: "0.75rem", color: "#94a3b8", marginTop: "1rem", textAlign: "right" }}>
        Model: {assessment.model_used} · Generated: {assessment.generated_at ? new Date(assessment.generated_at).toLocaleString() : "—"}
      </div>
    </div>
  );
}

/* ─── Early Warning Tab ───────────────────────────────────── */
function EarlyWarningTab({ data }: { data: EventEarlyWarning | null }) {
  if (!data) return <p className="empty-message">No early warning data available.</p>;

  const ps = data.predictive_score;
  const sevBadge: Record<string, string> = { low: "badge-gray", medium: "badge-amber", high: "badge-red", critical: "badge-red" };

  return (
    <div className="ew-tab">
      {/* ── Predictive Score ──────────────────── */}
      {ps && (
        <section className="intel-section">
          <h4 className="intel-section-title">📊 Predictive Score</h4>

          {/* Risk trend badge */}
          <div style={{ display: "flex", alignItems: "center", gap: "0.75rem", marginBottom: "0.75rem" }}>
            <span style={{ color: RISK_TREND_COLORS[ps.risk_trend] ?? "#94a3b8", fontWeight: 700, fontSize: "1.1rem" }}>
              {RISK_TREND_LABELS[ps.risk_trend] ?? ps.risk_trend}
            </span>
            <span className="badge badge-blue" style={{ fontSize: "0.75rem" }}>
              Priority {(parseFloat(ps.monitoring_priority) * 100).toFixed(0)}%
            </span>
          </div>

          {/* Probability bars */}
          <EWProbBar label="Escalation" value={parseFloat(ps.escalation_probability)} color="#ef4444" />
          <EWProbBar label="Continuation" value={parseFloat(ps.continuation_probability)} color="#f59e0b" />
          <EWProbBar label="Misleading" value={parseFloat(ps.misleading_probability)} color="#8b5cf6" />
          <EWProbBar label="Monitoring" value={parseFloat(ps.monitoring_priority)} color="#3b82f6" />

          {/* Factor breakdown */}
          <div style={{ marginTop: "1rem" }}>
            <h5>Factor Breakdown</h5>
            <div className="intel-factor-grid">
              <div className="intel-factor-item">Anomaly: <strong>{(parseFloat(ps.anomaly_factor) * 100).toFixed(0)}%</strong></div>
              <div className="intel-factor-item">Correlation: <strong>{(parseFloat(ps.correlation_factor) * 100).toFixed(0)}%</strong></div>
              <div className="intel-factor-item">Historical: <strong>{(parseFloat(ps.historical_factor) * 100).toFixed(0)}%</strong></div>
              <div className="intel-factor-item">Source Diversity: <strong>{(parseFloat(ps.source_diversity_factor) * 100).toFixed(0)}%</strong></div>
              <div className="intel-factor-item">Velocity: <strong>{(parseFloat(ps.velocity_factor) * 100).toFixed(0)}%</strong></div>
            </div>
          </div>

          {/* Reasoning */}
          {ps.reasoning && (
            <div className="intel-text-block" style={{ marginTop: "0.75rem" }}>
              <h5>AI Reasoning</h5>
              <p>{ps.reasoning}</p>
              {ps.reasoning_ar && <p className="intel-arabic">{ps.reasoning_ar}</p>}
            </div>
          )}

          {/* Weak signals */}
          {ps.weak_signals.length > 0 && (
            <div style={{ marginTop: "0.75rem" }}>
              <h5>⚡ Weak Signals ({ps.weak_signals.length})</h5>
              <div className="ew-weak-signals">
                {ps.weak_signals.map((ws, i) => (
                  <div key={i} className="ew-weak-signal-card">
                    <span className={`badge ${ws.source === "anomaly" ? "badge-red" : ws.source === "correlation" ? "badge-amber" : "badge-blue"}`} style={{ fontSize: "0.7rem" }}>
                      {ws.source}
                    </span>
                    <span className="ew-ws-text">{ws.signal}</span>
                    <span className="ew-ws-weight">{(ws.weight * 100).toFixed(0)}%</span>
                  </div>
                ))}
              </div>
            </div>
          )}

          <div style={{ fontSize: "0.75rem", color: "#94a3b8", marginTop: "0.5rem", textAlign: "right" }}>
            Model: {ps.model_used} · Scored: {ps.scored_at ? new Date(ps.scored_at).toLocaleString() : "—"}
          </div>
        </section>
      )}

      {/* ── Anomalies ────────────────────────── */}
      {data.anomalies.length > 0 && (
        <section className="intel-section">
          <h4 className="intel-section-title">🔴 Anomalies ({data.anomalies.length})</h4>
          <div className="ew-anomaly-list">
            {data.anomalies.map((a) => (
              <div key={a.id} className="ew-anomaly-card">
                <div style={{ display: "flex", alignItems: "center", gap: "0.5rem", marginBottom: "0.35rem" }}>
                  <span className={`badge ${sevBadge[a.severity] ?? "badge-gray"}`}>{a.severity}</span>
                  <span className="badge badge-blue" style={{ fontSize: "0.7rem" }}>
                    {EARLY_WARNING_ANOMALY_LABELS[a.anomaly_type] ?? a.anomaly_type}
                  </span>
                  <span className={`badge ${a.status === "active" ? "badge-green" : "badge-gray"}`} style={{ fontSize: "0.7rem" }}>
                    {a.status}
                  </span>
                </div>
                <div style={{ fontWeight: 600, marginBottom: "0.25rem" }}>{a.title}</div>
                <div style={{ fontSize: "0.85rem", color: "#94a3b8" }}>{a.description}</div>
                <div className="ew-anomaly-metrics">
                  <span>Baseline: {a.baseline_value.toFixed(1)}</span>
                  <span>Current: {a.current_value.toFixed(1)}</span>
                  <span>Deviation: ×{a.deviation_factor.toFixed(2)}</span>
                  <span>Confidence: {(parseFloat(a.confidence) * 100).toFixed(0)}%</span>
                </div>
                <div style={{ fontSize: "0.75rem", color: "#64748b", marginTop: "0.25rem" }}>
                  Detected: {new Date(a.detected_at).toLocaleString()}
                  {a.location_country && ` · ${a.location_country}`}
                </div>
              </div>
            ))}
          </div>
        </section>
      )}

      {/* ── Correlations ─────────────────────── */}
      {data.correlations.length > 0 && (
        <section className="intel-section">
          <h4 className="intel-section-title">🔗 Signal Correlations ({data.correlations.length})</h4>
          <div className="ew-corr-list">
            {data.correlations.map((c) => (
              <div key={c.id} className="ew-corr-card">
                <div style={{ display: "flex", alignItems: "center", gap: "0.5rem", marginBottom: "0.3rem" }}>
                  <span className="badge badge-blue" style={{ fontSize: "0.7rem" }}>
                    {CORRELATION_TYPE_LABELS[c.correlation_type] ?? c.correlation_type}
                  </span>
                  <span style={{ color: CORRELATION_STRENGTH_COLORS[c.strength] ?? "#6b7280", fontWeight: 600, fontSize: "0.85rem" }}>
                    {c.strength.toUpperCase()}
                  </span>
                  <span style={{ fontSize: "0.8rem", color: "#94a3b8" }}>
                    Score: {(parseFloat(c.correlation_score) * 100).toFixed(0)}%
                  </span>
                </div>
                <div style={{ fontWeight: 600, marginBottom: "0.2rem" }}>{c.title}</div>
                {c.reasoning && <div style={{ fontSize: "0.85rem", color: "#94a3b8" }}>{c.reasoning}</div>}
                <div style={{ fontSize: "0.75rem", color: "#64748b", marginTop: "0.25rem" }}>
                  Detected: {new Date(c.detected_at).toLocaleString()}
                </div>
              </div>
            ))}
          </div>
        </section>
      )}

      {/* ── Historical Patterns ──────────────── */}
      {data.historical_patterns.length > 0 && (
        <section className="intel-section">
          <h4 className="intel-section-title">📜 Historical Patterns ({data.historical_patterns.length})</h4>
          <div className="ew-pattern-list">
            {data.historical_patterns.map((p) => (
              <div key={p.id} className="ew-pattern-card">
                <div style={{ display: "flex", alignItems: "center", gap: "0.5rem", marginBottom: "0.3rem" }}>
                  <span className="badge badge-blue">{p.pattern_name}</span>
                  <span style={{ fontSize: "0.85rem", fontWeight: 600 }}>
                    Similarity: {(parseFloat(p.similarity_score) * 100).toFixed(0)}%
                  </span>
                </div>
                {p.matched_event_title && (
                  <div style={{ fontSize: "0.85rem", color: "#94a3b8", marginBottom: "0.25rem" }}>
                    Matched event: <strong>{p.matched_event_title}</strong>
                  </div>
                )}
                {p.matching_dimensions.length > 0 && (
                  <div style={{ display: "flex", gap: "0.3rem", flexWrap: "wrap", marginBottom: "0.3rem" }}>
                    {p.matching_dimensions.map((d, i) => (
                      <span key={i} className="badge badge-gray" style={{ fontSize: "0.7rem" }}>{d}</span>
                    ))}
                  </div>
                )}
                {p.historical_outcome && (
                  <div style={{ fontSize: "0.85rem", marginBottom: "0.2rem" }}>
                    <strong>Historical Outcome:</strong> {p.historical_outcome}
                  </div>
                )}
                {p.predicted_trajectory && (
                  <div className="intel-text-block">
                    <h5>Predicted Trajectory</h5>
                    <p>{p.predicted_trajectory}</p>
                    {p.predicted_trajectory_ar && <p className="intel-arabic">{p.predicted_trajectory_ar}</p>}
                  </div>
                )}
              </div>
            ))}
          </div>
        </section>
      )}

      {/* Empty state */}
      {!ps && data.anomalies.length === 0 && data.correlations.length === 0 && data.historical_patterns.length === 0 && (
        <p className="empty-message">No early warning signals detected for this event yet.</p>
      )}
    </div>
  );
}

function EWProbBar({ label, value, color }: { label: string; value: number; color: string }) {
  return (
    <div style={{ display: "flex", alignItems: "center", gap: "0.5rem", marginBottom: "0.4rem" }}>
      <span style={{ width: "100px", fontSize: "0.8rem", color: "#64748b" }}>{label}</span>
      <div style={{ flex: 1, background: "#1e293b", borderRadius: "4px", height: "14px", overflow: "hidden" }}>
        <div style={{ width: `${(value * 100).toFixed(0)}%`, background: color, height: "100%", borderRadius: "4px", transition: "width 0.3s" }} />
      </div>
      <span style={{ width: "40px", fontSize: "0.8rem", fontWeight: 600 }}>{(value * 100).toFixed(0)}%</span>
    </div>
  );
}

function ProbabilityBar({ label, value, color }: { label: string; value: number; color: string }) {
  return (
    <div style={{ display: "flex", alignItems: "center", gap: "0.5rem", marginBottom: "0.4rem" }}>
      <span style={{ width: "100px", fontSize: "0.8rem", color: "#64748b" }}>{label}</span>
      <div style={{ flex: 1, background: "#1e293b", borderRadius: "4px", height: "14px", overflow: "hidden" }}>
        <div style={{ width: `${(value * 100).toFixed(0)}%`, background: color, height: "100%", borderRadius: "4px", transition: "width 0.3s" }} />
      </div>
      <span style={{ width: "40px", fontSize: "0.8rem", fontWeight: 600 }}>{(value * 100).toFixed(0)}%</span>
    </div>
  );
}
