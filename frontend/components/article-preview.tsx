"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import { api } from "@/lib/api";
import { ExternalLink, ChevronDown, ChevronUp, Newspaper, Calendar, User } from "lucide-react";
import type { ArticleDetail } from "@/lib/types";

type Props = {
  articleId: number;
};

export function ArticlePreviewPanel({ articleId }: Props) {
  const [article, setArticle] = useState<ArticleDetail | null>(null);
  const [loading, setLoading] = useState(true);
  const [expanded, setExpanded] = useState(false);

  useEffect(() => {
    setLoading(true);
    api<ArticleDetail>(`/articles/${articleId}/`)
      .then(setArticle)
      .catch(() => setArticle(null))
      .finally(() => setLoading(false));
  }, [articleId]);

  if (loading) {
    return (
      <div className="article-preview">
        <div className="loading-state" style={{ padding: "0.75rem" }}>
          <div className="loading-spinner" /> Loading preview…
        </div>
      </div>
    );
  }

  if (!article) {
    return (
      <div className="article-preview">
        <div className="empty-state" style={{ padding: "0.75rem" }}>Article not available</div>
      </div>
    );
  }

  const hasContent = article.content && article.content.length > 0;
  const preview = article.content?.slice(0, 300) ?? "";
  const full = article.content ?? "";

  return (
    <div className="article-preview">
      <div className="article-preview-header">
        <Link href={`/articles/${article.id}`} className="article-preview-title">
          {article.title}
        </Link>
        <div className="article-preview-meta">
          {article.source_name && <span><Newspaper size={12} /> {article.source_name}</span>}
          {article.published_at && <span><Calendar size={12} /> {new Date(article.published_at).toLocaleDateString()}</span>}
          {article.author && <span><User size={12} /> {article.author}</span>}
        </div>
      </div>

      {hasContent && (
        <div className="article-preview-body">
          {expanded ? (
            <div className="article-preview-text">
              {full.split("\n\n").map((p, i) => (
                <p key={i}>{p}</p>
              ))}
            </div>
          ) : (
            <div className="article-preview-text">
              <p>{preview}{full.length > 300 ? "…" : ""}</p>
            </div>
          )}
          {full.length > 300 && (
            <button className="article-preview-toggle" onClick={() => setExpanded(!expanded)}>
              {expanded ? <><ChevronUp size={14} /> Show less</> : <><ChevronDown size={14} /> Read more</>}
            </button>
          )}
        </div>
      )}

      <div className="article-preview-actions">
        <Link href={`/articles/${article.id}`} className="action-btn action-btn-sm">
          <Newspaper size={13} /> Full Article
        </Link>
        {article.url && (
          <a href={article.url} target="_blank" rel="noopener noreferrer" className="action-btn action-btn-sm">
            <ExternalLink size={13} /> Original Source
          </a>
        )}
      </div>
    </div>
  );
}
