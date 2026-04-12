"use client";

import { useEffect, useState, useCallback, Suspense } from "react";
import { PageShell } from "@/components/shell";
import { api } from "@/lib/api";
import { FilterBar, type FilterDef } from "@/components/filter-bar";
import { ImportanceBadge } from "@/components/score-badge";
import { ExplainabilityDrawer } from "@/components/explainability-drawer";
import { AttachToCaseModal } from "@/components/attach-to-case-modal";
import { Calendar, Radar, Bell, Users, ChevronRight, Brain, FolderOpen } from "lucide-react";
import type { TimelineEntry } from "@/lib/types";
import { EVENT_TYPES } from "@/lib/types";

const RANGE_OPTIONS = [
  { value: "24h", label: "24 h" },
  { value: "7d", label: "7 days" },
  { value: "30d", label: "30 days" },
  { value: "90d", label: "90 days" },
];

const TL_FILTERS: FilterDef[] = [
  { key: "event_type", label: "Event Type", type: "select", options: EVENT_TYPES.map((t) => ({ value: t, label: t })) },
  { key: "country", label: "Country", type: "text", placeholder: "Country code…" },
  { key: "entity", label: "Entity", type: "text", placeholder: "Entity name…" },
];

function dotColor(type: string) {
  switch (type) {
    case "event": return "#2563eb";
    case "alert": return "#dc2626";
    case "entity": return "#7c3aed";
    default: return "#64748b";
  }
}

function TimelinePageInner() {
  const [entries, setEntries] = useState<TimelineEntry[]>([]);
  const [loading, setLoading] = useState(true);
  const [range, setRange] = useState("7d");
  const [filters, setFilters] = useState<Record<string, string>>({});
  const [selected, setSelected] = useState<TimelineEntry | null>(null);

  // Drawers / modals
  const [explainId, setExplainId] = useState<{ type: "event" | "alert"; id: number } | null>(null);
  const [attachEntry, setAttachEntry] = useState<{ type: string; id: number; title: string } | null>(null);

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const qs = new URLSearchParams();
      qs.set("range", range);
      for (const [k, v] of Object.entries(filters)) { if (v) qs.set(k, v); }
      const data = await api<{ entries: TimelineEntry[] }>(`/timeline/?${qs.toString()}`);
      setEntries(data.entries ?? []);
    } catch { setEntries([]); } finally { setLoading(false); }
  }, [range, filters]);

  useEffect(() => { void load(); }, [load]);

  // Group entries by date
  const grouped = entries.reduce<Record<string, TimelineEntry[]>>((acc, e) => {
    const day = new Date(e.ts).toLocaleDateString();
    if (!acc[day]) acc[day] = [];
    acc[day].push(e);
    return acc;
  }, {});

  return (
    <PageShell title="Timeline">
      <div style={{ display: "flex", gap: "0.5rem", marginBottom: "0.75rem", flexWrap: "wrap", alignItems: "center" }}>
        {RANGE_OPTIONS.map((r) => (
          <button
            key={r.value}
            className={`action-btn ${range === r.value ? "action-btn-primary" : ""}`}
            onClick={() => setRange(r.value)}
          >
            <Calendar size={13} /> {r.label}
          </button>
        ))}
      </div>

      <FilterBar filters={TL_FILTERS} values={filters} onChange={setFilters} searchType="timeline" />

      {loading ? (
        <div className="loading-state"><div className="loading-spinner" /> Loading timeline…</div>
      ) : entries.length === 0 ? (
        <div className="empty-state" style={{ padding: "3rem", textAlign: "center" }}>No entries for this period</div>
      ) : (
        <div className="split-layout">
          <div className="split-list" style={{ maxWidth: 600 }}>
            {Object.entries(grouped).map(([day, dayEntries]) => (
              <div key={day} className="tl-day-group">
                <div className="tl-day-header"><Calendar size={13} /> {day}</div>
                {dayEntries.map((entry, i) => (
                  <div
                    key={entry.id ?? i}
                    className={`timeline-entry-row ${selected?.id === entry.id ? "row-active" : ""}`}
                    onClick={() => setSelected(entry)}
                  >
                    <div className="timeline-entry-time">
                      {new Date(entry.ts).toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" })}
                    </div>
                    <div className="timeline-entry-dot" style={{ background: dotColor(entry.type) }} />
                    <div className="timeline-entry-body">
                      <div className="timeline-entry-label">{entry.title}</div>
                      <div className="timeline-entry-meta-row">
                        <span className={`badge ${entry.type === "event" ? "badge-blue" : entry.type === "alert" ? "badge-red" : "badge-purple"}`}>
                          {entry.type}
                        </span>
                        {entry.country && <span className="badge badge-gray">{entry.country}</span>}
                        {entry.importance != null && <ImportanceBadge value={entry.importance} />}
                      </div>
                    </div>
                    <ChevronRight size={14} className="timeline-entry-arrow" />
                  </div>
                ))}
              </div>
            ))}
          </div>

          {/* ── Detail Sidebar ─────────────────────── */}
          {selected && (
            <div className="split-detail">
              <div className="detail-panel">
                <button className="close-btn" onClick={() => setSelected(null)}>✕</button>
                <h3>{selected.title}</h3>
                <div style={{ display: "flex", gap: 6, flexWrap: "wrap", marginBottom: "0.75rem" }}>
                  <span className={`badge ${selected.type === "event" ? "badge-blue" : selected.type === "alert" ? "badge-red" : "badge-purple"}`}>
                    {selected.type}
                  </span>
                  {selected.country && <span className="badge badge-gray">{selected.country}</span>}
                  {selected.event_type && <span className="badge badge-blue">{selected.event_type}</span>}
                </div>

                <div className="case-stats-row">
                  {selected.importance != null && (
                    <div className="case-stat"><Radar size={14} /><span>Importance: {Number(selected.importance).toFixed(2)}</span></div>
                  )}
                  <div className="case-stat"><Calendar size={14} /><span>{new Date(selected.ts).toLocaleString()}</span></div>
                  {selected.sources != null && (
                    <div className="case-stat"><span>{selected.sources} sources</span></div>
                  )}
                </div>

                <div className="detail-actions" style={{ marginTop: "1rem" }}>
                  {(selected.type === "event" || selected.type === "alert") && (
                    <button className="action-btn" onClick={() => setExplainId({ type: selected.type as "event" | "alert", id: selected.id })}>
                      <Brain size={14} /> Explain
                    </button>
                  )}
                  {(selected.type === "event" || selected.type === "alert") && (
                    <button className="action-btn" onClick={() => setAttachEntry({ type: selected.type, id: selected.id, title: selected.title })}>
                      <FolderOpen size={14} /> Attach to Case
                    </button>
                  )}
                  {selected.type === "event" && (
                    <a href={`/events?highlight=${selected.id}`} className="action-btn action-btn-primary">
                      <Radar size={14} /> View Event
                    </a>
                  )}
                  {selected.type === "alert" && (
                    <a href={`/alerts?highlight=${selected.id}`} className="action-btn action-btn-primary">
                      <Bell size={14} /> View Alert
                    </a>
                  )}
                </div>
              </div>
            </div>
          )}
        </div>
      )}

      {explainId != null && (
        <ExplainabilityDrawer type={explainId.type} id={explainId.id} onClose={() => setExplainId(null)} />
      )}

      {attachEntry && (
        <AttachToCaseModal
          objectType={attachEntry.type as "event" | "alert"}
          objectId={attachEntry.id}
          objectTitle={attachEntry.title}
          onClose={() => setAttachEntry(null)}
          onSuccess={load}
        />
      )}
    </PageShell>
  );
}

export default function TimelinePage() {
  return <Suspense><TimelinePageInner /></Suspense>;
}
