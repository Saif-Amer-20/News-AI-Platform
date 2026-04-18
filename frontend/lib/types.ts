/* ── Shared domain types for the NewsIntel frontend ────────── */

/* ── Events ────────────────────────────────────────────────── */
export type EventSummary = {
  id: number;
  title: string;
  description: string;
  event_type: string;
  location_name: string;
  location_country: string;
  importance_score: number;
  confidence_score: number;
  conflict_flag: boolean;
  story_count: number;
  source_count: number;
  first_reported_at: string;
  last_reported_at: string;
  narrative_conflicts?: string;
};

export type EventDetail = EventSummary & {
  article_count: number;
};

export type EventExplain = {
  event_id: number;
  event_title: string;
  event_type: string;
  description: string;
  confidence_factors: {
    source_count: number;
    story_count: number;
    confidence_score: number;
    geo_confidence: number;
    conflict_flag: boolean;
    narrative_conflicts: string;
  };
  source_correlation: unknown;
  story_chain: {
    story_id: number;
    title: string;
    story_key: string;
    article_count: number;
    importance_score: number;
    articles: {
      id: number;
      title: string;
      source__name: string;
      quality_score: number;
      importance_score: number;
      published_at: string;
    }[];
  }[];
  timeline_json: unknown;
};

export type EventTimeline = {
  event_id: number;
  event_title: string;
  first_reported_at: string;
  last_reported_at: string;
  intelligence_timeline: unknown[];
  article_timeline: {
    id: number;
    title: string;
    published_at: string;
    source__name: string;
    importance_score: number;
  }[];
};

export type EventEntity = {
  entity_id: number;
  entity_name: string;
  entity_type: string;
  entity_country: string;
  mention_count: number;
  avg_relevance: number;
};

export type EventSource = {
  source_id: number;
  name: string;
  source_type: string;
  country: string;
  trust_score: number;
  article_count: number;
  earliest: string;
  latest: string;
};

export type RelatedEvent = {
  event_id: number;
  title: string;
  event_type: string;
  location_name: string;
  country: string;
  importance: number;
  relation: string;
  distance?: number;
};

/* ── Alerts ────────────────────────────────────────────────── */
export type AlertSummary = {
  id: number;
  title: string;
  summary: string;
  alert_type: string;
  severity: string;
  status: string;
  source__name: string;
  topic__name: string;
  triggered_at: string;
};

export type AlertDetail = AlertSummary & {
  description: string;
  acknowledged_at: string | null;
  resolved_at: string | null;
  event?: number;
  article?: number;
};

export type AlertExplain = {
  alert_id: number;
  alert_type: string;
  severity: string;
  rationale: string;
  trigger_data: {
    article?: Record<string, unknown>;
    matched_rules?: unknown;
    rule_details?: unknown;
  };
  context: {
    event?: Record<string, unknown>;
    similar_alerts?: unknown;
  };
  recommended_actions: string[];
};

/* ── Entities ──────────────────────────────────────────────── */
export type EntitySummary = {
  id: number;
  name: string;
  canonical_name?: string;
  normalized_name?: string;
  entity_type: string;
  country: string;
  description: string;
  article_count: number;
  event_count: number;
  aliases?: string[];
  merge_confidence?: string | number | null;
  merge_method?: string | null;
};

export type EntityCoOccurrence = {
  co_entity_id: number;
  co_entity_name: string;
  co_entity_type: string;
  co_entity_country: string;
  shared_articles: number;
  avg_relevance: number;
};

export type EntityMention = {
  article_id: number;
  article_title: string;
  source: string;
  published_at: string;
  relevance_score: number;
  mention_count: number;
  context_snippet: string;
};

/* ── Cases ─────────────────────────────────────────────────── */
export type CaseSummary = {
  id: number;
  title: string;
  description: string;
  status: string;
  priority: string;
  classification?: string;
  created_at: string;
  updated_at: string;
  opened_at: string;
  due_at?: string;
  article_count?: number;
  entity_count?: number;
  event_count?: number;
  note_count?: number;
  member_count?: number;
};

export type CaseNote = {
  id: number;
  text: string;
  note_type?: string;
  created_at: string;
  updated_at: string;
  author?: string;
};

export type CaseReference = {
  id: number;
  reference_type: string;
  reference_id: number;
  title: string;
  notes: string;
  added_at: string;
};

export type CaseTimelineEntry = {
  ts: string;
  type: string;
  title: string;
  detail?: string;
  actor?: string;
  object_id?: number;
  note_id?: number;
  reference_type?: string;
};

export type CaseDetailFull = CaseSummary & {
  notes: CaseNote[];
  alerts: { id: number; title: string; severity: string }[];
  events: { id: number; title: string; event_type: string }[];
  entities: { id: number; name: string; entity_type: string }[];
  articles: { id: number; title: string; source_name: string }[];
  references: CaseReference[];
  members: { id: number; user: string; role: string }[];
};

/* ── Timeline ──────────────────────────────────────────────── */
export type TimelineEntry = {
  ts: string;
  type: string;
  id: number;
  title: string;
  event_type?: string;
  location?: string;
  country?: string;
  importance?: number;
  confidence?: number;
  conflict?: boolean;
  stories?: number;
  sources?: number;
  source?: string;
  alert_type?: string;
  severity?: string;
  status?: string;
};

/* ── Map ───────────────────────────────────────────────────── */
export type MapFeature = {
  type: "Feature";
  geometry: { type: "Point"; coordinates: [number, number] };
  properties: {
    id: number;
    title: string;
    event_type: string;
    location_name: string;
    country: string;
    importance: number;
    confidence: number;
    conflict: boolean;
    stories: number;
    sources: number;
    first_reported: string;
    last_reported: string;
  };
};

export type HeatPoint = { lat: number; lon: number; weight: number; count: number };

export type ClusterPoint = {
  location_country: string;
  event_count: number;
  avg_lat: number;
  avg_lon: number;
  avg_importance: number;
  conflict_count: number;
};

/* ── Utility maps ──────────────────────────────────────────── */
export const SEVERITY_BADGE: Record<string, string> = {
  critical: "badge-red",
  high: "badge-amber",
  medium: "badge-blue",
  low: "badge-gray",
};

export const STATUS_BADGE: Record<string, string> = {
  open: "badge-red",
  acknowledged: "badge-amber",
  resolved: "badge-green",
  dismissed: "badge-gray",
  closed: "badge-green",
  escalated: "badge-red",
};

export const PRIORITY_BADGE: Record<string, string> = {
  critical: "badge-red",
  high: "badge-amber",
  medium: "badge-blue",
  low: "badge-gray",
};

export const EVENT_TYPES = [
  "political", "economic", "military", "social", "environmental",
  "legal", "health", "technology", "diplomatic", "humanitarian",
];

export const ENTITY_TYPES = [
  "person", "organization", "location", "facility", "event", "product", "other",
];

/* ── Entity Explain ────────────────────────────────────────── */
export type EntityExplain = {
  entity_id: number;
  entity_name: string;
  entity_type: string;
  description: string;
  importance_factors: {
    article_count: number;
    event_count: number;
    co_occurrence_count: number;
    mention_diversity: number;
    avg_relevance: number;
  };
  source_diversity: {
    unique_sources: number;
    source_types: string[];
    countries: string[];
  };
  top_events: { id: number; title: string; event_type: string; importance: number }[];
  top_co_entities: { id: number; name: string; entity_type: string; shared_articles: number }[];
};

/* ── Narrative / Conflict ──────────────────────────────────── */

/* ── Articles ──────────────────────────────────────────────── */
export type ArticleTranslation = {
  id: number;
  language_code: string;
  translated_title: string;
  translated_body: string;
  translation_status: "pending" | "completed" | "failed";
  translated_at: string | null;
  provider: string;
  error_message: string;
  created_at: string;
};

export type ArticleAISummary = {
  id: number;
  summary: string;
  predictions: string;
  summary_ar: string;
  predictions_ar: string;
  model_used: string;
  status: "pending" | "completed" | "failed";
  generated_at: string | null;
  error_message: string;
  created_at: string;
};

export type ArticleDetail = {
  id: number;
  title: string;
  normalized_title: string;
  url: string;
  canonical_url: string;
  content: string;
  author: string;
  image_url: string;
  source: number;
  source_name: string;
  story: number | null;
  story_title: string | null;
  published_at: string;
  is_duplicate: boolean;
  content_hash: string;
  quality_score: number;
  importance_score: number;
  matched_rule_labels: string[];
  entities: {
    id: number;
    entity: {
      id: number;
      name: string;
      entity_type: string;
      country: string;
    };
    relevance_score: number;
    mention_count: number;
    context_snippet: string;
  }[];
  matched_topic_names: string[];
  translations: ArticleTranslation[];
  ai_summary: ArticleAISummary | null;
  metadata: Record<string, unknown>;
  created_at: string;
  updated_at: string;
};

export type ArticleRelated = {
  id: number;
  title: string;
  source_name: string;
  published_at: string;
  importance_score: number;
  relation: string;
};

export type ArticleEvent = {
  id: number;
  title: string;
  event_type: string;
  location_name: string;
  location_country: string;
  importance_score: number;
  first_reported_at: string;
};

export type ArticleEntityLink = {
  entity_id: number;
  name: string;
  entity_type: string;
  country: string;
  relevance_score: number;
  mention_count: number;
  context_snippet: string;
};

/* ── Narrative / Conflict ──────────────────────────────────── */
export type NarrativeGroup = {
  narrative_id: number;
  label: string;
  stance: string;
  confidence: number;
  article_count: number;
  sources: { name: string; trust_score: number; country: string }[];
  summary: string;
  key_claims: string[];
};

export type ConflictAnalysis = {
  event_id: number;
  has_conflict: boolean;
  conflict_summary: string;
  narratives: NarrativeGroup[];
};

/* ── Hypothesis System ─────────────────────────────────────── */
export type HypothesisStatus = "draft" | "active" | "supported" | "refuted" | "inconclusive";

export type EvidenceLink = {
  id: string;
  ref_type: "event" | "entity" | "article";
  ref_id: number;
  ref_title: string;
  stance: "supports" | "contradicts" | "neutral";
  strength: number;       // 0-1
  analyst_note: string;
  added_at: string;
};

export type ConfidenceSnapshot = {
  ts: string;
  confidence: number;     // 0-1
  reason: string;
};

export type Hypothesis = {
  id: string;
  case_id: number;
  title: string;
  statement: string;
  status: HypothesisStatus;
  confidence: number;     // 0-1
  evidence: EvidenceLink[];
  confidence_history: ConfidenceSnapshot[];
  created_at: string;
  updated_at: string;
};

export const HYPOTHESIS_STATUS_BADGE: Record<HypothesisStatus, string> = {
  draft: "badge-gray",
  active: "badge-blue",
  supported: "badge-green",
  refuted: "badge-red",
  inconclusive: "badge-amber",
};

/* ── Reasoning Chains ──────────────────────────────────────── */
export type ReasoningNodeType = "event" | "entity" | "narrative" | "hypothesis" | "conclusion";

export type ReasoningNode = {
  id: string;
  type: ReasoningNodeType;
  ref_id?: number;
  label: string;
  detail?: string;
  confidence?: number;
};

export type ReasoningEdge = {
  from: string;
  to: string;
  relation: string;       // "leads_to" | "supports" | "contradicts" | "involves"
};

export type ReasoningChain = {
  id: string;
  case_id: number;
  title: string;
  nodes: ReasoningNode[];
  edges: ReasoningEdge[];
  conclusion?: string;
  created_at: string;
  updated_at: string;
};

/* ── Decision Support ──────────────────────────────────────── */
export type DecisionAction = "monitor" | "escalate" | "verify" | "close";

export type DecisionSuggestion = {
  action: DecisionAction;
  rationale: string;
  confidence_factor: number;
  conflict_factor: number;
  source_diversity_factor: number;
  overall_score: number;
};

export type DecisionRecord = {
  id: string;
  case_id: number;
  action: DecisionAction;
  rationale: string;
  decided_at: string;
  analyst?: string;
};

/* ── Anomaly / Signal Detection ────────────────────────────── */
export type AnomalyType = "spike" | "pattern_break" | "new_actor" | "geographic_shift" | "sentiment_shift";

export type AnomalySignal = {
  id: string;
  type: AnomalyType;
  title: string;
  description: string;
  severity: "low" | "medium" | "high";
  metric_name: string;
  baseline_value: number;
  current_value: number;
  detected_at: string;
  related_events: number[];
  related_entities: number[];
  dismissed: boolean;
};

export const ANOMALY_TYPE_LABELS: Record<AnomalyType, string> = {
  spike: "Volume Spike",
  pattern_break: "Pattern Break",
  new_actor: "New Actor",
  geographic_shift: "Geographic Shift",
  sentiment_shift: "Sentiment Shift",
};

/* ── Early Warning & Predictive Intelligence ───────────────── */

export type EarlyWarningAnomalyType =
  | "volume_spike"
  | "source_diversity"
  | "entity_surge"
  | "location_surge"
  | "narrative_shift";

export const EARLY_WARNING_ANOMALY_LABELS: Record<EarlyWarningAnomalyType, string> = {
  volume_spike: "Volume Spike",
  source_diversity: "Source Diversity",
  entity_surge: "Entity Surge",
  location_surge: "Location Surge",
  narrative_shift: "Narrative Shift",
};

export type EarlyWarningAnomaly = {
  id: number;
  anomaly_type: EarlyWarningAnomalyType;
  severity: "low" | "medium" | "high" | "critical";
  status: "active" | "acknowledged" | "dismissed" | "expired";
  title: string;
  description: string;
  metric_name: string;
  baseline_value: number;
  current_value: number;
  deviation_factor: number;
  confidence: string;
  event: number | null;
  entity: number | null;
  location_country: string;
  location_name: string;
  evidence: Record<string, unknown>;
  related_event_ids: number[];
  related_entity_ids: number[];
  detected_at: string;
  expires_at: string | null;
  created_at: string;
};

export type CorrelationStrength = "weak" | "moderate" | "strong";
export type CorrelationType =
  | "cross_event"
  | "cross_entity"
  | "cross_location"
  | "temporal"
  | "source_pattern";

export const CORRELATION_TYPE_LABELS: Record<CorrelationType, string> = {
  cross_event: "Cross-Event",
  cross_entity: "Cross-Entity",
  cross_location: "Cross-Location",
  temporal: "Temporal",
  source_pattern: "Source Pattern",
};

export type SignalCorrelation = {
  id: number;
  correlation_type: CorrelationType;
  strength: CorrelationStrength;
  title: string;
  description: string;
  correlation_score: string;
  event_a: number | null;
  event_b: number | null;
  entity_ids: number[];
  anomaly_ids: number[];
  reasoning: string;
  evidence: Record<string, unknown>;
  supporting_signals: { signal_type: string; detail: string; weight: number }[];
  detected_at: string;
  created_at: string;
};

export type WeakSignal = {
  signal: string;
  weight: number;
  source: "anomaly" | "correlation" | "pattern";
  severity?: string;
  strength?: string;
};

export type PredictiveScore = {
  id: number;
  event: number;
  escalation_probability: string;
  continuation_probability: string;
  misleading_probability: string;
  monitoring_priority: string;
  anomaly_factor: string;
  correlation_factor: string;
  historical_factor: string;
  source_diversity_factor: string;
  velocity_factor: string;
  reasoning: string;
  reasoning_ar: string;
  risk_trend: "rising" | "stable" | "declining";
  weak_signals: WeakSignal[];
  model_used: string;
  scored_at: string | null;
  created_at: string;
  updated_at: string;
};

export type HistoricalPattern = {
  id: number;
  event: number;
  matched_event: number | null;
  matched_event_title: string | null;
  pattern_name: string;
  similarity_score: string;
  matching_dimensions: string[];
  historical_outcome: string;
  predicted_trajectory: string;
  predicted_trajectory_ar: string;
  confidence: string;
  created_at: string;
};

export type GeoRadarZone = {
  id: number;
  title: string;
  description: string;
  center_lat: string;
  center_lon: string;
  radius_km: number;
  location_country: string;
  location_name: string;
  event_count: number;
  event_concentration: number;
  avg_severity: string;
  anomaly_count: number;
  temporal_trend: "intensifying" | "stable" | "subsiding";
  event_ids: number[];
  anomaly_ids: number[];
  status: "active" | "cooling" | "expired";
  first_detected_at: string;
  last_activity_at: string | null;
  created_at: string;
};

export type EventEarlyWarning = {
  event_id: number;
  anomalies: EarlyWarningAnomaly[];
  correlations: SignalCorrelation[];
  predictive_score: PredictiveScore | null;
  historical_patterns: HistoricalPattern[];
};

export type EarlyWarningDashboardSummary = {
  anomaly_stats: {
    total_active: number;
    critical: number;
    high: number;
    by_type: { anomaly_type: string; count: number }[];
  };
  rising_risk_events: number;
  active_hot_zones: number;
  active_correlations: number;
  top_anomalies: EarlyWarningAnomaly[];
  top_predictions: PredictiveScore[];
  top_correlations: SignalCorrelation[];
  hot_zones: GeoRadarZone[];
};

export const RISK_TREND_LABELS: Record<string, string> = {
  rising: "↗ Rising",
  stable: "→ Stable",
  declining: "↘ Declining",
};

export const RISK_TREND_COLORS: Record<string, string> = {
  rising: "#ef4444",
  stable: "#f59e0b",
  declining: "#22c55e",
};

export const CORRELATION_STRENGTH_COLORS: Record<CorrelationStrength, string> = {
  weak: "#6b7280",
  moderate: "#f59e0b",
  strong: "#ef4444",
};

export const TEMPORAL_TREND_LABELS: Record<string, string> = {
  intensifying: "🔥 Intensifying",
  stable: "→ Stable",
  subsiding: "↘ Subsiding",
};

/* ── Structured Notes ──────────────────────────────────────── */
export type StructuredNote = {
  id: string;
  case_id: number;
  text: string;
  note_type: "observation" | "assessment" | "action_item" | "question";
  tags: string[];
  linked_events: number[];
  linked_entities: number[];
  timeline_date?: string;
  created_at: string;
  updated_at: string;
  author?: string;
};

export const NOTE_TYPE_BADGE: Record<string, string> = {
  observation: "badge-blue",
  assessment: "badge-purple",
  action_item: "badge-amber",
  question: "badge-gray",
};

/* ── Case Evolution ────────────────────────────────────────── */
export type CaseEvolutionEntry = {
  ts: string;
  type: "event_added" | "entity_added" | "hypothesis_created" | "hypothesis_updated" |
        "evidence_added" | "decision_made" | "note_added" | "status_changed" | "chain_created";
  title: string;
  detail?: string;
  actor?: string;
  ref_id?: string;
  snapshot?: { confidence?: number; status?: string };
};

/* ── Intelligence Assessment ───────────────────────────────── */

export type IntelSourceEntry = {
  source_id: number;
  name: string;
  trust: number;
  country: string;
  articles: number;
  first: string | null;
  last: string | null;
};

export type IntelArticleLink = {
  id: number;
  title: string;
  url: string;
  source: string;
  published_at: string;
};

export type IntelTimelineEntry = {
  ts: string;
  source: string;
  article_id: number;
  title: string;
};

export type IntelClaim = {
  claim: string;
  sources: string[];
  status: "agreed" | "contradicted" | "unique";
};

export type IntelContradiction = {
  claim_a: string;
  source_a: string;
  claim_b: string;
  source_b: string;
};

export type VerificationStatus =
  | "verified"
  | "likely_true"
  | "mixed"
  | "unverified"
  | "likely_misleading";

export const VERIFICATION_LABELS: Record<VerificationStatus, string> = {
  verified: "Verified",
  likely_true: "Likely True",
  mixed: "Mixed / Conflicting",
  unverified: "Unverified",
  likely_misleading: "Likely Misleading",
};

export const VERIFICATION_COLORS: Record<VerificationStatus, string> = {
  verified: "#22c55e",
  likely_true: "#3b82f6",
  mixed: "#f59e0b",
  unverified: "#6b7280",
  likely_misleading: "#ef4444",
};

export type IntelAssessment = {
  id: number;
  event: number;
  // Diffusion
  coverage_count: number;
  distinct_source_count: number;
  first_seen: string | null;
  last_seen: string | null;
  source_list: IntelSourceEntry[];
  article_links: IntelArticleLink[];
  publication_timeline: IntelTimelineEntry[];
  // Cross-source comparison
  claims: IntelClaim[];
  agreements: string[];
  contradictions: IntelContradiction[];
  missing_details: string[];
  late_emerging_claims: string[];
  // AI assessment
  summary: string;
  source_agreement_summary: string;
  contradiction_summary: string;
  dominant_narrative: string;
  uncertain_elements: string;
  analyst_reasoning: string;
  // Arabic
  summary_ar: string;
  source_agreement_summary_ar: string;
  contradiction_summary_ar: string;
  dominant_narrative_ar: string;
  uncertain_elements_ar: string;
  analyst_reasoning_ar: string;
  // Credibility
  credibility_score: string;
  confidence_score: string;
  verification_status: VerificationStatus;
  credibility_factors: {
    source_diversity: number;
    coverage_volume: number;
    contradiction_count: number;
    agreement_count: number;
    time_span_hours: number;
  };
  // Predictions
  escalation_probability: string;
  continuation_probability: string;
  hidden_link_probability: string;
  monitoring_recommendation: string;
  forecast_signals: Record<string, number>;
  // Meta
  model_used: string;
  status: "pending" | "completed" | "failed";
  generated_at: string | null;
  error_message: string;
  created_at: string;
  updated_at: string;
};


/* ═══════════════════════════════════════════════════════════════
   SELF-LEARNING INTELLIGENCE LAYER
   ═══════════════════════════════════════════════════════════════ */

export type FeedbackTargetType = "alert" | "event" | "prediction" | "case" | "anomaly";
export type FeedbackType = "confirmed" | "false_positive" | "misleading" | "useful" | "escalated_correctly" | "dismissed_correctly";
export type AccuracyStatus = "pending" | "accurate" | "partially_accurate" | "inaccurate" | "indeterminate";

export type AnalystFeedback = {
  id: number;
  target_type: FeedbackTargetType;
  target_id: number;
  feedback_type: FeedbackType;
  comment: string;
  analyst_name: string;
  confidence: string;
  context_snapshot: Record<string, unknown> | null;
  created_at: string;
};

export type OutcomeRecord = {
  id: number;
  target_type: FeedbackTargetType;
  target_id: number;
  expected_outcome: string;
  actual_outcome: string;
  accuracy_status: AccuracyStatus;
  resolved_at: string | null;
  resolution_notes: string;
  prediction_snapshot: Record<string, unknown> | null;
  outcome_snapshot: Record<string, unknown> | null;
  created_at: string;
  updated_at: string;
};

export type SourceReputationLog = {
  id: number;
  source: number;
  source_name: string;
  previous_trust: string;
  new_trust: string;
  change_delta: string;
  reason: string;
  evidence: Record<string, unknown> | null;
  is_rollback: boolean;
  rolled_back_at: string | null;
  created_at: string;
};

export type AdaptiveThreshold = {
  id: number;
  param_name: string;
  param_type: string;
  current_value: string;
  previous_value: string | null;
  default_value: string;
  min_value: string;
  max_value: string;
  adjustment_reason: string;
  version: number;
  is_active: boolean;
  updated_at: string;
};

export type LearningRecord = {
  id: number;
  event: number | null;
  record_type: string;
  features: Record<string, unknown> | null;
  prediction_scores: Record<string, unknown> | null;
  anomaly_metrics: Record<string, unknown> | null;
  feedback_summary: Record<string, unknown> | null;
  outcome: Record<string, unknown> | null;
  accuracy_label: string;
  created_at: string;
};

export type FeedbackSummary = {
  target_type: string;
  target_id: number;
  total: number;
  by_type: Record<string, number>;
  avg_confidence: number;
  latest: AnalystFeedback[];
};

export type LearningDashboardSummary = {
  feedback_stats: {
    period_days: number;
    total_feedback: number;
    by_target_type: Record<string, number>;
    by_feedback_type: Record<string, number>;
    false_positive_rate: number;
  };
  accuracy_stats: {
    period_days: number;
    total_resolved: number;
    accuracy_rate: number;
    by_status: Record<string, number>;
  };
  learning_stats: {
    total_records: number;
    by_type: Record<string, number>;
    by_accuracy: Record<string, number>;
    latest_at: string | null;
  };
  accuracy_history: Array<{ date: string; total: number; accurate: number; rate: number }>;
  recent_reputation_changes: SourceReputationLog[];
  active_thresholds: AdaptiveThreshold[];
};

export const FEEDBACK_TYPE_LABELS: Record<FeedbackType, string> = {
  confirmed: "Confirmed",
  false_positive: "False Positive",
  misleading: "Misleading",
  useful: "Useful",
  escalated_correctly: "Escalated Correctly",
  dismissed_correctly: "Dismissed Correctly",
};

export const FEEDBACK_TYPE_COLORS: Record<FeedbackType, string> = {
  confirmed: "badge-green",
  false_positive: "badge-red",
  misleading: "badge-amber",
  useful: "badge-blue",
  escalated_correctly: "badge-purple",
  dismissed_correctly: "badge-gray",
};

export const ACCURACY_STATUS_LABELS: Record<AccuracyStatus, string> = {
  pending: "Pending",
  accurate: "Accurate",
  partially_accurate: "Partially Accurate",
  inaccurate: "Inaccurate",
  indeterminate: "Indeterminate",
};

export const ACCURACY_STATUS_COLORS: Record<AccuracyStatus, string> = {
  pending: "badge-gray",
  accurate: "badge-green",
  partially_accurate: "badge-amber",
  inaccurate: "badge-red",
  indeterminate: "badge-blue",
};
