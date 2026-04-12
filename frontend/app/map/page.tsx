"use client";

import { useEffect, useState, useCallback, Suspense } from "react";
import { PageShell } from "@/components/shell";
import { api } from "@/lib/api";
import { FilterBar, type FilterDef } from "@/components/filter-bar";
import { ImportanceBadge, ConfidenceBadge } from "@/components/score-badge";
import { ExplainabilityDrawer } from "@/components/explainability-drawer";
import { AttachToCaseModal } from "@/components/attach-to-case-modal";
import { MapPin, Globe, Layers, TrendingUp, Brain, FolderOpen } from "lucide-react";
import type { MapFeature, HeatPoint, ClusterPoint } from "@/lib/types";
import { EVENT_TYPES } from "@/lib/types";

const MAP_FILTERS: FilterDef[] = [
  { key: "event_type", label: "Event Type", type: "select", options: EVENT_TYPES.map((t) => ({ value: t, label: t })) },
  { key: "country", label: "Country", type: "text", placeholder: "Country code…" },
  { key: "min_importance", label: "Min Importance", type: "text", placeholder: "0-1" },
];

function MapPageInner() {
  const [features, setFeatures] = useState<MapFeature[]>([]);
  const [heatPoints, setHeatPoints] = useState<HeatPoint[]>([]);
  const [clusters, setClusters] = useState<ClusterPoint[]>([]);
  const [loading, setLoading] = useState(true);
  const [filters, setFilters] = useState<Record<string, string>>({});
  const [selected, setSelected] = useState<MapFeature | null>(null);
  const [view, setView] = useState<"events" | "heat" | "clusters">("events");

  // Drawers / modals
  const [explainId, setExplainId] = useState<number | null>(null);
  const [attachEvent, setAttachEvent] = useState<{ id: number; title: string } | null>(null);

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const qs = new URLSearchParams();
      for (const [k, v] of Object.entries(filters)) { if (v) qs.set(k, v); }
      const [ev, ht, cl] = await Promise.all([
        api<{ type: string; features: MapFeature[] }>(`/map/events/?${qs.toString()}`).catch(() => ({ features: [] as MapFeature[] })),
        api<{ points: HeatPoint[] }>(`/map/heat/?${qs.toString()}`).catch(() => ({ points: [] as HeatPoint[] })),
        api<{ clusters: ClusterPoint[] }>(`/map/clusters/?${qs.toString()}`).catch(() => ({ clusters: [] as ClusterPoint[] })),
      ]);
      setFeatures((ev as { features: MapFeature[] }).features ?? []);
      setHeatPoints(ht.points ?? []);
      setClusters(cl.clusters ?? []);
    } catch { /* empty */ } finally { setLoading(false); }
  }, [filters]);

  useEffect(() => { void load(); }, [load]);

  // Group events by country for spatial summary
  const countryGroups = features.reduce<Record<string, { count: number; avgImportance: number; events: MapFeature[] }>>((acc, f) => {
    const c = f.properties.country || "Unknown";
    if (!acc[c]) acc[c] = { count: 0, avgImportance: 0, events: [] };
    acc[c].count += 1;
    acc[c].avgImportance += Number(f.properties.importance) || 0;
    acc[c].events.push(f);
    return acc;
  }, {});
  for (const c of Object.values(countryGroups)) c.avgImportance = c.avgImportance / c.count;

  const sortedCountries = Object.entries(countryGroups).sort((a, b) => b[1].count - a[1].count);

  return (
    <PageShell title="Geo Intelligence">
      <FilterBar filters={MAP_FILTERS} values={filters} onChange={setFilters} searchType="map" />

      {/* View toggle tabs */}
      <div className="detail-tabs" style={{ marginBottom: "1rem" }}>
        {([["events", "Event Pins"], ["heat", "Heat Map"], ["clusters", "Clusters"]] as const).map(([key, label]) => (
          <button key={key} className={`detail-tab ${view === key ? "detail-tab--active" : ""}`} onClick={() => setView(key)}>
            {key === "events" && <MapPin size={14} />}
            {key === "heat" && <TrendingUp size={14} />}
            {key === "clusters" && <Layers size={14} />}
            {label}
          </button>
        ))}
      </div>

      {loading ? (
        <div className="loading-state"><div className="loading-spinner" /> Loading geo data…</div>
      ) : (
        <div className="split-layout">
          {/* ── Left: Spatial summary & list ────────── */}
          <div className="split-list" style={{ maxWidth: 900 }}>
            {/* Country summary cards */}
            {view === "events" && (
              <>
                <div className="geo-country-grid">
                  {sortedCountries.slice(0, 12).map(([country, data]) => (
                    <div
                      key={country}
                      className="geo-country-card"
                      onClick={() => setFilters((f) => ({ ...f, country }))}
                    >
                      <div className="geo-country-name"><Globe size={13} /> {country}</div>
                      <div className="geo-country-stats">
                        <span>{data.count} events</span>
                        <span className="geo-country-score">avg {data.avgImportance.toFixed(2)}</span>
                      </div>
                    </div>
                  ))}
                </div>

                {/* Event table */}
                <div className="data-table-wrap" style={{ marginTop: "1rem" }}>
                  <table className="data-table">
                    <thead>
                      <tr><th>Event</th><th>Type</th><th>Country</th><th>Score</th><th>Sources</th></tr>
                    </thead>
                    <tbody>
                      {features.length === 0 ? (
                        <tr><td colSpan={5} className="empty-state">No geo-located events</td></tr>
                      ) : features.map((f) => (
                        <tr key={f.properties.id} className={selected?.properties.id === f.properties.id ? "row-active" : ""} style={{ cursor: "pointer" }} onClick={() => setSelected(f)}>
                          <td style={{ fontWeight: 600, maxWidth: 420, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>{f.properties.title}</td>
                          <td><span className="badge badge-blue">{f.properties.event_type}</span></td>
                          <td>{f.properties.country || "—"}</td>
                          <td><ImportanceBadge value={f.properties.importance} /></td>
                          <td>{f.properties.sources}</td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              </>
            )}

            {view === "heat" && (
              <div className="data-table-wrap">
                <table className="data-table">
                  <thead><tr><th>Lat</th><th>Lon</th><th>Weight</th></tr></thead>
                  <tbody>
                    {heatPoints.length === 0 ? (
                      <tr><td colSpan={3} className="empty-state">No heat data</td></tr>
                    ) : heatPoints.map((p, i) => (
                      <tr key={i}>
                        <td>{p.lat.toFixed(3)}</td><td>{p.lon.toFixed(3)}</td><td>{p.weight.toFixed(2)}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            )}

            {view === "clusters" && (
              <div className="geo-country-grid">
                {clusters.length === 0 ? <div className="empty-state">No clusters</div> : clusters.map((c, i) => (
                  <div key={i} className="geo-country-card">
                    <div className="geo-country-name"><Layers size={13} /> Cluster #{i + 1}</div>
                    <div className="geo-country-stats">
                      <span>{c.event_count} events</span>
                      <span>{c.avg_lat.toFixed(2)}, {c.avg_lon.toFixed(2)}</span>
                    </div>
                    {c.location_country && <div style={{ fontSize: "0.78rem", color: "#64748b" }}>{c.location_country}</div>}
                  </div>
                ))}
              </div>
            )}
          </div>

          {/* ── Right: Selected event context ──────── */}
          {selected && (
            <div className="split-detail">
              <div className="detail-panel">
                <button className="close-btn" onClick={() => setSelected(null)}>✕</button>
                <h3>{selected.properties.title}</h3>
                <div style={{ display: "flex", gap: 6, flexWrap: "wrap", marginBottom: "0.75rem" }}>
                  <span className="badge badge-blue">{selected.properties.event_type}</span>
                  {selected.properties.country && <span className="badge badge-gray">{selected.properties.country}</span>}
                </div>
                <div className="case-stats-row">
                  <div className="case-stat"><MapPin size={14} /><span>{selected.geometry.coordinates[1]?.toFixed(4)}, {selected.geometry.coordinates[0]?.toFixed(4)}</span></div>
                </div>
                <div className="detail-score-row">
                  <div className="detail-score-item">
                    <span className="detail-score-label">Importance</span>
                    <ImportanceBadge value={selected.properties.importance} />
                  </div>
                  <div className="detail-score-item">
                    <span className="detail-score-label">Sources</span>
                    <span className="detail-score-num">{selected.properties.sources}</span>
                  </div>
                </div>
                <div className="detail-actions" style={{ marginTop: "1rem" }}>
                  <button className="action-btn" onClick={() => setExplainId(selected.properties.id)}>
                    <Brain size={14} /> Explain
                  </button>
                  <button className="action-btn" onClick={() => setAttachEvent({ id: selected.properties.id, title: selected.properties.title })}>
                    <FolderOpen size={14} /> Attach to Case
                  </button>
                  <a href={`/events?highlight=${selected.properties.id}`} className="action-btn action-btn-primary">View in Events</a>
                </div>
              </div>
            </div>
          )}
        </div>
      )}

      {explainId != null && (
        <ExplainabilityDrawer type="event" id={explainId} onClose={() => setExplainId(null)} />
      )}

      {attachEvent && (
        <AttachToCaseModal
          objectType="event"
          objectId={attachEvent.id}
          objectTitle={attachEvent.title}
          onClose={() => setAttachEvent(null)}
          onSuccess={load}
        />
      )}
    </PageShell>
  );
}

export default function MapPage() {
  return <Suspense><MapPageInner /></Suspense>;
}
