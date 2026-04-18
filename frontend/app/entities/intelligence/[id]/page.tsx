"use client";

/**
 * Entity Detail Intelligence View
 *
 * Shows comprehensive intelligence for a single entity:
 *   - Profile card (name, type, aliases, country)
 *   - Influence metrics
 *   - Mention timeline (30d sparkline)
 *   - Connected entities table
 *   - Ego-graph (entity + direct neighbors)
 *   - Signals feed for this entity
 */

import { useEffect, useState, useCallback } from "react";
import { useParams } from "next/navigation";
import Link from "next/link";
import { PageShell } from "@/components/shell";
import { api } from "@/lib/api";
import { EntityGraph, type GraphNode, type GraphEdge } from "@/components/entity-graph";
import {
  ArrowLeft, TrendingUp, Network, Bell, Zap, Shield,
  Users, Globe, RefreshCw, ExternalLink, BarChart3,
} from "lucide-react";

/* ── Types ─────────────────────────────────────────────────────────────── */

type Profile = {
  id: number;
  name: string;
  canonical_name: string;
  entity_type: string;
  country: string | null;
  aliases: string[];
  merge_confidence: number | null;
};

type Influence = {
  score: number;
  rank: number;
  degree_centrality: number;
  weighted_degree: number;
  velocity_score: number;
  mentions_24h: number;
  mentions_7d: number;
  mentions_30d: number;
  growth_flag: boolean;
};

type Relationship = {
  entity_id: number;
  entity_name: string;
  entity_type: string;
  strength: number;
  confidence: number;
  type: string;
  co_occurrences: number;
  last_seen_at: string | null;
};

type Signal = {
  id: number;
  signal_type: string;
  severity: string;
  title: string;
  description: string;
  entity_name: string;
  related_entity_name: string | null;
  is_read: boolean;
  created_at: string;
};

type TimelinePoint = { date: string; count: number };

type EntityDetailData = {
  profile: Profile;
  influence: Influence | null;
  relationships: Relationship[];
  signals: Signal[];
  mention_timeline: TimelinePoint[];
  total_articles: number;
};

type GraphData = { nodes: GraphNode[]; edges: GraphEdge[] };

/* ── Constants ─────────────────────────────────────────────────────────── */

const SEVERITY_COLORS: Record<string, string> = {
  high: "#ef4444", medium: "#f59e0b", low: "#10b981",
};

const TYPE_COLORS: Record<string, string> = {
  political: "#3b82f6", military: "#ef4444", economic: "#10b981",
  diplomatic: "#8b5cf6", conflict: "#f97316", social: "#06b6d4", unknown: "#64748b",
};

const SIGNAL_LABELS: Record<string, string> = {
  mention_spike: "Mention Spike", new_relationship: "New Relationship",
  unusual_pair: "Unusual Pair", rapid_growth: "Rapid Growth",
};

const ENTITY_ICONS: Record<string, typeof Users> = {
  PERSON: Users, LOCATION: Globe, ORGANIZATION: Shield,
};

/* ── Sparkline component ──────────────────────────────────────────────── */

function Sparkline({ data, width = 280, height = 50 }: { data: TimelinePoint[]; width?: number; height?: number }) {
  if (data.length < 2) return null;
  const maxV = Math.max(...data.map((d) => d.count), 1);
  const points = data.map((d, i) => {
    const x = (i / (data.length - 1)) * width;
    const y = height - (d.count / maxV) * (height - 6);
    return `${x},${y}`;
  }).join(" ");
  const fillPoints = `0,${height} ${points} ${width},${height}`;
  return (
    <svg width={width} height={height} style={{ display: "block" }}>
      <polygon points={fillPoints} fill="#6366f120" />
      <polyline points={points} fill="none" stroke="#6366f1" strokeWidth={2} strokeLinejoin="round" />
    </svg>
  );
}

/* ── Component ─────────────────────────────────────────────────────────── */

export default function EntityDetailPage() {
  const params = useParams();
  const entityId = Number(params.id);

  const [data, setData] = useState<EntityDetailData | null>(null);
  const [graph, setGraph] = useState<GraphData | null>(null);
  const [loading, setLoading] = useState(true);
  const [graphLoading, setGraphLoading] = useState(false);
  const [showGraph, setShowGraph] = useState(false);

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const d = await api<EntityDetailData>(`/entity-intelligence/entities/${entityId}/`);
      setData(d);
    } catch { /* ignore */ }
    finally { setLoading(false); }
  }, [entityId]);

  const loadGraph = useCallback(async () => {
    setGraphLoading(true);
    try {
      // Build an ego-graph: the entity + direct neighbors
      const d = await api<GraphData>(`/entity-intelligence/graph/?min_strength=0.10&limit_nodes=40&since_days=30`);
      // Filter to only include this entity's direct connections
      const selfEdges = d.edges.filter((e) => e.source === entityId || e.target === entityId);
      const neighborIds = new Set<number>();
      neighborIds.add(entityId);
      selfEdges.forEach((e) => { neighborIds.add(e.source); neighborIds.add(e.target); });
      const egoNodes = d.nodes.filter((n) => neighborIds.has(n.id)).map((n) => ({
        ...n, is_root: n.id === entityId,
      }));
      const egoEdges = d.edges.filter((e) => neighborIds.has(e.source) && neighborIds.has(e.target));
      setGraph({ nodes: egoNodes, edges: egoEdges });
    } catch { setGraph({ nodes: [], edges: [] }); }
    finally { setGraphLoading(false); }
  }, [entityId]);

  useEffect(() => { void load(); }, [load]);

  if (loading || !data) {
    return (
      <PageShell title="Entity Detail">
        <div className="loading-state"><div className="loading-spinner" /> Loading entity…</div>
      </PageShell>
    );
  }

  const { profile, influence, relationships, signals, mention_timeline, total_articles } = data;
  const Icon = ENTITY_ICONS[profile.entity_type] ?? Users;

  return (
    <PageShell title={profile.canonical_name}>
      {/* Back link */}
      <Link href="/entities/intelligence" style={{ display: "inline-flex", alignItems: "center", gap: 6, marginBottom: "1rem", fontSize: "0.83rem", color: "#6366f1", textDecoration: "none" }}>
        <ArrowLeft size={14} /> Back to Dashboard
      </Link>

      {/* ── Profile + Influence row ────────────────────────────────── */}
      <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 16, marginBottom: "1.5rem" }}>

        {/* Profile Card */}
        <div style={{ background: "#fff", border: "1px solid #e2e8f0", borderRadius: 12, padding: "1.2rem" }}>
          <div style={{ display: "flex", alignItems: "center", gap: 10, marginBottom: "0.75rem" }}>
            <div style={{ width: 42, height: 42, borderRadius: 10, background: "#6366f118", display: "flex", alignItems: "center", justifyContent: "center" }}>
              <Icon size={22} color="#6366f1" />
            </div>
            <div>
              <h2 style={{ fontSize: "1.15rem", fontWeight: 700, color: "#0f172a", margin: 0 }}>{profile.canonical_name}</h2>
              <div style={{ display: "flex", gap: 6, marginTop: 2 }}>
                <span className="badge badge-purple" style={{ fontSize: "0.7rem" }}>{profile.entity_type}</span>
                {profile.country && <span style={{ fontSize: "0.75rem", color: "#64748b" }}>🌍 {profile.country}</span>}
                {influence?.growth_flag && <span style={{ fontSize: "0.72rem", color: "#f59e0b", display: "flex", alignItems: "center", gap: 2 }}><Zap size={11} /> Growing</span>}
              </div>
            </div>
          </div>

          {/* Aliases */}
          {profile.aliases.length > 0 && (
            <div style={{ marginBottom: "0.5rem" }}>
              <span style={{ fontSize: "0.75rem", color: "#64748b" }}>Also known as: </span>
              {profile.aliases.map((a, i) => (
                <span key={i} style={{ fontSize: "0.78rem", color: "#64748b", background: "#f1f5f9", padding: "2px 6px", borderRadius: 4, marginRight: 4 }}>{a}</span>
              ))}
            </div>
          )}

          {/* Stats row */}
          <div style={{ display: "flex", gap: 16, marginTop: "0.75rem" }}>
            <div>
              <div style={{ fontSize: "1rem", fontWeight: 700, color: "#0f172a" }}>{total_articles}</div>
              <div style={{ fontSize: "0.72rem", color: "#94a3b8" }}>Articles</div>
            </div>
            <div>
              <div style={{ fontSize: "1rem", fontWeight: 700, color: "#0f172a" }}>{relationships.length}</div>
              <div style={{ fontSize: "0.72rem", color: "#94a3b8" }}>Connections</div>
            </div>
            <div>
              <div style={{ fontSize: "1rem", fontWeight: 700, color: "#0f172a" }}>{signals.length}</div>
              <div style={{ fontSize: "0.72rem", color: "#94a3b8" }}>Signals</div>
            </div>
          </div>
        </div>

        {/* Influence Card */}
        <div style={{ background: "#fff", border: "1px solid #e2e8f0", borderRadius: 12, padding: "1.2rem" }}>
          <h3 style={{ fontSize: "0.9rem", fontWeight: 600, color: "#0f172a", marginBottom: "0.75rem", display: "flex", alignItems: "center", gap: 6 }}>
            <TrendingUp size={15} color="#6366f1" /> Influence Score
          </h3>
          {influence ? (
            <>
              <div style={{ display: "flex", alignItems: "baseline", gap: 8, marginBottom: "0.75rem" }}>
                <span style={{ fontSize: "2rem", fontWeight: 800, color: "#6366f1" }}>{Math.round(influence.score * 100)}%</span>
                <span style={{ fontSize: "0.85rem", color: "#64748b" }}>Rank #{influence.rank}</span>
              </div>
              <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 8 }}>
                {[
                  { label: "Degree", value: influence.degree_centrality.toFixed(3) },
                  { label: "Velocity", value: influence.velocity_score.toFixed(3) },
                  { label: "Mentions 24h", value: influence.mentions_24h.toString() },
                  { label: "Mentions 7d", value: influence.mentions_7d.toString() },
                  { label: "Mentions 30d", value: influence.mentions_30d.toString() },
                  { label: "Weighted Deg", value: influence.weighted_degree.toFixed(2) },
                ].map(({ label, value }) => (
                  <div key={label} style={{ background: "#f8fafc", borderRadius: 6, padding: "0.35rem 0.6rem" }}>
                    <div style={{ fontSize: "0.88rem", fontWeight: 600, color: "#0f172a" }}>{value}</div>
                    <div style={{ fontSize: "0.68rem", color: "#94a3b8" }}>{label}</div>
                  </div>
                ))}
              </div>
            </>
          ) : (
            <p style={{ fontSize: "0.82rem", color: "#94a3b8" }}>No influence data available yet.</p>
          )}
        </div>
      </div>

      {/* ── Mention Timeline ──────────────────────────────────────── */}
      {mention_timeline.length > 0 && (
        <div style={{ background: "#fff", border: "1px solid #e2e8f0", borderRadius: 12, padding: "1rem 1.2rem", marginBottom: "1.5rem" }}>
          <h3 style={{ fontSize: "0.9rem", fontWeight: 600, color: "#0f172a", marginBottom: "0.5rem", display: "flex", alignItems: "center", gap: 6 }}>
            <BarChart3 size={15} color="#3b82f6" /> Mention Timeline (30 days)
          </h3>
          <Sparkline data={mention_timeline} width={700} height={60} />
          <div style={{ display: "flex", justifyContent: "space-between", fontSize: "0.68rem", color: "#94a3b8", marginTop: 4 }}>
            <span>{mention_timeline[0]?.date}</span>
            <span>{mention_timeline[mention_timeline.length - 1]?.date}</span>
          </div>
        </div>
      )}

      {/* ── Two-column: Connections + Ego-Graph ────────────────────── */}
      <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 16, marginBottom: "1.5rem" }}>

        {/* Connected Entities */}
        <div style={{ background: "#fff", border: "1px solid #e2e8f0", borderRadius: 12, padding: "1rem 1.2rem" }}>
          <h3 style={{ fontSize: "0.9rem", fontWeight: 600, color: "#0f172a", marginBottom: "0.75rem", display: "flex", alignItems: "center", gap: 6 }}>
            <Network size={15} color="#10b981" /> Connected Entities ({relationships.length})
          </h3>
          {relationships.length === 0 ? (
            <p style={{ fontSize: "0.82rem", color: "#94a3b8" }}>No connections found.</p>
          ) : (
            <div style={{ maxHeight: 380, overflowY: "auto", display: "flex", flexDirection: "column", gap: 4 }}>
              {relationships.map((rel, i) => {
                const pct = Math.round(rel.strength * 100);
                const tc  = TYPE_COLORS[rel.type] ?? "#64748b";
                return (
                  <Link key={i} href={`/entities/intelligence/${rel.entity_id}`} style={{
                    textDecoration: "none", display: "flex", alignItems: "center", gap: 6,
                    padding: "0.35rem 0.5rem", borderRadius: 6, background: "#f8fafc",
                  }}>
                    <span style={{ flex: 1, fontSize: "0.82rem", fontWeight: 500, color: "#334155" }}>{rel.entity_name}</span>
                    <span style={{ fontSize: "0.68rem", color: tc, padding: "1px 5px", background: tc + "18", borderRadius: 4 }}>{rel.type}</span>
                    <div style={{ width: 40, height: 4, background: "#e2e8f0", borderRadius: 2 }}>
                      <div style={{ width: `${pct}%`, height: 4, background: "#6366f1", borderRadius: 2 }} />
                    </div>
                    <span style={{ width: 30, fontSize: "0.72rem", color: "#64748b", textAlign: "right" }}>{pct}%</span>
                    <span style={{ width: 18, fontSize: "0.68rem", color: "#94a3b8", textAlign: "right" }}>{rel.co_occurrences}</span>
                  </Link>
                );
              })}
            </div>
          )}
        </div>

        {/* Ego-Graph */}
        <div style={{ background: "#fff", border: "1px solid #e2e8f0", borderRadius: 12, padding: "1rem 1.2rem" }}>
          <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: "0.5rem" }}>
            <h3 style={{ fontSize: "0.9rem", fontWeight: 600, color: "#0f172a", display: "flex", alignItems: "center", gap: 6, margin: 0 }}>
              <Network size={15} color="#6366f1" /> Network Graph
            </h3>
            {!showGraph && (
              <button onClick={() => { setShowGraph(true); void loadGraph(); }} style={{
                padding: "0.3rem 0.7rem", borderRadius: 6, background: "#6366f1", color: "#fff",
                fontSize: "0.78rem", cursor: "pointer", fontWeight: 600,
              }}>
                Load Graph
              </button>
            )}
          </div>
          {showGraph ? (
            graphLoading ? (
              <div className="loading-state"><div className="loading-spinner" /> Building graph…</div>
            ) : graph ? (
              <EntityGraph
                nodes={graph.nodes}
                edges={graph.edges}
                width={440}
                height={340}
                onNodeClick={(nd) => { window.location.href = `/entities/intelligence/${nd.id}`; }}
              />
            ) : null
          ) : (
            <div style={{ height: 200, display: "flex", alignItems: "center", justifyContent: "center", color: "#94a3b8", fontSize: "0.82rem" }}>
              Click "Load Graph" to render the ego-graph
            </div>
          )}
        </div>
      </div>

      {/* ── Signals for this entity ──────────────────────────────── */}
      <div style={{ background: "#fff", border: "1px solid #e2e8f0", borderRadius: 12, padding: "1rem 1.2rem" }}>
        <h3 style={{ fontSize: "0.9rem", fontWeight: 600, color: "#0f172a", marginBottom: "0.75rem", display: "flex", alignItems: "center", gap: 6 }}>
          <Bell size={15} color="#f59e0b" /> Signals ({signals.length})
        </h3>
        {signals.length === 0 ? (
          <p style={{ fontSize: "0.82rem", color: "#94a3b8" }}>No signals for this entity.</p>
        ) : (
          <div style={{ display: "flex", flexDirection: "column", gap: 6 }}>
            {signals.map((sig) => {
              const sc = SEVERITY_COLORS[sig.severity] ?? "#64748b";
              return (
                <div key={sig.id} style={{
                  borderLeft: `3px solid ${sc}`,
                  background: "#f8fafc", borderRadius: 6,
                  padding: "0.5rem 0.8rem", opacity: sig.is_read ? 0.6 : 1,
                }}>
                  <div style={{ display: "flex", gap: 6, alignItems: "center", marginBottom: 3 }}>
                    <span style={{ fontSize: "0.68rem", fontWeight: 600, color: "#fff", background: sc, padding: "1px 6px", borderRadius: 4 }}>
                      {sig.severity.toUpperCase()}
                    </span>
                    <span style={{ fontSize: "0.72rem", color: "#64748b" }}>{SIGNAL_LABELS[sig.signal_type] ?? sig.signal_type}</span>
                    <span style={{ fontSize: "0.68rem", color: "#94a3b8", marginLeft: "auto" }}>
                      {new Date(sig.created_at).toLocaleString()}
                    </span>
                  </div>
                  <p style={{ fontSize: "0.82rem", fontWeight: 600, color: "#334155", margin: 0 }}>{sig.title}</p>
                  {sig.description && <p style={{ fontSize: "0.76rem", color: "#64748b", margin: "2px 0 0" }}>{sig.description}</p>}
                  {sig.related_entity_name && (
                    <span style={{ fontSize: "0.72rem", color: "#6366f1" }}>↔ {sig.related_entity_name}</span>
                  )}
                </div>
              );
            })}
          </div>
        )}
      </div>
    </PageShell>
  );
}
