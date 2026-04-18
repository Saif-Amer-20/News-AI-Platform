"use client";

/**
 * Signal Explorer — full signal feed with filters, search, and bulk read.
 *
 * Filters: severity, signal type, unread/all, entity search.
 */

import { useEffect, useState, useCallback } from "react";
import Link from "next/link";
import { PageShell } from "@/components/shell";
import { api } from "@/lib/api";
import {
  ArrowLeft, Bell, BellOff, RefreshCw, Filter, CheckCheck, Search,
} from "lucide-react";

/* ── Types ─────────────────────────────────────────────────────────────── */

type Signal = {
  id: number;
  signal_type: string;
  severity: "low" | "medium" | "high";
  title: string;
  description: string;
  entity_id: number;
  entity_name: string;
  entity_type: string;
  related_entity_id: number | null;
  related_entity_name: string | null;
  metadata: Record<string, unknown>;
  is_read: boolean;
  created_at: string;
  expires_at: string | null;
};

/* ── Constants ─────────────────────────────────────────────────────────── */

const SEVERITY_COLORS: Record<string, string> = {
  high: "#ef4444", medium: "#f59e0b", low: "#10b981",
};

const SIGNAL_LABELS: Record<string, string> = {
  mention_spike:     "Mention Spike",
  new_relationship:  "New Relationship",
  unusual_pair:      "Unusual Pair",
  rapid_growth:      "Rapid Growth",
  relationship_decay:"Relationship Decay",
};

const SEVERITY_OPTIONS    = ["", "high", "medium", "low"];
const SIGNAL_TYPE_OPTIONS = ["", "mention_spike", "new_relationship", "unusual_pair", "rapid_growth"];

const selectStyle: React.CSSProperties = {
  padding: "0.35rem 0.65rem", borderRadius: 6,
  background: "#fff", color: "#334155",
  border: "1px solid #e2e8f0", fontSize: "0.83rem",
};

/* ── Component ─────────────────────────────────────────────────────────── */

export default function SignalExplorerPage() {
  // Filters
  const [severity, setSeverity]       = useState("");
  const [signalType, setSignalType]   = useState("");
  const [unreadOnly, setUnreadOnly]   = useState(false);
  const [searchTerm, setSearchTerm]   = useState("");

  // Data
  const [signals, setSignals]     = useState<Signal[]>([]);
  const [loading, setLoading]     = useState(true);

  const loadSignals = useCallback(async () => {
    setLoading(true);
    try {
      const qs = new URLSearchParams({ limit: "100" });
      if (severity)   qs.set("severity", severity);
      if (signalType) qs.set("signal_type", signalType);
      if (unreadOnly) qs.set("unread_only", "true");
      const data = await api<{ results: Signal[] }>(`/entity-intelligence/signals/?${qs}`);
      setSignals(data.results ?? []);
    } catch { /* ignore */ }
    finally { setLoading(false); }
  }, [severity, signalType, unreadOnly]);

  useEffect(() => { void loadSignals(); }, [loadSignals]);

  const markRead = async (id: number) => {
    await api(`/entity-intelligence/signals/${id}/read/`, { method: "POST" }).catch(() => null);
    setSignals((prev) => prev.map((s) => s.id === id ? { ...s, is_read: true } : s));
  };

  const markAllRead = async () => {
    const unread = signals.filter((s) => !s.is_read);
    await Promise.all(unread.map((s) => api(`/entity-intelligence/signals/${s.id}/read/`, { method: "POST" }).catch(() => null)));
    setSignals((prev) => prev.map((s) => ({ ...s, is_read: true })));
  };

  // Client-side search filter
  const filtered = searchTerm
    ? signals.filter((s) =>
        s.title.toLowerCase().includes(searchTerm.toLowerCase()) ||
        s.entity_name.toLowerCase().includes(searchTerm.toLowerCase()) ||
        (s.related_entity_name ?? "").toLowerCase().includes(searchTerm.toLowerCase()) ||
        (s.description ?? "").toLowerCase().includes(searchTerm.toLowerCase())
      )
    : signals;

  const unreadCount = signals.filter((s) => !s.is_read).length;

  // Stats
  const highCount   = filtered.filter((s) => s.severity === "high").length;
  const mediumCount = filtered.filter((s) => s.severity === "medium").length;
  const lowCount    = filtered.filter((s) => s.severity === "low").length;

  return (
    <PageShell title="Signal Explorer">
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
          Severity
          <select value={severity} onChange={(e) => setSeverity(e.target.value)} style={selectStyle}>
            {SEVERITY_OPTIONS.map((s) => <option key={s} value={s}>{s ? s.charAt(0).toUpperCase() + s.slice(1) : "All"}</option>)}
          </select>
        </label>

        <label style={{ fontSize: "0.8rem", color: "#64748b", display: "flex", alignItems: "center", gap: 4 }}>
          Type
          <select value={signalType} onChange={(e) => setSignalType(e.target.value)} style={selectStyle}>
            {SIGNAL_TYPE_OPTIONS.map((t) => <option key={t} value={t}>{t ? (SIGNAL_LABELS[t] ?? t) : "All"}</option>)}
          </select>
        </label>

        <label style={{ fontSize: "0.8rem", color: "#64748b", display: "flex", alignItems: "center", gap: 4, cursor: "pointer" }}>
          <input type="checkbox" checked={unreadOnly} onChange={(e) => setUnreadOnly(e.target.checked)} />
          Unread only
        </label>

        {/* Search */}
        <div style={{ display: "flex", alignItems: "center", gap: 4, marginLeft: "auto", background: "#f8fafc", borderRadius: 6, padding: "0.3rem 0.6rem", border: "1px solid #e2e8f0" }}>
          <Search size={14} color="#94a3b8" />
          <input
            type="text"
            placeholder="Search signals…"
            value={searchTerm}
            onChange={(e) => setSearchTerm(e.target.value)}
            style={{ background: "transparent", border: "none", color: "#334155", fontSize: "0.83rem", outline: "none", width: 160 }}
          />
        </div>

        <button onClick={() => void loadSignals()} style={{
          display: "flex", alignItems: "center", gap: 6,
          padding: "0.35rem 0.8rem", borderRadius: 6,
          background: "#f8fafc", color: "#64748b", fontSize: "0.82rem", cursor: "pointer",
          border: "1px solid #e2e8f0",
        }}>
          <RefreshCw size={13} /> Refresh
        </button>
      </div>

      {/* ── Stats + Actions ─────────────────────────────────────── */}
      <div style={{ display: "flex", gap: 12, marginBottom: "0.75rem", alignItems: "center", fontSize: "0.8rem" }}>
        <span style={{ color: "#64748b" }}>{filtered.length} signals</span>
        {unreadCount > 0 && (
          <span style={{ color: "#f59e0b" }}>{unreadCount} unread</span>
        )}
        <span style={{ display: "flex", gap: 6 }}>
          <span style={{ color: SEVERITY_COLORS.high }}>{highCount} high</span>
          <span style={{ color: SEVERITY_COLORS.medium }}>{mediumCount} med</span>
          <span style={{ color: SEVERITY_COLORS.low }}>{lowCount} low</span>
        </span>
        {unreadCount > 0 && (
          <button onClick={() => void markAllRead()} style={{
            marginLeft: "auto", display: "flex", alignItems: "center", gap: 4,
            padding: "0.3rem 0.7rem", borderRadius: 6,
            background: "#f8fafc", color: "#64748b", fontSize: "0.78rem", cursor: "pointer",
            border: "1px solid #e2e8f0",
          }}>
            <CheckCheck size={13} /> Mark all read
          </button>
        )}
      </div>

      {/* ── Signal List ───────────────────────────────────────────── */}
      {loading ? (
        <div className="loading-state"><div className="loading-spinner" /> Loading signals…</div>
      ) : filtered.length === 0 ? (
        <div className="empty-state">No signals match your filters.</div>
      ) : (
        <div style={{ display: "flex", flexDirection: "column", gap: 8 }}>
          {filtered.map((sig) => {
            const sc = SEVERITY_COLORS[sig.severity] ?? "#64748b";
            return (
              <div
                key={sig.id}
                style={{
                  background: sig.is_read ? "#fff" : "#f8fafc",
                  border: `1px solid ${sig.is_read ? "#e2e8f0" : sc + "44"}`,
                  borderLeft: `3px solid ${sc}`,
                  borderRadius: 8,
                  padding: "0.75rem 1rem",
                  opacity: sig.is_read ? 0.65 : 1,
                }}
              >
                <div style={{ display: "flex", justifyContent: "space-between", alignItems: "flex-start" }}>
                  <div style={{ flex: 1 }}>
                    {/* Header row */}
                    <div style={{ display: "flex", gap: 6, alignItems: "center", marginBottom: 4 }}>
                      <span style={{
                        display: "inline-block", padding: "1px 7px", borderRadius: 4,
                        fontSize: "0.7rem", fontWeight: 600, color: "#fff", background: sc,
                      }}>{sig.severity.toUpperCase()}</span>
                      <span style={{ fontSize: "0.72rem", color: "#64748b" }}>
                        {SIGNAL_LABELS[sig.signal_type] ?? sig.signal_type}
                      </span>
                      <span style={{ fontSize: "0.72rem", color: "#94a3b8" }}>
                        {new Date(sig.created_at).toLocaleString()}
                      </span>
                    </div>

                    {/* Title + description */}
                    <p style={{ fontSize: "0.88rem", fontWeight: 600, color: "#0f172a", margin: 0 }}>{sig.title}</p>
                    {sig.description && (
                      <p style={{ fontSize: "0.8rem", color: "#64748b", margin: "4px 0 0" }}>{sig.description}</p>
                    )}

                    {/* Entity links */}
                    <div style={{ display: "flex", gap: 8, marginTop: 6 }}>
                      <Link
                        href={`/entities/intelligence/${sig.entity_id}`}
                        style={{ fontSize: "0.75rem", color: "#6366f1", textDecoration: "none" }}
                      >
                        📌 {sig.entity_name}
                        <span style={{ color: "#94a3b8", marginLeft: 4 }}>{sig.entity_type}</span>
                      </Link>
                      {sig.related_entity_name && sig.related_entity_id && (
                        <Link
                          href={`/entities/intelligence/${sig.related_entity_id}`}
                          style={{ fontSize: "0.75rem", color: "#94a3b8", textDecoration: "none" }}
                        >
                          ↔ {sig.related_entity_name}
                        </Link>
                      )}
                    </div>

                    {/* Metadata peek */}
                    {sig.metadata && Object.keys(sig.metadata).length > 0 && (
                      <div style={{ marginTop: 6, display: "flex", gap: 6, flexWrap: "wrap" }}>
                        {Object.entries(sig.metadata).slice(0, 5).map(([k, v]) => (
                          <span key={k} style={{ fontSize: "0.68rem", color: "#94a3b8", background: "#f1f5f9", padding: "1px 5px", borderRadius: 3 }}>
                            {k}: {String(v)}
                          </span>
                        ))}
                      </div>
                    )}
                  </div>

                  {/* Mark read button */}
                  {!sig.is_read && (
                    <button
                      title="Mark as read"
                      onClick={() => void markRead(sig.id)}
                      style={{ background: "none", color: "#94a3b8", cursor: "pointer", padding: 4, borderRadius: 4, flexShrink: 0 }}
                    >
                      <BellOff size={14} />
                    </button>
                  )}
                </div>
              </div>
            );
          })}
        </div>
      )}
    </PageShell>
  );
}
