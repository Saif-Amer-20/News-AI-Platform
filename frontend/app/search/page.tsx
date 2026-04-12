"use client";

import { useState, useCallback } from "react";
import Link from "next/link";
import { PageShell } from "@/components/shell";
import { api } from "@/lib/api";

type SearchResult = {
  id: number;
  article_id?: number;
  title: string;
  snippet: string;
  score: number;
  source_type: string;
  source_name?: string;
  published_at?: string;
  content?: string;
};

export default function SearchPage() {
  const [query, setQuery] = useState("");
  const [tab, setTab] = useState<"articles" | "events">("articles");
  const [results, setResults] = useState<SearchResult[]>([]);
  const [loading, setLoading] = useState(false);
  const [searched, setSearched] = useState(false);

  const doSearch = useCallback(async () => {
    if (!query.trim()) return;
    setLoading(true);
    setSearched(true);
    try {
      const data = await api<{ results: Record<string, unknown>[] }>(
        `/search/${tab}/?q=${encodeURIComponent(query.trim())}`
      );
      setResults((data.results ?? []).map((r) => ({
        id: (r.article_id ?? r.event_id ?? r.id) as number,
        title: r.title as string,
        snippet: (r.content ?? r.description ?? "") as string,
        score: (r.importance_score ?? r.confidence_score ?? 0) as number,
        source_type: (r.source_type ?? r.event_type ?? "") as string,
        source_name: r.source_name as string | undefined,
        published_at: (r.published_at ?? r.first_reported_at) as string | undefined,
      })));
    } catch {
      setResults([]);
    } finally {
      setLoading(false);
    }
  }, [query, tab]);

  return (
    <PageShell title="Search">
      <div style={{ display: "flex", gap: "0.5rem", marginBottom: "1rem" }}>
        <input
          className="filter-input"
          style={{ flex: 1 }}
          placeholder="Search articles and events…"
          value={query}
          onChange={(e) => setQuery(e.target.value)}
          onKeyDown={(e) => e.key === "Enter" && doSearch()}
        />
        <button className="action-btn action-btn-primary" onClick={doSearch}>Search</button>
      </div>

      <div style={{ display: "flex", gap: "0.5rem", marginBottom: "1rem" }}>
        {(["articles", "events"] as const).map((t) => (
          <button
            key={t}
            className={`action-btn ${tab === t ? "action-btn-primary" : ""}`}
            onClick={() => { setTab(t); setResults([]); setSearched(false); }}
          >
            {t.charAt(0).toUpperCase() + t.slice(1)}
          </button>
        ))}
      </div>

      {loading ? (
        <div className="loading-state"><div className="loading-spinner" /> Searching…</div>
      ) : !searched ? (
        <div style={{ padding: "3rem", textAlign: "center", color: "#94a3b8" }}>
          Enter a query to search across {tab}
        </div>
      ) : results.length === 0 ? (
        <div className="empty-state" style={{ padding: "3rem", textAlign: "center", color: "#94a3b8" }}>
          No results found for &quot;{query}&quot;
        </div>
      ) : (
        <div style={{ display: "flex", flexDirection: "column", gap: "0.75rem" }}>
          {results.map((r) => (
            <div key={r.id} style={{
              padding: "1rem", background: "#fff", borderRadius: 8,
              border: "1px solid #e2e8f0",
            }}>
              <div style={{ display: "flex", justifyContent: "space-between", marginBottom: 4 }}>
                <span style={{ fontWeight: 600 }}>{r.title}</span>
                <span className="badge badge-gray">score: {Number(r.score || 0).toFixed(3)}</span>
              </div>
              {r.snippet && <p style={{ margin: "4px 0", fontSize: "0.88rem", color: "#475569" }}>{r.snippet.length > 200 ? r.snippet.slice(0, 200) + "…" : r.snippet}</p>}
              <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginTop: 6 }}>
                <div style={{ display: "flex", gap: 6, fontSize: "0.8rem", color: "#94a3b8" }}>
                  {r.source_name && <span>{r.source_name}</span>}
                  {r.published_at && <span>· {new Date(r.published_at).toLocaleString()}</span>}
                </div>
                <Link
                  href={tab === "articles" ? `/articles/${r.id}` : `/events?highlight=${r.id}`}
                  className="action-btn action-btn-primary"
                  style={{ fontSize: "0.8rem", padding: "4px 12px", textDecoration: "none" }}
                >
                  {tab === "articles" ? "View Article" : "View Event"}
                </Link>
              </div>
            </div>
          ))}
        </div>
      )}
    </PageShell>
  );
}
