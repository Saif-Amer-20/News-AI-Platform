"use client";

import { useState, useEffect, useCallback } from "react";
import { api, apiPost } from "@/lib/api";
import {
  ThumbsUp, ThumbsDown, AlertTriangle, CheckCircle, XCircle,
  ArrowUpCircle, Trash2, Clock, MessageSquare, ChevronDown, ChevronRight,
  Loader2, Send,
} from "lucide-react";
import type {
  AnalystFeedback,
  FeedbackTargetType,
  FeedbackType,
  FeedbackSummary,
} from "@/lib/types";
import {
  FEEDBACK_TYPE_LABELS,
  FEEDBACK_TYPE_COLORS,
} from "@/lib/types";

/* ── Feedback buttons config ───────────────────────────────── */
const FEEDBACK_BUTTONS: Array<{
  type: FeedbackType;
  icon: React.ReactNode;
  label: string;
  color: string;
}> = [
  { type: "confirmed",            icon: <CheckCircle size={14} />,   label: "Confirmed",          color: "#22c55e" },
  { type: "false_positive",       icon: <XCircle size={14} />,       label: "False Positive",     color: "#ef4444" },
  { type: "misleading",           icon: <AlertTriangle size={14} />, label: "Misleading",         color: "#f59e0b" },
  { type: "useful",               icon: <ThumbsUp size={14} />,      label: "Useful",             color: "#3b82f6" },
  { type: "escalated_correctly",  icon: <ArrowUpCircle size={14} />, label: "Escalated OK",       color: "#a855f7" },
  { type: "dismissed_correctly",  icon: <Trash2 size={14} />,        label: "Dismissed OK",       color: "#6b7280" },
];

/* ── Props ─────────────────────────────────────────────────── */
type Props = {
  targetType: FeedbackTargetType;
  targetId: number;
  /** Show only a subset of feedback buttons */
  allowedTypes?: FeedbackType[];
  compact?: boolean;
};

export function FeedbackPanel({ targetType, targetId, allowedTypes, compact = false }: Props) {
  const [expanded, setExpanded] = useState(!compact);
  const [summary, setSummary] = useState<FeedbackSummary | null>(null);
  const [history, setHistory] = useState<AnalystFeedback[]>([]);
  const [submitting, setSubmitting] = useState<FeedbackType | null>(null);
  const [comment, setComment] = useState("");
  const [showComment, setShowComment] = useState(false);
  const [showHistory, setShowHistory] = useState(false);

  const buttons = allowedTypes
    ? FEEDBACK_BUTTONS.filter((b) => allowedTypes.includes(b.type))
    : FEEDBACK_BUTTONS;

  const loadData = useCallback(async () => {
    try {
      const [s, h] = await Promise.all([
        api<FeedbackSummary>(
          `/learning/feedback/summary/?target_type=${targetType}&target_id=${targetId}`,
        ),
        api<{ results: AnalystFeedback[] }>(
          `/learning/feedback/?target_type=${targetType}&target_id=${targetId}&ordering=-created_at`,
        ),
      ]);
      setSummary(s);
      setHistory(h.results ?? []);
    } catch {
      /* silent — panel is informational */
    }
  }, [targetType, targetId]);

  useEffect(() => {
    void loadData();
  }, [loadData]);

  const submitFeedback = async (feedbackType: FeedbackType) => {
    setSubmitting(feedbackType);
    try {
      await apiPost("/learning/feedback/submit/", {
        target_type: targetType,
        target_id: targetId,
        feedback_type: feedbackType,
        comment,
      });
      setComment("");
      setShowComment(false);
      await loadData();
    } catch {
      /* silent */
    } finally {
      setSubmitting(null);
    }
  };

  const totalFb = summary?.total ?? 0;

  return (
    <div className="feedback-panel">
      {/* Header */}
      <button
        className="feedback-panel-header"
        onClick={() => setExpanded(!expanded)}
      >
        <span className="feedback-panel-title">
          {expanded ? <ChevronDown size={14} /> : <ChevronRight size={14} />}
          <ThumbsUp size={14} />
          Analyst Feedback
          {totalFb > 0 && <span className="badge-count">{totalFb}</span>}
        </span>
      </button>

      {expanded && (
        <div className="feedback-panel-body">
          {/* Quick feedback buttons */}
          <div className="feedback-buttons-row">
            {buttons.map((btn) => {
              const count = summary?.by_type?.[btn.type] ?? 0;
              return (
                <button
                  key={btn.type}
                  className={`feedback-btn ${FEEDBACK_TYPE_COLORS[btn.type]}`}
                  style={{ borderColor: btn.color }}
                  onClick={() => void submitFeedback(btn.type)}
                  disabled={submitting !== null}
                  title={btn.label}
                >
                  {submitting === btn.type ? (
                    <Loader2 size={14} className="spin" />
                  ) : (
                    btn.icon
                  )}
                  <span>{btn.label}</span>
                  {count > 0 && <span className="feedback-btn-count">{count}</span>}
                </button>
              );
            })}
          </div>

          {/* Comment toggle */}
          <div className="feedback-comment-row">
            <button
              className="feedback-comment-toggle"
              onClick={() => setShowComment(!showComment)}
            >
              <MessageSquare size={13} />
              {showComment ? "Hide Comment" : "Add Comment"}
            </button>
          </div>

          {showComment && (
            <div className="feedback-comment-input">
              <input
                type="text"
                value={comment}
                onChange={(e) => setComment(e.target.value)}
                placeholder="Add a note…"
                className="feedback-input"
              />
              <button
                className="feedback-send-btn"
                onClick={() => {
                  if (comment.trim()) void submitFeedback("useful");
                }}
                disabled={!comment.trim() || submitting !== null}
              >
                <Send size={13} />
              </button>
            </div>
          )}

          {/* Summary bar */}
          {totalFb > 0 && summary && (
            <div className="feedback-summary-bar">
              {Object.entries(summary.by_type).map(([type, count]) => {
                const pct = Math.round(((count as number) / totalFb) * 100);
                const btn = FEEDBACK_BUTTONS.find((b) => b.type === type);
                return (
                  <div
                    key={type}
                    className="feedback-bar-segment"
                    style={{
                      width: `${pct}%`,
                      backgroundColor: btn?.color ?? "#6b7280",
                    }}
                    title={`${FEEDBACK_TYPE_LABELS[type as FeedbackType] ?? type}: ${count} (${pct}%)`}
                  />
                );
              })}
            </div>
          )}

          {/* History toggle */}
          {history.length > 0 && (
            <>
              <button
                className="feedback-history-toggle"
                onClick={() => setShowHistory(!showHistory)}
              >
                <Clock size={13} />
                {showHistory ? "Hide History" : `View History (${history.length})`}
              </button>

              {showHistory && (
                <div className="feedback-history">
                  {history.slice(0, 10).map((fb) => (
                    <div key={fb.id} className="feedback-history-item">
                      <span className={`badge-sm ${FEEDBACK_TYPE_COLORS[fb.feedback_type]}`}>
                        {FEEDBACK_TYPE_LABELS[fb.feedback_type]}
                      </span>
                      {fb.comment && (
                        <span className="feedback-history-comment">{fb.comment}</span>
                      )}
                      <span className="feedback-history-meta">
                        {fb.analyst_name || "—"} · {new Date(fb.created_at).toLocaleDateString("en-US")}
                      </span>
                    </div>
                  ))}
                </div>
              )}
            </>
          )}
        </div>
      )}
    </div>
  );
}
