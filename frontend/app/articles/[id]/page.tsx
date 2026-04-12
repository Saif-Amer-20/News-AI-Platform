"use client";

import { useEffect, useState, useCallback } from "react";
import { useParams } from "next/navigation";
import Link from "next/link";
import { PageShell } from "@/components/shell";
import { api, apiPost } from "@/lib/api";
import { ImportanceBadge } from "@/components/score-badge";
import {
  ExternalLink, Calendar, User, Newspaper, Users, Radar, Link2,
  ChevronRight, Tag, FileText, Languages, Undo2, Loader2, Brain, Sparkles,
} from "lucide-react";
import type { ArticleDetail, ArticleRelated, ArticleEvent, ArticleEntityLink, ArticleTranslation, ArticleAISummary } from "@/lib/types";

export default function ArticleDetailPage() {
  const params = useParams();
  const id = params.id as string;
  const [article, setArticle] = useState<ArticleDetail | null>(null);
  const [entities, setEntities] = useState<ArticleEntityLink[]>([]);
  const [events, setEvents] = useState<ArticleEvent[]>([]);
  const [related, setRelated] = useState<ArticleRelated[]>([]);
  const [loading, setLoading] = useState(true);
  const [activeTab, setActiveTab] = useState<"content" | "entities" | "events" | "related">("content");

  // Translation state
  const [showArabic, setShowArabic] = useState(false);
  const [translating, setTranslating] = useState(false);
  const [translation, setTranslation] = useState<ArticleTranslation | null>(null);
  const [translationError, setTranslationError] = useState("");

  // AI Summary state
  const [aiSummary, setAiSummary] = useState<ArticleAISummary | null>(null);
  const [generatingAi, setGeneratingAi] = useState(false);
  const [aiError, setAiError] = useState("");
  const [showAiArabic, setShowAiArabic] = useState(false);

  useEffect(() => {
    if (!id) return;
    setLoading(true);
    setShowArabic(false);
    setTranslation(null);
    setTranslationError("");
    setAiSummary(null);
    setAiError("");
    Promise.all([
      api<ArticleDetail>(`/articles/${id}/`),
      api<{ entities: ArticleEntityLink[] }>(`/articles/${id}/entities/`).catch(() => ({ entities: [] })),
      api<{ events: ArticleEvent[] }>(`/articles/${id}/events/`).catch(() => ({ events: [] })),
      api<{ related: ArticleRelated[] }>(`/articles/${id}/related/`).catch(() => ({ related: [] })),
    ]).then(([a, ent, ev, rel]) => {
      setArticle(a);
      setEntities(ent.entities ?? []);
      setEvents(ev.events ?? []);
      setRelated(rel.related ?? []);
      // Check if Arabic translation already exists
      const arTranslation = (a.translations ?? []).find(
        (t) => t.language_code === "ar" && t.translation_status === "completed"
      );
      if (arTranslation) setTranslation(arTranslation);
      // Load existing AI summary
      if (a.ai_summary && a.ai_summary.status === "completed") {
        setAiSummary(a.ai_summary);
      }
    }).catch(() => setArticle(null))
      .finally(() => setLoading(false));
  }, [id]);

  const handleTranslate = useCallback(async () => {
    if (!article) return;
    // If we already have a completed translation, just toggle view
    if (translation && translation.translation_status === "completed") {
      setShowArabic(true);
      return;
    }
    setTranslating(true);
    setTranslationError("");
    try {
      const result = await apiPost<ArticleTranslation>(
        `/articles/${article.id}/translate/`,
        { target_language: "ar" },
      );
      if (result.translation_status === "completed") {
        setTranslation(result);
        setShowArabic(true);
      } else if (result.translation_status === "failed") {
        setTranslationError(result.error_message || "Translation failed.");
      } else {
        setTranslationError("Translation is still processing. Please try again shortly.");
      }
    } catch {
      setTranslationError("Failed to request translation.");
    } finally {
      setTranslating(false);
    }
  }, [article, translation]);

  const handleAiSummary = useCallback(async () => {
    if (!article) return;
    if (aiSummary && aiSummary.status === "completed") return;
    setGeneratingAi(true);
    setAiError("");
    try {
      const result = await apiPost<ArticleAISummary>(
        `/articles/${article.id}/ai-summary/`,
        {},
      );
      if (result.status === "completed") {
        setAiSummary(result);
      } else if (result.status === "failed") {
        setAiError(result.error_message || "AI summary generation failed.");
      } else {
        setAiError("AI summary is still processing. Please try again shortly.");
      }
    } catch {
      setAiError("Failed to generate AI summary.");
    } finally {
      setGeneratingAi(false);
    }
  }, [article, aiSummary]);

  if (loading) {
    return (
      <PageShell title="Article">
        <div className="loading-state"><div className="loading-spinner" /> Loading article…</div>
      </PageShell>
    );
  }

  if (!article) {
    return (
      <PageShell title="Article">
        <div className="empty-state">Article not found</div>
      </PageShell>
    );
  }

  const hasFullContent = article.content && article.content.length > 200;

  return (
    <PageShell title="Article Detail">
      <div className="article-detail-page">
        {/* ── Header ────────────────────────────────── */}
        <div className="article-header">
          <h1 className="article-title">{article.title}</h1>

          <div className="article-meta-row">
            {article.source_name && (
              <span className="article-meta-item">
                <Newspaper size={14} /> {article.source_name}
              </span>
            )}
            {article.published_at && (
              <span className="article-meta-item">
                <Calendar size={14} /> {new Date(article.published_at).toLocaleString()}
              </span>
            )}
            {article.author && (
              <span className="article-meta-item">
                <User size={14} /> {article.author}
              </span>
            )}
            <ImportanceBadge value={article.importance_score} />
          </div>

          {/* Topic tags */}
          {article.matched_topic_names && article.matched_topic_names.length > 0 && (
            <div className="article-tags">
              <Tag size={13} />
              {article.matched_topic_names.map((t) => (
                <span key={t} className="badge badge-blue">{t}</span>
              ))}
            </div>
          )}

          {/* Actions */}
          <div className="article-actions">
            {article.url && (
              <a href={article.url} target="_blank" rel="noopener noreferrer" className="action-btn action-btn-primary">
                <ExternalLink size={14} /> Open Original Source
              </a>
            )}
            {article.story_title && (
              <Link href={`/events?story=${article.story}`} className="action-btn">
                <Radar size={14} /> View Story
              </Link>
            )}

            {/* Translation buttons */}
            {!showArabic ? (
              <button
                className="action-btn action-btn-translate"
                onClick={handleTranslate}
                disabled={translating}
              >
                {translating ? (
                  <><Loader2 size={14} className="spin-icon" /> جاري الترجمة…</>
                ) : (
                  <><Languages size={14} /> عرض الترجمة العربية</>
                )}
              </button>
            ) : (
              <button
                className="action-btn"
                onClick={() => setShowArabic(false)}
              >
                <Undo2 size={14} /> إظهار النص الأصلي
              </button>
            )}

            {/* AI Summary button */}
            <button
              className="action-btn action-btn-ai"
              onClick={handleAiSummary}
              disabled={generatingAi || (aiSummary?.status === "completed")}
            >
              {generatingAi ? (
                <><Loader2 size={14} className="spin-icon" /> Generating AI Summary…</>
              ) : aiSummary?.status === "completed" ? (
                <><Brain size={14} /> AI Summary Ready</>
              ) : (
                <><Sparkles size={14} /> Generate AI Summary</>
              )}
            </button>
          </div>
          {translationError && (
            <div className="translation-error">{translationError}</div>
          )}
          {aiError && (
            <div className="translation-error">{aiError}</div>
          )}
        </div>

        {/* ── Tabs ──────────────────────────────────── */}
        <div className="detail-tabs">
          {([
            ["content", `Content${hasFullContent ? "" : " (Summary)"}`],
            ["entities", `Entities (${entities.length})`],
            ["events", `Events (${events.length})`],
            ["related", `Related (${related.length})`],
          ] as const).map(([key, label]) => (
            <button
              key={key}
              className={`detail-tab ${activeTab === key ? "detail-tab--active" : ""}`}
              onClick={() => setActiveTab(key)}
            >
              {label}
            </button>
          ))}
        </div>

        {/* ── Tab Content ───────────────────────────── */}
        <div className="article-tab-content">
          {activeTab === "content" && (
            <div className="article-content-tab">
              {article.image_url && (
                <div className="article-hero-img">
                  {/* eslint-disable-next-line @next/next/no-img-element */}
                  <img src={article.image_url} alt="" />
                </div>
              )}

              {/* Arabic translation view */}
              {showArabic && translation ? (
                <div className="article-body article-body--arabic" dir="rtl" lang="ar">
                  <div className="translation-banner">
                    <Languages size={16} />
                    <span>الترجمة العربية — مقدمة عبر {translation.provider === "google" ? "Google Translate" : translation.provider}</span>
                  </div>
                  {translation.translated_title && (
                    <h2 className="article-translated-title">{translation.translated_title}</h2>
                  )}
                  {translation.translated_body ? (
                    translation.translated_body.split("\n\n").map((p, i) => (
                      <p key={i}>{p}</p>
                    ))
                  ) : (
                    <p className="article-summary-text">لا يتوفر محتوى مترجم. يُعرض الملخص المترجم فقط.</p>
                  )}
                  {article.url && (
                    <a href={article.url} target="_blank" rel="noopener noreferrer" className="action-btn action-btn-primary" style={{ marginTop: "1rem", display: "inline-flex" }}>
                      <ExternalLink size={14} /> اقرأ المقالة الكاملة من المصدر الأصلي
                    </a>
                  )}
                </div>
              ) : hasFullContent ? (
                <div className="article-body">
                  {article.content.split("\n\n").map((p, i) => (
                    <p key={i}>{p}</p>
                  ))}
                </div>
              ) : (
                <div className="article-body article-body--summary">
                  <div className="article-summary-banner">
                    <FileText size={16} />
                    <span>Full article content is not available. Showing extracted summary.</span>
                  </div>
                  <div className="article-summary-text">
                    {article.content || "No content available."}
                  </div>
                  {article.url && (
                    <a href={article.url} target="_blank" rel="noopener noreferrer" className="action-btn action-btn-primary" style={{ marginTop: "1rem", display: "inline-flex" }}>
                      <ExternalLink size={14} /> Read Full Article on Original Source
                    </a>
                  )}
                </div>
              )}

              {/* Quality metadata */}
              <div className="article-quality-row">
                <div className="article-quality-item">
                  <span className="article-quality-label">Quality</span>
                  <span className="article-quality-value">{Number(article.quality_score).toFixed(2)}</span>
                </div>
                <div className="article-quality-item">
                  <span className="article-quality-label">Importance</span>
                  <span className="article-quality-value">{Number(article.importance_score).toFixed(2)}</span>
                </div>
                {article.story_title && (
                  <div className="article-quality-item">
                    <span className="article-quality-label">Story</span>
                    <span className="article-quality-value">{article.story_title}</span>
                  </div>
                )}
              </div>

              {/* AI Summary section */}
              {aiSummary && aiSummary.status === "completed" && (
                <div className="ai-summary-section">
                  <div className="ai-summary-header">
                    <Brain size={18} />
                    <span>AI Intelligence Summary</span>
                    <span className="ai-summary-model">({aiSummary.model_used})</span>
                    {/* Arabic toggle for AI summary */}
                    {(aiSummary.summary_ar || aiSummary.predictions_ar) && (
                      <button
                        className="ai-lang-toggle"
                        onClick={() => setShowAiArabic(!showAiArabic)}
                      >
                        <Languages size={14} />
                        {showAiArabic ? "English" : "العربية"}
                      </button>
                    )}
                  </div>

                  <div className={showAiArabic ? "ai-summary-arabic" : ""} dir={showAiArabic ? "rtl" : undefined} lang={showAiArabic ? "ar" : undefined}>
                    <div className="ai-summary-block">
                      <h3 className="ai-summary-subtitle">
                        <FileText size={15} /> {showAiArabic ? "الملخص" : "Summary"}
                      </h3>
                      <div className="ai-summary-text">
                        {(showAiArabic ? aiSummary.summary_ar || aiSummary.summary : aiSummary.summary).split("\n").map((line, i) => (
                          <p key={i}>{line}</p>
                        ))}
                      </div>
                    </div>

                    {(showAiArabic ? (aiSummary.predictions_ar || aiSummary.predictions) : aiSummary.predictions) && (
                      <div className="ai-summary-block ai-predictions-block">
                        <h3 className="ai-summary-subtitle">
                          <Sparkles size={15} /> {showAiArabic ? "التنبؤات والتوقعات" : "Predictions & Forecast"}
                        </h3>
                        <div className="ai-summary-text">
                          {(showAiArabic ? aiSummary.predictions_ar || aiSummary.predictions : aiSummary.predictions).split("\n").map((line, i) => (
                            <p key={i}>{line}</p>
                          ))}
                        </div>
                      </div>
                    )}
                  </div>

                  {aiSummary.generated_at && (
                    <div className="ai-summary-footer">
                      Generated {new Date(aiSummary.generated_at).toLocaleString()}
                    </div>
                  )}
                </div>
              )}
            </div>
          )}

          {activeTab === "entities" && (
            <div className="tab-list">
              {entities.length === 0 ? (
                <div className="empty-state">No entities extracted</div>
              ) : (
                entities.map((e) => (
                  <Link key={e.entity_id} href={`/entities?highlight=${e.entity_id}`} className="tab-list-item" style={{ textDecoration: "none", color: "inherit" }}>
                    <div className="tab-list-item-main">
                      <Users size={14} />
                      <strong>{e.name}</strong>
                      <span className="badge badge-purple">{e.entity_type}</span>
                      {e.country && <span className="badge badge-gray">{e.country}</span>}
                    </div>
                    <div className="tab-list-item-meta">
                      relevance {Number(e.relevance_score).toFixed(2)} · {e.mention_count} mentions
                    </div>
                    <ChevronRight size={14} className="tab-list-arrow" />
                  </Link>
                ))
              )}
            </div>
          )}

          {activeTab === "events" && (
            <div className="tab-list">
              {events.length === 0 ? (
                <div className="empty-state">No linked events</div>
              ) : (
                events.map((ev) => (
                  <Link key={ev.id} href={`/events?highlight=${ev.id}`} className="tab-list-item" style={{ textDecoration: "none", color: "inherit" }}>
                    <div className="tab-list-item-main">
                      <Radar size={14} />
                      <strong>{ev.title}</strong>
                      <span className="badge badge-blue">{ev.event_type}</span>
                      {ev.location_country && <span className="badge badge-gray">{ev.location_country}</span>}
                    </div>
                    <div className="tab-list-item-meta">
                      importance {Number(ev.importance_score).toFixed(2)} · {new Date(ev.first_reported_at).toLocaleDateString()}
                    </div>
                    <ChevronRight size={14} className="tab-list-arrow" />
                  </Link>
                ))
              )}
            </div>
          )}

          {activeTab === "related" && (
            <div className="tab-list">
              {related.length === 0 ? (
                <div className="empty-state">No related articles</div>
              ) : (
                related.map((r) => (
                  <Link key={r.id} href={`/articles/${r.id}`} className="tab-list-item" style={{ textDecoration: "none", color: "inherit" }}>
                    <div className="tab-list-item-main">
                      <Link2 size={14} />
                      <span>{r.title}</span>
                      <span className={`badge ${r.relation === "same_story" ? "badge-blue" : "badge-purple"}`}>
                        {r.relation === "same_story" ? "Same Story" : "Shared Entities"}
                      </span>
                    </div>
                    <div className="tab-list-item-meta">
                      {r.source_name} · {r.published_at ? new Date(r.published_at).toLocaleDateString() : "—"}
                    </div>
                    <ChevronRight size={14} className="tab-list-arrow" />
                  </Link>
                ))
              )}
            </div>
          )}
        </div>
      </div>
    </PageShell>
  );
}
