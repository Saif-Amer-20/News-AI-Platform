"use client";

/**
 * Entity Intelligence Dashboard
 *
 * Landing page for the intelligence hub.  Shows:
 *   - KPI cards (entities, relationships, signals, avg strength)
 *   - Top influential entities
 *   - Strongest relationships
 *   - Emerging entities
 *   - Latest signals
 *   - Relationship type distribution
 */

import { useEffect, useState, useCallback } from "react";
import Link from "next/link";
import { PageShell } from "@/components/shell";
import { api } from "@/lib/api";
import {
  TrendingUp, Network, Bell, Zap, ArrowRight, Users,
  RefreshCw, Activity, Shield, Globe,
} from "lucide-react";

/* ── Types ─────────────────────────────────────────────────────────────── */

type KPIs = {
  entities: number;
  relationships: number;
  signals: number;
  avg_strength: number;
  max_strength: number;
  scored_entities: number;
};

type InfluenceRow = {
  id: number;
  name: string;
  type: string;
  score: number;
  rank: number;
  mentions_7d: number;
  growth_flag: boolean;
  degree: number;
};

type RelRow = {
  entity_a_id: number;
  entity_a_name: string;
  entity_b_id: number;
  entity_b_name: string;
  strength: number;
  type: string;
  co_occurrences: number;
  confidence: number;
};

type EmergingRow = {
  id: number;
  name: string;
  type: string;
  mentions_24h: number;
  mentions_7d: number;
  velocity: number;
  growth_flag: boolean;
};

type SignalRow = {
  id: number;
  signal_type: string;
  severity: string;
  title: string;
  description: string;
  entity_id: number;
  entity_name: string;
  is_read: boolean;
  created_at: string;
};

type TypeDist = { relationship_type: string; count: number; avg_str: number };

type DashboardData = {
  kpis: KPIs;
  top_influence: InfluenceRow[];
  top_relationships: RelRow[];
  emerging: EmergingRow[];
  recent_signals: SignalRow[];
  type_distribution: TypeDist[];
};

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

/* ── Component ─────────────────────────────────────────────────────────── */

export default function IntelligenceDashboard() {
  const [data, setData] = useState<DashboardData | null>(null);
  const [loading, setLoading] = useState(true);

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const d = await api<DashboardData>("/entity-intelligence/dashboard/");
      setData(d);
    } catch { /* ignore */ }
    finally { setLoading(false); }
  }, []);

  useEffect(() => { void load(); }, [load]);

  if (loading || !data) {
    return (
      <PageShell title="Entity Intelligence">
        <div className="loading-state"><div className="loading-spinner" /> Loading dashboard…</div>
      </PageShell>
    );
  }

  const { kpis, top_influence, top_relationships, emerging, recent_signals, type_distribution } = data;

  return (
    <PageShell title="Entity Intelligence">
      {/* ── Quick nav ──────────────────────────────────────────────── */}
      <div style={{ display: "flex", gap: 8, marginBottom: "1.5rem", flexWrap: "wrap" }}>
        {[
          { href: "/entities/intelligence/graph",   label: "Graph Explorer",  icon: Network },
          { href: "/entities/intelligence/signals", label: "Signal Explorer", icon: Bell },
        ].map(({ href, label, icon: Icon }) => (
          <Link key={href} href={href} style={{
            display: "flex", alignItems: "center", gap: 6,
            padding: "0.4rem 0.9rem", borderRadius: 8,
            background: "#f8fafc", color: "#64748b", fontSize: "0.83rem",
            textDecoration: "none", border: "1px solid #e2e8f0",
          }}>
            <Icon size={14} /> {label} <ArrowRight size={12} />
          </Link>
        ))}
        <button onClick={() => void load()} style={{
          marginLeft: "auto", display: "flex", alignItems: "center", gap: 6,
          padding: "0.4rem 0.9rem", borderRadius: 8,
          background: "#f8fafc", color: "#64748b", fontSize: "0.83rem",
          cursor: "pointer", border: "1px solid #e2e8f0",
        }}>
          <RefreshCw size={13} /> Refresh
        </button>
      </div>

      {/* ── KPI Cards ──────────────────────────────────────────────── */}
      <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(180px, 1fr))", gap: 12, marginBottom: "1.5rem" }}>
        {[
          { label: "Scored Entities", value: kpis.scored_entities.toLocaleString(), icon: Users, color: "#6366f1" },
          { label: "Relationships",   value: kpis.relationships.toLocaleString(),   icon: Network, color: "#10b981" },
          { label: "Active Signals",  value: kpis.signals.toLocaleString(),         icon: Bell, color: "#f59e0b" },
          { label: "Avg Strength",    value: (kpis.avg_strength * 100).toFixed(1) + "%", icon: Activity, color: "#3b82f6" },
          { label: "Max Strength",    value: (kpis.max_strength * 100).toFixed(1) + "%", icon: Zap, color: "#8b5cf6" },
        ].map(({ label, value, icon: Icon, color }) => (
          <div key={label} style={{
            background: "#fff", border: "1px solid #e2e8f0", borderRadius: 12,
            padding: "1rem 1.1rem", display: "flex", alignItems: "center", gap: 12,
          }}>
            <div style={{ width: 36, height: 36, borderRadius: 8, background: color + "18", display: "flex", alignItems: "center", justifyContent: "center" }}>
              <Icon size={18} color={color} />
            </div>
            <div>
              <div style={{ fontSize: "1.2rem", fontWeight: 700, color: "#0f172a" }}>{value}</div>
              <div style={{ fontSize: "0.75rem", color: "#64748b" }}>{label}</div>
            </div>
          </div>
        ))}
      </div>

      {/* ── Two-column layout ──────────────────────────────────────── */}
      <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 16, marginBottom: "1.5rem" }}>

        {/* Left: Top Influential Entities */}
        <div style={{ background: "#fff", border: "1px solid #e2e8f0", borderRadius: 12, padding: "1rem 1.2rem" }}>
          <h3 style={{ fontSize: "0.9rem", fontWeight: 600, color: "#0f172a", marginBottom: "0.75rem", display: "flex", alignItems: "center", gap: 6 }}>
            <TrendingUp size={15} color="#6366f1" /> Top Influential Entities
          </h3>
          <div style={{ display: "flex", flexDirection: "column", gap: 6 }}>
            {top_influence.map((row) => {
              const pct = Math.round(row.score * 100);
              return (
                <Link key={row.id} href={`/entities/intelligence/${row.id}`} style={{ textDecoration: "none", display: "flex", alignItems: "center", gap: 8, padding: "0.35rem 0.5rem", borderRadius: 6, background: "#f8fafc" }}>
                  <span style={{ width: 22, fontSize: "0.75rem", color: "#94a3b8", textAlign: "center" }}>#{row.rank}</span>
                  <span style={{ flex: 1, fontSize: "0.84rem", fontWeight: 600, color: "#334155" }}>{row.name}</span>
                  <span className="badge badge-purple" style={{ fontSize: "0.68rem" }}>{row.type}</span>
                  {row.growth_flag && <Zap size={12} color="#f59e0b" />}
                  <div style={{ width: 50, height: 5, background: "#e2e8f0", borderRadius: 3 }}>
                    <div style={{ width: `${pct}%`, height: 5, background: "#6366f1", borderRadius: 3 }} />
                  </div>
                  <span style={{ width: 32, fontSize: "0.73rem", color: "#64748b", textAlign: "right" }}>{pct}%</span>
                </Link>
              );
            })}
          </div>
        </div>

        {/* Right: Strongest Relationships */}
        <div style={{ background: "#fff", border: "1px solid #e2e8f0", borderRadius: 12, padding: "1rem 1.2rem" }}>
          <h3 style={{ fontSize: "0.9rem", fontWeight: 600, color: "#0f172a", marginBottom: "0.75rem", display: "flex", alignItems: "center", gap: 6 }}>
            <Network size={15} color="#10b981" /> Strongest Relationships
          </h3>
          <div style={{ display: "flex", flexDirection: "column", gap: 6 }}>
            {top_relationships.map((rel, i) => {
              const pct = Math.round(rel.strength * 100);
              const tc  = TYPE_COLORS[rel.type] ?? "#64748b";
              return (
                <div key={i} style={{ display: "flex", alignItems: "center", gap: 6, padding: "0.35rem 0.5rem", borderRadius: 6, background: "#f8fafc" }}>
                  <Link href={`/entities/intelligence/${rel.entity_a_id}`} style={{ fontSize: "0.82rem", color: "#6366f1", textDecoration: "none", fontWeight: 500 }}>{rel.entity_a_name}</Link>
                  <span style={{ fontSize: "0.72rem", color: tc, padding: "1px 5px", background: tc + "18", borderRadius: 4 }}>{rel.type}</span>
                  <Link href={`/entities/intelligence/${rel.entity_b_id}`} style={{ fontSize: "0.82rem", color: "#6366f1", textDecoration: "none", fontWeight: 500 }}>{rel.entity_b_name}</Link>
                  <span style={{ marginLeft: "auto", fontSize: "0.73rem", color: "#64748b" }}>{pct}%</span>
                  <span style={{ fontSize: "0.68rem", color: "#94a3b8" }}>{rel.co_occurrences} co-occ</span>
                </div>
              );
            })}
          </div>
        </div>
      </div>

      {/* ── Second row: Emerging + Signals + Type dist ─────────────── */}
      <div style={{ display: "grid", gridTemplateColumns: "1fr 1.5fr", gap: 16 }}>

        {/* Left: Emerging + Type Distribution */}
        <div style={{ display: "flex", flexDirection: "column", gap: 16 }}>
          {/* Emerging Entities */}
          <div style={{ background: "#fff", border: "1px solid #e2e8f0", borderRadius: 12, padding: "1rem 1.2rem" }}>
            <h3 style={{ fontSize: "0.9rem", fontWeight: 600, color: "#0f172a", marginBottom: "0.75rem", display: "flex", alignItems: "center", gap: 6 }}>
              <Zap size={15} color="#f59e0b" /> Emerging Entities
            </h3>
            {emerging.length === 0 ? (
              <p style={{ fontSize: "0.82rem", color: "#94a3b8" }}>No emerging entities detected.</p>
            ) : (
              <div style={{ display: "flex", flexDirection: "column", gap: 6 }}>
                {emerging.map((e: EmergingRow) => (
                  <Link key={e.id} href={`/entities/intelligence/${e.id}`} style={{ textDecoration: "none", display: "flex", alignItems: "center", gap: 8, padding: "0.35rem 0.5rem", borderRadius: 6, background: "#f8fafc" }}>
                    <span style={{ flex: 1, fontSize: "0.84rem", fontWeight: 600, color: "#334155" }}>{e.name}</span>
                    <span className="badge badge-purple" style={{ fontSize: "0.68rem" }}>{e.type}</span>
                    <span style={{ fontSize: "0.73rem", color: "#f59e0b" }}>+{e.mentions_24h} 24h</span>
                    <span style={{ fontSize: "0.73rem", color: "#64748b" }}>{e.mentions_7d} 7d</span>
                  </Link>
                ))}
              </div>
            )}
          </div>

          {/* Type Distribution */}
          <div style={{ background: "#fff", border: "1px solid #e2e8f0", borderRadius: 12, padding: "1rem 1.2rem" }}>
            <h3 style={{ fontSize: "0.9rem", fontWeight: 600, color: "#0f172a", marginBottom: "0.75rem" }}>
              Relationship Types
            </h3>
            <div style={{ display: "flex", flexDirection: "column", gap: 4 }}>
              {type_distribution.map((td) => {
                const total = type_distribution.reduce((s, t) => s + t.count, 0);
                const pct   = total > 0 ? Math.round((td.count / total) * 100) : 0;
                const tc    = TYPE_COLORS[td.relationship_type] ?? "#64748b";
                return (
                  <div key={td.relationship_type} style={{ display: "flex", alignItems: "center", gap: 8 }}>
                    <span style={{ width: 70, fontSize: "0.78rem", color: tc, fontWeight: 500 }}>{td.relationship_type}</span>
                    <div style={{ flex: 1, height: 6, background: "#e2e8f0", borderRadius: 3 }}>
                      <div style={{ width: `${pct}%`, height: 6, background: tc, borderRadius: 3, transition: "width 0.3s" }} />
                    </div>
                    <span style={{ width: 48, fontSize: "0.73rem", color: "#64748b", textAlign: "right" }}>{td.count}</span>
                  </div>
                );
              })}
            </div>
          </div>
        </div>

        {/* Right: Latest Signals */}
        <div style={{ background: "#fff", border: "1px solid #e2e8f0", borderRadius: 12, padding: "1rem 1.2rem" }}>
          <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: "0.75rem" }}>
            <h3 style={{ fontSize: "0.9rem", fontWeight: 600, color: "#0f172a", display: "flex", alignItems: "center", gap: 6, margin: 0 }}>
              <Bell size={15} color="#f59e0b" /> Latest Signals
            </h3>
            <Link href="/entities/intelligence/signals" style={{ fontSize: "0.78rem", color: "#6366f1", textDecoration: "none", display: "flex", alignItems: "center", gap: 4 }}>
              View all <ArrowRight size={12} />
            </Link>
          </div>
          {recent_signals.length === 0 ? (
            <p style={{ fontSize: "0.82rem", color: "#94a3b8" }}>No signals yet.</p>
          ) : (
            <div style={{ display: "flex", flexDirection: "column", gap: 6 }}>
              {recent_signals.map((sig) => {
                const sc = SEVERITY_COLORS[sig.severity] ?? "#64748b";
                return (
                  <div key={sig.id} style={{
                    borderLeft: `3px solid ${sc}`,
                    background: "#f8fafc", borderRadius: 6,
                    padding: "0.55rem 0.8rem",
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
                    <Link href={`/entities/intelligence/${sig.entity_id}`} style={{ fontSize: "0.73rem", color: "#6366f1", textDecoration: "none" }}>
                      → {sig.entity_name}
                    </Link>
                  </div>
                );
              })}
            </div>
          )}
        </div>
      </div>
    </PageShell>
  );
}
