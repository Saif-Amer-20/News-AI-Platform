"use client";

/**
 * Graph Explorer — full-screen interactive graph with comprehensive filters.
 *
 * Filters: entity type, relationship type, min strength, time range, node limit.
 * Includes summary stats, legend, and click-to-navigate.
 */

import { useEffect, useState, useCallback } from "react";
import Link from "next/link";
import { PageShell } from "@/components/shell";
import { api } from "@/lib/api";
import { EntityGraph, type GraphNode, type GraphEdge } from "@/components/entity-graph";
import { ArrowLeft, Filter, RefreshCw, Network, Download } from "lucide-react";

/* ── Types ─────────────────────────────────────────────────────────────── */

type GraphData = { nodes: GraphNode[]; edges: GraphEdge[] };
type TypeStat = { relationship_type: string; count: number };

/* ── Constants ─────────────────────────────────────────────────────────── */

const ENTITY_TYPE_OPTIONS = ["", "PERSON", "LOCATION", "ORGANIZATION"];
const REL_TYPE_OPTIONS    = ["", "political", "military", "economic", "diplomatic", "conflict", "social", "unknown"];

const NODE_LIMIT_OPTIONS  = [30, 50, 80, 120, 160, 200];
const TIME_RANGE_OPTIONS  = [
  { value: "7",   label: "Last 7 days" },
  { value: "14",  label: "Last 14 days" },
  { value: "30",  label: "Last 30 days" },
  { value: "60",  label: "Last 60 days" },
  { value: "90",  label: "Last 90 days" },
  { value: "",    label: "All time" },
];

const selectStyle: React.CSSProperties = {
  padding: "0.35rem 0.65rem", borderRadius: 6,
  background: "#fff", color: "#334155",
  border: "1px solid #e2e8f0", fontSize: "0.83rem",
};

const inputStyle: React.CSSProperties = {
  width: 60, padding: "0.25rem 0.45rem", borderRadius: 4,
  background: "#fff", color: "#334155",
  border: "1px solid #e2e8f0", fontSize: "0.83rem",
};

/* ── Component ─────────────────────────────────────────────────────────── */

export default function GraphExplorerPage() {
  // Filters
  const [entityType, setEntityType]       = useState("");
  const [relType, setRelType]             = useState("");
  const [minStrength, setMinStrength]     = useState("0.10");
  const [sinceDays, setSinceDays]         = useState("30");
  const [nodeLimit, setNodeLimit]         = useState(80);

  // Data
  const [graphData, setGraphData]   = useState<GraphData>({ nodes: [], edges: [] });
  const [loading, setLoading]       = useState(false);
  const [loaded, setLoaded]         = useState(false);
  const [relTypeStats, setRelTypeStats] = useState<TypeStat[]>([]);

  // Load graph
  const loadGraph = useCallback(async () => {
    setLoading(true);
    try {
      const qs = new URLSearchParams({
        min_strength: minStrength,
        limit_nodes: String(nodeLimit),
      });
      if (entityType) qs.set("entity_type", entityType);
      if (relType)    qs.set("relationship_type", relType);
      if (sinceDays)  qs.set("since_days", sinceDays);

      const data = await api<GraphData>(`/entity-intelligence/graph/?${qs}`);
      setGraphData(data);
      setLoaded(true);
    } catch {
      setGraphData({ nodes: [], edges: [] });
    } finally { setLoading(false); }
  }, [entityType, relType, minStrength, sinceDays, nodeLimit]);

  // Load type stats on mount
  useEffect(() => {
    api<{ by_type: TypeStat[] }>("/entity-intelligence/relationship-types/").then((d) => {
      setRelTypeStats(d.by_type ?? []);
    }).catch(() => {});
  }, []);

  // Auto-load graph on mount
  useEffect(() => { void loadGraph(); }, []); // eslint-disable-line react-hooks/exhaustive-deps

  // Stats
  const uniqueTypes = new Set(graphData.edges.map((e) => e.type));
  const avgStrength = graphData.edges.length > 0
    ? (graphData.edges.reduce((s, e) => s + e.strength, 0) / graphData.edges.length).toFixed(3)
    : "—";

  return (
    <PageShell title="Graph Explorer">
      {/* Back link */}
      <Link href="/entities/intelligence" style={{ display: "inline-flex", alignItems: "center", gap: 6, marginBottom: "1rem", fontSize: "0.83rem", color: "#6366f1", textDecoration: "none" }}>
        <ArrowLeft size={14} /> Back to Dashboard
      </Link>

      {/* ── Filters ──────────────────────────────────────────────── */}
      <div style={{
        background: "#fff", border: "1px solid #e2e8f0", borderRadius: 12,
        padding: "0.8rem 1rem", marginBottom: "1rem",
        display: "flex", gap: 10, flexWrap: "wrap", alignItems: "center",
      }}>
        <label style={{ fontSize: "0.8rem", color: "#64748b", display: "flex", alignItems: "center", gap: 4 }}>
          Entity Type
          <select value={entityType} onChange={(e) => setEntityType(e.target.value)} style={selectStyle}>
            {ENTITY_TYPE_OPTIONS.map((t) => <option key={t} value={t}>{t || "All"}</option>)}
          </select>
        </label>

        <label style={{ fontSize: "0.8rem", color: "#64748b", display: "flex", alignItems: "center", gap: 4 }}>
          Relationship
          <select value={relType} onChange={(e) => setRelType(e.target.value)} style={selectStyle}>
            {REL_TYPE_OPTIONS.map((t) => <option key={t} value={t}>{t || "All"}</option>)}
          </select>
        </label>

        <label style={{ fontSize: "0.8rem", color: "#64748b", display: "flex", alignItems: "center", gap: 4 }}>
          Min Strength
          <input type="number" min="0" max="1" step="0.05" value={minStrength} onChange={(e) => setMinStrength(e.target.value)} style={inputStyle} />
        </label>

        <label style={{ fontSize: "0.8rem", color: "#64748b", display: "flex", alignItems: "center", gap: 4 }}>
          Time Range
          <select value={sinceDays} onChange={(e) => setSinceDays(e.target.value)} style={selectStyle}>
            {TIME_RANGE_OPTIONS.map((t) => <option key={t.value} value={t.value}>{t.label}</option>)}
          </select>
        </label>

        <label style={{ fontSize: "0.8rem", color: "#64748b", display: "flex", alignItems: "center", gap: 4 }}>
          Max Nodes
          <select value={nodeLimit} onChange={(e) => setNodeLimit(Number(e.target.value))} style={selectStyle}>
            {NODE_LIMIT_OPTIONS.map((n) => <option key={n} value={n}>{n}</option>)}
          </select>
        </label>

        <button onClick={() => void loadGraph()} style={{
          display: "flex", alignItems: "center", gap: 6,
          padding: "0.38rem 1rem", borderRadius: 6,
          background: "#6366f1", color: "#fff",
          fontSize: "0.83rem", cursor: "pointer", fontWeight: 600,
          marginLeft: "auto",
        }}>
          <Filter size={13} /> Apply Filters
        </button>
      </div>

      {/* ── Stats bar ──────────────────────────────────────────────── */}
      <div style={{
        display: "flex", gap: 16, marginBottom: "0.75rem",
        fontSize: "0.8rem", color: "#64748b", alignItems: "center",
      }}>
        <span style={{ display: "flex", alignItems: "center", gap: 4 }}>
          <Network size={13} /> {graphData.nodes.length} nodes
        </span>
        <span>{graphData.edges.length} edges</span>
        <span>Avg strength: {avgStrength}</span>
        <span>{uniqueTypes.size} relationship types</span>
        {loading && <span style={{ color: "#f59e0b" }}>Loading…</span>}
      </div>

      {/* ── Graph ──────────────────────────────────────────────────── */}
      <div style={{ background: "#fff", border: "1px solid #e2e8f0", borderRadius: 12, padding: "0.75rem" }}>
        {loading ? (
          <div className="loading-state" style={{ minHeight: 500 }}><div className="loading-spinner" /> Building graph…</div>
        ) : graphData.nodes.length === 0 ? (
          <div style={{ minHeight: 400, display: "flex", alignItems: "center", justifyContent: "center", color: "#94a3b8", fontSize: "0.85rem" }}>
            No data matches your filters. Try reducing the minimum strength or expanding the time range.
          </div>
        ) : (
          <EntityGraph
            nodes={graphData.nodes}
            edges={graphData.edges}
            height={650}
            onNodeClick={(nd) => { window.location.href = `/entities/intelligence/${nd.id}`; }}
          />
        )}
      </div>

      {/* ── Relationship type breakdown ────────────────────────────── */}
      {relTypeStats.length > 0 && (
        <div style={{ marginTop: "1rem", background: "#fff", border: "1px solid #e2e8f0", borderRadius: 12, padding: "0.8rem 1rem" }}>
          <h4 style={{ fontSize: "0.85rem", fontWeight: 600, color: "#0f172a", marginBottom: "0.5rem" }}>
            Relationship Type Distribution (all data)
          </h4>
          <div style={{ display: "flex", gap: 12, flexWrap: "wrap" }}>
            {relTypeStats.map((s) => (
              <div key={s.relationship_type} style={{
                background: "#f8fafc", borderRadius: 6, padding: "0.3rem 0.6rem",
                fontSize: "0.78rem", color: "#64748b",
              }}>
                <span style={{ fontWeight: 600, color: "#334155" }}>{s.relationship_type}</span>
                <span style={{ marginLeft: 6 }}>{s.count}</span>
              </div>
            ))}
          </div>
        </div>
      )}
    </PageShell>
  );
}
