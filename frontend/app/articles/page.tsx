"use client";

import { useEffect, useState, useCallback, Suspense } from "react";
import Link from "next/link";
import { PageShell } from "@/components/shell";
import { api } from "@/lib/api";
import { FilterBar, type FilterDef } from "@/components/filter-bar";
import { ImportanceBadge } from "@/components/score-badge";
import { Newspaper, Calendar, ArrowUpDown, ExternalLink } from "lucide-react";

type ArticleListItem = {
  id: number;
  title: string;
  url: string;
  source: number;
  source_name: string;
  story: number | null;
  story_title: string | null;
  published_at: string;
  quality_score: number;
  importance_score: number;
};

const FILTER_DEFS: FilterDef[] = [
  { key: "search", label: "Search", type: "text", placeholder: "Title or content…" },
  { key: "source", label: "Source ID", type: "text", placeholder: "Source ID" },
  { key: "min_quality", label: "Min Quality", type: "text", placeholder: "e.g. 0.5" },
  { key: "min_importance", label: "Min Importance", type: "text", placeholder: "e.g. 0.5" },
];

function ArticlesPageInner() {
  const [articles, setArticles] = useState<ArticleListItem[]>([]);
  const [loading, setLoading] = useState(true);
  const [filters, setFilters] = useState<Record<string, string>>({
    search: "", source: "", min_quality: "", min_importance: "",
  });
  const [ordering, setOrdering] = useState("-published_at");

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const qs = new URLSearchParams();
      for (const [k, v] of Object.entries(filters)) { if (v) qs.set(k, v); }
      if (ordering) qs.set("ordering", ordering);
      const data = await api<{ results: ArticleListItem[] }>(`/articles/?${qs.toString()}`);
      setArticles(data.results ?? []);
    } catch { /* empty */ } finally { setLoading(false); }
  }, [filters, ordering]);

  useEffect(() => { void load(); }, [load]);

  const toggleSort = (field: string) => {
    setOrdering((o) => o === field ? `-${field}` : o === `-${field}` ? field : `-${field}`);
  };

  return (
    <PageShell title="Articles">
      <FilterBar filters={FILTER_DEFS} values={filters} onChange={setFilters} searchType="article" />

      <div className="data-table-wrap">
        {loading ? (
          <div className="loading-state"><div className="loading-spinner" /> Loading articles…</div>
        ) : articles.length === 0 ? (
          <div className="empty-state">No articles found</div>
        ) : (
          <table className="data-table">
            <thead>
              <tr>
                <th>Article</th>
                <th>Source</th>
                <th className="sortable-th" onClick={() => toggleSort("importance_score")}>
                  Importance <ArrowUpDown size={11} />
                </th>
                <th className="sortable-th" onClick={() => toggleSort("quality_score")}>
                  Quality <ArrowUpDown size={11} />
                </th>
                <th className="sortable-th" onClick={() => toggleSort("published_at")}>
                  Date <ArrowUpDown size={11} />
                </th>
                <th>Link</th>
              </tr>
            </thead>
            <tbody>
              {articles.map((a) => (
                <tr key={a.id}>
                  <td>
                    <Link href={`/articles/${a.id}`} style={{ textDecoration: "none", color: "inherit" }}>
                      <div className="event-cell-title">{a.title}</div>
                      {a.story_title && <div className="event-cell-meta">Story: {a.story_title}</div>}
                    </Link>
                  </td>
                  <td><span className="badge badge-gray">{a.source_name}</span></td>
                  <td><ImportanceBadge value={a.importance_score} /></td>
                  <td>{Number(a.quality_score).toFixed(2)}</td>
                  <td className="cell-date">{a.published_at ? new Date(a.published_at).toLocaleDateString() : "—"}</td>
                  <td>
                    {a.url && (
                      <a href={a.url} target="_blank" rel="noopener noreferrer" className="article-open-link">
                        <ExternalLink size={13} /> Source
                      </a>
                    )}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </div>
    </PageShell>
  );
}

export default function ArticlesPage() {
  return <Suspense><ArticlesPageInner /></Suspense>;
}
